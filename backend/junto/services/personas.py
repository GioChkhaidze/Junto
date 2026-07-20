from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Literal
from uuid import UUID, uuid5

from junto.domain.entities import Participant

KnowledgeLevel = Literal["novice", "developing", "proficient", "advanced"]
ConfidenceStyle = Literal["cautious", "calibrated", "assertive"]
AnswerStyle = Literal["terse", "plain", "structured", "exploratory"]
ErrorTendency = Literal[
  "none",
  "overgeneralize",
  "confuse_correlation",
  "miss_exception",
  "reverse_causality",
  "formula_slip",
  "answer_adjacent_question",
]
ParticipationStyle = Literal["complete", "selective", "sparse"]
SYNTHETIC_SESSION_PREFIX = "junto-synthetic:"


@dataclass(frozen=True, slots=True)
class SyntheticPersona:
  id: str
  display_name: str
  knowledge_level: KnowledgeLevel
  confidence: ConfidenceStyle
  answer_style: AnswerStyle
  error_tendency: ErrorTendency
  participation: ParticipationStyle


_NAMES = (
  "Maya",
  "Alex",
  "Jordan",
  "Priya",
  "Leo",
  "Samira",
  "Owen",
  "Nia",
  "Mateo",
  "Elise",
  "Ravi",
  "Hana",
  "Noah",
  "Amara",
  "Theo",
  "Lin",
  "Sofia",
  "Daniel",
  "Imani",
  "Luca",
)

# Traits are deliberately separate from names. The seed rotates the pairing so a
# knowledge level or mistake pattern never becomes a demographic claim.
_TRAITS: tuple[
  tuple[
    KnowledgeLevel,
    ConfidenceStyle,
    AnswerStyle,
    ErrorTendency,
    ParticipationStyle,
  ],
  ...,
] = (
  ("advanced", "calibrated", "structured", "none", "complete"),
  ("novice", "assertive", "terse", "overgeneralize", "selective"),
  ("developing", "cautious", "plain", "miss_exception", "complete"),
  ("proficient", "assertive", "structured", "none", "complete"),
  ("novice", "cautious", "exploratory", "formula_slip", "sparse"),
  ("developing", "calibrated", "plain", "confuse_correlation", "complete"),
  ("advanced", "assertive", "terse", "miss_exception", "complete"),
  ("proficient", "cautious", "exploratory", "none", "selective"),
  ("developing", "assertive", "structured", "reverse_causality", "complete"),
  ("novice", "calibrated", "plain", "answer_adjacent_question", "selective"),
  ("proficient", "calibrated", "structured", "none", "complete"),
  ("advanced", "cautious", "exploratory", "none", "complete"),
  ("novice", "assertive", "plain", "confuse_correlation", "sparse"),
  ("developing", "cautious", "terse", "overgeneralize", "selective"),
  ("proficient", "assertive", "plain", "formula_slip", "complete"),
  ("advanced", "calibrated", "terse", "none", "selective"),
  ("developing", "assertive", "exploratory", "miss_exception", "complete"),
  ("novice", "cautious", "structured", "reverse_causality", "sparse"),
  ("proficient", "calibrated", "plain", "answer_adjacent_question", "complete"),
  ("advanced", "assertive", "structured", "overgeneralize", "complete"),
)


def synthetic_personas(size: int, *, seed: int = 41) -> tuple[SyntheticPersona, ...]:
  if not 1 <= size <= len(_NAMES):
    raise ValueError(f"Synthetic cohorts must contain between 1 and {len(_NAMES)} students.")
  # Shuffle names and traits independently. A previous offset-based permutation
  # accidentally kept each name tied to the same traits across different seeds.
  names = list(_NAMES)
  traits = list(_TRAITS)
  Random(seed).shuffle(names)
  Random(seed ^ 0x5F3759DF).shuffle(traits)
  return tuple(
    SyntheticPersona(
      id=f"student-{index + 1:02d}",
      display_name=names[index],
      knowledge_level=traits[index][0],
      confidence=traits[index][1],
      answer_style=traits[index][2],
      error_tendency=traits[index][3],
      participation=traits[index][4],
    )
    for index in range(size)
  )


def synthetic_session_nonce(persona_id: str, *, seed: int) -> str:
  return f"{SYNTHETIC_SESSION_PREFIX}{seed}:{persona_id}"


def synthetic_participant_id(room_id: UUID, persona_id: str, *, seed: int) -> UUID:
  return uuid5(room_id, synthetic_session_nonce(persona_id, seed=seed))


def is_synthetic_participant(participant: Participant) -> bool:
  return participant.session_nonce.startswith(SYNTHETIC_SESSION_PREFIX)


def synthetic_identity(participant: Participant) -> tuple[int, str] | None:
  if not is_synthetic_participant(participant):
    return None
  encoded = participant.session_nonce.removeprefix(SYNTHETIC_SESSION_PREFIX)
  seed_text, separator, persona_id = encoded.partition(":")
  if not separator or not persona_id:
    return None
  try:
    seed = int(seed_text)
  except ValueError:
    return None
  return seed, persona_id
