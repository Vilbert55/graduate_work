from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        env_prefix='UGC_',
        case_sensitive=False,
        extra='ignore',
    )

    project_name: str = Field('UGC API', alias='PROJECT_NAME')

    # JWT — shared secret with auth-service
    jwt_secret_key: str = Field(alias='AUTH_JWT_SECRET_KEY')
    jwt_algorithm: str = Field('HS256', alias='AUTH_JWT_ALGORITHM')

    # Server
    server_host: str = '0.0.0.0'  # noqa: S104
    server_port: int = 8003
    debug: bool = False

    # Gunicorn
    gunicorn_workers: int = Field(4, description='Количество воркеров Gunicorn')
    gunicorn_worker_class: str = Field('gevent', description='Тип воркера')
    gunicorn_loglevel: str = Field('info', description='Уровень логирования Gunicorn')

    # Kafka
    kafka_host: str = 'movies-kafka'
    kafka_port: int = 9092

    # Topics
    kafka_topic_clicks: str = 'clicks'
    kafka_topic_views: str = 'views'
    kafka_topic_custom: str = 'custom_events'
    kafka_topic_recommendations: str = 'recommendations'

    # Sentry (пустая строка отключает интеграцию)
    sentry_dsn: str = ''

    @property
    def kafka_bootstrap_servers(self) -> str:
        return f'{self.kafka_host}:{self.kafka_port}'


settings = Settings()
