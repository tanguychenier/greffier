"""Traiter une réunion enregistrée : de l'audio au compte rendu envoyé.

Ce module ne connaît aucun outil. Il reçoit des ports, les appelle dans l'ordre,
applique les règles du domaine et rend un résultat. C'est ce qui permet de le
tester entièrement avec des doublures, sans audio, sans modèle et sans réseau —
et de savoir que la logique est juste indépendamment de whisper ou d'Ollama.
"""

from __future__ import annotations

import contextlib
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from greffier.domain import names as noms_domaine
from greffier.domain import profiles
from greffier.domain import voiceprints as voix_domaine
from greffier.domain.attribution import voice_of
from greffier.domain.boilerplate import is_an_annotation, is_boilerplate
from greffier.domain.language import LanguageProfile
from greffier.domain.meeting import StoredMeeting
from greffier.domain.minutes import title as titre_du_compte_rendu
from greffier.domain.models import (
    Phase,
    Span,
    SpeakerTurn,
    Utterance,
    Voiceprint,
)
from greffier.domain.profiles.neutral import NEUTRAL
from greffier.ports import outbound

# En dessous, tous les canaux sont considérés muets et il n'y a rien à
# transcrire. Le bruit de fond d'un micro ouvert dans une pièce vide tourne
# autour de -55 dB ; -70 ne retient que le vrai silence numérique.
SEUIL_MUET_DB = -70.0

# Entre les deux, on prévient sans alarmer : une heure de réunion comporte des
# silences, et 80 % de couverture reste normal. En dessous, il manque du texte.
COUVERTURE_BASSE = 0.80
# Sous ce nombre de mots, rédiger un compte rendu ne produit que du bruit. Sans
# ce contrôle, un enregistrement inaudible donnait un « compte rendu » fabriqué
# de toutes pièces, expédié par mail (constaté le 2026-08-20).
MOTS_MINIMUM = 20

AVERTISSEMENT_SANS_BOUCLE = "· boucle système muette, à préciser"

class ChainStopped(Exception):
    """Arrêt volontaire de la chaîne, avec une raison présentable."""

    def __init__(self, phase: Phase, because: str) -> None:
        super().__init__(because)
        self.phase = phase
        self.because = because

@dataclass
class Outcome:
    audio: Path
    utterances: list[Utterance] = field(default_factory=list)
    turns: list[SpeakerTurn] = field(default_factory=list)
    # voix acoustique → nom retenu
    names: dict[str, str] = field(default_factory=dict)
    # voix → nom proposé mais pas assez étayé pour être affirmé
    propositions: dict[str, str] = field(default_factory=dict)
    minutes: str = ""
    envoye: bool = False
    fichier_maitre: Path | None = None
    transcript_written: Path | None = None
    compte_rendu_ecrit: Path | None = None
    warnings: list[str] = field(default_factory=list)
    hardware_events: list[str] = field(default_factory=list)
    profil: LanguageProfile = NEUTRAL
    commencee_le: datetime | None = None
    terminee_le: datetime | None = None
    subject: str = ""

    @property
    def words(self) -> int:
        """Le nombre de mots, compté comme la langue les sépare.

        Compter les espaces refusait une transcription chinoise, japonaise ou
        thaï parfaitement valable : elle tombait sous le seuil et la chaîne
        s'interrompait sur « Transcription quasi vide », avant de rédiger.
        """
        return sum(self.profil.decoupage.count_them(r.text) for r in self.utterances)

    def nom_de(self, voice: str | None) -> str:
        if voice is None:
            return "Indéterminé"
        return self.names.get(voice, f"Personne {voice}")

    def speaking_time(self) -> dict[str, float]:
        """Secondes parlées par voix, du plus bavard au moins bavard."""
        cumul: dict[str, float] = {}
        for turn in self.turns:
            cumul[turn.voice] = cumul.get(turn.voice, 0.0) + turn.span.duration
        return dict(sorted(cumul.items(), key=lambda x: -x[1]))

    @property
    def duration(self) -> float:
        """Durée couverte par la réunion, d'après le dernier tour de parole."""
        return self.turns[-1].span.end if self.turns else 0.0

    @property
    def coverage(self) -> float:
        """Part de l'audio qui porte effectivement du texte."""
        if self.duration <= 0:
            return 0.0
        return min(1.0, sum(r.span.duration for r in self.utterances) / self.duration)

    def gaps(self, minimum: float = 5.0) -> list[Span]:
        """Passages d'au moins `minimum` secondes sans une seule réplique.

        Un silence peut être un vrai silence — ou du texte perdu. On les liste
        sans trancher : c'est au compte rendu de le dire honnêtement.
        """
        if not self.utterances:
            return [Span(0.0, self.duration)] if self.duration > minimum else []
        manques: list[Span] = []
        precedent = 0.0
        for utterance in sorted(self.utterances, key=lambda r: r.span.start):
            if utterance.span.start - precedent >= minimum:
                manques.append(Span(precedent, utterance.span.start))
            precedent = max(precedent, utterance.span.end)
        if self.duration - precedent >= minimum:
            manques.append(Span(precedent, self.duration))
        return manques

    def significant_voices(self, minimum: float = 10.0) -> dict[str, float]:
        """Voix ayant assez parlé pour être un participant.

        La segmentation laisse toujours une traîne de fragments d'une seconde,
        trop courts pour porter un timbre. Les compter comme des participants
        donnerait « 22 personnes » à une réunion qui en compte cinq.
        """
        return {v: d for v, d in self.speaking_time().items() if d >= minimum}

@dataclass
class Chain:
    """Assemble les ports. La composition décide de qui est branché où."""

    audio_recorder: outbound.AudioRecorder
    transcriber: outbound.Transcriber
    diariser: outbound.Diariser
    extractor: outbound.VoiceprintExtractor | None = None
    bank: outbound.VoiceBank | None = None
    writer: outbound.Writer | None = None
    sender: outbound.Sender | None = None
    log: outbound.StateJournal | None = None
    notificateur: outbound.Notifier | None = None
    store: outbound.MeetingStore | None = None
    dossier_transcriptions: Path | None = None
    dossier_comptes_rendus: Path | None = None

    language: str = "fr"
    prompt_seed: str = ""
    context_header: str = ""
    people: int | None = None
    not_first_names: frozenset[str] = frozenset()
    recipient: str = ""
    disclosure: str = "rien"
    hardware_events: list[str] = field(default_factory=list)

    # ------------------------------------------------------------- avancement

    def _phase(self, phase: Phase, message: str = "") -> None:
        if self.log:
            self.log.publish(phase.value, message)

    def _notify_user(self, title: str, message: str) -> None:
        if self.notificateur:
            self.notificateur.notify(title, message)

    # ---------------------------------------------------------------- étapes

    def _check_audio(self, audio: Path, outcome: Outcome) -> None:
        """Refuse de transcrire un enregistrement muet.

        Sans ce garde-fou, whisper rend un fichier vide, le compte rendu est
        rédigé à partir de rien, et il part quand même par mail.
        """
        levels = self.audio_recorder.levels(audio)
        if not levels:
            return
        if all(level < SEUIL_MUET_DB for level in levels):
            raise ChainStopped(
                Phase.ECHEC,
                "Enregistrement muet sur tous les canaux. "
                "Vérifie l'autorisation micro et le périphérique d'entrée.",
            )
        # Un seul canal muet est légitime en présentiel : le son système n'existe
        # pas. On le signale sans bloquer.
        if len(levels) >= 2:
            if levels[0] < SEUIL_MUET_DB:
                outcome.warnings.append(
                    "Ton micro est resté muet : seuls les autres participants sont transcrits."
                )
            elif max(levels[1:]) < SEUIL_MUET_DB:
                # Deux situations donnent le même silence, et on ne peut pas les
                # distinguer ici : une réunion en salle, où tout passe par le
                # micro et où ce silence est normal ; une visio dont la boucle
                # système n'a pas été branchée, où les autres participants sont
                # perdus. La première est de loin la plus fréquente, et annoncer
                # « seule ta voix est transcrite » y était simplement faux — le
                # micro de table entend tout le monde. `_preciser_les_canaux`
                # tranche après le découpage, quand on sait combien de personnes
                # ce micro portait.
                outcome.warnings.append(AVERTISSEMENT_SANS_BOUCLE)

    def _preciser_les_canaux(self, outcome: Outcome) -> None:
        """Dit ce que le silence de la boucle système voulait dire.

        Une seule voix sur le micro : la boucle manquait vraiment, et les autres
        participants sont perdus. Plusieurs voix : c'est une réunion en salle, le
        micro a tout entendu, et il n'y a rien à signaler. Le rédacteur lit ces
        avertissements ; lui laisser croire qu'il manque du monde lui fait écrire
        un compte rendu prudent sur une transcription complète.
        """
        if AVERTISSEMENT_SANS_BOUCLE not in outcome.warnings:
            return
        outcome.warnings.remove(AVERTISSEMENT_SANS_BOUCLE)
        if len(outcome.significant_voices()) > 1:
            return
        outcome.warnings.append(
            "Aucun son système capté et une seule voix entendue : si la réunion "
            "était en visio, les autres participants n'ont pas été enregistrés."
        )

    def _warn_about_coverage(self, outcome: Outcome) -> None:
        """Dit à l'utilisateur ce que la transcription a perdu.

        Le taux était calculé, transmis au rédacteur, et jamais montré. Sur une
        réunion réelle, 22 % de l'audio ne portait aucun texte : le compte rendu
        l'a mentionné de lui-même, l'utilisateur n'a rien vu passer.
        """
        from greffier.application.render import COUVERTURE_SUSPECTE, TROU_SIGNIFICATIF

        coverage = outcome.coverage
        if coverage <= 0:
            return
        gaps = [t for t in outcome.gaps(TROU_SIGNIFICATIF) if t.duration >= TROU_SIGNIFICATIF]
        perdu = sum(t.duration for t in gaps)
        if coverage < COUVERTURE_SUSPECTE:
            outcome.warnings.append(
                f"Couverture de {coverage * 100:.0f} % seulement : le modèle a "
                "probablement décroché sur une partie de la réunion. Le compte rendu "
                "en est averti, mais réécoute les passages qui te paraissent absents."
            )
        elif coverage < COUVERTURE_BASSE:
            outcome.warnings.append(
                f"Couverture de {coverage * 100:.0f} % : "
                f"{perdu / 60:.0f} min sans aucun texte. Des silences peuvent "
                "l'expliquer, mais vérifie qu'il ne manque rien d'important."
            )
        elif gaps:
            outcome.warnings.append(
                f"{len(gaps)} passage(s) sans texte, {perdu / 60:.0f} min au total. "
                "Un silence, ou du texte perdu : le compte rendu ne tranche pas."
            )

    def _warn_about_attendees(self, outcome: Outcome) -> None:
        """Dit quand le nombre annoncé contredit ce que l'audio contient.

        Annoncer un nombre force **exactement** autant de groupes : une voix de
        plus est fondue dans une autre, en silence. Sur une réunion réelle du
        2026-09-09, « 4 participants » avait été laissé dans la configuration et
        la réunion en comptait davantage — deux personnes se sont retrouvées
        confondues sans que rien ne le signale, et le compte rendu leur a prêté
        les propos l'une de l'autre.

        On ne peut pas savoir laquelle des deux valeurs est juste : le nombre
        vient d'un humain, le recollage d'une mesure. On dit l'écart.
        """
        if self.people is None:
            return
        entendues = len(outcome.significant_voices())
        if entendues == 0 or entendues == self.people:
            return
        outcome.warnings.append(
            f"{self.people} participants sont annoncés dans la configuration, "
            f"mais {entendues} voix distinctes ont été entendues. Le nombre "
            "annoncé l'emporte, donc des personnes ont pu être confondues. "
            "Laisse « participants » vide pour que le nombre soit déduit."
        )

    def _identify_voices(self, audio: Path, turns: list[SpeakerTurn]) -> list[SpeakerTurn]:
        """Recolle les voix sur-découpées par la segmentation.

        La segmentation éclate volontiers une personne en plusieurs groupes —
        **298 voix pour trois personnes** autour d'une table, mesuré sur une
        réunion réelle de 92 minutes. Sans ce recollage, le compte rendu invente
        des participants ; avec, il en reste 23, dont 3 portent plus de dix
        secondes.
        """
        if self.extractor is None:
            return turns
        per_voice: dict[str, list[Span]] = {}
        for turn in turns:
            per_voice.setdefault(turn.voice, []).append(turn.span)
        voiceprints = self._voiceprints_per_voice(audio, per_voice)
        membership = voix_domaine.stitch(voiceprints)
        return [
            SpeakerTurn(t.span, membership.get(t.voice, t.voice), t.source) for t in turns
        ]

    def _voiceprints_per_voice(
        self, audio: Path, per_voice: dict[str, list[Span]]
    ) -> dict[str, list[Voiceprint]]:
        """Les empreintes de chaque voix, en ne lisant l'audio qu'une fois."""
        from greffier.application.render import voiceprints_per_voice

        if self.extractor is None:
            return {}
        return voiceprints_per_voice(self.extractor, audio, per_voice)

    def _recognise(self, audio: Path, turns: list[SpeakerTurn]) -> dict[str, str]:
        """Noms venus de la banque de voix, pour les personnes déjà connues."""
        if self.extractor is None or self.bank is None:
            return {}
        connues = self.bank.people()
        if not connues:
            return {}
        trouves: dict[str, str] = {}
        per_voice: dict[str, list[Span]] = {}
        for turn in turns:
            per_voice.setdefault(turn.voice, []).append(turn.span)
        for voice, intervalles in per_voice.items():
            extraits = self.extractor.extract_spans(audio, intervalles)
            if not extraits:
                continue
            match = voix_domaine.recognise(voix_domaine.aggregate(extraits), connues)
            if match and match.sure:
                trouves[voice] = match.name
        return trouves

    def _attribute_names(
        self,
        utterances: list[Utterance],
        turns: list[SpeakerTurn],
        depuis_banque: dict[str, str],
        outcome: Outcome,
    ) -> None:
        """Croise les noms prononcés et les voix reconnues.

        Une voix à la fois reconnue par son empreinte *et* nommée par un
        collègue est une certitude. Une seule des deux reste une proposition :
        mieux vaut demander que d'écrire un nom inventé dans un compte rendu.
        """
        mentions = noms_domaine.spot_mentions(
            utterances, outcome.profil, self.not_first_names
        )
        attribution = noms_domaine.attribute(mentions, turns)

        for voice, name in depuis_banque.items():
            outcome.names[voice] = name

        for voice, trouve in attribution.certitudes.items():
            connu = depuis_banque.get(voice)
            if connu and connu.lower() != trouve.name.lower():
                # Désaccord : la banque a été validée par un humain, elle prime,
                # mais l'écart mérite d'être signalé plutôt qu'enterré.
                outcome.warnings.append(
                    f"La voix {voice} est reconnue comme {connu} mais nommée {trouve.name} "
                    "pendant la réunion."
                )
                continue
            outcome.names[voice] = trouve.name

        for proposition in attribution.propositions:
            if proposition.voice not in outcome.names:
                outcome.propositions[proposition.voice] = proposition.name

    def _attach_voices(self, utterances: list[Utterance], turns: list[SpeakerTurn]) -> None:
        """Donne à chaque réplique la voix qui la tient nettement, sinon aucune.

        Le « nettement » est la règle du domaine : une phrase qui enjambe un
        changement de locuteur ne désigne personne plutôt que le plus bavard.
        """
        for utterance in utterances:
            utterance.voice = voice_of(utterance.span, turns)

    def _join_namesakes(self, outcome: Outcome) -> None:
        """Replie sur une seule voix celles qui portent le même nom.

        Après l'attribution, et non avant : c'est elle qui donne les noms, et
        c'est le nom qui dit ici que deux voix sont la même personne. Le
        recollage par empreinte a déjà fait ce qu'il pouvait ; ce qui reste, il
        ne peut pas le savoir — quelques secondes de parole ne ressemblent
        assez à rien.
        """
        poids = {
            voice: sum(
                t.span.end - t.span.start
                for t in outcome.turns if t.voice == voice
            )
            for voice in set(outcome.names)
        }
        membership = noms_domaine.join_namesakes(outcome.names, poids)
        replies = {v: c for v, c in membership.items() if v != c}
        if not replies:
            return
        outcome.turns = [
            SpeakerTurn(
                t.span, membership.get(t.voice, t.voice), t.source
            )
            for t in outcome.turns
        ]
        for utterance in outcome.utterances:
            if utterance.voice is not None:
                utterance.voice = membership.get(utterance.voice, utterance.voice)
        for voice in replies:
            outcome.names.pop(voice, None)
            outcome.propositions.pop(voice, None)

    # ------------------------------------------------------------- exécution

    def run_chain(
        self,
        audio: Path,
        send: bool = True,
        hardware_events: list[str] | None = None,
        commencee_le: datetime | None = None,
        terminee_le: datetime | None = None,
    ) -> Outcome:
        # Ce que la veille a constaté du matériel : le rédacteur doit le savoir
        # avant d'écrire, pas après.
        self.hardware_events = list(hardware_events or [])
        outcome = Outcome(
            audio=audio,
            hardware_events=self.hardware_events,
            commencee_le=commencee_le,
            terminee_le=terminee_le,
        )

        self._phase(Phase.TRANSCRIPTION, "Vérification de l'enregistrement…")
        self._check_audio(audio, outcome)

        self._phase(Phase.TRANSCRIPTION, "Transcription…")
        # L'audio est mis à niveau avant d'être transcrit. Un signal faible ne
        # donne pas une transcription pauvre, il en donne une inventée : sur un
        # enregistrement réel à -43 dB, le modèle a rendu « Merci d'avoir
        # regardé cette vidéo ! » là où la personne disait « Test, test de
        # réunion ». La durée ne change pas, donc les horodatages restent justes.
        with tempfile.TemporaryDirectory() as folder:
            prepare = self.audio_recorder.prepare_transcript(
                audio, Path(folder) / f"{audio.stem}-niveau.wav"
            )
            brutes = self.transcriber.transcribe(
                prepare, self.language, self.prompt_seed
            )
        # Les génériques que le modèle invente sur signal faible — « Sous-titrage
        # réalisé par… » — n'ont été prononcés par personne. Les garder revenait
        # à les attribuer à quelqu'un dans le compte rendu.
        profil = profiles.pour(self.language)
        outcome.profil = profil
        outcome.utterances = [
            r for r in brutes
            if not is_boilerplate(r.text, profil) and not is_an_annotation(r.text)
        ]
        if outcome.words < MOTS_MINIMUM:
            raise ChainStopped(
                Phase.ECHEC,
                f"Transcription quasi vide ({outcome.words} mots) : "
                "aucun compte rendu n'a été rédigé.",
            )

        self._phase(Phase.LOCUTEURS, "Identification des locuteurs…")
        turns = self.diariser.segment(audio, self.people)
        turns = self._identify_voices(audio, turns)
        outcome.turns = turns
        self._attach_voices(outcome.utterances, turns)
        self._attribute_names(outcome.utterances, turns, self._recognise(audio, turns), outcome)
        self._join_namesakes(outcome)
        # Après le découpage : c'est le nombre de voix entendues qui dit si le
        # silence de la boucle système était normal ou coûteux.
        self._preciser_les_canaux(outcome)
        self._warn_about_coverage(outcome)
        self._warn_about_attendees(outcome)

        # Gardée **avant** de rédiger, et non seulement quand aucun rédacteur
        # n'est branché. Rédiger est la seule étape qui dépende d'un outil hors
        # du poste, donc celle qui échoue : une expiration du rédacteur faisait
        # perdre la transcription et l'attribution des voix d'une réunion
        # entière — 32 minutes, le 2026-09-09 — alors que tout le calcul coûteux
        # était déjà fait et juste. Gardée ici, la réunion se reprend d'un
        # « greffier rediger », sans réécouter l'audio.
        self._keep(audio, outcome)

        if self.writer is None:
            self._phase(Phase.TERMINE, "Transcription prête, aucun rédacteur configuré.")
            return outcome

        self._phase(Phase.REDACTION, f"{outcome.words} mots transcrits. Rédaction…")
        # Le rédacteur apprend d'abord ce que la transcription a perdu : sans
        # cela, le compte rendu présente comme complet un texte qui ne l'est pas.
        from greffier.application.render import (
            context_header,
            disclosure_header,
            hardware_header,
            reliability_header,
            render_transcript,
        )

        duration = outcome.turns[-1].span.end if outcome.turns else 0.0
        # Les voix qui ont réellement porté la réunion, nommées ou non : sans ce
        # compte, un compte rendu dont aucune voix n'est nommée ne disait rien
        # de qui était présent — constaté à l'usage. Les fragments en sont
        # exclus, sans quoi la ligne annonce « et 295 voix non nommées » là où
        # trois personnes étaient présentes.
        entendues = [
            v for v in outcome.significant_voices() if v
        ] + [v for v in outcome.names if v not in outcome.significant_voices()]
        header = (
            context_header(audio.stem, duration,
                            names=[outcome.names[v] for v in entendues if v in outcome.names],
                            voix_entendues=len(entendues),
                            commencee_le=outcome.commencee_le,
                            terminee_le=outcome.terminee_le)
            + hardware_header(self.hardware_events)
            + reliability_header(outcome)
            + disclosure_header(self.disclosure)
            + self.context_header
        )
        outcome.minutes = self.writer.write_up(
            render_transcript(outcome, header)
        )
        # La réunion se nomme d'elle-même : le titre du compte rendu a été écrit
        # après lecture de toute la transcription, et « 2026-09-09_10h05_reunion »
        # ne dit rien de ce qui s'y est passé. Le préfixe « Compte rendu : » est
        # retiré — dans une liste de réunions, il ne distingue rien.
        titre_ecrit = titre_du_compte_rendu(outcome.minutes, "")
        if titre_ecrit:
            outcome.subject = (
                titre_ecrit.split(":", 1)[-1].strip() if ":" in titre_ecrit else titre_ecrit
            )

        # Le compte rendu rejoint ce qui était déjà gardé, **avant** l'envoi :
        # un serveur de courriel indisponible ne doit pas faire perdre une
        # heure de transcription et sa rédaction.
        self._keep(audio, outcome)

        if send and self.sender and self.recipient:
            self._phase(Phase.ENVOI, "Envoi du compte rendu…")
            try:
                self._send(audio, outcome)
            except Exception as trouble:  # noqa: BLE001
                # L'envoi ne doit pas emporter la chaîne. Tout est déjà sur le
                # disque : la transcription, les voix, le compte rendu. Laisser
                # l'exception remonter n'ajoutait rien et coûtait deux fois — le
                # 2026-09-10, une réunion de 1 h 42 est restée figée sur
                # « envoi » deux heures durant, parce que la phase suivante
                # n'était jamais publiée et que l'échec ne se rapportait que par
                # une fenêtre modale que personne n'a vue.
                outcome.warnings.append(
                    f"Compte rendu NON envoyé : {trouble} "
                    "Le compte rendu est gardé ; « greffier envoyer » réessaie."
                )
            else:
                outcome.envoye = True
        elif send:
            # Sauter l'envoi sans le dire laissait croire à un compte rendu parti.
            # L'interface affichait même « Compte rendu envoyé ».
            manque = ("aucun destinataire n'est configuré" if not self.recipient
                      else "aucun moyen d'envoi n'est configuré")
            outcome.warnings.append(
                f"Compte rendu NON envoyé : {manque}. "
                "« greffier envoyer » pour l'expédier, ou renseigne "
                "compte_rendu.destinataire dans la configuration."
            )

        self._phase(
            Phase.TERMINE,
            "Compte rendu envoyé." if outcome.envoye else "Compte rendu prêt, non envoyé.",
        )
        self._notify_user("Greffier", "Compte rendu prêt.")
        return outcome

    def _keep(self, audio: Path, outcome: Outcome) -> None:
        """Écrit le fichier maître, la transcription et le compte rendu.

        Rien n'est écrit si l'appelant n'a pas fourni où : la chaîne reste
        utilisable en mémoire, ce dont les tests d'intégration profitent.
        """
        from greffier.application.render import render_transcript

        duration = outcome.turns[-1].span.end if outcome.turns else 0.0
        if self.store is not None:
            # Un sujet saisi à la main l'emporte, et survit donc à un
            # retraitement : c'est une correction, et une correction que la
            # chaîne écraserait ne servirait à rien.
            with contextlib.suppress(Exception):
                garde = self.store.read(outcome.audio.stem).subject
                if garde:
                    outcome.subject = garde
            outcome.fichier_maitre = self.store.record(
                _as_stored_meeting(outcome, duration))
        if self.dossier_transcriptions is None:
            return
        transcription = self.dossier_transcriptions / f"{audio.stem}.txt"
        transcription.parent.mkdir(parents=True, exist_ok=True)
        transcription.write_text(render_transcript(outcome), encoding="utf-8")
        outcome.transcript_written = transcription
        if outcome.minutes and self.dossier_comptes_rendus is not None:
            minutes = self.dossier_comptes_rendus / f"{audio.stem}.md"
            minutes.parent.mkdir(parents=True, exist_ok=True)
            minutes.write_text(outcome.minutes, encoding="utf-8")
            outcome.compte_rendu_ecrit = minutes

    def _send(self, audio: Path, outcome: Outcome) -> None:
        """Expédie le compte rendu, sans pièce jointe.

        Le corps du message **est** le compte rendu : le joindre une seconde fois
        en fichier n'apporte rien, et expédier la transcription intégrale ferait
        circuler par courriel les propos de chacun mot à mot. « greffier envoyer
        --avec-transcription » la joint quand elle est vraiment demandée.
        """
        assert self.sender is not None
        self.sender.send(
            self.recipient,
            titre_du_compte_rendu(
                outcome.minutes, f"Compte rendu de réunion — {audio.stem}"
            ),
            outcome.minutes,
            [],
        )

def _as_stored_meeting(outcome: Outcome, duration: float) -> StoredMeeting:
    """Le fichier maître, depuis ce que la chaîne a produit.

    Ici et non dans l'adaptateur de dépôt : la conversion appartient au cas
    d'usage qui produit le résultat. Elle y vivait derrière un `Protocol` écrit
    pour éviter que l'adaptateur importe le cas d'usage — un contournement qui
    n'avait plus lieu d'être une fois la dépendance remise à l'endroit.
    """
    return StoredMeeting(
        identifier=outcome.audio.stem,
        audio=outcome.audio,
        traitee_le=datetime.now(UTC),
        duration=duration,
        utterances=outcome.utterances,
        turns=outcome.turns,
        names=dict(outcome.names),
        propositions=dict(outcome.propositions),
        warnings=list(outcome.warnings),
        hardware_events=list(outcome.hardware_events),
        subject=outcome.subject,
        commencee_le=outcome.commencee_le,
        terminee_le=outcome.terminee_le,
    )
