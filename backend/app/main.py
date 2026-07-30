from dataclasses import dataclass, field
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import SecretStr

from app.api.errors import install_error_handlers
from app.api.health import router as health_router
from app.api.demo_reset import router as demo_reset_router
from app.api.classifications import router as classifications_router
from app.api.qbo_oauth import router as qbo_oauth_router
from app.api.qbo_sync import router as qbo_sync_router
from app.api.reconciliations import router as reconciliations_router
from app.api.reports import router as reports_router
from app.api.transactions import router as transactions_router
from app.api.uploads import router as uploads_router
from app.core.config import Settings
from app.core.logging import install_access_log_redaction
from app.integrations.quickbooks.client import QuickBooksClient
from app.repositories.memory import InMemoryUnitOfWork
from app.repositories.mongo import MongoUnitOfWork
from app.services.ledger_bridge import LedgerBridgeService


@dataclass(frozen=True, slots=True)
class _QboRuntimeSettings:
    """Plaintext values held only in the running OAuth client boundary."""

    qbo_client_id: str | None = field(repr=False)
    qbo_client_secret: str | None = field(repr=False)
    qbo_redirect_uri: str | None
    qbo_environment: str
    qbo_authorization_url: str
    qbo_token_url: str
    qbo_base_url: str
    qbo_scope: str

    @classmethod
    def from_settings(cls, settings: Settings) -> "_QboRuntimeSettings":
        def reveal(value: SecretStr | None) -> str | None:
            return value.get_secret_value() if value is not None else None

        return cls(
            qbo_client_id=reveal(settings.qbo_client_id),
            qbo_client_secret=reveal(settings.qbo_client_secret),
            qbo_redirect_uri=settings.qbo_redirect_uri,
            qbo_environment=settings.qbo_environment,
            qbo_authorization_url=settings.qbo_authorization_url,
            qbo_token_url=settings.qbo_token_url,
            qbo_base_url=settings.qbo_base_url,
            qbo_scope=settings.qbo_scope,
        )


def create_app(
    qbo_client=None,
    settings: Settings | None = None,
    unit_of_work=None,
    qbo_gateway=None,
    ai_provider=None,
    ledger_bridge: LedgerBridgeService | None = None,
) -> FastAPI:
    settings = settings or Settings.from_environment(require_qbo=False)
    settings.validate_public_runtime()
    qbo_settings = _QboRuntimeSettings.from_settings(settings)
    owns_unit_of_work = unit_of_work is None and settings.repository_backend == "mongo"
    selected_uow = unit_of_work
    if selected_uow is None:
        selected_uow = (
            MongoUnitOfWork.from_uri(
                settings.mongodb_uri.get_secret_value(),
                settings.mongodb_database,
            )
            if settings.repository_backend == "mongo"
            else InMemoryUnitOfWork()
        )

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.repository_ready = True
        if owns_unit_of_work:
            try:
                await selected_uow.create_indexes()
            except Exception:
                application.state.repository_ready = False
                if settings.app_environment == "production":
                    await selected_uow.aclose()
                    raise RuntimeError(
                        "Required repository initialization failed"
                    ) from None
        yield
        if owns_unit_of_work:
            await selected_uow.aclose()

    install_access_log_redaction()
    app = FastAPI(
        title="Finz Ledger Bridge",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = qbo_settings
    app.state.core_settings = settings
    app.state.qbo_client = qbo_client or QuickBooksClient(qbo_settings)
    app.state.unit_of_work = selected_uow
    app.state.repository_backend = (
        settings.repository_backend if unit_of_work is None else "injected"
    )
    app.state.qbo_gateway = qbo_gateway
    app.state.ai_provider = ai_provider
    app.state.ledger_bridge = ledger_bridge or LedgerBridgeService(
        app.state.unit_of_work
    )

    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(demo_reset_router)
    app.include_router(uploads_router)
    app.include_router(transactions_router)
    app.include_router(classifications_router)
    app.include_router(reports_router)
    app.include_router(qbo_oauth_router)
    app.include_router(qbo_sync_router)
    app.include_router(reconciliations_router)
    _install_frontend_routes(app, settings.frontend_static_dir)
    return app


def _install_frontend_routes(app: FastAPI, static_dir: Path | None) -> None:
    """Serve a built SPA only after all API and documentation routes are registered."""
    if static_dir is None or not (index_file := static_dir / "index.html").is_file():
        return
    root = static_dir.resolve()
    reserved_paths = {"api", "health", "ready", "docs", "redoc", "openapi.json"}

    @app.get("/{requested_path:path}", include_in_schema=False)
    async def frontend(requested_path: str):
        first_segment = requested_path.split("/", 1)[0]
        if first_segment in reserved_paths:
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = (root / requested_path).resolve()
        if candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index_file)


app = create_app()
