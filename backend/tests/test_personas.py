from __future__ import annotations

import pytest

from junto.services.personas import synthetic_personas


def test_persona_catalog_is_deterministic_unique_and_varied() -> None:
  first = synthetic_personas(20, seed=41)
  repeated = synthetic_personas(20, seed=41)

  assert first == repeated
  assert len({persona.id for persona in first}) == 20
  assert len({persona.display_name for persona in first}) == 20
  assert {persona.knowledge_level for persona in first} == {
    "novice",
    "developing",
    "proficient",
    "advanced",
  }
  assert {persona.participation for persona in first} == {
    "complete",
    "selective",
    "sparse",
  }
  assert "none" in {persona.error_tendency for persona in first}
  assert len({persona.error_tendency for persona in first} - {"none"}) >= 5


def test_seed_changes_name_to_trait_pairings_without_changing_identity_pool() -> None:
  first = synthetic_personas(20, seed=41)
  second = synthetic_personas(20, seed=42)
  first_by_name = {persona.display_name: persona for persona in first}
  second_by_name = {persona.display_name: persona for persona in second}

  assert set(first_by_name) == set(second_by_name)
  assert any(
    (
      first_by_name[name].knowledge_level,
      first_by_name[name].error_tendency,
      first_by_name[name].answer_style,
    )
    != (
      second_by_name[name].knowledge_level,
      second_by_name[name].error_tendency,
      second_by_name[name].answer_style,
    )
    for name in first_by_name
  )


@pytest.mark.parametrize("size", [0, 21])
def test_persona_catalog_rejects_unsupported_cohort_sizes(size: int) -> None:
  with pytest.raises(ValueError, match="between 1 and 20"):
    synthetic_personas(size)
