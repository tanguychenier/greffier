"""Une conversation entière avec l'assistant, dans du vrai son.

Les tests unitaires disent que chaque règle est juste. Ils ne disent pas ce qui
se passe quand on enchaîne : elle répond, sa réponse sort par le haut-parleur,
la capture la reprend, le transcripteur la rend déformée, et le fil lui donne
une voix de plus. C'est là que la boucle est née, et aucune doublure ne
l'aurait montrée.

Le harnais fabrique un vrai fichier de réunion avec la synthèse du système, une
voix par personne, et **réinjecte la réponse de l'assistant dans l'audio** —
c'est ce que fait un haut-parleur dans une pièce. Puis il fait tourner le vrai
veilleur, tranche par tranche, avec le vrai transcripteur.

Le cerveau est une doublure : le but n'est pas d'éprouver le modèle, c'est
d'éprouver la boucle autour de lui.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from greffier.adapters.configuration import Config
from greffier.application.follow import Position
from greffier.application.take_part import AssistantSettings
from greffier.application.watch import Watcher
from greffier.domain.instructions import WatchRules
from greffier.domain.participation import Manners
from greffier.wiring import light_transcriber

NAME = "Lucie"

#: Deux voix du système, pour que les personnes se distinguent à l'oreille.
VOIX_DE_LA_SALLE = "Thomas"
VOIX_DE_L_ASSISTANTE = "Amélie"


def _dispo() -> bool:
    return shutil.which("say") is not None and shutil.which("ffmpeg") is not None


def _synthetiser(voice: str, text: str, cible: Path) -> Path | None:
    """Une phrase prononcée, en wav 16 kHz mono."""
    brut = cible.with_suffix(".aiff")
    subprocess.run(["say", "-v", voice, "-o", str(brut), text],
                   check=False, capture_output=True)
    if not brut.exists():
        return None
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(brut),
         "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(cible)],
        check=False, capture_output=True,
    )
    return cible if cible.exists() else None


def _silence(secondes: float, cible: Path) -> Path:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "anullsrc=r=16000:cl=mono", "-t", str(secondes),
         "-c:a", "pcm_s16le", str(cible)],
        check=False, capture_output=True,
    )
    return cible


def _coller(morceaux: list[Path], cible: Path) -> Path:
    """Recolle des wav bout à bout, comme un enregistrement continu."""
    liste = cible.with_suffix(".txt")
    liste.write_text(
        "".join(f"file '{p}'\n" for p in morceaux), encoding="utf-8"
    )
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
         "-safe", "0", "-i", str(liste), "-c", "copy", str(cible)],
        check=False, capture_output=True,
    )
    return cible


@dataclass
class HautParleur:
    """La voix de l'assistante, et ce qu'elle laisse dans la pièce.

    Elle retient ce qui a été prononcé — c'est ce qu'on vérifie — et le
    harnais le réinjecte ensuite dans l'audio de la réunion, parce que c'est
    exactement ce qu'un haut-parleur fait.
    """

    dites: list[str] = field(default_factory=list)
    parle_encore: bool = False
    coupures: int = 0

    def say(self, text: str) -> bool:
        if self.parle_encore:
            # Ce que fait la vraie voix depuis le correctif : elle refuse
            # plutôt que de se couper elle-même.
            self.coupures += 1
            return False
        self.dites.append(text)
        return True

    def go_quiet(self) -> None:
        self.parle_encore = False

    def is_speaking(self) -> bool:
        return self.parle_encore


@dataclass
class CerveauDeTest:
    """Répond de façon déterministe, et compte combien de fois on l'appelle."""

    reponses: list[str] = field(default_factory=list)
    demandes: list[str] = field(default_factory=list)
    defaut: str = "Je n'ai pas la réponse dans ce qui a été dit."

    def write_up(self, demande: str) -> str:
        self.demandes.append(demande)
        if self.reponses:
            return self.reponses.pop(0)
        return self.defaut


@dataclass
class Reunion:
    """Un enregistrement qui s'allonge, comme pendant une vraie réunion."""

    dossier: Path
    morceaux: list[Path] = field(default_factory=list)
    rang: int = 0
    dernier_tour: int = 0

    #: Une tranche plus courte que ceci n'est pas transcrite : le modèle y
    #: invente plus qu'il n'entend. Le harnais complète donc chaque prise par
    #: du silence, comme une vraie pièce entre deux phrases.
    TRANCHE_UTILE = 3.4

    def dire(self, voice: str, text: str, avant: float = 0.6) -> None:
        self.rang += 1
        if avant:
            self.morceaux.append(
                _silence(avant, self.dossier / f"blanc{self.rang}.wav")
            )
        piece = _synthetiser(voice, text, self.dossier / f"dit{self.rang}.wav")
        if piece is None:
            pytest.skip("synthèse impossible")
        self.morceaux.append(piece)
        self.respirer()

    def respirer(self) -> None:
        """Complète la prise pour que la tranche vaille d'être transcrite."""
        import soundfile

        since = sum(
            float(soundfile.info(str(p)).duration)
            for p in self.morceaux[self.dernier_tour:]
        )
        if since < self.TRANCHE_UTILE:
            self.rang += 1
            self.morceaux.append(_silence(
                self.TRANCHE_UTILE - since,
                self.dossier / f"souffle{self.rang}.wav",
            ))
        self.dernier_tour = len(self.morceaux)

    def audio(self) -> Path:
        return _coller(self.morceaux, self.dossier / "reunion.wav")

    def duree(self) -> float:
        import soundfile

        return float(soundfile.info(str(self.audio())).duration)


@pytest.fixture(scope="module")
def transcriber():
    if not _dispo():
        pytest.skip("« say » ou ffmpeg absent")
    outil = light_transcriber(Config())
    if outil is None:
        pytest.skip("aucun modèle de transcription installé")
    return outil


def _veilleur(reunion: Reunion, assistante: AssistantSettings,
              transcriber, dossier: Path) -> Watcher:
    return Watcher(
        watch_rules=WatchRules(keyword="greffier"),
        log=dossier / "propositions.jsonl",
        transcriber=transcriber,
        situer=lambda: Position(
            morceau=reunion.audio(), written=reunion.duree(), offset=0.0
        ),
        assistant_of=assistante,
        reread_participation=lambda: (True, False),
    )


def _assistante(cerveau: CerveauDeTest, voice: HautParleur) -> AssistantSettings:
    return AssistantSettings(
        name=NAME, cerveau=cerveau, voice=voice,
        manners=Manners(creux_minimal=0.0),
        context=lambda: "Réunion d'équipe sur la recette et la migration.",
    )


def _un_tour(veilleur: Watcher, assistante: AssistantSettings,
             dossier: Path) -> None:
    """Une tranche, puis on attend la réponse : elle est formulée à part."""
    ou = veilleur.situer()
    assert ou is not None
    veilleur.transcription_turn(ou, dossier)
    if assistante._job is not None:
        assistante._job.join(timeout=60)


@pytest.mark.integration
class TestUneConversationEntiere:
    """Ce qui se passe quand on enchaîne, et non sur une seule phrase."""

    def test_appelee_puis_sa_reponse_revient_et_elle_se_tait(
        self, transcriber, tmp_path
    ):
        """Le défaut vécu, reproduit puis prouvé impossible.

        Elle répond, sa réponse ressort par le haut-parleur, la capture la
        reprend, et elle doit rester muette. Avant, elle y lisait son nom et
        repartait — quinze fois en quinze secondes.
        """
        reunion = Reunion(tmp_path)
        reunion.dire(VOIX_DE_LA_SALLE,
                     f"{NAME}, est-ce que tu peux faire des recherches sur Internet ?")
        cerveau = CerveauDeTest(reponses=[
            "Je peux chercher, d'après la documentation de l'éditeur."
        ])
        voice = HautParleur()
        assistante = _assistante(cerveau, voice)
        veilleur = _veilleur(reunion, assistante, transcriber, tmp_path)

        _un_tour(veilleur, assistante, tmp_path)
        assert len(voice.dites) == 1, voice.dites
        assert NAME not in voice.dites[0], "son nom ne doit jamais sortir"

        # Le haut-parleur : ce qu'elle a dit entre dans la pièce.
        reunion.dire(VOIX_DE_L_ASSISTANTE, voice.dites[0])
        _un_tour(veilleur, assistante, tmp_path)
        assert len(voice.dites) == 1, (
            "elle a répondu à sa propre voix : " + str(voice.dites)
        )

    def test_la_salle_reste_entendue_apres_qu_elle_a_parle(
        self, transcriber, tmp_path
    ):
        """L'autre moitié : le garde ne doit pas la rendre sourde."""
        reunion = Reunion(tmp_path)
        reunion.dire(VOIX_DE_LA_SALLE, f"{NAME}, où en est la recette ?")
        cerveau = CerveauDeTest(reponses=[
            "La recette est décalée à jeudi.",
            "Il reste deux anomalies bloquantes.",
        ])
        voice = HautParleur()
        assistante = _assistante(cerveau, voice)
        veilleur = _veilleur(reunion, assistante, transcriber, tmp_path)

        _un_tour(veilleur, assistante, tmp_path)
        assert len(voice.dites) == 1, voice.dites

        reunion.dire(VOIX_DE_L_ASSISTANTE, voice.dites[0])
        reunion.dire(VOIX_DE_LA_SALLE, f"Et les anomalies {NAME} ?")
        _un_tour(veilleur, assistante, tmp_path)
        assert len(voice.dites) == 2, (
            "une nouvelle question de la salle doit obtenir une réponse : "
            + str(voice.dites)
        )

    def test_elle_ne_repond_pas_quand_on_ne_l_appelle_pas(
        self, transcriber, tmp_path
    ):
        """Un assistant qui répond à tout est aussi inutilisable qu'un sourd."""
        reunion = Reunion(tmp_path)
        reunion.dire(VOIX_DE_LA_SALLE,
                     "On passe au point suivant, la recette est calée pour jeudi.")
        cerveau = CerveauDeTest()
        voice = HautParleur()
        assistante = _assistante(cerveau, voice)
        veilleur = _veilleur(reunion, assistante, transcriber, tmp_path)

        _un_tour(veilleur, assistante, tmp_path)
        assert voice.dites == [], voice.dites
        assert cerveau.demandes == [], "le modèle n'a même pas à être appelé"

    def test_elle_ne_se_coupe_pas_quand_elle_parle_encore(
        self, transcriber, tmp_path
    ):
        """« Des fois elle se met à parler et ça se coupe. »

        Deux appels rapprochés : le second ne doit pas tuer la phrase en cours.
        """
        reunion = Reunion(tmp_path)
        reunion.dire(VOIX_DE_LA_SALLE, f"{NAME}, tu nous entends ?")
        cerveau = CerveauDeTest(reponses=["Oui, je vous entends très bien."])
        voice = HautParleur()
        assistante = _assistante(cerveau, voice)
        veilleur = _veilleur(reunion, assistante, transcriber, tmp_path)

        _un_tour(veilleur, assistante, tmp_path)
        assert len(voice.dites) == 1

        # Elle parle encore quand la question suivante arrive.
        voice.parle_encore = True
        reunion.dire(VOIX_DE_LA_SALLE,
                     f"{NAME}, et où en est la migration en Symfony sept ?")
        _un_tour(veilleur, assistante, tmp_path)
        assert len(voice.dites) == 1, "rien de neuf n'a été prononcé"
        assert voice.coupures >= 1, "le refus doit avoir eu lieu"
        assert voice.parle_encore, "la phrase en cours n'a pas été coupée"

    def test_la_boucle_du_transcripteur_ne_la_multiplie_pas(
        self, transcriber, tmp_path
    ):
        """La même question répétée n'obtient qu'une réponse.

        Sur le fil réel, whisper a rendu la question onze fois d'affilée ; sans
        garde, chaque répétition la rappelait.
        """
        reunion = Reunion(tmp_path)
        for _ in range(3):
            reunion.dire(VOIX_DE_LA_SALLE, f"{NAME}, tu peux nous rappeler la date ?",
                         avant=0.15)
        cerveau = CerveauDeTest(reponses=["C'est jeudi."])
        voice = HautParleur()
        assistante = _assistante(cerveau, voice)
        veilleur = _veilleur(reunion, assistante, transcriber, tmp_path)

        _un_tour(veilleur, assistante, tmp_path)
        assert len(voice.dites) <= 1, voice.dites

    def test_un_participant_qui_reprend_son_idee_est_entendu(
        self, transcriber, tmp_path
    ):
        """Le risque du garde par les mots : prendre un humain pour elle."""
        from greffier.domain.participation import own_words

        assistante = _assistante(CerveauDeTest(), HautParleur())
        assistante.its_own_words.append((0.0, own_words("La recette est décalée à jeudi.")))
        from greffier.domain.models import Span, Utterance

        humain = Utterance(
            span=Span(300.0, 306.0),
            text="je propose plutôt de caler la recette mardi avec Pascal",
        )
        assert not assistante._is_his_own(humain, 310.0)
