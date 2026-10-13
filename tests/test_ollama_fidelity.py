"""Evidence checks must refuse the failures seen with two real local models."""

from __future__ import annotations

import pytest

from greffier.adapters.ollama_fidelity import violations
from greffier.adapters.writer_ollama import OllamaWriter, UnfaithfulMinutesError

SOURCE = (
    "[Jacques]\n00:00 Bonjour Sophie, nous faisons le point sur la recette.\n"
    "[Sophie]\n00:08 Les deux anomalies sont corrigées mais pas encore validées.\n"
    "[Jacques]\n00:16 On décale la recette à jeudi prochain. "
    "Nous préviendrons les utilisateurs mercredi en fin de journée.\n"
)
PARTICIPANTS = (
    "| Nom | Rôle |\n|---|---|\n"
    "| Jacques | rôle non précisé |\n| Sophie | rôle non précisé |\n\n"
)
GOOD = PARTICIPANTS + (
    "| Quoi | Qui | Quand |\n|---|---|---|\n"
    "| Prévenir les utilisateurs | Responsable non précisé | Mercredi en fin de journée |"
)
BAD = GOOD.replace("Responsable non précisé", "Sophie")


@pytest.mark.parametrize("source", [SOURCE, SOURCE.replace("00:16", "00:01:16")])
def test_a_collective_action_with_no_named_owner_passes(source):
    assert violations(source, GOOD) == []


@pytest.mark.parametrize("owner", ["Jacques", "Sophie", "**Sophie**"])
def test_a_collective_action_has_no_single_named_owner(owner):
    report = GOOD.replace("Responsable non précisé", owner)
    assert "collective" in " ".join(violations(SOURCE, report))


@pytest.mark.parametrize("role", ["Président", "Rapporteur", "Responsable de la recette"])
def test_an_asserted_role_needs_evidence(role):
    assert violations(SOURCE, GOOD.replace("rôle non précisé", role))


def test_an_inferred_role_is_marked_as_uncertain():
    assert violations(SOURCE, GOOD.replace("rôle non précisé", "animateur à confirmer")) == []


def test_an_explicit_role_can_be_reported():
    source = SOURCE.replace("Bonjour Sophie", "Je suis responsable de la recette. Bonjour Sophie")
    report = GOOD.replace("Jacques | rôle non précisé", "Jacques | responsable de la recette")
    assert violations(source, report) == []


@pytest.mark.parametrize("extra", ["Personne N", "Personne 3", "Maud"])
def test_an_extra_participant_is_not_inferred(extra):
    report = GOOD.replace("| Sophie |", f"| {extra} |")
    assert "participant" in " ".join(violations(SOURCE, report))


def test_a_first_person_commitment_can_have_a_named_owner():
    source = SOURCE.replace("Nous préviendrons", "Je préviendrai")
    report = GOOD.replace("Responsable non précisé", "Jacques")
    assert violations(source, report) == []


def test_the_word_nous_as_an_object_does_not_make_a_commitment_collective():
    source = SOURCE.replace("Nous préviendrons les utilisateurs", "Sophie nous préviendra")
    assert violations(source, BAD) == []


def test_an_unrelated_collective_sentence_does_not_own_another_task():
    source = SOURCE.replace("Nous préviendrons", "Je préviendrai")
    assert violations(source, GOOD.replace("Responsable non précisé", "Sophie")) == []


def test_missing_participants_are_reported():
    assert violations(SOURCE, "# Un résumé sans tableau")


def test_a_plain_prompt_cannot_be_treated_as_an_attributed_transcript():
    assert violations("Une question simple", "Une réponse simple") == []


def test_a_new_response_can_correct_the_rejected_one(monkeypatch):
    writer = OllamaWriter("local")
    responses = iter((BAD, GOOD))
    requests = []

    def answer(prompt):
        requests.append(prompt)
        return next(responses)

    monkeypatch.setattr(writer, "_generate", answer)
    assert writer.write_up(SOURCE) == GOOD
    assert len(requests) == 2
    assert "action collective" in requests[1]
    assert SOURCE in requests[1]


def test_a_repeated_unsupported_attribution_is_refused(monkeypatch):
    writer = OllamaWriter("local")
    requests = []
    monkeypatch.setattr(writer, "_generate", lambda prompt: (requests.append(prompt), BAD)[1])
    with pytest.raises(UnfaithfulMinutesError, match="Compte rendu non validé"):
        writer.write_up(SOURCE)
    assert len(requests) == 2


def test_conversation_answers_keep_their_own_contract(monkeypatch):
    writer = OllamaWriter("local", own_guidance="Réponds à la question.")
    requests = []
    monkeypatch.setattr(writer, "_generate", lambda prompt: (requests.append(prompt), "Oui.")[1])
    assert writer.write_up(SOURCE) == "Oui."
    assert len(requests) == 1


def test_one_speakers_explicit_role_is_not_given_to_another():
    source = SOURCE.replace("Bonjour Sophie", "Je suis responsable de la recette. Bonjour Sophie")
    report = GOOD.replace("Sophie | rôle non précisé", "Sophie | responsable de la recette")
    assert violations(source, report)


def test_a_collective_commitment_after_an_address_still_has_no_named_owner():
    source = SOURCE.replace("On décale", "Merci Sophie, on décale").replace(
        "prochain. Nous préviendrons", "prochain et nous préviendrons",
    )
    assert "collective" in " ".join(violations(source, BAD))


def test_an_unmentioned_owner_is_refused():
    report = GOOD.replace("Responsable non précisé", "Maud")
    assert "responsable" in " ".join(violations(SOURCE, report))


@pytest.mark.parametrize("owner", ["Collectif", "Tous", "Équipe", "À définir", "-"])
def test_generic_or_unspecified_owners_are_not_invented_people(owner):
    assert violations(SOURCE, GOOD.replace("Responsable non précisé", owner)) == []


def test_another_language_keeps_the_existing_writers_contract(monkeypatch):
    writer = OllamaWriter("local", language="es")
    monkeypatch.setattr(writer, "_generate", lambda _: "Un resumen en otra lengua.")
    assert writer.write_up(SOURCE) == "Un resumen en otra lengua."


@pytest.mark.parametrize("owner", [
    "Collectif (Jacques)", "Collectif Jacques", "Équipe de Sophie",
    "Responsable non précisé (Jacques)", "Jacques et Sophie", "**Collectif (Sophie)**",
])
def test_a_collective_label_cannot_hide_named_owners(owner):
    report = GOOD.replace("Responsable non précisé", owner)
    assert "action collective" in " ".join(violations(SOURCE, report))


@pytest.mark.parametrize("owner", ["Collectif (Maud)", "Équipe imaginaire", "Team Maud"])
def test_a_generic_prefix_cannot_hide_an_unmentioned_owner(owner):
    report = GOOD.replace("Responsable non précisé", owner)
    assert "responsable" in " ".join(violations(SOURCE, report))


def test_wrapped_collective_owners_are_refused_after_the_correction_attempt(monkeypatch):
    writer = OllamaWriter("local")
    report = GOOD.replace("Responsable non précisé", "Collectif (Jacques)")
    monkeypatch.setattr(writer, "_generate", lambda _: report)
    with pytest.raises(UnfaithfulMinutesError, match="action collective"):
        writer.write_up(SOURCE)
