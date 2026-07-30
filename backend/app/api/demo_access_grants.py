"""Anonymous access-code exchange for a one-time protected-operation grant."""

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, SecretStr


router = APIRouter(prefix="/api/v1/demo", tags=["demo-access"])


class AccessGrantRequest(BaseModel):
    access_code: SecretStr = Field(min_length=1, max_length=128)


class AccessGrantResponse(BaseModel):
    grant_token: str
    token_type: str = "bearer"
    expires_in_seconds: int


@router.post(
    "/access-grants",
    response_model=AccessGrantResponse,
    status_code=status.HTTP_201_CREATED,
)
async def issue_access_grant(
    payload: AccessGrantRequest,
    request: Request,
    response: Response,
) -> AccessGrantResponse:
    issued = await request.app.state.demo_access_grant_service.issue(
        payload.access_code.get_secret_value()
    )
    if issued is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access authorization failed",
        )
    response.headers["Cache-Control"] = "no-store"
    return AccessGrantResponse(
        grant_token=issued.token,
        expires_in_seconds=issued.expires_in_seconds,
    )
