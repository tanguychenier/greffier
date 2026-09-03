"""Le fil publié pendant la réunion, et les corrections qui lui reviennent.

Deux processus se parlent par des fichiers : celui qui écoute publie ce qui se
dit, la fenêtre y dépose ses corrections. Tout est éprouvé ici sans audio, sans
modèle et sans écran — seules les doublures changent.
"""

from __future__ import annotations

import json
from pathlib import Path

from greffier.application.suivre import (
    GENRE_CORRECTION,
    GENRE_TOUR,
    Suivi,
    ajouter,
    demander,
    fichiers,
    lire_depuis,
    position,
    rejouer,
)
from greffier.domaine.canaux import VOIX_LOCALE
from greffier.domaine.direct import NOM_LOCAL, Certitude, Fil
from greffier.domaine.empreintes import normaliser
from greffier.domaine.modeles import Empreinte, Intervalle, Personne, Replique


def empreinte(x: float, y: float, duree: float = 8.0) -> Empreinte:
    return normaliser([x, y, 0.0], duree_source=duree)


def replique(debut: float, fin: float, texte: str = "on cale la recette jeudi") -> Replique:
    return Replique(intervalle=Intervalle(debut, fin), texte=texte)


class CanauxDits:
    """Dit d'avance quels passages viennent du micro."""

    def __init__(self, locaux: list[Intervalle] | None = None) -> None:
        self.locaux = locaux or []

    def passages_locaux(self, audio: Path) -> list[Intervalle]:
        return self.locaux


class ExtracteurDeSuite:
    """Rend les empreintes préparées, et retient ce qu'on lui a demandé."""

    def __init__(self, empreintes: list[Empreinte] | None = None) -> None:
        self.empreintes = list(empreintes or [])
        self.demandes: list[list[Intervalle]] = []

    def extraire_intervalles(
        self, audio: Path, intervalles: list[Intervalle]
    ) -> list[Empreinte]:
        self.demandes.append(intervalles)
        return [self.empreintes.pop(0)] if self.empreintes else []


class BanqueEnMemoire:
    def __init__(self, connues: list[Personne] | None = None) -> None:
        self.connues = list(connues or [])
        self.recues: list[tuple[str, Empreinte]] = []

    def personnes(self) -> list[Personne]:
        return self.connues

    def enregistrer(self, nom: str, e: Empreinte) -> Personne:
        self.recues.append((nom, e))
        personne = Personne(nom=nom, empreintes=[e])
        self.connues.append(personne)
        return personne


def suivi(tmp_path: Path, **remplacements: object) -> Suivi:
    journal, demandes = fichiers(tmp_path, "2026-08-27_10h00_reunion")
    defauts: dict[str, object] = dict(
        fil=Fil(), journal=journal, demandes=demandes, canaux=CanauxDits()
    )
    defauts.update(remplacements)
    return Suivi(**defauts)  # type: ignore[arg-type]


def lignes_du(journal: Path) -> list[dict[str, object]]:
    lues, _ = lire_depuis(journal)
    return lues


class TestPositionDansLAudio:
    def test_le_dernier_morceau_est_celui_qu_on_suit(self, tmp_path: Path) -> None:
        morceaux = [tmp_path / "a.wav", tmp_path / "b.wav"]
        ou = position(morceaux, lambda m: 600.0 if m.name == "a.wav" else 30.0)
        assert ou is not None
        assert ou.morceau.name == "b.wav"
        assert ou.ecrit == 30.0

    def test_les_morceaux_precedents_donnent_l_heure_de_la_reunion(
        self, tmp_path: Path
    ) -> None:
        # Une pause coupe l'enregistrement en deux fichiers. Sans le cumul, la
        # reprise s'afficherait au début de la réunion.
        morceaux = [tmp_path / "a.wav", tmp_path / "b.wav"]
        ou = position(morceaux, lambda m: 600.0 if m.name == "a.wav" else 30.0)
        assert ou is not None
        assert ou.decalage == 600.0
        assert ou.globale == 630.0

    def test_un_morceau_pas_encore_ecrit_est_ignore(self, tmp_path: Path) -> None:
        morceaux = [tmp_path / "a.wav", tmp_path / "b.wav"]
        ou = position(morceaux, lambda m: 12.0 if m.name == "a.wav" else None)
        assert ou is not None and ou.morceau.name == "a.wav"

    def test_sans_audio_il_n_y_a_pas_de_position(self, tmp_path: Path) -> None:
        assert position([tmp_path / "a.wav"], lambda _m: None) is None
        assert position([], lambda _m: 10.0) is None


class TestLectureIncrementale:
    def test_on_ne_relit_que_ce_qui_a_ete_ajoute(self, tmp_path: Path) -> None:
        # La fenêtre relit quatre fois par seconde : relire une heure de réunion
        # à chaque tour coûterait pour rien.
        journal = tmp_path / "fil.jsonl"
        ajouter(journal, [{"genre": GENRE_TOUR, "numero": 1}])
        premieres, ou = lire_depuis(journal)
        assert len(premieres) == 1
        ajouter(journal, [{"genre": GENRE_TOUR, "numero": 2}])
        suivantes, _ = lire_depuis(journal, ou)
        assert [x["numero"] for x in suivantes] == [2]

    def test_une_ligne_a_moitie_ecrite_attend_la_fois_suivante(self, tmp_path: Path) -> None:
        journal = tmp_path / "fil.jsonl"
        entiere = '{"genre": "tour", "numero": 1}\n'
        journal.write_text(entiere + '{"genre": "tou', encoding="utf-8")
        lues, ou = lire_depuis(journal)
        assert [x["numero"] for x in lues] == [1]
        # La position s'arrête à la dernière ligne complète : la suite sera lue
        # quand elle sera entière.
        assert ou == len(entiere)

    def test_un_journal_absent_ne_fait_pas_d_histoires(self, tmp_path: Path) -> None:
        assert lire_depuis(tmp_path / "rien.jsonl") == ([], 0)


class TestPublication:
    def test_chaque_phrase_devient_une_ligne(self, tmp_path: Path) -> None:
        instance = suivi(tmp_path)
        instance.accueillir(
            tmp_path / "tranche.wav", [replique(0, 4), replique(4, 8)], decalage=0.0
        )
        lignes = lignes_du(instance.journal)
        assert [x["genre"] for x in lignes] == [GENRE_TOUR, GENRE_TOUR]
        assert [x["numero"] for x in lignes] == [1, 2]

    def test_le_micro_affiche_toi_sans_consulter_de_modele(self, tmp_path: Path) -> None:
        extracteur = ExtracteurDeSuite()
        instance = suivi(
            tmp_path,
            canaux=CanauxDits([Intervalle(0, 4)]),
            extracteur=extracteur,
        )
        instance.accueillir(tmp_path / "tranche.wav", [replique(0, 4)], decalage=0.0)
        assert instance.fil.tours[0].voix == VOIX_LOCALE
        assert instance.fil.etiquette(VOIX_LOCALE) == NOM_LOCAL
        # Aucune empreinte prélevée : dépenser du calcul pour confirmer ce que le
        # câblage établit n'apporte rien.
        assert extracteur.demandes == []

    def test_l_empreinte_est_prelevee_aux_temps_de_la_tranche(self, tmp_path: Path) -> None:
        # L'affichage est à l'heure de la réunion, l'audio découpé ne l'est pas :
        # prélever à 1802 s dans une tranche de 10 s ne donnerait rien.
        extracteur = ExtracteurDeSuite([empreinte(1, 0)])
        instance = suivi(tmp_path, extracteur=extracteur)
        instance.accueillir(tmp_path / "tranche.wav", [replique(2, 9)], decalage=1800.0)
        assert extracteur.demandes[0][0].debut == 2.0
        assert instance.fil.tours[0].intervalle.debut == 1802.0

    def test_l_empreinte_evite_ce_que_le_micro_a_capte(self, tmp_path: Path) -> None:
        # La transcription coupe à la phrase, pas au changement de locuteur : un
        # passage distant peut porter la fin d'une phrase locale. Prélever sur le
        # tout mêlait deux voix, et faisait de la même personne deux participants.
        extracteur = ExtracteurDeSuite([empreinte(1, 0)])
        instance = suivi(
            tmp_path,
            canaux=CanauxDits([Intervalle(9.5, 13.8)]),
            extracteur=extracteur,
        )
        instance.accueillir(tmp_path / "tranche.wav", [replique(13.2, 14.7)], decalage=0.0)
        assert extracteur.demandes[0] == [Intervalle(13.8, 14.7)]

    def test_une_phrase_deja_affichee_ne_revient_pas(self, tmp_path: Path) -> None:
        # Les tranches se recouvrent de 5 s pour qu'une phrase à cheval reste
        # entière dans l'une des deux.
        instance = suivi(tmp_path)
        instance.accueillir(tmp_path / "t1.wav", [replique(0, 8)], decalage=0.0)
        instance.accueillir(
            tmp_path / "t2.wav", [replique(0, 8), replique(8, 12)], decalage=0.0
        )
        assert [t.numero for t in instance.fil.tours] == [1, 2]
        assert instance.fil.tours[1].intervalle.debut == 8.0

    def test_une_voix_de_la_banque_est_nommee_des_la_premiere_phrase(
        self, tmp_path: Path
    ) -> None:
        marc = Personne(nom="Marc", empreintes=[empreinte(1, 0, duree=30)])
        instance = suivi(
            tmp_path,
            fil=Fil(connues=[marc]),
            extracteur=ExtracteurDeSuite([empreinte(1, 0)]),
        )
        instance.accueillir(tmp_path / "tranche.wav", [replique(0, 8)], decalage=0.0)
        assert lignes_du(instance.journal)[0]["nom"] == "Marc"

    def test_un_modele_qui_tombe_n_interrompt_pas_la_reunion(self, tmp_path: Path) -> None:
        class Casse:
            def extraire_intervalles(self, audio: Path, intervalles: list[Intervalle]):
                raise RuntimeError("BroadcastIterator::Init")

        instance = suivi(tmp_path, extracteur=Casse())
        instance.accueillir(tmp_path / "tranche.wav", [replique(0, 8)], decalage=0.0)
        # La phrase s'affiche sans nom, et se corrige d'un clic.
        assert len(instance.fil.tours) == 1


class TestCorrectionsRecues:
    def _un_fil(self, tmp_path: Path) -> Suivi:
        instance = suivi(
            tmp_path,
            extracteur=ExtracteurDeSuite([empreinte(1, 0)]),
            banque=BanqueEnMemoire(),
        )
        instance.accueillir(tmp_path / "tranche.wav", [replique(0, 8)], decalage=0.0)
        return instance

    def test_une_correction_deposee_est_appliquee(self, tmp_path: Path) -> None:
        instance = self._un_fil(tmp_path)
        demander(instance.demandes, numero=1, nom="Marc")
        faites = instance.appliquer_les_demandes()
        assert [c.nom for c in faites] == ["Marc"]
        assert instance.fil.etiquette(instance.fil.tours[0].voix) == "Marc"

    def test_la_correction_est_confirmee_dans_le_journal(self, tmp_path: Path) -> None:
        # C'est ainsi que la fenêtre sait que sa correction a été prise, et que
        # toute autre fenêtre ouverte l'apprend aussi.
        instance = self._un_fil(tmp_path)
        demander(instance.demandes, numero=1, nom="Marc")
        instance.appliquer_les_demandes()
        confirmations = [
            x for x in lignes_du(instance.journal) if x["genre"] == GENRE_CORRECTION
        ]
        assert confirmations[0]["nom"] == "Marc"
        assert confirmations[0]["numeros"] == [1]

    def test_une_correction_verse_l_empreinte_en_banque(self, tmp_path: Path) -> None:
        # Le point de tout l'échange : corriger une fois pendant la réunion, et
        # que le compte rendu final retrouve la personne tout seul.
        banque = BanqueEnMemoire()
        instance = suivi(
            tmp_path,
            extracteur=ExtracteurDeSuite([empreinte(1, 0)]),
            banque=banque,
        )
        instance.accueillir(tmp_path / "tranche.wav", [replique(0, 8)], decalage=0.0)
        demander(instance.demandes, numero=1, nom="Marc")
        instance.appliquer_les_demandes()
        assert [nom for nom, _ in banque.recues] == ["Marc"]

    def test_toi_n_entre_jamais_en_banque(self, tmp_path: Path) -> None:
        # Le micro identifie déjà la personne qui enregistre : stocker sa voix
        # comme celle d'un participant n'apporterait rien et l'exposerait.
        banque = BanqueEnMemoire()
        instance = suivi(tmp_path, canaux=CanauxDits([Intervalle(0, 8)]), banque=banque)
        instance.accueillir(tmp_path / "tranche.wav", [replique(0, 8)], decalage=0.0)
        demander(instance.demandes, numero=1, nom="Tanguy")
        instance.appliquer_les_demandes()
        assert banque.recues == []

    def test_une_voix_corrigee_trop_tot_est_apprise_des_qu_elle_a_de_quoi(
        self, tmp_path: Path
    ) -> None:
        """Le défaut qui vidait la banque de voix.

        On corrige dès la première phrase — c'est le but — quand l'empreinte n'a
        pas encore la matière du seuil. Refuser une fois pour toutes perdait la
        correction : elle s'affichait, puis ne servait ni à la réunion suivante
        ni au compte rendu.
        """
        banque = BanqueEnMemoire()
        instance = suivi(
            tmp_path,
            extracteur=ExtracteurDeSuite(
                # 2,5 s : de quoi fonder une voix (le plancher est à 2,0 s,
                # mesuré) mais pas de quoi la verser en banque.
                [empreinte(1, 0, duree=2.5), empreinte(0.95, 0.31, duree=4.0)]
            ),
            banque=banque,
        )
        instance.accueillir(tmp_path / "t1.wav", [replique(0, 2)], decalage=0.0)
        demander(instance.demandes, numero=1, nom="Sandy")
        instance.appliquer_les_demandes()
        # Trop peu de matière pour apprendre quoi que ce soit d'utile.
        assert banque.recues == []
        # La personne reparle : cette fois il y a de quoi.
        instance.accueillir(tmp_path / "t2.wav", [replique(3, 9)], decalage=0.0)
        assert [nom for nom, _ in banque.recues] == ["Sandy"]

    def test_une_voix_n_est_apprise_qu_une_fois(self, tmp_path: Path) -> None:
        banque = BanqueEnMemoire()
        instance = suivi(
            tmp_path,
            extracteur=ExtracteurDeSuite([empreinte(1, 0), empreinte(0.95, 0.31)]),
            banque=banque,
        )
        instance.accueillir(tmp_path / "t1.wav", [replique(0, 8)], decalage=0.0)
        demander(instance.demandes, numero=1, nom="Sandy")
        instance.appliquer_les_demandes()
        instance.accueillir(tmp_path / "t2.wav", [replique(9, 17)], decalage=0.0)
        assert [nom for nom, _ in banque.recues] == ["Sandy"]

    def test_une_demande_qui_ne_correspond_a_rien_est_ignoree(self, tmp_path: Path) -> None:
        instance = self._un_fil(tmp_path)
        demander(instance.demandes, numero=99, nom="Marc")
        demander(instance.demandes, numero=1, nom="  ")
        assert instance.appliquer_les_demandes() == []

    def test_une_demande_n_est_appliquee_qu_une_fois(self, tmp_path: Path) -> None:
        instance = self._un_fil(tmp_path)
        demander(instance.demandes, numero=1, nom="Marc")
        assert len(instance.appliquer_les_demandes()) == 1
        assert instance.appliquer_les_demandes() == []

    def test_les_phrases_suivantes_portent_le_nom_corrige(self, tmp_path: Path) -> None:
        instance = suivi(
            tmp_path,
            extracteur=ExtracteurDeSuite([empreinte(1, 0), empreinte(0.9, 0.44)]),
            banque=BanqueEnMemoire(),
        )
        instance.accueillir(tmp_path / "t1.wav", [replique(0, 8)], decalage=0.0)
        demander(instance.demandes, numero=1, nom="Marc")
        instance.accueillir(tmp_path / "t2.wav", [replique(9, 17)], decalage=0.0)
        assert lignes_du(instance.journal)[-1]["nom"] == "Marc"


class TestRejouerPourAfficher:
    def test_le_fil_se_reconstruit_depuis_le_journal(self, tmp_path: Path) -> None:
        instance = suivi(tmp_path, extracteur=ExtracteurDeSuite([empreinte(1, 0)]))
        instance.accueillir(
            tmp_path / "t.wav", [replique(0, 4, "bonjour"), replique(4, 8)], decalage=0.0
        )
        rejoue = rejouer(lignes_du(instance.journal))
        assert [t.texte for t in rejoue.tours] == ["bonjour", "on cale la recette jeudi"]
        assert rejoue.etiquette(rejoue.tours[0].voix) == "Voix 1"

    def test_une_correction_du_journal_renomme_les_phrases_passees(
        self, tmp_path: Path
    ) -> None:
        instance = suivi(
            tmp_path,
            extracteur=ExtracteurDeSuite([empreinte(1, 0)]),
            banque=BanqueEnMemoire(),
        )
        instance.accueillir(tmp_path / "t.wav", [replique(0, 8)], decalage=0.0)
        demander(instance.demandes, numero=1, nom="Marc")
        instance.appliquer_les_demandes()
        rejoue = rejouer(lignes_du(instance.journal))
        assert rejoue.etiquette(rejoue.tours[0].voix) == "Marc"
        assert rejoue.voix[rejoue.tours[0].voix].certitude is Certitude.HUMAINE

    def test_rejouer_deux_fois_ne_duplique_pas_les_phrases(self, tmp_path: Path) -> None:
        # La fenêtre lit par morceaux : un chevauchement ne doit pas afficher la
        # même phrase deux fois.
        instance = suivi(tmp_path)
        instance.accueillir(tmp_path / "t.wav", [replique(0, 8)], decalage=0.0)
        lignes = lignes_du(instance.journal)
        fil = rejouer(lignes)
        rejouer(lignes, fil)
        assert len(fil.tours) == 1

    def test_une_ligne_abimee_n_empeche_pas_de_lire_les_autres(
        self, tmp_path: Path
    ) -> None:
        journal = tmp_path / "fil.jsonl"
        journal.write_text(
            "ceci n'est pas du json\n"
            + json.dumps({"genre": GENRE_TOUR, "numero": 1, "debut": 0, "fin": 2,
                          "texte": "bonjour", "voix": "v1", "nom": None,
                          "certitude": "inconnue", "rang": 1})
            + "\n",
            encoding="utf-8",
        )
        assert len(rejouer(lignes_du(journal)).tours) == 1


class TestDeuxFichiers:
    def test_chacun_ecrit_dans_le_sien(self, tmp_path: Path) -> None:
        # Aucun verrou à poser : celui qui écoute écrit le journal et lit les
        # demandes, la fenêtre fait l'inverse.
        journal, demandes = fichiers(tmp_path, "2026-08-27_10h00_reunion")
        assert journal != demandes
        assert journal.parent == demandes.parent
