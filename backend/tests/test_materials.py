from __future__ import annotations

from collections.abc import Callable
from io import BytesIO
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from docx import Document
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from junto.config import Settings
from junto.domain.errors import DomainError
from junto.main import create_app
from junto.services.references import DefaultReferenceTextExtractor, ReferenceTextExtractor
from tests.conftest import CapturingScheduler, ManualClock, create_prepared_room, mutate

BackendFixture = tuple[FastAPI, CapturingScheduler, ManualClock]


class CountingExtractor(ReferenceTextExtractor):
  def __init__(self) -> None:
    self.calls = 0
    self.on_extract: Callable[[], None] | None = None

  def extract(self, *, file_name: str, content: bytes) -> tuple[str, str]:
    self.calls += 1
    if self.on_extract is not None:
      self.on_extract()
    return "text/plain", content.decode("utf-8")


def test_material_type_and_size_are_bounded() -> None:
  app = create_app(
    app_settings=Settings(
      session_secret="test-session-secret",
      max_reference_file_bytes=12,
    ),
    scheduler=CapturingScheduler(),
    clock=ManualClock(),
  )
  host = TestClient(app)
  room_id, _join_code, _question_id = create_prepared_room(host)

  invalid_type = mutate(
    host,
    "POST",
    f"/api/rooms/{room_id}/materials",
    files={"file": ("notes.exe", b"plain text", "application/octet-stream")},
  )
  assert invalid_type.status_code == 422
  assert invalid_type.json()["error"]["code"] == "UNSUPPORTED_REFERENCE_TYPE"

  legacy_doc = mutate(
    host,
    "POST",
    f"/api/rooms/{room_id}/materials",
    files={"file": ("notes.doc", b"legacy", "application/msword")},
  )
  assert legacy_doc.status_code == 422
  assert legacy_doc.json()["error"]["code"] == "UNSUPPORTED_REFERENCE_TYPE"

  oversized = mutate(
    host,
    "POST",
    f"/api/rooms/{room_id}/materials",
    files={"file": ("notes.txt", b"x" * 13, "text/plain")},
  )
  assert oversized.status_code == 422
  assert oversized.json()["error"]["code"] == "REFERENCE_FILE_TOO_LARGE"


def test_material_can_only_change_in_draft(backend: BackendFixture) -> None:
  app, _scheduler, _clock = backend
  host = TestClient(app)
  room_id, _join_code, _question_id = create_prepared_room(host)
  mutate(host, "POST", f"/api/rooms/{room_id}/open")
  response = mutate(
    host,
    "POST",
    f"/api/rooms/{room_id}/materials",
    files={"file": ("late.txt", b"late reference", "text/plain")},
  )
  assert response.status_code == 409
  assert response.json()["error"]["code"] == "ROOM_NOT_DRAFT"


def test_material_request_is_bounded_before_multipart_processing() -> None:
  app = create_app(
    app_settings=Settings(
      session_secret="test-session-secret",
      max_reference_file_bytes=12,
    ),
    scheduler=CapturingScheduler(),
    clock=ManualClock(),
  )
  host = TestClient(app)
  room_id, _join_code, _question_id = create_prepared_room(host)

  response = mutate(
    host,
    "POST",
    f"/api/rooms/{room_id}/materials",
    files={"file": ("large.txt", b"x" * (300 * 1024), "text/plain")},
  )

  assert response.status_code == 413
  assert response.json()["error"]["code"] == "REFERENCE_REQUEST_TOO_LARGE"


def test_rejected_material_uploads_do_not_run_extraction() -> None:
  extractor = CountingExtractor()
  app = create_app(
    app_settings=Settings(
      session_secret="test-session-secret",
      max_reference_files_per_room=1,
    ),
    extractor=extractor,
    scheduler=CapturingScheduler(),
    clock=ManualClock(),
  )
  host = TestClient(app)
  room_id, _join_code, _question_id = create_prepared_room(host)

  first = mutate(
    host,
    "POST",
    f"/api/rooms/{room_id}/materials",
    files={"file": ("first.txt", b"first", "text/plain")},
  )
  capacity_rejected = mutate(
    host,
    "POST",
    f"/api/rooms/{room_id}/materials",
    files={"file": ("second.txt", b"second", "text/plain")},
  )
  mutate(host, "POST", f"/api/rooms/{room_id}/open")
  state_rejected = mutate(
    host,
    "POST",
    f"/api/rooms/{room_id}/materials",
    files={"file": ("late.txt", b"late", "text/plain")},
  )

  assert first.status_code == 201
  assert capacity_rejected.status_code == 422
  assert capacity_rejected.json()["error"]["code"] == "REFERENCE_FILE_LIMIT_REACHED"
  assert state_rejected.status_code == 409
  assert state_rejected.json()["error"]["code"] == "ROOM_NOT_DRAFT"
  assert extractor.calls == 1


def test_material_state_is_rechecked_after_extraction() -> None:
  extractor = CountingExtractor()
  app = create_app(
    app_settings=Settings(session_secret="test-session-secret"),
    extractor=extractor,
    scheduler=CapturingScheduler(),
    clock=ManualClock(),
  )
  host = TestClient(app)
  room_id, _join_code, _question_id = create_prepared_room(host)
  extractor.on_extract = lambda: app.state.room_service.open_lobby(UUID(room_id))

  response = mutate(
    host,
    "POST",
    f"/api/rooms/{room_id}/materials",
    files={"file": ("racing.txt", b"bounded", "text/plain")},
  )

  assert response.status_code == 409
  assert response.json()["error"]["code"] == "ROOM_NOT_DRAFT"
  saved = app.state.room_service.get_room(UUID(room_id))
  assert saved.reference_attachments == {}
  assert extractor.calls == 1


def test_pdf_page_count_is_bounded_before_text_extraction() -> None:
  writer = PdfWriter()
  writer.add_blank_page(width=72, height=72)
  writer.add_blank_page(width=72, height=72)
  content = BytesIO()
  writer.write(content)
  extractor = DefaultReferenceTextExtractor(max_characters=1_000, max_pdf_pages=1)

  with pytest.raises(DomainError) as raised:
    extractor.extract(file_name="two-pages.pdf", content=content.getvalue())

  assert raised.value.code == "REFERENCE_PDF_PAGE_LIMIT"


def test_docx_expansion_and_extracted_text_are_bounded() -> None:
  expanded = BytesIO()
  with ZipFile(expanded, "w", compression=ZIP_DEFLATED) as archive:
    archive.writestr("word/document.xml", "x" * 2_000)
  expansion_limited = DefaultReferenceTextExtractor(
    max_characters=10_000,
    max_docx_uncompressed_bytes=1_000,
  )
  with pytest.raises(DomainError) as expansion_error:
    expansion_limited.extract(file_name="expanded.docx", content=expanded.getvalue())
  assert expansion_error.value.code == "REFERENCE_DOCX_EXPANSION_LIMIT"

  document = Document()
  document.add_paragraph("A" * 80)
  normal_docx = BytesIO()
  document.save(normal_docx)
  text_limited = DefaultReferenceTextExtractor(
    max_characters=20,
    max_docx_uncompressed_bytes=2 * 1024 * 1024,
  )
  with pytest.raises(DomainError) as text_error:
    text_limited.extract(file_name="long.docx", content=normal_docx.getvalue())
  assert text_error.value.code == "REFERENCE_TEXT_TOO_LONG"
