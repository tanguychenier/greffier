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


class SliceTranscriber:
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


def where_in(tmp_path, written, offset=0.0):
    """La position dans l'audio réellement écrit, telle que la lit le direct."""
    return Position(morceau=tmp_path / "r-01.wav", written=written, offset=offset)


class TestTheClipboard:
    def test_a_pasted_link_becomes_a_suggestion(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "voir https://miro.com/x")
        fresh = watcher(tmp_path).clipboard_turn(12.0)
        assert [p.text for p in fresh] == ["https://miro.com/x"]

    def test_the_same_link_is_not_offered_every_turn(self, tmp_path, monkeypatch):
        """Le presse-papier est relu toutes les deux secondes."""
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "https://miro.com/x")
        instance = watcher(tmp_path)
        assert len(instance.clipboard_turn(2.0)) == 1
        assert instance.clipboard_turn(4.0) == []

    def test_an_empty_clipboard_does_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "")
        assert watcher(tmp_path).clipboard_turn(1.0) == []


class TestTheSuggestionsLog:
    def test_every_suggestion_is_one_line(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "https://a.fr https://b.fr")
        instance = watcher(tmp_path)
        instance.clipboard_turn(7.0)
        lines = (tmp_path / "propositions.jsonl").read_text().strip().splitlines()
        assert len(lines) == 2
        first_call = json.loads(lines[0])
        assert first_call["genre"] == Kind.LINK.value
        assert first_call["instant"] == 7.0

    def test_the_log_is_appended_to_and_never_rewritten(self, tmp_path, monkeypatch):
        """Une interruption ne doit rien perdre de ce qui précède."""
        instance = watcher(tmp_path)
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "https://a.fr")
        instance.clipboard_turn(1.0)
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "https://b.fr")
        instance.clipboard_turn(2.0)
        assert len((tmp_path / "propositions.jsonl").read_text().strip().splitlines()) == 2


class TestTranscribingAsItGoes:
    def test_the_instants_are_put_back_on_the_meeting_clock(self, tmp_path, monkeypatch):
        """Une réplique datée dans sa tranche renverrait au mauvais moment."""
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        # La fenêtre transcrite précède la tranche de CONTEXTE_S : une réplique
        # dite 3 s après le début de la tranche y est datée d'autant plus tard.
        transcriber = SliceTranscriber(
            [[utterance(watch.CONTEXTE_S + 3, "Greffier, ouvre le tableau")]]
        )
        instance = watcher(tmp_path, transcriber=transcriber, traite=120.0)
        fresh = instance.transcription_turn(where_in(tmp_path, written=150.0), tmp_path)
        # 120 s déjà lues, 5 s de recouvrement : la tranche part de 115 s.
        assert fresh[0].at_instant == 118.0

    def test_the_timestamps_follow_the_pieces_not_the_clock(self, tmp_path, monkeypatch):
        """Après une pause, l'audio écrit et l'horloge ont divergé.

        Le second morceau redémarre à zéro dans son fichier : sans le décalage,
        une phrase dite à la 40ᵉ minute s'afficherait à la 2ᵉ.
        """
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        transcriber = SliceTranscriber(
            [[utterance(2, "Greffier, ouvre le ticket")]]
        )
        # Le morceau ne porte que 20 s : la fenêtre ne peut pas remonter plus
        # haut que son début, donc les temps sont ceux de la tranche.
        instance = watcher(tmp_path, transcriber=transcriber, traite=1800.0)
        fresh = instance.transcription_turn(
            where_in(tmp_path, written=20.0, offset=1800.0), tmp_path
        )
        # Une demi-heure déjà enregistrée avant ce morceau, plus 2 s dedans.
        assert fresh[0].at_instant == 1802.0

    def test_too_short_a_slice_is_not_transcribed(self, tmp_path, monkeypatch):
        # Le modèle invente plus qu'il n'entend sur deux secondes d'audio.
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        transcriber = SliceTranscriber([[utterance(0, "à peine un mot")]])
        instance = watcher(tmp_path, transcriber=transcriber)
        assert instance.transcription_turn(where_in(tmp_path, written=2.0), tmp_path) == []
        assert transcriber.appels == 0

    def test_the_text_overlap_between_two_slices_is_removed(
        self, tmp_path, monkeypatch
    ):
        """Le vrai pipeline, sans modèle : seul le port Transcripteur est une
        doublure. Une phrase à cheval sur deux tranches successives ne doit
        plus s'afficher avec la fin de la précédente collée devant."""
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        transcriber = SliceTranscriber([
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
        instance.transcription_turn(where_in(tmp_path, written=10.0), tmp_path)
        instance.transcription_turn(where_in(tmp_path, written=20.0), tmp_path)
        assert follower.thread.turns[-1].text == "Sandy, tu peux nous dire où on en est ?"

    def test_a_failed_slice_does_not_grow_for_ever(self, tmp_path, monkeypatch):
        """Un échec durable ferait grossir la tranche jusqu'à des minutes de calcul."""
        demandees = []
        monkeypatch.setattr(
            watch, "extract_slice",
            lambda audio, start, end, dest: demandees.append((start, end)) or None,
        )
        instance = watcher(tmp_path, transcriber=SliceTranscriber([]))
        instance.transcription_turn(where_in(tmp_path, written=600.0), tmp_path)
        start, end = demandees[0]
        assert end - start == watch.TRANCHE_MAXIMALE

    def test_an_unreadable_slice_does_not_stop_the_watch(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watch, "extract_slice", lambda *args: None)
        instance = watcher(tmp_path, transcriber=SliceTranscriber([]))
        assert instance.transcription_turn(where_in(tmp_path, written=30.0), tmp_path) == []

    def test_with_no_transcriber_only_the_clipboard_watch_runs(self, tmp_path):
        veille = watcher(tmp_path)
        assert veille.transcription_turn(where_in(tmp_path, written=30.0), tmp_path) == []


class TestTheEndOfTheMeeting:
    """Les dernières secondes ne doivent pas rester dans le tuyau.

    Sans rattrapage, il reste toujours jusqu'à une période d'audio non
    transcrite : on finit sa phrase devant un fil qui s'arrête avant elle.
    """

    def test_audio_that_stops_growing_is_still_transcribed(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "")
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        transcriber = SliceTranscriber([[utterance(1, "Greffier, ouvre le ticket")]])
        instance = watcher(tmp_path, transcriber=transcriber, slice_period=30.0)
        fige = where_in(tmp_path, written=6.0)
        # Premier passage : on ne sait pas encore si la capture avance.
        assert not instance._is_time(fige)
        # Second : la taille n'a pas bougé, il reste 6 s à dire.
        assert instance._is_time(fige)

    def test_the_last_pass_catches_what_was_left(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "")
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        transcriber = SliceTranscriber([[utterance(1, "Greffier, ouvre le ticket")]])
        instance = watcher(
            tmp_path, transcriber=transcriber, slice_period=30.0,
            situer=lambda: where_in(tmp_path, written=12.0),
        )
        # La réunion s'arrête tout de suite : rien n'a atteint la période.
        propositions = instance.loop(
            still_running=lambda: False, since=lambda: 0.0, job=tmp_path,
            pause=lambda _: None,
        )
        assert transcriber.appels == 1
        assert propositions

    def test_too_short_a_remainder_triggers_nothing(self, tmp_path):
        instance = watcher(tmp_path, slice_period=30.0)
        fige = where_in(tmp_path, written=1.5)
        instance._is_time(fige)
        assert not instance._is_time(fige)


class TestTheWholeLoop:
    def test_the_two_rhythms_live_together(self, tmp_path, monkeypatch):
        """Le presse-papier est relu souvent, la transcription rarement :
        une tranche coûte plusieurs secondes de calcul."""
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "")
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        transcriber = SliceTranscriber([[], [], []])
        written = {"s": 0.0}
        instance = watcher(
            tmp_path,
            transcriber=transcriber,
            situer=lambda: where_in(tmp_path, written=written["s"]),
        )

        turns = {"n": 0}

        def still_running():
            turns["n"] += 1
            return turns["n"] <= 40

        instance.loop(
            still_running=still_running,
            since=lambda: written["s"],
            job=tmp_path,
            # Chaque pause de deux secondes ajoute deux secondes d'audio écrit.
            pause=lambda _: written.__setitem__("s", written["s"] + 2.0),
        )
        # 40 tours × 2 s = 80 s : deux tranches de 30 s, pas quarante — plus la
        # passe de fin, qui rattrape les vingt dernières secondes.
        assert transcriber.appels == 3

    def test_the_rhythm_follows_the_audio_written_not_the_clock(self, tmp_path, monkeypatch):
        """En pause, le fichier ne grandit plus : une seule tranche, pas quarante.

        Celle-là est nécessaire — c'est le rattrapage qui affiche la fin de ce
        qui vient d'être dit. Ensuite il n'y a plus rien de neuf, et l'horloge
        qui continue d'avancer ne doit pas réclamer des tranches d'un passage
        qui n'existe pas.
        """
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "")
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        transcriber = SliceTranscriber([[], []])
        clock = {"t": 0.0}
        instance = watcher(
            tmp_path,
            transcriber=transcriber,
            # L'audio reste figé : l'enregistrement est suspendu.
            situer=lambda: where_in(tmp_path, written=4.0),
        )
        turns = {"n": 0}

        def still_running():
            turns["n"] += 1
            return turns["n"] <= 40

        instance.loop(
            still_running=still_running, since=lambda: clock["t"], job=tmp_path,
            pause=lambda _: clock.__setitem__("t", clock["t"] + 2.0),
        )
        assert transcriber.appels == 1

    def test_the_loop_stops_with_the_recording(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "")
        instance = watcher(tmp_path)
        assert instance.loop(still_running=lambda: False, since=lambda: 0.0,
                                job=tmp_path, pause=lambda _: None) == []


class TestAJoinPublishedToTheWindow:
    """La réunion de voix voyage par le journal, comme les tours.

    La fenêtre reconstruit le fil sans jamais calculer d'empreinte : il lui faut
    le résultat du recollage, pas de quoi le refaire.
    """

    def test_a_join_replays_from_the_log(self):
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

    def test_a_name_given_by_hand_survives_the_replayed_join(self):
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

    def test_an_incomplete_join_line_is_ignored(self):
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


class TestThePromptSeedRereadMidMeeting:
    """Un terme appris en réunion doit servir à la phrase suivante.

    Le processus du direct figeait son amorce au démarrage, si bien qu'ajouter
    « OTP » pendant la réunion ne servait qu'à la réunion d'après — alors que
    c'est justement en réunion qu'on découvre les mots qui manquent.
    """

    def watcher_with(self, prompt_seed: str, relire=None):
        return Watcher(
            watch_rules=WatchRules(keyword="greffier"),
            log=pathlib.Path("/tmp/greffier-essai.jsonl"),
            transcriber=None,
            situer=lambda: None,
            prompt_seed=prompt_seed,
            relire_l_amorce=relire,
        )

    def test_without_rereading_the_seed_does_not_change(self):
        watcher = self.watcher_with("Vocabulaire : CASA.")
        assert watcher._current_prompt_seed() == "Vocabulaire : CASA."

    def test_a_fresh_seed_replaces_the_old_one(self):
        watcher = self.watcher_with(
            "Vocabulaire : CASA.", relire=lambda: "Vocabulaire : CASA, OTP."
        )
        assert "OTP" in watcher._current_prompt_seed()
        assert "OTP" in watcher.prompt_seed, "la nouvelle est retenue"

    def test_an_empty_reread_does_not_lose_the_seed(self):
        """Un contexte momentanément illisible ne doit pas dégrader la tranche."""
        watcher = self.watcher_with("Vocabulaire : CASA.", relire=lambda: "")
        assert watcher._current_prompt_seed() == "Vocabulaire : CASA."

    def test_a_reread_that_fails_does_not_raise(self):
        def tomber():
            raise OSError("fichier occupé")

        watcher = self.watcher_with("Vocabulaire : CASA.", relire=tomber)
        assert watcher._current_prompt_seed() == "Vocabulaire : CASA."


class TestTheWindowOfContext:
    """Le modèle reçoit ce qui précède, et n'en réaffiche rien.

    Mesuré le 2026-09-09 sur une réunion réelle : le même passage donne « sur
    la ZIS » avec 15 s de fenêtre, « sur Asis » avec 30 s, « sur Oasis » avec
    60 s. Le contexte fait le mot juste, mais il ne doit rien redire.
    """

    def test_the_model_gets_more_audio_than_the_slice(self, tmp_path, monkeypatch):
        demandees = []

        def extract(audio, start, end, dest):
            demandees.append((start, end))
            return dest

        monkeypatch.setattr(watch, "extract_slice", extract)
        transcriber = SliceTranscriber([[]])
        instance = watcher(tmp_path, transcriber=transcriber, traite=120.0)
        instance.transcription_turn(where_in(tmp_path, written=150.0), tmp_path)
        slice_, window = demandees
        assert slice_ == (115.0, 150.0)
        assert window == (115.0 - watch.CONTEXTE_S, 150.0)

    def test_what_is_in_the_context_is_not_shown_again(self, tmp_path, monkeypatch):
        """Sinon chaque phrase s'afficherait six fois."""
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        transcriber = SliceTranscriber([[
            utterance(2, "phrase déjà affichée, dans le contexte"),
            utterance(watch.CONTEXTE_S + 1, "phrase neuve, dans la tranche"),
        ]])
        instance = watcher(tmp_path, transcriber=transcriber, traite=120.0)
        fresh = instance.transcription_turn(where_in(tmp_path, written=150.0), tmp_path)
        instance_veille = [p.text for p in fresh]
        assert not any("déjà affichée" in t for t in instance_veille)

    def test_at_the_start_the_window_does_not_reach_before_zero(
        self, tmp_path, monkeypatch
    ):
        demandees = []
        monkeypatch.setattr(
            watch, "extract_slice",
            lambda audio, start, end, dest: demandees.append(start) or dest,
        )
        transcriber = SliceTranscriber([[]])
        instance = watcher(tmp_path, transcriber=transcriber)
        instance.transcription_turn(where_in(tmp_path, written=12.0), tmp_path)
        assert all(start >= 0.0 for start in demandees)

    def test_an_utterance_astride_is_kept_whole(self):
        """Couper une phrase au milieu vaut moins que retirer son début affiché."""
        kept = watch._within_the_slice(
            [Utterance(Span(8, 14), "dernier. Sandy, tu peux nous dire…")], 10.0
        )
        assert len(kept) == 1
        assert kept[0].span.start == 0.0
        assert kept[0].span.end == 4.0

    def test_an_utterance_wholly_inside_the_context_goes(self):
        assert watch._within_the_slice(
            [Utterance(Span(2, 6), "déjà dit")], 10.0
        ) == []

    def test_with_no_context_nothing_is_touched(self):
        utterances = [Utterance(Span(2, 6), "du texte")]
        assert watch._within_the_slice(utterances, 0.0) == utterances



class TestTheTwoButtonsDuringAMeeting:
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
            watch_rules=WatchRules(keyword="greffier"),
            log=Path("/tmp/inutilise.jsonl"),
            assistant_of=assistant_of,
            reread_participation=lambda: buttons,
            give_voice_back=(lambda: voix_neuve) if voix_neuve else None,
        )

    def _assistant_of(self, avec_voix=True):
        from greffier.application.take_part import AssistantSettings
        from greffier.domain.participation import Manners

        class FakeVoice:
            def __init__(self):
                self.tue = False

            def say(self, _t):
                return True

            def go_quiet(self):
                self.tue = True

            def is_speaking(self):
                return False

        return AssistantSettings(name="Lucie", voice=FakeVoice() if avec_voix else None,
                           manners=Manners(active=True))

    def test_cutting_the_voice_stops_it_at_once(self):
        """Appuyer pendant qu'il parle doit couper, pas attendre la fin."""
        lui = self._assistant_of()
        voice = lui.voice
        self._watcher(lui, (False, False))._apply_the_buttons(False, False)
        assert voice.tue

    def test_taking_the_voice_away_leaves_it_writing(self):
        lui = self._assistant_of()
        self._watcher(lui, (False, False))._apply_the_buttons(False, False)
        assert lui.voice is None
        assert lui.manners.active, "il participe toujours, sans se faire entendre"

    def test_giving_the_voice_back_loads_it_once(self):
        """Charger un modèle coûte : on ne le fait qu'à la demande."""
        lui = self._assistant_of(avec_voix=False)
        neuve = object()
        watcher = self._watcher(lui, (True, False), voix_neuve=neuve)
        watcher._apply_the_buttons(True, False)
        assert lui.voice is neuve

    def test_with_no_way_to_give_it_back_it_stays_silent(self):
        """Aucun modèle installé : il participe par écrit, sans se plaindre."""
        lui = self._assistant_of(avec_voix=False)
        self._watcher(lui, (True, False))._apply_the_buttons(True, False)
        assert lui.voice is None and lui.manners.active

    def test_the_initiative_can_be_taken_mid_meeting(self):
        """Le bouton n'agissait qu'à la réunion suivante, ce qui ne se devine pas."""
        lui = self._assistant_of()
        watcher = self._watcher(lui, (True, True))
        assert not watcher.initiative, "livrée éteinte"
        watcher._apply_the_buttons(True, True)
        assert watcher.initiative

    def test_the_initiative_can_be_taken_back_too(self):
        lui = self._assistant_of()
        watcher = self._watcher(lui, (True, False))
        watcher.initiative = True
        watcher._apply_the_buttons(True, False)
        assert not watcher.initiative

    def test_without_the_initiative_it_does_not_ask_who_is_speaking(self):
        """La règle qui le rend supportable : un mot seulement si on l'appelle."""
        lui = self._assistant_of()
        watcher = self._watcher(lui, (True, False))
        watcher._apply_the_buttons(True, False)
        assert watcher._voices_to_ask_about(now=600.0) == []

    def test_nothing_changes_when_nothing_changes(self):
        lui = self._assistant_of()
        voice = lui.voice
        self._watcher(lui, (True, True))._apply_the_buttons(True, True)
        assert lui.manners.active and lui.voice is voice and not voice.tue


class TestOnceTheMeetingEnds:
    """Clicking "end the meeting" must end it, the assistant included.

    The last slice is still transcribed, so nothing said at the very end is
    lost, but it is transcribed silently: an answer coming out of the speakers
    in a room that has just been told the meeting is over would be the one
    thing everybody remembers of the demonstration.
    """

    class FakeVoice:
        def __init__(self):
            self.tue = False
            self.said = []

        def say(self, text):
            self.said.append(text)
            return True

        def go_quiet(self):
            self.tue = True

        def is_speaking(self):
            return False

    def _assistant(self):
        from greffier.application.take_part import AssistantSettings
        from greffier.domain.participation import Manners

        return AssistantSettings(
            name="Lucie", voice=self.FakeVoice(), manners=Manners(active=True),
        )

    def _watcher(self, tmp_path, monkeypatch, written, lui):
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "")
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        return watcher(
            tmp_path,
            transcriber=SliceTranscriber([[utterance(0.0, "Lucie, tu en penses quoi ?")]]),
            situer=lambda: where_in(tmp_path, written=written),
            assistant_of=lui,
        )

    def test_the_last_slice_is_still_transcribed(self, tmp_path, monkeypatch):
        lui = self._assistant()
        instance = self._watcher(tmp_path, monkeypatch, 20.0, lui)
        instance.last_pass(tmp_path)
        assert instance.traite == 20.0, "the closing audio is read"

    def test_she_does_not_answer_on_the_last_slice(self, tmp_path, monkeypatch):
        """Called by name in the last seconds: transcribed, not answered."""
        lui = self._assistant()
        appels = []
        lui.answer_aside = lambda opening, now: appels.append(opening)
        instance = self._watcher(tmp_path, monkeypatch, 20.0, lui)
        instance.last_pass(tmp_path)
        assert appels == []

    def test_she_answers_on_an_ordinary_slice(self, tmp_path, monkeypatch):
        """The counter-proof: the same slice mid-meeting does reach her."""
        lui = self._assistant()
        appels = []
        lui.answer_aside = lambda opening, now: appels.append(opening)
        instance = self._watcher(tmp_path, monkeypatch, 20.0, lui)
        instance.transcription_turn(where_in(tmp_path, written=20.0), tmp_path)
        assert len(appels) == 1

    def test_the_voice_is_cut_when_the_loop_ends(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "")
        lui = self._assistant()
        voice = lui.voice
        watcher(tmp_path, assistant_of=lui).loop(
            still_running=lambda: False, since=lambda: 0.0, job=tmp_path,
            pause=lambda _: None,
        )
        assert voice.tue, "a sentence under way stops with the meeting"
        assert lui.stopped

    def test_a_watch_without_an_assistant_ends_quietly(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "")
        watcher(tmp_path).loop(still_running=lambda: False, since=lambda: 0.0,
                               job=tmp_path, pause=lambda _: None)
