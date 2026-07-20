from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from junto.access.middleware import (
  RequestTelemetryMiddleware,
  SecurityHeadersMiddleware,
  SlidingWindowRateLimitMiddleware,
  TrustedOriginMiddleware,
)
from junto.access.request_limits import MaterialUploadLimitMiddleware
from junto.api.routes import build_router
from junto.config import Settings, settings
from junto.domain.errors import DomainError
from junto.domain.grouping import DeterministicPlaceholderGroupingService, GroupingService
from junto.engine.compiler import CompilerLimits, SemanticCompiler
from junto.engine.openrouter import OpenRouterStructuredClient
from junto.engine.openrouter_provider import OpenRouterSemanticProvider
from junto.engine.optimizer import CoverageFirstOptimizer, OptimizerConfig
from junto.engine.provider import (
  OpenAISemanticProvider,
  RecordedSemanticProvider,
  SemanticProvider,
)
from junto.persistence.database import create_postgres_engine, create_session_factory
from junto.repositories.base import RoomRepository
from junto.repositories.memory import InMemoryRoomRepository
from junto.repositories.postgres import PostgresRoomRepository
from junto.services.analysis import AnalysisPipeline, CoverageAnalysisPipeline
from junto.services.authoring import AuthoringService, OpenAIAuthoringService, OpenRouterAuthoringService
from junto.services.references import DefaultReferenceTextExtractor, ReferenceTextExtractor
from junto.services.rooms import RoomService, utc_now
from junto.services.scheduling import Scheduler, ThreadingScheduler
from junto.services.simulation import (
  OpenRouterSyntheticAnswerProvider,
  PatternedSyntheticAnswerProvider,
  SyntheticAnswerProvider,
  SyntheticClassroomService,
)


def create_app(
  *,
  app_settings: Settings = settings,
  repository: RoomRepository | None = None,
  grouping: GroupingService | None = None,
  extractor: ReferenceTextExtractor | None = None,
  scheduler: Scheduler | None = None,
  clock: Callable[[], datetime] = utc_now,
  frontend_dist: Path | None = None,
  analysis_pipeline: AnalysisPipeline | None = None,
  authoring_service: AuthoringService | None = None,
  openrouter_synthetic_provider: SyntheticAnswerProvider | None = None,
) -> FastAPI:
  database_engine = None
  if repository is not None:
    room_repository = repository
  elif app_settings.database_url:
    database_engine = create_postgres_engine(app_settings.database_url)
    room_repository = PostgresRoomRepository(create_session_factory(database_engine))
  else:
    room_repository = InMemoryRoomRepository()
  openrouter_client = _build_openrouter_client(app_settings)
  configured_pipeline = analysis_pipeline or _build_analysis_pipeline(
    app_settings,
    openrouter_client=openrouter_client,
  )
  reference_extractor = extractor or DefaultReferenceTextExtractor(
    max_characters=app_settings.max_extracted_reference_characters,
    max_pdf_pages=app_settings.max_pdf_pages,
    max_docx_uncompressed_bytes=app_settings.max_docx_uncompressed_bytes,
  )
  configured_authoring = authoring_service or _build_authoring_service(
    app_settings,
    openrouter_client=openrouter_client,
  )
  room_service = RoomService(
    room_repository,
    grouping or DeterministicPlaceholderGroupingService(),
    reference_extractor,
    scheduler or ThreadingScheduler(),
    app_settings,
    clock=clock,
    analysis_pipeline=configured_pipeline,
  )
  synthetic_classroom = _build_synthetic_classroom(
    room_service,
    app_settings,
    openrouter_client=openrouter_client,
    openrouter_provider=openrouter_synthetic_provider,
  )

  @asynccontextmanager
  async def lifespan(_application: FastAPI) -> AsyncIterator[None]:
    room_service.run_maintenance()
    try:
      yield
    finally:
      if database_engine is not None:
        database_engine.dispose()

  application = FastAPI(title="Junto API", version="0.2.0", lifespan=lifespan)
  application.state.room_service = room_service
  application.state.room_repository = room_repository
  application.state.database_engine = database_engine
  application.state.synthetic_classroom = synthetic_classroom
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
  application.add_middleware(
    TrustedOriginMiddleware,
    trusted_origins=app_settings.trusted_origins,
  )
  application.add_middleware(
    SlidingWindowRateLimitMiddleware,
    join_per_minute=app_settings.join_rate_limit_per_minute,
    create_per_minute=app_settings.room_create_rate_limit_per_minute,
    authoring_per_minute=app_settings.authoring_rate_limit_per_minute,
    analysis_per_minute=app_settings.analysis_rate_limit_per_minute,
    answer_per_minute=app_settings.answer_rate_limit_per_minute,
    status_per_minute=app_settings.status_rate_limit_per_minute,
    max_participants_per_room=app_settings.max_participants_per_room,
  )
  application.add_middleware(
    SecurityHeadersMiddleware,
    production=app_settings.environment == "production",
  )
  application.add_middleware(RequestTelemetryMiddleware)
  application.include_router(
    build_router(
      room_service,
      authoring_service=configured_authoring,
      reference_extractor=reference_extractor,
      synthetic_classroom=synthetic_classroom,
    )
  )

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

  resolved_frontend = frontend_dist or Path(__file__).resolve().parents[2] / "frontend" / "dist"
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


def _build_analysis_pipeline(
  settings: Settings,
  *,
  openrouter_client: OpenRouterStructuredClient | None = None,
) -> AnalysisPipeline | None:
  if settings.engine_mode == "placeholder":
    return None
  provider: SemanticProvider
  if settings.engine_mode == "openai":
    if settings.openai_api_key is None:
      raise RuntimeError("OPENAI_API_KEY is required for the OpenAI analysis engine.")
    provider = OpenAISemanticProvider.from_api_key(
      api_key=settings.openai_api_key,
      model=settings.openai_model,
      sdk_timeout_seconds=settings.provider_timeout_seconds,
      reasoning_effort=cast(
        Literal["none", "low", "medium", "high", "xhigh", "max"],
        settings.openai_reasoning_effort,
      ),
    )
  elif settings.engine_mode == "openrouter":
    if openrouter_client is None:
      raise RuntimeError("OPENROUTER_API_KEY is required for the OpenRouter analysis engine.")
    provider = OpenRouterSemanticProvider(client=openrouter_client, model=settings.openrouter_model)
  else:
    fixture_directory = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "semantic"
    fixture_paths = sorted(fixture_directory.glob("*.json"))
    if not fixture_paths:
      raise RuntimeError("Recorded semantic fixtures are unavailable.")
    provider = RecordedSemanticProvider.from_fixture_files(fixture_paths)

  compiler = SemanticCompiler(
    provider,
    limits=CompilerLimits(
      max_questions=settings.max_questions_per_room,
      max_participants=settings.max_participants_per_room,
      max_question_characters=4_000,
      max_reference_characters=settings.max_semantic_reference_characters,
      max_coverage_units=8,
      max_coverage_unit_characters=300,
      max_answer_characters=settings.max_answer_characters,
      max_provider_input_characters=240_000,
    ),
    max_concurrency=settings.semantic_max_concurrency,
    request_timeout_seconds=settings.provider_timeout_seconds,
    room_timeout_seconds=settings.semantic_room_timeout_seconds,
  )
  optimizer = CoverageFirstOptimizer(
    OptimizerConfig(
      timeout_seconds=settings.solver_timeout_seconds,
      random_seed=settings.solver_random_seed,
    )
  )
  return CoverageAnalysisPipeline(
    compiler=compiler,
    optimizer=optimizer,
    solver_timeout_seconds=settings.solver_timeout_seconds,
  )


def _build_openrouter_client(settings: Settings) -> OpenRouterStructuredClient | None:
  if settings.openrouter_api_key is None:
    return None
  return OpenRouterStructuredClient(
    api_key=settings.openrouter_api_key,
    timeout_seconds=settings.provider_timeout_seconds,
  )


def _build_synthetic_classroom(
  rooms: RoomService,
  settings: Settings,
  *,
  openrouter_client: OpenRouterStructuredClient | None,
  openrouter_provider: SyntheticAnswerProvider | None,
) -> SyntheticClassroomService:
  configured_openrouter = openrouter_provider
  if configured_openrouter is None and openrouter_client is not None:
    configured_openrouter = OpenRouterSyntheticAnswerProvider(
      client=openrouter_client,
      model=settings.openrouter_model,
    )
  return SyntheticClassroomService(
    rooms,
    enabled=settings.synthetic_classroom_enabled,
    patterned_provider=(
      PatternedSyntheticAnswerProvider()
      if settings.synthetic_classroom_enabled and settings.engine_mode == "placeholder"
      else None
    ),
    openrouter_provider=(configured_openrouter if settings.synthetic_classroom_enabled else None),
    max_cohort_size=settings.synthetic_max_cohort_size,
    generation_timeout_seconds=settings.synthetic_generation_timeout_seconds,
  )


def _build_authoring_service(
  settings: Settings,
  *,
  openrouter_client: OpenRouterStructuredClient | None = None,
) -> AuthoringService | None:
  if openrouter_client is not None:
    return OpenRouterAuthoringService(client=openrouter_client, model=settings.openrouter_model)
  if settings.openai_api_key is None:
    return None
  return OpenAIAuthoringService.from_api_key(
    api_key=settings.openai_api_key,
    model=settings.openai_model,
    sdk_timeout_seconds=settings.provider_timeout_seconds,
    reasoning_effort=cast(
      Literal["none", "low", "medium", "high", "xhigh", "max"],
      settings.openai_reasoning_effort,
    ),
  )


app = create_app()
