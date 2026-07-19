from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from junto.access.request_limits import MaterialUploadLimitMiddleware
from junto.api.routes import build_router
from junto.config import Settings, settings
from junto.domain.errors import DomainError
from junto.domain.grouping import DeterministicPlaceholderGroupingService, GroupingService
from junto.repositories.base import RoomRepository
from junto.repositories.memory import InMemoryRoomRepository
from junto.services.references import DefaultReferenceTextExtractor, ReferenceTextExtractor
from junto.services.rooms import RoomService, utc_now
from junto.services.scheduling import Scheduler, ThreadingScheduler


def create_app(
    *,
    app_settings: Settings = settings,
    repository: RoomRepository | None = None,
    grouping: GroupingService | None = None,
    extractor: ReferenceTextExtractor | None = None,
    scheduler: Scheduler | None = None,
    clock: Callable[[], datetime] = utc_now,
    frontend_dist: Path | None = None,
) -> FastAPI:
    room_repository = repository or InMemoryRoomRepository()
    room_service = RoomService(
        room_repository,
        grouping or DeterministicPlaceholderGroupingService(),
        extractor
        or DefaultReferenceTextExtractor(
            max_characters=app_settings.max_extracted_reference_characters,
            max_pdf_pages=app_settings.max_pdf_pages,
            max_docx_uncompressed_bytes=app_settings.max_docx_uncompressed_bytes,
        ),
        scheduler or ThreadingScheduler(),
        app_settings,
        clock=clock,
    )
    application = FastAPI(title="Junto API", version="0.1.0")
    application.state.room_service = room_service
    application.add_middleware(
        SessionMiddleware,
        secret_key=app_settings.session_secret,
        session_cookie=app_settings.session_cookie_name,
        same_site="lax",
        https_only=app_settings.secure_cookies,
        max_age=14 * 24 * 60 * 60,
    )
    application.add_middleware(
        MaterialUploadLimitMiddleware,
        maximum_bytes=app_settings.max_reference_file_bytes + 256 * 1024,
    )
    application.include_router(build_router(room_service))

    @application.exception_handler(DomainError)
    async def handle_domain_error(_request: Request, error: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "details": error.details,
                }
            },
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        safe_errors = [
            {
                "location": [str(item) for item in issue.get("loc", ())],
                "type": str(issue.get("type", "validation_error")),
                "message": str(issue.get("msg", "Invalid value.")),
            }
            for issue in error.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_FAILED",
                    "message": "One or more fields are invalid.",
                    "details": {"fields": safe_errors},
                }
            },
        )

    resolved_frontend = (
        frontend_dist or Path(__file__).resolve().parents[2] / "frontend" / "dist"
    )
    index_file = resolved_frontend / "index.html"
    assets_directory = resolved_frontend / "assets"
    favicon_file = resolved_frontend / "favicon.svg"
    if index_file.is_file():
        if assets_directory.is_dir():
            application.mount("/assets", StaticFiles(directory=assets_directory), name="assets")

        if favicon_file.is_file():

            @application.get(
                "/favicon.svg",
                include_in_schema=False,
                response_model=None,
            )
            async def favicon() -> FileResponse:
                return FileResponse(favicon_file, media_type="image/svg+xml")

        @application.get(
            "/{browser_path:path}",
            include_in_schema=False,
            response_model=None,
        )
        async def frontend_fallback(browser_path: str) -> FileResponse | JSONResponse:
            if browser_path == "api" or browser_path.startswith("api/"):
                return JSONResponse(status_code=404, content={"detail": "Not Found"})
            return FileResponse(index_file)

    return application


app = create_app()
