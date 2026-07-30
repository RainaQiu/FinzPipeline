"""Secret-protected administration endpoint for the shared demo reset."""

from hmac import compare_digest

from fastapi import APIRouter, Header, HTTPException, Request

from app.services.demo_reset import DemoResetInProgressError, DemoResetService


router = APIRouter(prefix="/api/v1/admin", tags=["demo-admin"])


@router.post("/reset")
async def reset_shared_demo(
    request: Request,
    reset_secret: str | None = Header(
        default=None,
        alias="X-Finz-Reset-Secret",
        include_in_schema=False,
    ),
) -> dict[str, str]:
    configured = request.app.state.core_settings.demo_reset_secret
    expected = configured.get_secret_value() if configured is not None else ""
    if not expected or not compare_digest(reset_secret or "", expected):
        raise HTTPException(status_code=401, detail="Reset authorization failed")

    service = DemoResetService(request.app.state.unit_of_work)
    try:
        result = await service.reset_shared_workspace()
    except DemoResetInProgressError as exc:
        raise HTTPException(
            status_code=409,
            detail="Shared workspace reset already in progress",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Shared workspace reset failed",
        ) from exc
    return {
        "status": result.status,
        "scope": result.scope,
        "qbo_connection": result.qbo_connection,
    }
