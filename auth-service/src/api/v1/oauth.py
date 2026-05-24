import uuid
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.postgres import get_session
from src.db.redis import get_redis
from src.models.entity import User
from src.schemas.auth import TokenResponse
from src.services.auth import AuthService
from src.services.oauth.providers import get_provider
from src.services.oauth.service import OAuthService
from src.utils.dependencies import get_current_user


router = APIRouter(prefix="/auth/oauth", tags=["oauth"])


@router.get("/login/{provider}")
async def oauth_login(
    request: Request,
    redis: Annotated[Redis, Depends(get_redis)],
    provider: Annotated[str, Path()],
):
    """Инициирует OAuth-поток для входа/регистрации через соцсеть."""
    provider_instance = get_provider(provider)

    state = str(uuid.uuid4())
    await redis.setex(f"oauth_state:{provider}:{state}", 600, "pending")

    redirect_uri = str(request.url_for("oauth_callback_register", provider=provider))
    auth_url = provider_instance.get_authorization_url(state, redirect_uri)
    return {"authorization_url": auth_url}


@router.get("/link/{provider}")
async def oauth_link(
    request: Request,
    redis: Annotated[Redis, Depends(get_redis)],
    provider: Annotated[str, Path()],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Инициирует OAuth-поток для привязки соцсети к текущему пользователю."""
    provider_instance = get_provider(provider)

    state = str(uuid.uuid4())
    await redis.setex(f"oauth_link_state:{provider}:{state}", 600, str(current_user.id))

    redirect_uri = str(request.url_for("oauth_callback_login", provider=provider))
    auth_url = provider_instance.get_authorization_url(state, redirect_uri)
    return {"authorization_url": auth_url}


@router.get("/callback/register/{provider}")
async def oauth_callback_register(  # noqa: PLR0913, PLR0917
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    provider: Annotated[str, Path()],
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
):
    """Колбэк для входа/регистрации через соцсеть."""
    if error:
        raise HTTPException(status_code=400, detail=f"Authorization failed: {error}")

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    saved_state = await redis.get(f"oauth_state:{provider}:{state}")
    if not saved_state:
        raise HTTPException(status_code=400, detail="Invalid state")
    await redis.delete(f"oauth_state:{provider}:{state}")

    provider_instance = get_provider(provider)
    user_info = await provider_instance.handle_callback(code)

    oauth_service = OAuthService(db, redis)

    user = await oauth_service.process_provider_login(provider, user_info)

    auth_service = AuthService(db, redis)
    access, refresh = await auth_service.login(
        user=user,
        user_agent=request.headers.get("user-agent", ""),
        ip_address=request.client.host,
    )
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.get("/callback/login/{provider}")
async def oauth_callback_login(  # noqa: PLR0913, PLR0917
    _request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    provider: Annotated[str, Path()],
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
):
    """Колбэк для привязки соцсети к уже залогиненному пользователю."""
    if error:
        raise HTTPException(status_code=400, detail=f"Authorization failed: {error}")

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    user_id_str = await redis.get(f"oauth_link_state:{provider}:{state}")
    if not user_id_str:
        raise HTTPException(status_code=400, detail="Invalid state")
    await redis.delete(f"oauth_link_state:{provider}:{state}")

    provider_instance = get_provider(provider)
    user_info = await provider_instance.handle_callback(code)

    oauth_service = OAuthService(db, redis)
    await oauth_service.create_provider_link(
        user_id=UUID(user_id_str),
        provider=provider,
        provider_user_id=user_info["provider_user_id"],
        provider_email=user_info.get("email"),
    )

    return {"message": "Provider linked successfully"}
