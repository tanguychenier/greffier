"""Le fil publié pendant la réunion, et les corrections qui lui reviennent.

Deux processus se parlent par des fichiers : celui qui écoute publie ce qui se
dit, la fenêtre y dépose ses corrections. Tout est éprouvé ici sans audio, sans
modèle et sans écran — seules les doublures changent.
"""

from __future__ import annotations

import json
from pathlib import Path

from greffier.application.follow import (
    GENRE_CORRECTION,
    GENRE_SEPARATION,
    GENRE_TOUR,
    Follower,
    add,
    ask,
    files,
    position,
    read_from,
    replay,
    request_a_split,
)
from greffier.domain.channels import VOIX_LOCALE
from greffier.domain.live import NOM_LOCAL, Certainty, LiveThread
from greffier.domain.models import Person, Span, Utterance, Voiceprint
from greffier.domain.voiceprints import normalise


def voiceprint(x: float, y: float, duration: float = 8.0) -> Voiceprint:
    return normalise([x, y, 0.0], source_duration=duration)


def utterance(start: float, end: float, text: str = "on cale la recette jeudi") -> Utterance:
    return Utterance(span=Span(start, end), text=text)


class CanauxDits:
    """Dit d'avance quels passages viennent du micro."""

    def __init__(self, locaux: list[Span] | None = None) -> None:
        self.locaux = locaux or []

    def local_passages(self, audio: Path) -> list[Span]:
        return self.locaux


class ExtracteurDeSuite:
    """Rend les empreintes préparées, et retient ce qu'on lui a demandé."""

    def __init__(self, voiceprints: list[Voiceprint] | None = None) -> None:
        self.voiceprints = list(voiceprints or [])
        self.requests: list[list[Span]] = []

    def extract_spans(
        self, audio: Path, intervalles: list[Span]
    ) -> list[Voiceprint]:
        self.requests.append(intervalles)
        return [self.voiceprints.pop(0)] if self.voiceprints else []


class BanqueEnMemoire:
    def __init__(self, connues: list[Person] | None = None) -> None:
        self.connues = list(connues or [])
        self.recues: list[tuple[str, Voiceprint]] = []

    def people(self) -> list[Person]:
        return self.connues

    def record(self, name: str, e: Voiceprint) -> Person:
        self.recues.append((name, e))
        personne = Person(name=name, voiceprints=[e])
        self.connues.append(personne)
        return personne


def follower(tmp_path: Path, **overrides: object) -> Follower:
    log, requests = files(tmp_path, "2026-08-27_10h00_reunion")
    defauts: dict[str, object] = dict(
        thread=LiveThread(), log=log, requests=requests, channels=CanauxDits()
    )
    defauts.update(overrides)
    return Follower(**defauts)  # type: ignore[arg-type]


def lignes_du(log: Path) -> list[dict[str, object]]:
    lues, _ = read_from(log)
    return lues


class TestPositionDansLAudio:
    def test_le_dernier_morceau_est_celui_qu_on_suit(self, tmp_path: Path) -> None:
        chunks = [tmp_path / "a.wav", tmp_path / "b.wav"]
        ou = position(chunks, lambda m: 600.0 if m.name == "a.wav" else 30.0)
        assert ou is not None
        assert ou.morceau.name == "b.wav"
        assert ou.ecrit == 30.0

    def test_les_morceaux_precedents_donnent_l_heure_de_la_reunion(
        self, tmp_path: Path
    ) -> None:
        # Une pause coupe l'enregistrement en deux fichiers. Sans le cumul, la
        # reprise s'afficherait au début de la réunion.
        chunks = [tmp_path / "a.wav", tmp_path / "b.wav"]
        ou = position(chunks, lambda m: 600.0 if m.name == "a.wav" else 30.0)
        assert ou is not None
        assert ou.decalage == 600.0
        assert ou.overall == 630.0

    def test_un_morceau_pas_encore_ecrit_est_ignore(self, tmp_path: Path) -> None:
        chunks = [tmp_path / "a.wav", tmp_path / "b.wav"]
        ou = position(chunks, lambda m: 12.0 if m.name == "a.wav" else None)
        assert ou is not None and ou.morceau.name == "a.wav"

    def test_sans_audio_il_n_y_a_pas_de_position(self, tmp_path: Path) -> None:
        assert position([tmp_path / "a.wav"], lambda _m: None) is None
        assert position([], lambda _m: 10.0) is None


class TestLectureIncrementale:
    def test_on_ne_relit_que_ce_qui_a_ete_ajoute(self, tmp_path: Path) -> None:
        # La fenêtre relit quatre fois par seconde : relire une heure de réunion
        # à chaque tour coûterait pour rien.
        log = tmp_path / "fil.jsonl"
        add(log, [{"genre": GENRE_TOUR, "numero": 1}])
        premieres, ou = read_from(log)
        assert len(premieres) == 1
        add(log, [{"genre": GENRE_TOUR, "numero": 2}])
        suivantes, _ = read_from(log, ou)
        assert [x["numero"] for x in suivantes] == [2]

    def test_une_ligne_a_moitie_ecrite_attend_la_fois_suivante(self, tmp_path: Path) -> None:
        log = tmp_path / "fil.jsonl"
        entiere = '{"genre": "tour", "numero": 1}\n'
        log.write_text(entiere + '{"genre": "tou', encoding="utf-8")
        lues, ou = read_from(log)
        assert [x["numero"] for x in lues] == [1]
        # La position s'arrête à la dernière ligne complète : la suite sera lue
        # quand elle sera entière.
        assert ou == len(entiere)

    def test_un_journal_absent_ne_fait_pas_d_histoires(self, tmp_path: Path) -> None:
        assert read_from(tmp_path / "rien.jsonl") == ([], 0)


class TestPublication:
    def test_chaque_phrase_devient_une_ligne(self, tmp_path: Path) -> None:
        instance = follower(tmp_path)
        instance.take_in(
            tmp_path / "tranche.wav", [utterance(0, 4), utterance(4, 8)], decalage=0.0
        )
        lines = lignes_du(instance.log)
        assert [x["genre"] for x in lines] == [GENRE_TOUR, GENRE_TOUR]
        assert [x["numero"] for x in lines] == [1, 2]

    def test_le_micro_affiche_toi_sans_consulter_de_modele(self, tmp_path: Path) -> None:
        extractor = ExtracteurDeSuite()
        instance = follower(
            tmp_path,
            channels=CanauxDits([Span(0, 4)]),
            extractor=extractor,
        )
        instance.take_in(tmp_path / "tranche.wav", [utterance(0, 4)], decalage=0.0)
        assert instance.thread.turns[0].voice == VOIX_LOCALE
        assert instance.thread.label(VOIX_LOCALE) == NOM_LOCAL
        # Aucune empreinte prélevée : dépenser du calcul pour confirmer ce que le
        # câblage établit n'apporte rien.
        assert extractor.requests == []

    def test_l_empreinte_est_prelevee_aux_temps_de_la_tranche(self, tmp_path: Path) -> None:
        # L'affichage est à l'heure de la réunion, l'audio découpé ne l'est pas :
        # prélever à 1802 s dans une tranche de 10 s ne donnerait rien.
        extractor = ExtracteurDeSuite([voiceprint(1, 0)])
        instance = follower(tmp_path, extractor=extractor)
        instance.take_in(tmp_path / "tranche.wav", [utterance(2, 9)], decalage=1800.0)
        assert extractor.requests[0][0].start == 2.0
        assert instance.thread.turns[0].span.start == 1802.0

    def test_l_empreinte_evite_ce_que_le_micro_a_capte(self, tmp_path: Path) -> None:
        # La transcription coupe à la phrase, pas au changement de locuteur : un
        # passage distant peut porter la fin d'une phrase locale. Prélever sur le
        # tout mêlait deux voix, et faisait de la même personne deux participants.
        extractor = ExtracteurDeSuite([voiceprint(1, 0)])
        instance = follower(
            tmp_path,
            channels=CanauxDits([Span(9.5, 13.8)]),
            extractor=extractor,
        )
        instance.take_in(tmp_path / "tranche.wav", [utterance(13.2, 14.7)], decalage=0.0)
        assert extractor.requests[0] == [Span(13.8, 14.7)]

    def test_une_phrase_deja_affichee_ne_revient_pas(self, tmp_path: Path) -> None:
        # Les tranches se recouvrent de 5 s pour qu'une phrase à cheval reste
        # entière dans l'une des deux.
        instance = follower(tmp_path)
        instance.take_in(tmp_path / "t1.wav", [utterance(0, 8)], decalage=0.0)
        instance.take_in(
            tmp_path / "t2.wav", [utterance(0, 8), utterance(8, 12)], decalage=0.0
        )
        assert [t.number for t in instance.thread.turns] == [1, 2]
        assert instance.thread.turns[1].span.start == 8.0

    def test_une_voix_de_la_banque_est_nommee_des_la_premiere_phrase(
        self, tmp_path: Path
    ) -> None:
        marc = Person(name="Marc", voiceprints=[voiceprint(1, 0, duration=30)])
        instance = follower(
            tmp_path,
            thread=LiveThread(connues=[marc]),
            extractor=ExtracteurDeSuite([voiceprint(1, 0)]),
        )
        instance.take_in(tmp_path / "tranche.wav", [utterance(0, 8)], decalage=0.0)
        assert lignes_du(instance.log)[0]["nom"] == "Marc"

    def test_un_modele_qui_tombe_n_interrompt_pas_la_reunion(self, tmp_path: Path) -> None:
        class Casse:
            def extract_spans(self, audio: Path, intervalles: list[Span]):
                raise RuntimeError("BroadcastIterator::Init")

        instance = follower(tmp_path, extractor=Casse())
        instance.take_in(tmp_path / "tranche.wav", [utterance(0, 8)], decalage=0.0)
        # La phrase s'affiche sans nom, et se corrige d'un clic.
        assert len(instance.thread.turns) == 1


class TestCorrectionsRecues:
    def _un_fil(self, tmp_path: Path) -> Follower:
        instance = follower(
            tmp_path,
            extractor=ExtracteurDeSuite([voiceprint(1, 0)]),
            bank=BanqueEnMemoire(),
        )
        instance.take_in(tmp_path / "tranche.wav", [utterance(0, 8)], decalage=0.0)
        return instance

    def test_une_correction_deposee_est_appliquee(self, tmp_path: Path) -> None:
        instance = self._un_fil(tmp_path)
        ask(instance.requests, number=1, name="Marc")
        faites = instance.apply_requests()
        assert [c.name for c in faites] == ["Marc"]
        assert instance.thread.label(instance.thread.turns[0].voice) == "Marc"

    def test_la_correction_est_confirmee_dans_le_journal(self, tmp_path: Path) -> None:
        # C'est ainsi que la fenêtre sait que sa correction a été prise, et que
        # toute autre fenêtre ouverte l'apprend aussi.
        instance = self._un_fil(tmp_path)
        ask(instance.requests, number=1, name="Marc")
        instance.apply_requests()
        confirmations = [
            x for x in lignes_du(instance.log) if x["genre"] == GENRE_CORRECTION
        ]
        assert confirmations[0]["nom"] == "Marc"
        assert confirmations[0]["numeros"] == [1]

    def test_une_correction_verse_l_empreinte_en_banque(self, tmp_path: Path) -> None:
        # Le point de tout l'échange : corriger une fois pendant la réunion, et
        # que le compte rendu final retrouve la personne tout seul.
        bank = BanqueEnMemoire()
        instance = follower(
            tmp_path,
            extractor=ExtracteurDeSuite([voiceprint(1, 0)]),
            bank=bank,
        )
        instance.take_in(tmp_path / "tranche.wav", [utterance(0, 8)], decalage=0.0)
        ask(instance.requests, number=1, name="Marc")
        instance.apply_requests()
        assert [name for name, _ in bank.recues] == ["Marc"]

    def test_toi_n_entre_jamais_en_banque(self, tmp_path: Path) -> None:
        # Le micro identifie déjà la personne qui enregistre : stocker sa voix
        # comme celle d'un participant n'apporterait rien et l'exposerait.
        bank = BanqueEnMemoire()
        instance = follower(tmp_path, channels=CanauxDits([Span(0, 8)]), bank=bank)
        instance.take_in(tmp_path / "tranche.wav", [utterance(0, 8)], decalage=0.0)
        ask(instance.requests, number=1, name="Tanguy")
        instance.apply_requests()
        assert bank.recues == []

    def test_une_voix_corrigee_trop_tot_est_apprise_des_qu_elle_a_de_quoi(
        self, tmp_path: Path
    ) -> None:
        """Le défaut qui vidait la banque de voix.

        On corrige dès la première phrase — c'est le but — quand l'empreinte n'a
        pas encore la matière du seuil. Refuser une fois pour toutes perdait la
        correction : elle s'affichait, puis ne servait ni à la réunion suivante
        ni au compte rendu.
        """
        bank = BanqueEnMemoire()
        instance = follower(
            tmp_path,
            extractor=ExtracteurDeSuite(
                # 2,5 s : de quoi fonder une voix (le plancher est à 2,0 s,
                # mesuré) mais pas de quoi la verser en banque.
                [voiceprint(1, 0, duration=2.5), voiceprint(0.95, 0.31, duration=4.0)]
            ),
            bank=bank,
        )
        instance.take_in(tmp_path / "t1.wav", [utterance(0, 2)], decalage=0.0)
        ask(instance.requests, number=1, name="Sandy")
        instance.apply_requests()
        # Trop peu de matière pour apprendre quoi que ce soit d'utile.
        assert bank.recues == []
        # La personne reparle : cette fois il y a de quoi.
        instance.take_in(tmp_path / "t2.wav", [utterance(3, 9)], decalage=0.0)
        assert [name for name, _ in bank.recues] == ["Sandy"]

    def test_une_voix_n_est_apprise_qu_une_fois(self, tmp_path: Path) -> None:
        bank = BanqueEnMemoire()
        instance = follower(
            tmp_path,
            extractor=ExtracteurDeSuite([voiceprint(1, 0), voiceprint(0.95, 0.31)]),
            bank=bank,
        )
        instance.take_in(tmp_path / "t1.wav", [utterance(0, 8)], decalage=0.0)
        ask(instance.requests, number=1, name="Sandy")
        instance.apply_requests()
        instance.take_in(tmp_path / "t2.wav", [utterance(9, 17)], decalage=0.0)
        assert [name for name, _ in bank.recues] == ["Sandy"]

    def test_une_demande_qui_ne_correspond_a_rien_est_ignoree(self, tmp_path: Path) -> None:
        instance = self._un_fil(tmp_path)
        ask(instance.requests, number=99, name="Marc")
        ask(instance.requests, number=1, name="  ")
        assert instance.apply_requests() == []

    def test_une_demande_n_est_appliquee_qu_une_fois(self, tmp_path: Path) -> None:
        instance = self._un_fil(tmp_path)
        ask(instance.requests, number=1, name="Marc")
        assert len(instance.apply_requests()) == 1
        assert instance.apply_requests() == []

    def test_les_phrases_suivantes_portent_le_nom_corrige(self, tmp_path: Path) -> None:
        instance = follower(
            tmp_path,
            extractor=ExtracteurDeSuite([voiceprint(1, 0), voiceprint(0.9, 0.44)]),
            bank=BanqueEnMemoire(),
        )
        instance.take_in(tmp_path / "t1.wav", [utterance(0, 8)], decalage=0.0)
        ask(instance.requests, number=1, name="Marc")
        instance.take_in(tmp_path / "t2.wav", [utterance(9, 17)], decalage=0.0)
        assert lignes_du(instance.log)[-1]["nom"] == "Marc"


class TestRejouerPourAfficher:
    def test_le_fil_se_reconstruit_depuis_le_journal(self, tmp_path: Path) -> None:
        instance = follower(tmp_path, extractor=ExtracteurDeSuite([voiceprint(1, 0)]))
        instance.take_in(
            tmp_path / "t.wav", [utterance(0, 4, "bonjour"), utterance(4, 8)], decalage=0.0
        )
        rejoue = replay(lignes_du(instance.log))
        assert [t.text for t in rejoue.turns] == ["bonjour", "on cale la recette jeudi"]
        assert rejoue.label(rejoue.turns[0].voice) == "Voix 1"

    def test_une_correction_du_journal_renomme_les_phrases_passees(
        self, tmp_path: Path
    ) -> None:
        instance = follower(
            tmp_path,
            extractor=ExtracteurDeSuite([voiceprint(1, 0)]),
            bank=BanqueEnMemoire(),
        )
        instance.take_in(tmp_path / "t.wav", [utterance(0, 8)], decalage=0.0)
        ask(instance.requests, number=1, name="Marc")
        instance.apply_requests()
        rejoue = replay(lignes_du(instance.log))
        assert rejoue.label(rejoue.turns[0].voice) == "Marc"
        assert rejoue.voice[rejoue.turns[0].voice].certitude is Certainty.HUMAINE

    def test_rejouer_deux_fois_ne_duplique_pas_les_phrases(self, tmp_path: Path) -> None:
        # La fenêtre lit par morceaux : un chevauchement ne doit pas afficher la
        # même phrase deux fois.
        instance = follower(tmp_path)
        instance.take_in(tmp_path / "t.wav", [utterance(0, 8)], decalage=0.0)
        lines = lignes_du(instance.log)
        thread = replay(lines)
        replay(lines, thread)
        assert len(thread.turns) == 1

    def test_une_ligne_abimee_n_empeche_pas_de_lire_les_autres(
        self, tmp_path: Path
    ) -> None:
        log = tmp_path / "fil.jsonl"
        log.write_text(
            "ceci n'est pas du json\n"
            + json.dumps({"genre": GENRE_TOUR, "numero": 1, "debut": 0, "fin": 2,
                          "texte": "bonjour", "voix": "v1", "nom": None,
                          "certitude": "inconnue", "rang": 1})
            + "\n",
            encoding="utf-8",
        )
        assert len(replay(lignes_du(log)).turns) == 1


class TestDeuxFichiers:
    def test_chacun_ecrit_dans_le_sien(self, tmp_path: Path) -> None:
        # Aucun verrou à poser : celui qui écoute écrit le journal et lit les
        # demandes, la fenêtre fait l'inverse.
        log, requests = files(tmp_path, "2026-08-27_10h00_reunion")
        assert log != requests
        assert log.parent == requests.parent


class TestSeparationEntreLesDeuxProcessus:
    """La séparation traverse les deux processus, comme une correction.

    La fenêtre l'affiche tout de suite, mais c'est le processus qui écoute qui
    tient les empreintes : lui seul peut les rendre à chaque voix, et c'est de
    ça que dépend ce qui entrera en banque de voix.
    """

    def _deux_voix_reunies(self, tmp_path: Path) -> Follower:
        instance = follower(
            tmp_path,
            extractor=ExtracteurDeSuite([voiceprint(1, 0), voiceprint(0, 1)]),
            bank=BanqueEnMemoire(),
        )
        instance.take_in(
            tmp_path / "un.wav", [utterance(0, 8, "on cale la recette jeudi")],
            decalage=0.0,
        )
        instance.take_in(
            tmp_path / "deux.wav", [utterance(9, 17, "le devis part demain matin")],
            decalage=0.0,
        )
        assert len({t.voice for t in instance.thread.turns}) == 2, "deux voix distinctes"
        ask(instance.requests, number=1, name="Tanguy")
        ask(instance.requests, number=2, name="Tanguy")
        instance.apply_requests()
        assert len({t.voice for t in instance.thread.turns}) == 1, "réunies"
        return instance

    def test_une_separation_deposee_est_appliquee(self, tmp_path: Path) -> None:
        instance = self._deux_voix_reunies(tmp_path)
        gardee = instance.thread.turns[0].voice
        request_a_split(instance.requests, gardee)
        instance.apply_requests()
        assert len({t.voice for t in instance.thread.turns}) == 2

    def test_la_separation_est_confirmee_dans_le_journal(self, tmp_path: Path) -> None:
        # C'est ainsi que toute autre fenêtre ouverte, et un fil repris après
        # un plantage, apprennent que ces deux voix ne sont pas la même.
        instance = self._deux_voix_reunies(tmp_path)
        gardee = instance.thread.turns[0].voice
        request_a_split(instance.requests, gardee)
        instance.apply_requests()
        dites = [
            x for x in lignes_du(instance.log) if x["genre"] == GENRE_SEPARATION
        ]
        assert len(dites) == 1
        assert dites[0]["de"] == gardee
        assert dites[0]["numeros"] == [2]

    def test_un_fil_rejoue_garde_les_voix_separees(self, tmp_path: Path) -> None:
        """Le point qui fait tout : une reprise de fil ne refait pas la fusion."""
        instance = self._deux_voix_reunies(tmp_path)
        gardee = instance.thread.turns[0].voice
        request_a_split(instance.requests, gardee)
        instance.apply_requests()
        repris = replay(lignes_du(instance.log))
        assert len({t.voice for t in repris.turns}) == 2
        assert repris.split_apart, "la paire doit rester tenue à part"

    def test_chaque_empreinte_revient_a_sa_voix(self, tmp_path: Path) -> None:
        instance = self._deux_voix_reunies(tmp_path)
        gardee = instance.thread.turns[0].voice
        request_a_split(instance.requests, gardee)
        instance.apply_requests()
        comptes = {
            i: len(v.voiceprints)
            for i, v in instance.thread.voice.items()
            if v.voiceprints
        }
        assert sorted(comptes.values()) == [1, 1], comptes

    def test_separer_ce_qui_n_a_rien_absorbe_ne_dit_rien(self, tmp_path: Path) -> None:
        instance = self._deux_voix_reunies(tmp_path)
        request_a_split(instance.requests, "voix-jamais-vue")
        instance.apply_requests()
        assert not [
            x for x in lignes_du(instance.log) if x["genre"] == GENRE_SEPARATION
        ]


class TestPorteeDeLaCorrectionRejouee:
    """La portée d'une correction voyage dans le journal, elle ne se déduit pas.

    Le défaut : la ligne ne portait que les numéros touchés, et le rejeu en
    tirait la portée. Une correction « toute la voix » saisie alors que la voix
    n'avait qu'un seul tour se rejouait donc en « seulement cette phrase », et à
    la reprise du fil les tours suivants de cette voix perdaient le nom.
    Rencontré pour de vrai : un fil de six cent quarante-six tours repris à la
    cinquantième minute.
    """

    def _log(self, tmp_path: Path, whole_voice: bool | None = None) -> Path:
        log, _ = files(tmp_path, "2026-09-10_10h10_reunion")
        correction: dict[str, object] = {
            "genre": GENRE_CORRECTION, "nom": "Marc", "voix": "v1", "numeros": [1],
        }
        if whole_voice is not None:
            correction["toute_la_voix"] = whole_voice
        add(log, [
            {"genre": GENRE_TOUR, "numero": 1, "debut": 0.0, "fin": 8.0,
             "texte": "on cale la recette jeudi", "voix": "v1",
             "nom": None, "certitude": Certainty.INCONNUE.value, "rang": 1},
            correction,
            {"genre": GENRE_TOUR, "numero": 2, "debut": 9.0, "fin": 17.0,
             "texte": "le devis part demain matin", "voix": "v1",
             "nom": None, "certitude": Certainty.INCONNUE.value, "rang": 1},
        ])
        return log

    def test_toute_la_voix_couvre_les_tours_qui_arrivent_apres(
        self, tmp_path: Path
    ) -> None:
        repris = replay(lignes_du(self._log(tmp_path, True)))
        names = {repris.label(t.voice) for t in repris.turns}
        assert names == {"Marc"}, names

    def test_seulement_cette_phrase_ne_couvre_que_la_phrase(
        self, tmp_path: Path
    ) -> None:
        repris = replay(lignes_du(self._log(tmp_path, False)))
        par_numero = {t.number: repris.label(t.voice) for t in repris.turns}
        assert par_numero[1] == "Marc"
        assert par_numero[2] != "Marc"

    def test_un_journal_d_avant_reste_lisible(self, tmp_path: Path) -> None:
        """Sans le champ : on retombe sur l'ancienne déduction, faute de mieux."""
        repris = replay(lignes_du(self._log(tmp_path)))
        assert repris.turns, "le journal doit rester relisible"


class TestIdentifiantsJamaisReutilises:
    """Un fil repris ne doit jamais redistribuer un identifiant déjà porté.

    Le défaut, silencieux : le rejeu du journal inscrivait les voix « v1 »,
    « v2 »… directement, sans avancer le compteur. La voix suivante que le fil
    fondait s'appelait donc « v1 » de nouveau et **écrasait** l'entrée
    existante : les tours de deux personnes passaient sous un seul identifiant,
    sans rien qui le signale. Toute reprise de fil était touchée — et il y en a
    eu une sur un fil de six cent quarante-six tours.
    """

    def _journal_a_deux_voix(self, tmp_path: Path) -> Path:
        log, _ = files(tmp_path, "2026-09-10_10h10_reunion")
        add(log, [
            {"genre": GENRE_TOUR, "numero": number, "debut": float(number * 10),
             "fin": float(number * 10 + 8), "texte": f"phrase {number}",
             "voix": f"v{number}", "nom": None,
             "certitude": Certainty.INCONNUE.value, "rang": number}
            for number in (1, 2, 3)
        ])
        return log

    def test_le_compteur_repart_apres_la_derniere_voix_du_journal(
        self, tmp_path: Path
    ) -> None:
        repris = replay(lignes_du(self._journal_a_deux_voix(tmp_path)))
        assert repris._identifier() == "v4"

    def test_une_correction_de_phrase_n_ecrase_aucune_voix(
        self, tmp_path: Path
    ) -> None:
        """Le symptôme visible : trois voix rejouées, une correction, toujours
        trois personnes distinctes — et non deux tours sous le même nom."""
        repris = replay(lignes_du(self._journal_a_deux_voix(tmp_path)))
        avant = {t.number: t.voice for t in repris.turns}
        repris.correct(2, "Marc", whole_voice=False)
        apres = {t.number: t.voice for t in repris.turns}
        assert apres[1] == avant[1], "la phrase 1 a changé de voix"
        assert apres[3] == avant[3], "la phrase 3 a changé de voix"
        assert len(set(apres.values())) == 3, apres
