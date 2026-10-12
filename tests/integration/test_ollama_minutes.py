"""The local writer must not turn a collective promise into a named owner.

Run explicitly with GREFFIER_TEST_OLLAMA_MODEL naming an installed local model.
No recording, account or external server is used.
"""

from __future__ import annotations

import os

import pytest

from greffier.adapters.writer_ollama import (
    OllamaWriter,
    UnfaithfulMinutesError,
    available_models,
)

pytestmark = pytest.mark.integration


def test_a_collective_commitment_is_faithful_or_explicitly_refused(tmp_path):
    model = os.environ.get("GREFFIER_TEST_OLLAMA_MODEL", "")
    if not model or model not in available_models():
        pytest.skip("aucun modèle local explicitement choisi pour cet essai")
    transcript = (
        "[Jacques]\n00:00 Bonjour Sophie, nous faisons le point sur la recette.\n"
        "[Sophie]\n00:08 Les deux anomalies sont corrigées mais pas encore validées.\n"
        "[Jacques]\n00:16 On décale la recette à jeudi prochain. "
        "Nous préviendrons les utilisateurs mercredi en fin de journée.\n"
    )
    try:
        result = OllamaWriter(model).write_up(transcript)
    except UnfaithfulMinutesError as rejected:
        (tmp_path / "refusal.txt").write_text(str(rejected))
        return
    (tmp_path / "minutes.md").write_text(result)
    lowered = result.lower()
    actions = [line for line in lowered.splitlines()
               if line.lstrip().startswith("|") and "mercredi" in line]
    assert actions, result
    assert all("jacques" not in line and "sophie" not in line for line in actions), result
    assert "président" not in lowered and "rapporteur" not in lowered, result
    inferred = [line for line in lowered.splitlines()
                if line.lstrip().startswith("|") and ("jacques" in line or "sophie" in line)]
    assert inferred, result
    assert all("non précisé" in line or "à confirmer" in line for line in inferred), result
