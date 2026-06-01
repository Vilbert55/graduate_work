import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, PrimaryKeyConstraint, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.db.postgres import Base


class User(Base):
    __tablename__ = 'users'
    __table_args__ = {'schema': 'auth'}
    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    login = Column(String(255), unique=True, nullable=False)
    email = Column(String(255), unique=True, nullable=True)
    password = Column(String(255), nullable=False)  # хеш
    first_name = Column(String(50))
    last_name = Column(String(50))
    created_at = Column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))

    is_superuser = Column(Boolean, default=False)

    # Поля сегментации — нужны для построения dim_users в StarRocks
    # и для правил alerting-service (winback, segment_trend, ...).
    gender = Column(String(16), nullable=True)
    age = Column(Integer, nullable=True)
    country = Column(String(2), nullable=True)
    # is_demo — маркер тестового пользователя, созданного demo-tools.
    # demo-seeder удаляет всех is_demo=TRUE и пересоздаёт — идемпотентность.
    is_demo = Column(Boolean, nullable=False, server_default='false', default=False)

    oauth_providers = relationship("UserOAuthProvider", back_populates="user", cascade="all, delete-orphan")


class UserOAuthProvider(Base):
    __tablename__ = 'user_oauth_providers'
    __table_args__ = (
        UniqueConstraint('provider', 'provider_user_id', name='uq_provider_user'),
        {'schema': 'auth'},
    )
    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID, ForeignKey('auth.users.id', ondelete='CASCADE'), nullable=False)
    provider = Column(String(50), nullable=False)               # варианты 'yandex', 'google', 'github'
    provider_user_id = Column(String(255), nullable=False)      # id от провайдера
    provider_email = Column(String(255), nullable=True)         # email от провайдера (для информации)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))

    user = relationship("User", back_populates="oauth_providers")


class Role(Base):
    __tablename__ = 'roles'
    __table_args__ = (
        UniqueConstraint('name', name='uq_role_name'),
        {'schema': 'auth'},
    )
    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    name = Column(String(50), unique=True, nullable=False)
    description = Column(String(255))


class UserRole(Base):
    __tablename__ = 'user_roles'
    __table_args__ = (
        UniqueConstraint('user_id', 'role_id', name='uq_user_role'),
        {'schema': 'auth'},
    )
    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID, ForeignKey('auth.users.id'))
    role_id = Column(UUID, ForeignKey('auth.roles.id'))
    created_at = Column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))


class LoginHistory(Base):
    __tablename__ = 'login_history'
    __table_args__ = (
        # Составной первичный ключ
        PrimaryKeyConstraint('id', 'created_at'),
        {'schema': 'auth', 'postgresql_partition_by': 'RANGE (created_at)'},
    )
    id = Column(UUID, default=uuid.uuid4, nullable=False)  # больше не primary_key сама по себе
    user_id = Column(UUID, ForeignKey('auth.users.id'))
    user_agent = Column(String(255))
    ip_address = Column(String(45))
    created_at = Column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False)


class RefreshToken(Base):
    __tablename__ = 'refresh_tokens'
    __table_args__ = {'schema': 'auth'}
    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID, ForeignKey('auth.users.id'))
    token_hash = Column(String(255), unique=True)  # храним хеш токена
    device_info = Column(String(255))  # например, user_agent
    expires_at = Column(DateTime)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))
