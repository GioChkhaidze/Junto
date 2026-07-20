from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, inspect, select

from alembic import command
from junto.config import Settings
from junto.domain.entities import (
  AnalysisPhase,
  CoverageUnit,
  Group,
  GroupingPolicy,
  GroupingResult,
  GroupSize,
  Participant,
  Question,
  ReferenceAttachment,
  Response,
  Room,
  RoomStatus,
)
from junto.domain.errors import DomainError
from junto.engine.models import (
  CompleteCoverageStatus,
  EngineGroup,
  GroupingArtifact,
  ObjectiveOutcome,
  QuestionSemanticArtifact,
  ResponseFamily,
  SemanticArtifact,
  SemanticAssignment,
  SolverStatus,
)
from junto.main import create_app
from junto.persistence.models import (
  CoverageUnitRecord,
  ParticipantRecord,
  QuestionRecord,
  ReferenceMaterialRecord,
  ResponseRecord,
  RoomRecord,
)
from junto.services.personas import is_synthetic_participant, synthetic_personas
from tests.conftest import CapturingScheduler, ManualClock

from .conftest import PostgresHarness

NOW = datetime(2026, 7, 19, 9, 30, tzinfo=UTC)


def _room(
  *,
  room_id: UUID | None = None,
  join_code: str = "JUNT02",
  session_nonce: str = "session-alpha",
  legacy_grouping: bool = False,
) -> Room:
  actual_room_id = room_id or uuid4()
  question_id = uuid4()
  first_participant = uuid4()
  second_participant = uuid4()
  participants = {
    first_participant: Participant(
      id=first_participant,
      display_name="Maya",
      joined_at=NOW,
      session_nonce=session_nonce,
      submitted_at=NOW + timedelta(minutes=7),
    ),
    second_participant: Participant(
      id=second_participant,
      display_name="Alex",
      joined_at=NOW + timedelta(seconds=2),
      session_nonce=f"{session_nonce}-second",
      submitted_at=NOW + timedelta(minutes=8),
    ),
  }
  semantic = SemanticArtifact(
    compiled_at=NOW + timedelta(minutes=8),
    model="recorded-postgres-test",
    questions=(
      QuestionSemanticArtifact(
        question_id=question_id,
        unit_ids=("u_state", "u_tradeoff"),
        families=(
          ResponseFamily(id="f_top_down", label="Top-down reasoning"),
          ResponseFamily(id="f_bottom_up", label="Bottom-up reasoning"),
        ),
        assignments=(
          SemanticAssignment(
            participant_id=first_participant,
            family_id="f_top_down",
            covered_unit_ids=("u_state",),
          ),
          SemanticAssignment(
            participant_id=second_participant,
            family_id="f_bottom_up",
            covered_unit_ids=("u_tradeoff",),
          ),
        ),
      ),
    ),
  )
  if legacy_grouping:
    grouping: GroupingResult | GroupingArtifact = GroupingResult(
      generation_mode="placeholder",
      policy=GroupingPolicy.TEACH,
      trigger="all_submitted",
      generated_at=NOW + timedelta(minutes=9),
      groups=(Group(id="g1", participant_ids=(first_participant, second_participant)),),
    )
  else:
    grouping = GroupingArtifact(
      policy="teach",
      trigger="all_submitted",
      generated_at=NOW + timedelta(minutes=9),
      groups=(EngineGroup(id="g1", participant_ids=(first_participant, second_participant)),),
      solver_status=SolverStatus.OPTIMAL,
      complete_coverage_status=CompleteCoverageStatus.FEASIBLE,
      solve_milliseconds=19,
      objectives=(ObjectiveOutcome(name="covered group-units", value=2, proven_optimal=True),),
    )
  return Room(
    id=actual_room_id,
    join_code=join_code,
    title="Durable discussion",
    policy=GroupingPolicy.TEACH,
    group_size=GroupSize(minimum=2, preferred=2, maximum=4),
    duration_minutes=20,
    status=RoomStatus.PUBLISHED,
    created_at=NOW,
    updated_at=NOW + timedelta(minutes=9),
    questions=[
      Question(
        id=question_id,
        position=0,
        prompt="Compare the two approaches.",
        reference_material="Use the supplied worked example.",
        coverage_units=[
          CoverageUnit(id="u_state", text="Defines the state"),
          CoverageUnit(id="u_tradeoff", text="Explains the tradeoff"),
        ],
      )
    ],
    participants=participants,
    responses={
      (first_participant, question_id): Response(
        participant_id=first_participant,
        question_id=question_id,
        text="A top-down answer with a clear state.",
        updated_at=NOW + timedelta(minutes=5),
      ),
      (second_participant, question_id): Response(
        participant_id=second_participant,
        question_id=question_id,
        text="A bottom-up answer emphasizing the tradeoff.",
        updated_at=NOW + timedelta(minutes=6),
      ),
    },
    reference_attachments={
      (material_id := uuid4()): ReferenceAttachment(
        id=material_id,
        file_name="worked-example.txt",
        content_type="text/plain",
        size_bytes=42,
        extracted_text="This is extracted text; original bytes are deliberately absent.",
        uploaded_at=NOW + timedelta(minutes=1),
      )
    },
    cohort_ids=(first_participant, second_participant),
    started_at=NOW + timedelta(minutes=2),
    deadline_at=NOW + timedelta(minutes=22),
    analysis_mode="coverage_aware",
    analysis_phase=AnalysisPhase.COMPLETE,
    analysis_trigger="all_submitted",
    analysis_started_at=NOW + timedelta(minutes=8),
    analysis_completed_at=NOW + timedelta(minutes=9),
    analysis_attempt_count=1,
    analysis_result=semantic,
    grouping_result=grouping,
  )


@pytest.mark.parametrize("legacy_grouping", [False, True])
def test_round_trips_complete_room_aggregate(
  postgres_harness: PostgresHarness,
  legacy_grouping: bool,
) -> None:
  room = _room(legacy_grouping=legacy_grouping)

  postgres_harness.repository.add(room)

  assert postgres_harness.repository.get(room.id) == room
  assert postgres_harness.repository.get_by_join_code(room.join_code) == room


def test_transaction_commits_atomically_and_rolls_back_exception(
  postgres_harness: PostgresHarness,
) -> None:
  room = _room()
  postgres_harness.repository.add(room)

  with postgres_harness.repository.transaction(room.id) as mutable:
    mutable.title = "Committed title"
    mutable.responses.clear()

  committed = postgres_harness.repository.get(room.id)
  assert committed is not None
  assert committed.title == "Committed title"
  assert committed.responses == {}

  with (
    pytest.raises(RuntimeError, match="abort this unit of work"),
    postgres_harness.repository.transaction(room.id) as mutable,
  ):
    mutable.title = "Must roll back"
    raise RuntimeError("abort this unit of work")

  rolled_back = postgres_harness.repository.get(room.id)
  assert rolled_back is not None
  assert rolled_back.title == "Committed title"


def test_unique_join_code_maps_to_domain_conflict(postgres_harness: PostgresHarness) -> None:
  postgres_harness.repository.add(_room(join_code="SAME22"))

  with pytest.raises(DomainError) as raised:
    postgres_harness.repository.add(_room(join_code="SAME22"))

  assert raised.value.code == "JOIN_CODE_COLLISION"


def test_session_nonce_is_unique_per_room_but_reusable_in_another_room(
  postgres_harness: PostgresHarness,
) -> None:
  first = _room(join_code="NONC01", session_nonce="same-browser")
  second = _room(join_code="NONC02", session_nonce="same-browser")
  postgres_harness.repository.add(first)
  postgres_harness.repository.add(second)

  invalid_room = _room(join_code="NONC03", session_nonce="duplicate")
  participants = list(invalid_room.participants.values())
  participants[1].session_nonce = participants[0].session_nonce
  with pytest.raises(DomainError) as raised:
    postgres_harness.repository.add(invalid_room)

  assert raised.value.code == "PARTICIPANT_SESSION_COLLISION"


def test_room_row_lock_serializes_aggregate_transactions(
  postgres_harness: PostgresHarness,
) -> None:
  room = _room()
  postgres_harness.repository.add(room)
  first_has_lock = Event()
  release_first = Event()
  second_has_lock = Event()

  def first_writer() -> None:
    with postgres_harness.repository.transaction(room.id) as mutable:
      mutable.title += " | first"
      first_has_lock.set()
      assert release_first.wait(timeout=3)

  def second_writer() -> None:
    assert first_has_lock.wait(timeout=3)
    with postgres_harness.repository.transaction(room.id) as mutable:
      second_has_lock.set()
      assert mutable.title.endswith("| first")
      mutable.title += " | second"

  with ThreadPoolExecutor(max_workers=2) as executor:
    first_future = executor.submit(first_writer)
    second_future = executor.submit(second_writer)
    assert first_has_lock.wait(timeout=3)
    assert not second_has_lock.wait(timeout=0.2)
    release_first.set()
    first_future.result(timeout=3)
    second_future.result(timeout=3)

  saved = postgres_harness.repository.get(room.id)
  assert saved is not None
  assert saved.title.endswith("| first | second")


def test_database_cascade_removes_all_room_scoped_data(
  postgres_harness: PostgresHarness,
) -> None:
  room = _room()
  postgres_harness.repository.add(room)

  with postgres_harness.session_factory.begin() as session:
    session.execute(delete(RoomRecord).where(RoomRecord.id == room.id))

  with postgres_harness.session_factory() as session:
    for model in (
      RoomRecord,
      QuestionRecord,
      CoverageUnitRecord,
      ReferenceMaterialRecord,
      ParticipantRecord,
      ResponseRecord,
    ):
      assert session.scalar(select(func.count()).select_from(model)) == 0


def test_health_and_manual_delete_operations(postgres_harness: PostgresHarness) -> None:
  analyzing = _room(join_code="RUN001")
  analyzing.status = RoomStatus.ANALYZING
  analyzing.analysis_phase = AnalysisPhase.ANALYZING_RESPONSES
  analyzing.updated_at = NOW - timedelta(days=8)
  analyzing.analysis_started_at = NOW - timedelta(hours=2)
  postgres_harness.repository.add(analyzing)

  assert postgres_harness.repository.ping()
  assert postgres_harness.repository.get(analyzing.id) is not None
  assert postgres_harness.repository.delete(analyzing.id)
  assert not postgres_harness.repository.delete(analyzing.id)


def test_recover_stale_analysis_clears_partial_artifacts(
  postgres_harness: PostgresHarness,
) -> None:
  room = _room()
  room.status = RoomStatus.ANALYZING
  room.analysis_phase = AnalysisPhase.FORMING_GROUPS
  room.analysis_started_at = NOW - timedelta(hours=2)
  room.analysis_completed_at = None
  postgres_harness.repository.add(room)
  failed_at = NOW + timedelta(minutes=1)

  recovered = postgres_harness.repository.recover_stale_analyses(
    before=NOW - timedelta(hours=1),
    failed_at=failed_at,
  )

  assert recovered == 1
  saved = postgres_harness.repository.get(room.id)
  assert saved is not None
  assert saved.status == RoomStatus.FAILED
  assert saved.analysis_phase == AnalysisPhase.FAILED
  assert saved.analysis_result is None
  assert saved.grouping_result is None
  assert saved.analysis_completed_at == failed_at
  assert saved.updated_at == failed_at
  assert saved.last_error == "Analysis was interrupted. The host can retry once."


def test_migration_upgrade_and_downgrade_round_trip(
  postgres_harness: PostgresHarness,
) -> None:
  expected = {
    "rooms",
    "questions",
    "coverage_units",
    "reference_materials",
    "participants",
    "responses",
  }
  assert expected <= set(inspect(postgres_harness.engine).get_table_names())

  postgres_harness.engine.dispose()
  command.downgrade(postgres_harness.alembic_config, "base")
  assert not expected & set(inspect(postgres_harness.engine).get_table_names())

  command.upgrade(postgres_harness.alembic_config, "head")
  assert expected <= set(inspect(postgres_harness.engine).get_table_names())


def test_bulk_synthetic_twenty_by_eight_commit_round_trips_once(
  postgres_harness: PostgresHarness,
) -> None:
  clock = ManualClock(now=NOW)
  scheduler = CapturingScheduler()
  app = create_app(
    app_settings=Settings(
      environment="test",
      session_secret="postgres-synthetic-bulk-secret",
      max_questions_per_room=8,
      max_participants_per_room=60,
    ),
    repository=postgres_harness.repository,
    scheduler=scheduler,
    clock=clock,
  )
  service = app.state.room_service
  room = service.create_room(
    title="Twenty by eight synthetic load",
    policy=GroupingPolicy.TEACH,
    group_size=GroupSize(minimum=3, preferred=4, maximum=5),
    duration_minutes=20,
  )
  for index in range(8):
    service.add_question(
      room.id,
      prompt=f"Question {index + 1}",
      position=None,
      reference_material=None,
      coverage_units=[(None, f"Coverage unit {index + 1}")],
    )
  service.open_lobby(room.id)
  service.configure_synthetic_cohort(
    room.id,
    synthetic_personas(20, seed=41),
    seed=41,
  )
  started = service.start_activity(room.id)
  participant_ids = tuple(
    participant_id
    for participant_id in started.cohort_ids
    if is_synthetic_participant(started.participants[participant_id])
  )
  question_ids = tuple(question.id for question in started.questions)
  answers = {
    participant_id: {
      question_id: f"Participant {participant_index} answer {question_index}."
      for question_index, question_id in enumerate(question_ids)
    }
    for participant_index, participant_id in enumerate(participant_ids)
  }

  assert service.complete_synthetic_responses(room.id, answers) == 160

  saved = postgres_harness.repository.get(room.id)
  assert saved is not None
  assert saved.status == RoomStatus.ANALYZING
  assert saved.analysis_trigger == "all_submitted"
  assert len(saved.responses) == 160
  assert len(saved.participants) == 20
  assert all(participant.submitted_at == NOW for participant in saved.participants.values())
  assert sum(delay == 0 for delay, _callback in scheduler.callbacks) == 1
