import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.integrations.quickbooks.client import QuickBooksIntegrationError
from app.repositories.protocols import OAuthStateExpiredError


router = APIRouter(prefix="/api/v1/integrations/qbo", tags=["QuickBooks"])
OAUTH_COOKIE = "finz_qbo_oauth_state"
OAUTH_STATE_TTL_SECONDS = 600


@router.get("/connect")
async def connect(request: Request) -> RedirectResponse:
    settings = request.app.state.settings
    state = secrets.token_urlsafe(32)
    async with request.app.state.unit_of_work as uow:
        await uow.oauth_states.put(
            state,
            expires_at=datetime.now(timezone.utc)
            + timedelta(seconds=OAUTH_STATE_TTL_SECONDS),
        )
    query = urlencode(
        {
            "client_id": settings.qbo_client_id,
            "redirect_uri": settings.qbo_redirect_uri,
            "response_type": "code",
            "scope": settings.qbo_scope,
            "state": state,
        }
    )
    response = RedirectResponse(f"{settings.qbo_authorization_url}?{query}")
    response.set_cookie(
        OAUTH_COOKIE,
        state,
        max_age=OAUTH_STATE_TTL_SECONDS,
        httponly=True,
        secure=(settings.qbo_redirect_uri or "").startswith("https://"),
        samesite="lax",
        path="/api/v1/integrations/qbo",
    )
    return response


@router.get("/callback")
async def callback(
    request: Request,
    code: str,
    state: str,
    realmId: str,
) -> JSONResponse:
    cookie_state = request.cookies.get(OAUTH_COOKIE)
    if cookie_state is None or not secrets.compare_digest(cookie_state, state):
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired OAuth state",
        )
    try:
        async with request.app.state.unit_of_work as uow:
            saved_state = await uow.oauth_states.consume(state)
    except OAuthStateExpiredError as exc:
        raise HTTPException(
            status_code=400, detail="Invalid or expired OAuth state"
        ) from exc
    if saved_state is None:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired OAuth state",
        )
    try:
        result = await request.app.state.qbo_client.complete_authorization(
            code=code,
            realm_id=realmId,
        )
        response = JSONResponse(result)
        response.delete_cookie(
            OAUTH_COOKIE,
            path="/api/v1/integrations/qbo",
            httponly=True,
            samesite="lax",
        )
        return response
    except QuickBooksIntegrationError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "QuickBooks integration failed",
                "stage": exc.stage,
                "upstream_status": exc.upstream_status,
                "upstream_error": exc.upstream_error,
            },
        ) from None
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": (
                    "QuickBooks authorization or company verification failed"
                ),
                "stage": "unexpected",
                "exception_type": type(exc).__name__,
            },
        ) from None
