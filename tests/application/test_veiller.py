"""La veille en réunion, sans micro ni presse-papier."""

import json

from greffier.application import veiller
from greffier.application.suivre import Position, Suivi
from greffier.application.veiller import Veilleur
from greffier.domaine.direct import Fil
from greffier.domaine.instructions import Genre, Veille
from greffier.domaine.modeles import Intervalle, Replique


class TranscripteurDeTranche:
    """Rend, pour chaque tranche, les répliques qu'on lui a données d'avance."""

    def __init__(self, tranches):
        self.tranches = list(tranches)
        self.appels = 0

    def transcrire(self, audio, langue, amorce):
        self.appels += 1
        return self.tranches.pop(0) if self.tranches else []


def replique(debut, texte):
    return Replique(intervalle=Intervalle(debut, debut + 4), texte=texte)


def veilleur(tmp_path, **remplacements):
    defauts = dict(veille=Veille(), journal=tmp_path / "propositions.jsonl")
    defauts.update(remplacements)
    return Veilleur(**defauts)


def ou(tmp_path, ecrit, decalage=0.0):
    """La position dans l'audio réellement écrit, telle que la lit le direct."""
    return Position(morceau=tmp_path / "r-01.wav", ecrit=ecrit, decalage=decalage)


class TestPressePapier:
    def test_un_lien_colle_devient_une_proposition(self, tmp_path, monkeypatch):
        monkeypatch.setattr(veiller, "lire_presse_papier", lambda: "voir https://miro.com/x")
        nouvelles = veilleur(tmp_path).tour_presse_papier(12.0)
        assert [p.texte for p in nouvelles] == ["https://miro.com/x"]

    def test_le_meme_lien_n_est_pas_proposé_a_chaque_tour(self, tmp_path, monkeypatch):
        """Le presse-papier est relu toutes les deux secondes."""
        monkeypatch.setattr(veiller, "lire_presse_papier", lambda: "https://miro.com/x")
        instance = veilleur(tmp_path)
        assert len(instance.tour_presse_papier(2.0)) == 1
        assert instance.tour_presse_papier(4.0) == []

    def test_un_presse_papier_vide_ne_fait_rien(self, tmp_path, monkeypatch):
        monkeypatch.setattr(veiller, "lire_presse_papier", lambda: "")
        assert veilleur(tmp_path).tour_presse_papier(1.0) == []


class TestJournal:
    def test_chaque_proposition_est_une_ligne(self, tmp_path, monkeypatch):
        monkeypatch.setattr(veiller, "lire_presse_papier", lambda: "https://a.fr https://b.fr")
        instance = veilleur(tmp_path)
        instance.tour_presse_papier(7.0)
        lignes = (tmp_path / "propositions.jsonl").read_text().strip().splitlines()
        assert len(lignes) == 2
        premier = json.loads(lignes[0])
        assert premier["genre"] == Genre.LIEN.value
        assert premier["instant"] == 7.0

    def test_le_journal_s_ajoute_et_ne_se_reecrit_pas(self, tmp_path, monkeypatch):
        """Une interruption ne doit rien perdre de ce qui précède."""
        instance = veilleur(tmp_path)
        monkeypatch.setattr(veiller, "lire_presse_papier", lambda: "https://a.fr")
        instance.tour_presse_papier(1.0)
        monkeypatch.setattr(veiller, "lire_presse_papier", lambda: "https://b.fr")
        instance.tour_presse_papier(2.0)
        assert len((tmp_path / "propositions.jsonl").read_text().strip().splitlines()) == 2


class TestTranscriptionAuFilDeLEau:
    def test_les_instants_sont_remis_a_l_heure_de_la_reunion(self, tmp_path, monkeypatch):
        """Une réplique datée dans sa tranche renverrait au mauvais moment."""
        monkeypatch.setattr(veiller, "extraire_tranche",
                            lambda audio, debut, fin, dest: dest)
        transcripteur = TranscripteurDeTranche([[replique(3, "Greffier, ouvre le tableau")]])
        instance = veilleur(tmp_path, transcripteur=transcripteur, traite=120.0)
        nouvelles = instance.tour_transcription(ou(tmp_path, ecrit=150.0), tmp_path)
        # 120 s déjà lues, 5 s de recouvrement : la tranche part de 115 s.
        assert nouvelles[0].instant == 118.0

    def test_l_horodatage_suit_les_morceaux_et_non_l_horloge(self, tmp_path, monkeypatch):
        """Après une pause, l'audio écrit et l'horloge ont divergé.

        Le second morceau redémarre à zéro dans son fichier : sans le décalage,
        une phrase dite à la 40ᵉ minute s'afficherait à la 2ᵉ.
        """
        monkeypatch.setattr(veiller, "extraire_tranche",
                            lambda audio, debut, fin, dest: dest)
        transcripteur = TranscripteurDeTranche(
            [[replique(2, "Greffier, ouvre le ticket")]]
        )
        instance = veilleur(tmp_path, transcripteur=transcripteur, traite=1800.0)
        nouvelles = instance.tour_transcription(
            ou(tmp_path, ecrit=20.0, decalage=1800.0), tmp_path
        )
        # Une demi-heure déjà enregistrée avant ce morceau, plus 2 s dedans.
        assert nouvelles[0].instant == 1802.0

    def test_une_tranche_trop_courte_n_est_pas_transcrite(self, tmp_path, monkeypatch):
        # Le modèle invente plus qu'il n'entend sur deux secondes d'audio.
        monkeypatch.setattr(veiller, "extraire_tranche",
                            lambda audio, debut, fin, dest: dest)
        transcripteur = TranscripteurDeTranche([[replique(0, "à peine un mot")]])
        instance = veilleur(tmp_path, transcripteur=transcripteur)
        assert instance.tour_transcription(ou(tmp_path, ecrit=2.0), tmp_path) == []
        assert transcripteur.appels == 0

    def test_le_recouvrement_de_texte_entre_deux_tranches_est_retire(
        self, tmp_path, monkeypatch
    ):
        """Le vrai pipeline, sans modèle : seul le port Transcripteur est une
        doublure. Une phrase à cheval sur deux tranches successives ne doit
        plus s'afficher avec la fin de la précédente collée devant."""
        monkeypatch.setattr(veiller, "extraire_tranche",
                            lambda audio, debut, fin, dest: dest)
        transcripteur = TranscripteurDeTranche([
            # Tranche 1 (0-10 s de réunion) : une phrase se termine à 8 s.
            [Replique(Intervalle(0, 8), "c'est notre dernier.")],
            # Tranche 2 (5-20 s, recouvrement de 5 s) : la même fin retranscrite,
            # suivie de la phrase suivante. Relatif à la tranche, qui démarre à
            # 5 s de réunion : (3, 9) devient (8, 14) une fois recalé.
            [Replique(Intervalle(3, 9), "dernier. Sandy, tu peux nous dire où on en est ?")],
        ])
        suivi = Suivi(fil=Fil(), journal=tmp_path / "direct.jsonl",
                       demandes=tmp_path / "demandes.jsonl")
        instance = veilleur(tmp_path, transcripteur=transcripteur, suivi=suivi)
        instance.tour_transcription(ou(tmp_path, ecrit=10.0), tmp_path)
        instance.tour_transcription(ou(tmp_path, ecrit=20.0), tmp_path)
        assert suivi.fil.tours[-1].texte == "Sandy, tu peux nous dire où on en est ?"

    def test_une_tranche_ratee_ne_grandit_pas_sans_fin(self, tmp_path, monkeypatch):
        """Un échec durable ferait grossir la tranche jusqu'à des minutes de calcul."""
        demandees = []
        monkeypatch.setattr(
            veiller, "extraire_tranche",
            lambda audio, debut, fin, dest: demandees.append((debut, fin)) or None,
        )
        instance = veilleur(tmp_path, transcripteur=TranscripteurDeTranche([]))
        instance.tour_transcription(ou(tmp_path, ecrit=600.0), tmp_path)
        debut, fin = demandees[0]
        assert fin - debut == veiller.TRANCHE_MAXIMALE

    def test_une_tranche_illisible_n_interrompt_pas_la_veille(self, tmp_path, monkeypatch):
        monkeypatch.setattr(veiller, "extraire_tranche", lambda *args: None)
        instance = veilleur(tmp_path, transcripteur=TranscripteurDeTranche([]))
        assert instance.tour_transcription(ou(tmp_path, ecrit=30.0), tmp_path) == []

    def test_sans_transcripteur_seule_la_veille_du_presse_papier_tourne(self, tmp_path):
        assert veilleur(tmp_path).tour_transcription(ou(tmp_path, ecrit=30.0), tmp_path) == []


class TestFinDeReunion:
    """Les dernières secondes ne doivent pas rester dans le tuyau.

    Sans rattrapage, il reste toujours jusqu'à une période d'audio non
    transcrite : on finit sa phrase devant un fil qui s'arrête avant elle.
    """

    def test_l_audio_qui_ne_grandit_plus_est_quand_meme_transcrit(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(veiller, "lire_presse_papier", lambda: "")
        monkeypatch.setattr(veiller, "extraire_tranche",
                            lambda audio, debut, fin, dest: dest)
        transcripteur = TranscripteurDeTranche([[replique(1, "Greffier, ouvre le ticket")]])
        instance = veilleur(tmp_path, transcripteur=transcripteur, periode_tranche=30.0)
        fige = ou(tmp_path, ecrit=6.0)
        # Premier passage : on ne sait pas encore si la capture avance.
        assert not instance._est_temps(fige)
        # Second : la taille n'a pas bougé, il reste 6 s à dire.
        assert instance._est_temps(fige)

    def test_la_derniere_passe_rattrape_ce_qui_restait(self, tmp_path, monkeypatch):
        monkeypatch.setattr(veiller, "lire_presse_papier", lambda: "")
        monkeypatch.setattr(veiller, "extraire_tranche",
                            lambda audio, debut, fin, dest: dest)
        transcripteur = TranscripteurDeTranche([[replique(1, "Greffier, ouvre le ticket")]])
        instance = veilleur(
            tmp_path, transcripteur=transcripteur, periode_tranche=30.0,
            situer=lambda: ou(tmp_path, ecrit=12.0),
        )
        # La réunion s'arrête tout de suite : rien n'a atteint la période.
        propositions = instance.boucler(
            encore=lambda: False, depuis=lambda: 0.0, travail=tmp_path,
            pause=lambda _: None,
        )
        assert transcripteur.appels == 1
        assert propositions

    def test_un_reste_trop_court_ne_declenche_rien(self, tmp_path):
        instance = veilleur(tmp_path, periode_tranche=30.0)
        fige = ou(tmp_path, ecrit=1.5)
        instance._est_temps(fige)
        assert not instance._est_temps(fige)


class TestBoucle:
    def test_les_deux_rythmes_cohabitent(self, tmp_path, monkeypatch):
        """Le presse-papier est relu souvent, la transcription rarement :
        une tranche coûte plusieurs secondes de calcul."""
        monkeypatch.setattr(veiller, "lire_presse_papier", lambda: "")
        monkeypatch.setattr(veiller, "extraire_tranche",
                            lambda audio, debut, fin, dest: dest)
        transcripteur = TranscripteurDeTranche([[], [], []])
        ecrit = {"s": 0.0}
        instance = veilleur(
            tmp_path,
            transcripteur=transcripteur,
            situer=lambda: ou(tmp_path, ecrit=ecrit["s"]),
        )

        tours = {"n": 0}

        def encore():
            tours["n"] += 1
            return tours["n"] <= 40

        instance.boucler(
            encore=encore,
            depuis=lambda: ecrit["s"],
            travail=tmp_path,
            # Chaque pause de deux secondes ajoute deux secondes d'audio écrit.
            pause=lambda _: ecrit.__setitem__("s", ecrit["s"] + 2.0),
        )
        # 40 tours × 2 s = 80 s : deux tranches de 30 s, pas quarante — plus la
        # passe de fin, qui rattrape les vingt dernières secondes.
        assert transcripteur.appels == 3

    def test_le_rythme_suit_l_audio_ecrit_et_non_l_horloge(self, tmp_path, monkeypatch):
        """En pause, le fichier ne grandit plus : une seule tranche, pas quarante.

        Celle-là est nécessaire — c'est le rattrapage qui affiche la fin de ce
        qui vient d'être dit. Ensuite il n'y a plus rien de neuf, et l'horloge
        qui continue d'avancer ne doit pas réclamer des tranches d'un passage
        qui n'existe pas.
        """
        monkeypatch.setattr(veiller, "lire_presse_papier", lambda: "")
        monkeypatch.setattr(veiller, "extraire_tranche",
                            lambda audio, debut, fin, dest: dest)
        transcripteur = TranscripteurDeTranche([[], []])
        horloge = {"t": 0.0}
        instance = veilleur(
            tmp_path,
            transcripteur=transcripteur,
            # L'audio reste figé : l'enregistrement est suspendu.
            situer=lambda: ou(tmp_path, ecrit=4.0),
        )
        tours = {"n": 0}

        def encore():
            tours["n"] += 1
            return tours["n"] <= 40

        instance.boucler(
            encore=encore, depuis=lambda: horloge["t"], travail=tmp_path,
            pause=lambda _: horloge.__setitem__("t", horloge["t"] + 2.0),
        )
        assert transcripteur.appels == 1

    def test_la_boucle_s_arrete_avec_l_enregistrement(self, tmp_path, monkeypatch):
        monkeypatch.setattr(veiller, "lire_presse_papier", lambda: "")
        instance = veilleur(tmp_path)
        assert instance.boucler(encore=lambda: False, depuis=lambda: 0.0,
                                travail=tmp_path, pause=lambda _: None) == []


class TestReunionPubliee:
    """La réunion de voix voyage par le journal, comme les tours.

    La fenêtre reconstruit le fil sans jamais calculer d'empreinte : il lui faut
    le résultat du recollage, pas de quoi le refaire.
    """

    def test_une_reunion_se_rejoue_depuis_le_journal(self):
        from greffier.application.suivre import GENRE_REUNION, GENRE_TOUR, rejouer

        lignes = [
            {"genre": GENRE_TOUR, "numero": 1, "debut": 0.0, "fin": 2.0,
             "texte": "bonjour", "voix": "v1", "nom": None,
             "certitude": "inconnue", "rang": 1},
            {"genre": GENRE_TOUR, "numero": 2, "debut": 2.0, "fin": 4.0,
             "texte": "salut", "voix": "v2", "nom": None,
             "certitude": "inconnue", "rang": 2},
            {"genre": GENRE_REUNION, "voix": "v2", "vers": "v1"},
        ]
        fil = rejouer(lignes)
        assert {t.voix for t in fil.tours} == {"v1"}
        assert "v2" not in fil.voix

    def test_un_nom_humain_survit_a_la_reunion_rejouee(self):
        from greffier.application.suivre import GENRE_CORRECTION, GENRE_REUNION, GENRE_TOUR, rejouer

        lignes = [
            {"genre": GENRE_TOUR, "numero": 1, "debut": 0.0, "fin": 2.0,
             "texte": "bonjour", "voix": "v1", "nom": None,
             "certitude": "inconnue", "rang": 1},
            {"genre": GENRE_TOUR, "numero": 2, "debut": 2.0, "fin": 4.0,
             "texte": "salut", "voix": "v2", "nom": None,
             "certitude": "inconnue", "rang": 2},
            {"genre": GENRE_CORRECTION, "nom": "Sophie", "voix": "v2", "numeros": [2]},
            {"genre": GENRE_REUNION, "voix": "v2", "vers": "v1"},
        ]
        fil = rejouer(lignes)
        assert {t.voix for t in fil.tours} == {"v1"}
        assert fil.voix["v1"].nom == "Sophie"

    def test_une_ligne_de_reunion_incomplete_est_ignoree(self):
        """Un journal tronqué ne doit pas faire tomber la fenêtre."""
        from greffier.application.suivre import GENRE_REUNION, GENRE_TOUR, rejouer

        lignes = [
            {"genre": GENRE_TOUR, "numero": 1, "debut": 0.0, "fin": 2.0,
             "texte": "bonjour", "voix": "v1", "nom": None,
             "certitude": "inconnue", "rang": 1},
            {"genre": GENRE_REUNION, "voix": "v1"},
            {"genre": GENRE_REUNION, "vers": "v1"},
            {"genre": GENRE_REUNION, "voix": "v1", "vers": "v1"},
        ]
        fil = rejouer(lignes)
        assert {t.voix for t in fil.tours} == {"v1"}
