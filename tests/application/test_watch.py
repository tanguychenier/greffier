"""La veille en réunion, sans micro ni presse-papier."""

import json
import pathlib
from pathlib import Path

from greffier.application import watch
from greffier.application.follow import Follower, Position
from greffier.application.watch import Watcher
from greffier.domain.instructions import Kind, WatchRules
from greffier.domain.live import LiveThread
from greffier.domain.models import Span, Utterance


class TranscripteurDeTranche:
    """Rend, pour chaque tranche, les répliques qu'on lui a données d'avance."""

    def __init__(self, tranches):
        self.tranches = list(tranches)
        self.appels = 0

    def transcribe(self, audio, language, prompt_seed):
        self.appels += 1
        return self.tranches.pop(0) if self.tranches else []


def utterance(start, text):
    return Utterance(span=Span(start, start + 4), text=text)


def watcher(tmp_path, **overrides):
    defauts = dict(watch_rules=WatchRules(), log=tmp_path / "propositions.jsonl")
    defauts.update(overrides)
    return Watcher(**defauts)


def ou(tmp_path, ecrit, decalage=0.0):
    """La position dans l'audio réellement écrit, telle que la lit le direct."""
    return Position(morceau=tmp_path / "r-01.wav", ecrit=ecrit, decalage=decalage)


class TestPressePapier:
    def test_un_lien_colle_devient_une_proposition(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "voir https://miro.com/x")
        nouvelles = watcher(tmp_path).clipboard_turn(12.0)
        assert [p.text for p in nouvelles] == ["https://miro.com/x"]

    def test_le_meme_lien_n_est_pas_proposé_a_chaque_tour(self, tmp_path, monkeypatch):
        """Le presse-papier est relu toutes les deux secondes."""
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "https://miro.com/x")
        instance = watcher(tmp_path)
        assert len(instance.clipboard_turn(2.0)) == 1
        assert instance.clipboard_turn(4.0) == []

    def test_un_presse_papier_vide_ne_fait_rien(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "")
        assert watcher(tmp_path).clipboard_turn(1.0) == []


class TestJournal:
    def test_chaque_proposition_est_une_ligne(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "https://a.fr https://b.fr")
        instance = watcher(tmp_path)
        instance.clipboard_turn(7.0)
        lines = (tmp_path / "propositions.jsonl").read_text().strip().splitlines()
        assert len(lines) == 2
        premier = json.loads(lines[0])
        assert premier["genre"] == Kind.LIEN.value
        assert premier["instant"] == 7.0

    def test_le_journal_s_ajoute_et_ne_se_reecrit_pas(self, tmp_path, monkeypatch):
        """Une interruption ne doit rien perdre de ce qui précède."""
        instance = watcher(tmp_path)
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "https://a.fr")
        instance.clipboard_turn(1.0)
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "https://b.fr")
        instance.clipboard_turn(2.0)
        assert len((tmp_path / "propositions.jsonl").read_text().strip().splitlines()) == 2


class TestTranscriptionAuFilDeLEau:
    def test_les_instants_sont_remis_a_l_heure_de_la_reunion(self, tmp_path, monkeypatch):
        """Une réplique datée dans sa tranche renverrait au mauvais moment."""
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        # La fenêtre transcrite précède la tranche de CONTEXTE_S : une réplique
        # dite 3 s après le début de la tranche y est datée d'autant plus tard.
        transcriber = TranscripteurDeTranche(
            [[utterance(watch.CONTEXTE_S + 3, "Greffier, ouvre le tableau")]]
        )
        instance = watcher(tmp_path, transcriber=transcriber, traite=120.0)
        nouvelles = instance.transcription_turn(ou(tmp_path, ecrit=150.0), tmp_path)
        # 120 s déjà lues, 5 s de recouvrement : la tranche part de 115 s.
        assert nouvelles[0].at_instant == 118.0

    def test_l_horodatage_suit_les_morceaux_et_non_l_horloge(self, tmp_path, monkeypatch):
        """Après une pause, l'audio écrit et l'horloge ont divergé.

        Le second morceau redémarre à zéro dans son fichier : sans le décalage,
        une phrase dite à la 40ᵉ minute s'afficherait à la 2ᵉ.
        """
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        transcriber = TranscripteurDeTranche(
            [[utterance(2, "Greffier, ouvre le ticket")]]
        )
        # Le morceau ne porte que 20 s : la fenêtre ne peut pas remonter plus
        # haut que son début, donc les temps sont ceux de la tranche.
        instance = watcher(tmp_path, transcriber=transcriber, traite=1800.0)
        nouvelles = instance.transcription_turn(
            ou(tmp_path, ecrit=20.0, decalage=1800.0), tmp_path
        )
        # Une demi-heure déjà enregistrée avant ce morceau, plus 2 s dedans.
        assert nouvelles[0].at_instant == 1802.0

    def test_une_tranche_trop_courte_n_est_pas_transcrite(self, tmp_path, monkeypatch):
        # Le modèle invente plus qu'il n'entend sur deux secondes d'audio.
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        transcriber = TranscripteurDeTranche([[utterance(0, "à peine un mot")]])
        instance = watcher(tmp_path, transcriber=transcriber)
        assert instance.transcription_turn(ou(tmp_path, ecrit=2.0), tmp_path) == []
        assert transcriber.appels == 0

    def test_le_recouvrement_de_texte_entre_deux_tranches_est_retire(
        self, tmp_path, monkeypatch
    ):
        """Le vrai pipeline, sans modèle : seul le port Transcripteur est une
        doublure. Une phrase à cheval sur deux tranches successives ne doit
        plus s'afficher avec la fin de la précédente collée devant."""
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        transcriber = TranscripteurDeTranche([
            # Tranche 1 (0-10 s de réunion) : une phrase se termine à 8 s.
            [Utterance(Span(0, 8), "c'est notre dernier.")],
            # Tranche 2 : la fenêtre repart de 0 s — le morceau ne porte pas
            # plus — et la phrase à cheval y est datée de 8 à 14 s, comme le
            # modèle la datera. Elle déborde la tranche, qui démarre à 5 s.
            [Utterance(Span(8, 14), "dernier. Sandy, tu peux nous dire où on en est ?")],
        ])
        follower = Follower(thread=LiveThread(), log=tmp_path / "direct.jsonl",
                       requests=tmp_path / "demandes.jsonl")
        instance = watcher(tmp_path, transcriber=transcriber, follower=follower)
        instance.transcription_turn(ou(tmp_path, ecrit=10.0), tmp_path)
        instance.transcription_turn(ou(tmp_path, ecrit=20.0), tmp_path)
        assert follower.thread.turns[-1].text == "Sandy, tu peux nous dire où on en est ?"

    def test_une_tranche_ratee_ne_grandit_pas_sans_fin(self, tmp_path, monkeypatch):
        """Un échec durable ferait grossir la tranche jusqu'à des minutes de calcul."""
        demandees = []
        monkeypatch.setattr(
            watch, "extract_slice",
            lambda audio, start, end, dest: demandees.append((start, end)) or None,
        )
        instance = watcher(tmp_path, transcriber=TranscripteurDeTranche([]))
        instance.transcription_turn(ou(tmp_path, ecrit=600.0), tmp_path)
        start, end = demandees[0]
        assert end - start == watch.TRANCHE_MAXIMALE

    def test_une_tranche_illisible_n_interrompt_pas_la_veille(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watch, "extract_slice", lambda *args: None)
        instance = watcher(tmp_path, transcriber=TranscripteurDeTranche([]))
        assert instance.transcription_turn(ou(tmp_path, ecrit=30.0), tmp_path) == []

    def test_sans_transcripteur_seule_la_veille_du_presse_papier_tourne(self, tmp_path):
        assert watcher(tmp_path).transcription_turn(ou(tmp_path, ecrit=30.0), tmp_path) == []


class TestFinDeReunion:
    """Les dernières secondes ne doivent pas rester dans le tuyau.

    Sans rattrapage, il reste toujours jusqu'à une période d'audio non
    transcrite : on finit sa phrase devant un fil qui s'arrête avant elle.
    """

    def test_l_audio_qui_ne_grandit_plus_est_quand_meme_transcrit(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "")
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        transcriber = TranscripteurDeTranche([[utterance(1, "Greffier, ouvre le ticket")]])
        instance = watcher(tmp_path, transcriber=transcriber, slice_period=30.0)
        fige = ou(tmp_path, ecrit=6.0)
        # Premier passage : on ne sait pas encore si la capture avance.
        assert not instance._is_time(fige)
        # Second : la taille n'a pas bougé, il reste 6 s à dire.
        assert instance._is_time(fige)

    def test_la_derniere_passe_rattrape_ce_qui_restait(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "")
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        transcriber = TranscripteurDeTranche([[utterance(1, "Greffier, ouvre le ticket")]])
        instance = watcher(
            tmp_path, transcriber=transcriber, slice_period=30.0,
            situer=lambda: ou(tmp_path, ecrit=12.0),
        )
        # La réunion s'arrête tout de suite : rien n'a atteint la période.
        propositions = instance.loop(
            still_running=lambda: False, depuis=lambda: 0.0, job=tmp_path,
            pause=lambda _: None,
        )
        assert transcriber.appels == 1
        assert propositions

    def test_un_reste_trop_court_ne_declenche_rien(self, tmp_path):
        instance = watcher(tmp_path, slice_period=30.0)
        fige = ou(tmp_path, ecrit=1.5)
        instance._is_time(fige)
        assert not instance._is_time(fige)


class TestBoucle:
    def test_les_deux_rythmes_cohabitent(self, tmp_path, monkeypatch):
        """Le presse-papier est relu souvent, la transcription rarement :
        une tranche coûte plusieurs secondes de calcul."""
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "")
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        transcriber = TranscripteurDeTranche([[], [], []])
        ecrit = {"s": 0.0}
        instance = watcher(
            tmp_path,
            transcriber=transcriber,
            situer=lambda: ou(tmp_path, ecrit=ecrit["s"]),
        )

        turns = {"n": 0}

        def still_running():
            turns["n"] += 1
            return turns["n"] <= 40

        instance.loop(
            still_running=still_running,
            depuis=lambda: ecrit["s"],
            job=tmp_path,
            # Chaque pause de deux secondes ajoute deux secondes d'audio écrit.
            pause=lambda _: ecrit.__setitem__("s", ecrit["s"] + 2.0),
        )
        # 40 tours × 2 s = 80 s : deux tranches de 30 s, pas quarante — plus la
        # passe de fin, qui rattrape les vingt dernières secondes.
        assert transcriber.appels == 3

    def test_le_rythme_suit_l_audio_ecrit_et_non_l_horloge(self, tmp_path, monkeypatch):
        """En pause, le fichier ne grandit plus : une seule tranche, pas quarante.

        Celle-là est nécessaire — c'est le rattrapage qui affiche la fin de ce
        qui vient d'être dit. Ensuite il n'y a plus rien de neuf, et l'horloge
        qui continue d'avancer ne doit pas réclamer des tranches d'un passage
        qui n'existe pas.
        """
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "")
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        transcriber = TranscripteurDeTranche([[], []])
        clock = {"t": 0.0}
        instance = watcher(
            tmp_path,
            transcriber=transcriber,
            # L'audio reste figé : l'enregistrement est suspendu.
            situer=lambda: ou(tmp_path, ecrit=4.0),
        )
        turns = {"n": 0}

        def still_running():
            turns["n"] += 1
            return turns["n"] <= 40

        instance.loop(
            still_running=still_running, depuis=lambda: clock["t"], job=tmp_path,
            pause=lambda _: clock.__setitem__("t", clock["t"] + 2.0),
        )
        assert transcriber.appels == 1

    def test_la_boucle_s_arrete_avec_l_enregistrement(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "")
        instance = watcher(tmp_path)
        assert instance.loop(still_running=lambda: False, depuis=lambda: 0.0,
                                job=tmp_path, pause=lambda _: None) == []


class TestReunionPubliee:
    """La réunion de voix voyage par le journal, comme les tours.

    La fenêtre reconstruit le fil sans jamais calculer d'empreinte : il lui faut
    le résultat du recollage, pas de quoi le refaire.
    """

    def test_une_reunion_se_rejoue_depuis_le_journal(self):
        from greffier.application.follow import GENRE_REUNION, GENRE_TOUR, replay

        lines = [
            {"genre": GENRE_TOUR, "numero": 1, "debut": 0.0, "fin": 2.0,
             "texte": "bonjour", "voix": "v1", "nom": None,
             "certitude": "inconnue", "rang": 1},
            {"genre": GENRE_TOUR, "numero": 2, "debut": 2.0, "fin": 4.0,
             "texte": "salut", "voix": "v2", "nom": None,
             "certitude": "inconnue", "rang": 2},
            {"genre": GENRE_REUNION, "voix": "v2", "vers": "v1"},
        ]
        thread = replay(lines)
        assert {t.voice for t in thread.turns} == {"v1"}
        assert "v2" not in thread.voice

    def test_un_nom_humain_survit_a_la_reunion_rejouee(self):
        from greffier.application.follow import GENRE_CORRECTION, GENRE_REUNION, GENRE_TOUR, replay

        lines = [
            {"genre": GENRE_TOUR, "numero": 1, "debut": 0.0, "fin": 2.0,
             "texte": "bonjour", "voix": "v1", "nom": None,
             "certitude": "inconnue", "rang": 1},
            {"genre": GENRE_TOUR, "numero": 2, "debut": 2.0, "fin": 4.0,
             "texte": "salut", "voix": "v2", "nom": None,
             "certitude": "inconnue", "rang": 2},
            # « toute_la_voix » explicite, comme le journal l'écrit désormais :
            # le déduire du nombre de numéros rejouait en « seulement cette
            # phrase » une correction portant sur une voix d'un seul tour.
            {"genre": GENRE_CORRECTION, "nom": "Sophie", "voix": "v2",
             "numeros": [2], "toute_la_voix": True},
            {"genre": GENRE_REUNION, "voix": "v2", "vers": "v1"},
        ]
        thread = replay(lines)
        assert {t.voice for t in thread.turns} == {"v1"}
        assert thread.voice["v1"].name == "Sophie"

    def test_une_ligne_de_reunion_incomplete_est_ignoree(self):
        """Un journal tronqué ne doit pas faire tomber la fenêtre."""
        from greffier.application.follow import GENRE_REUNION, GENRE_TOUR, replay

        lines = [
            {"genre": GENRE_TOUR, "numero": 1, "debut": 0.0, "fin": 2.0,
             "texte": "bonjour", "voix": "v1", "nom": None,
             "certitude": "inconnue", "rang": 1},
            {"genre": GENRE_REUNION, "voix": "v1"},
            {"genre": GENRE_REUNION, "vers": "v1"},
            {"genre": GENRE_REUNION, "voix": "v1", "vers": "v1"},
        ]
        thread = replay(lines)
        assert {t.voice for t in thread.turns} == {"v1"}


class TestAmorceRelueEnCoursDeReunion:
    """Un terme appris en réunion doit servir à la phrase suivante.

    Le processus du direct figeait son amorce au démarrage, si bien qu'ajouter
    « OTP » pendant la réunion ne servait qu'à la réunion d'après — alors que
    c'est justement en réunion qu'on découvre les mots qui manquent.
    """

    def veilleur_avec(self, prompt_seed: str, relire=None):
        return Watcher(
            watch_rules=WatchRules(mot_cle="greffier"),
            log=pathlib.Path("/tmp/greffier-essai.jsonl"),
            transcriber=None,
            situer=lambda: None,
            prompt_seed=prompt_seed,
            relire_l_amorce=relire,
        )

    def test_sans_relecture_l_amorce_ne_change_pas(self):
        watcher = self.veilleur_avec("Vocabulaire : CASA.")
        assert watcher._current_prompt_seed() == "Vocabulaire : CASA."

    def test_une_amorce_fraiche_remplace_l_ancienne(self):
        watcher = self.veilleur_avec(
            "Vocabulaire : CASA.", relire=lambda: "Vocabulaire : CASA, OTP."
        )
        assert "OTP" in watcher._current_prompt_seed()
        assert "OTP" in watcher.prompt_seed, "la nouvelle est retenue"

    def test_une_relecture_vide_ne_perd_pas_l_amorce(self):
        """Un contexte momentanément illisible ne doit pas dégrader la tranche."""
        watcher = self.veilleur_avec("Vocabulaire : CASA.", relire=lambda: "")
        assert watcher._current_prompt_seed() == "Vocabulaire : CASA."

    def test_une_relecture_qui_echoue_ne_leve_pas(self):
        def tomber():
            raise OSError("fichier occupé")

        watcher = self.veilleur_avec("Vocabulaire : CASA.", relire=tomber)
        assert watcher._current_prompt_seed() == "Vocabulaire : CASA."


class TestLaFenetreDeContexte:
    """Le modèle reçoit ce qui précède, et n'en réaffiche rien.

    Mesuré le 2026-09-09 sur une réunion réelle : le même passage donne « sur
    la ZIS » avec 15 s de fenêtre, « sur Asis » avec 30 s, « sur Oasis » avec
    60 s. Le contexte fait le mot juste, mais il ne doit rien redire.
    """

    def test_le_modele_recoit_plus_d_audio_que_la_tranche(self, tmp_path, monkeypatch):
        demandees = []

        def extract(audio, start, end, dest):
            demandees.append((start, end))
            return dest

        monkeypatch.setattr(watch, "extract_slice", extract)
        transcriber = TranscripteurDeTranche([[]])
        instance = watcher(tmp_path, transcriber=transcriber, traite=120.0)
        instance.transcription_turn(ou(tmp_path, ecrit=150.0), tmp_path)
        tranche, window = demandees
        assert tranche == (115.0, 150.0)
        assert window == (115.0 - watch.CONTEXTE_S, 150.0)

    def test_ce_qui_est_dans_le_contexte_n_est_pas_reaffiche(self, tmp_path, monkeypatch):
        """Sinon chaque phrase s'afficherait six fois."""
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        transcriber = TranscripteurDeTranche([[
            utterance(2, "phrase déjà affichée, dans le contexte"),
            utterance(watch.CONTEXTE_S + 1, "phrase neuve, dans la tranche"),
        ]])
        instance = watcher(tmp_path, transcriber=transcriber, traite=120.0)
        nouvelles = instance.transcription_turn(ou(tmp_path, ecrit=150.0), tmp_path)
        instance_veille = [p.text for p in nouvelles]
        assert not any("déjà affichée" in t for t in instance_veille)

    def test_au_debut_de_la_reunion_la_fenetre_ne_remonte_pas_avant_zero(
        self, tmp_path, monkeypatch
    ):
        demandees = []
        monkeypatch.setattr(
            watch, "extract_slice",
            lambda audio, start, end, dest: demandees.append(start) or dest,
        )
        transcriber = TranscripteurDeTranche([[]])
        instance = watcher(tmp_path, transcriber=transcriber)
        instance.transcription_turn(ou(tmp_path, ecrit=12.0), tmp_path)
        assert all(start >= 0.0 for start in demandees)

    def test_une_replique_a_cheval_est_gardee_entiere(self):
        """Couper une phrase au milieu vaut moins que retirer son début affiché."""
        kept = watch._within_the_slice(
            [Utterance(Span(8, 14), "dernier. Sandy, tu peux nous dire…")], 10.0
        )
        assert len(kept) == 1
        assert kept[0].span.start == 0.0
        assert kept[0].span.end == 4.0

    def test_une_replique_entierement_dans_le_contexte_part(self):
        assert watch._within_the_slice(
            [Utterance(Span(2, 6), "déjà dit")], 10.0
        ) == []

    def test_sans_contexte_rien_n_est_touche(self):
        utterances = [Utterance(Span(2, 6), "du texte")]
        assert watch._within_the_slice(utterances, 0.0) == utterances



class TestLesDeuxBoutonsEnCoursDeReunion:
    """La fenêtre et la veille sont deux processus.

    Les boutons écrivent dans la configuration, la veille la relit à chaque
    tranche. Sans quoi il faudrait redémarrer la réunion pour changer d'avis,
    ce qui n'a aucun sens.

    Deux boutons : **la voix**, s'il se fait entendre dans la pièce, et
    **l'initiative**, s'il peut parler sans qu'on l'ait appelé. Il participe
    toujours — écouter, prendre des notes, poser ses questions par écrit est son
    travail, et un troisième réglage qui le débranchait a fait qu'il ne
    répondait plus à son nom sans que rien ne le dise.
    """

    def _watcher(self, assistant_of, buttons, voix_neuve=None):
        from greffier.application.watch import Watcher
        from greffier.domain.instructions import WatchRules

        return Watcher(
            watch_rules=WatchRules(mot_cle="greffier"),
            log=Path("/tmp/inutilise.jsonl"),
            assistant_of=assistant_of,
            reread_participation=lambda: buttons,
            give_voice_back=(lambda: voix_neuve) if voix_neuve else None,
        )

    def _assistant_of(self, avec_voix=True):
        from greffier.application.take_part import AssistantSettings
        from greffier.domain.participation import Manners

        class Voix:
            def __init__(self):
                self.tue = False

            def say(self, _t):
                return True

            def go_quiet(self):
                self.tue = True

            def is_speaking(self):
                return False

        return AssistantSettings(name="Lucie", voice=Voix() if avec_voix else None,
                           manners=Manners(active=True))

    def test_couper_la_voix_l_interrompt_tout_de_suite(self):
        """Appuyer pendant qu'il parle doit couper, pas attendre la fin."""
        lui = self._assistant_of()
        voice = lui.voice
        self._watcher(lui, (False, False))._apply_the_buttons(False, False)
        assert voice.tue

    def test_retirer_la_voix_le_laisse_participer_par_ecrit(self):
        lui = self._assistant_of()
        self._watcher(lui, (False, False))._apply_the_buttons(False, False)
        assert lui.voice is None
        assert lui.manners.active, "il participe toujours, sans se faire entendre"

    def test_lui_rendre_la_voix_la_recharge_une_fois(self):
        """Charger un modèle coûte : on ne le fait qu'à la demande."""
        lui = self._assistant_of(avec_voix=False)
        neuve = object()
        watcher = self._watcher(lui, (True, False), voix_neuve=neuve)
        watcher._apply_the_buttons(True, False)
        assert lui.voice is neuve

    def test_sans_moyen_de_la_rendre_il_reste_muet(self):
        """Aucun modèle installé : il participe par écrit, sans se plaindre."""
        lui = self._assistant_of(avec_voix=False)
        self._watcher(lui, (True, False))._apply_the_buttons(True, False)
        assert lui.voice is None and lui.manners.active

    def test_l_initiative_se_prend_en_cours_de_reunion(self):
        """Le bouton n'agissait qu'à la réunion suivante, ce qui ne se devine pas."""
        lui = self._assistant_of()
        watcher = self._watcher(lui, (True, True))
        assert not watcher.initiative, "livrée éteinte"
        watcher._apply_the_buttons(True, True)
        assert watcher.initiative

    def test_l_initiative_se_reprend_aussi(self):
        lui = self._assistant_of()
        watcher = self._watcher(lui, (True, False))
        watcher.initiative = True
        watcher._apply_the_buttons(True, False)
        assert not watcher.initiative

    def test_sans_initiative_il_ne_demande_pas_qui_parle(self):
        """La règle qui le rend supportable : un mot seulement si on l'appelle."""
        lui = self._assistant_of()
        watcher = self._watcher(lui, (True, False))
        watcher._apply_the_buttons(True, False)
        assert watcher._voices_to_ask_about(now=600.0) == []

    def test_rien_ne_change_quand_rien_ne_change(self):
        lui = self._assistant_of()
        voice = lui.voice
        self._watcher(lui, (True, True))._apply_the_buttons(True, True)
        assert lui.manners.active and lui.voice is voice and not voice.tue
