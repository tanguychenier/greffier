"""Racine de composition : c'est ici, et seulement ici, qu'on choisit les outils.

Le reste du code ne connaît que des ports. Ce module est le seul à savoir que la
transcription passe par whisper.cpp sur macOS et par faster-whisper ailleurs, ou
que la rédaction interroge Ollama. Changer d'outil ne touche que ce fichier.
"""

from __future__ import annotations

import platform
import sys
from pathlib import Path

from greffier.adaptateurs.audio_ffmpeg import EnregistreurFfmpeg
from greffier.adaptateurs.banque_fichiers import BanqueFichiers
from greffier.adaptateurs.canaux_fichier import LecteurCanauxFichier
from greffier.adaptateurs.courriel import (
    ExpediteurFichier,
    ExpediteurOutlook,
    ExpediteurSmtp,
)
from greffier.adaptateurs.depot_fichiers import DepotFichiers
from greffier.adaptateurs.diarisation_sherpa import DiariseurSherpa
from greffier.adaptateurs.empreintes_titanet import ExtracteurTitaNet
from greffier.adaptateurs.notifications import NotificateurSysteme
from greffier.adaptateurs.peripheriques_coreaudio import ListeurCoreAudio
from greffier.adaptateurs.redaction_ollama import RedacteurOllama
from greffier.application.enregistrer import Enregistrement
from greffier.application.nommer import Nommage
from greffier.application.suivre import Suivi, fichiers, personnes_connues
from greffier.application.traiter import Traitement
from greffier.config import Config
from greffier.domaine.direct import Fil
from greffier.ports import sortants


def _transcripteur(config: Config) -> sortants.Transcripteur:
    modeles = config.chemins.modeles
    if config.transcription.moteur == "whisper.cpp":
        from greffier.adaptateurs.transcription_whisper_cpp import TranscripteurWhisperCpp

        return TranscripteurWhisperCpp(
            modele=modeles / "ggml-large-v3-turbo.bin",
            vad=modeles / "ggml-silero-v5.1.2.bin",
        )
    # Import tardif : faster-whisper n'est installé que là où il sert, et
    # l'importer inconditionnellement casserait un poste macOS sans cet extra.
    from greffier.adaptateurs.transcription_faster_whisper import TranscripteurFasterWhisper

    return TranscripteurFasterWhisper(taille=config.transcription.modele)


def _modele_du_direct(config: Config) -> str:
    """Le modèle que cette machine fait tourner dans le budget d'une tranche.

    Le même critère que la transcription définitive : mémoire et accélération
    disponibles. Mesuré sur un Mac Apple Silicon, tranche de dix secondes réelle
    — 0,72 s avec `small`, 1,44 s avec `large-v3-turbo`, pour un budget de dix
    secondes. Le grand modèle tient avec sept fois la marge, et rend une phrase
    là où le petit rendait trois fragments faux.
    """
    from greffier import diagnostic

    return diagnostic.machine(config.chemins.donnees).modele_conseille


def transcripteur_leger(config: Config) -> sortants.Transcripteur | None:
    """Le modèle de la transcription en direct : rapide plutôt que juste.

    Il faut rendre une tranche en moins de temps qu'il n'en faut pour en
    enregistrer une autre, sans quoi l'affichage prend du retard qu'il ne
    rattrape jamais. Ce n'est pas une raison de prendre le plus petit modèle :
    sur une machine qui en a les moyens, le grand tient dans le budget et le
    petit rendait le fil illisible — mesuré, pas supposé.

    Rend `None` quand aucun modèle n'est là : le direct affichera alors ce que
    l'audio dit des canaux, et le dira, plutôt que de rester vide sans raison.
    """
    taille = config.direct.modele or _modele_du_direct(config)
    if config.transcription.moteur == "whisper.cpp":
        modeles = config.chemins.modeles
        candidats = [modeles / f"ggml-{taille}.bin", modeles / "ggml-large-v3-turbo.bin"]
        modele = next((m for m in candidats if m.exists()), None)
        if modele is None:
            return None
        from greffier.adaptateurs.transcription_whisper_cpp import TranscripteurWhisperCpp

        # Pas de détection d'activité vocale : elle coûte un modèle de plus à
        # charger à chaque tranche, pour une tranche qui en dure dix secondes.
        return TranscripteurWhisperCpp(modele=modele, vad=None)
    from greffier.adaptateurs.transcription_faster_whisper import TranscripteurFasterWhisper

    return TranscripteurFasterWhisper(taille=taille)


def suivi(config: Config, identifiant: str) -> Suivi:
    """Le fil affiché pendant la réunion, et ce qui le corrige.

    L'extracteur d'empreintes est facultatif ici, alors qu'il est requis pour le
    traitement : sans lui, le direct montre ce qui se dit et distingue « toi »
    des autres, ce qui est déjà l'essentiel. Refuser de rien afficher parce
    qu'un modèle manque serait le pire des deux mondes.
    """
    journal, demandes = fichiers(config.chemins.direct, identifiant)
    banque = BanqueFichiers(config.chemins.banque_de_voix)
    extracteur: sortants.ExtracteurEmpreintes | None = None
    try:
        extracteur = ExtracteurTitaNet(
            config.chemins.modeles / "diarisation" / "nemo_en_titanet_large.onnx"
        )
    except FileNotFoundError:
        extracteur = None
    return Suivi(
        fil=Fil(connues=personnes_connues(banque),
                personnes=config.locuteurs.personnes),
        journal=journal,
        demandes=demandes,
        canaux=LecteurCanauxFichier(),
        extracteur=extracteur,
        banque=banque,
    )


def redacteur(config: Config) -> sortants.Redacteur | None:
    """Le rédacteur seul, pour régénérer un compte rendu sans tout réassembler."""
    moteur = config.compte_rendu.moteur
    if moteur == "ollama":
        return RedacteurOllama(config.compte_rendu.modele_effectif)
    if moteur == "claude":
        from greffier.adaptateurs.redaction_claude import RedacteurClaude

        return RedacteurClaude(config.compte_rendu.modele_effectif)
    return None


def depot(config: Config) -> DepotFichiers:
    """Les fichiers maîtres, source de vérité d'une réunion traitée."""
    return DepotFichiers(config.chemins.donnees / "reunions")


def nommage(config: Config) -> Nommage:
    """Le cas d'usage « donner un nom à une voix », après la réunion."""
    diarisation = config.chemins.modeles / "diarisation"
    return Nommage(
        depot=depot(config),
        banque=BanqueFichiers(config.chemins.banque_de_voix),
        extracteur=ExtracteurTitaNet(diarisation / "nemo_en_titanet_large.onnx"),
    )


def _expediteur(config: Config, exiger_destinataire: bool = True) -> sortants.Expediteur | None:
    """Comment part le compte rendu.

    Outlook là où il existe : le compte est déjà authentifié, donc aucun mot de
    passe à stocker. Sinon SMTP, s'il est renseigné. Sinon rien ne part, et le
    compte rendu reste simplement sur le disque.

    « greffier envoyer » demande le destinataire à l'écran : il passe
    `exiger_destinataire=False` pour obtenir un expéditeur même quand la
    configuration n'en désigne aucun.
    """
    if exiger_destinataire and not config.compte_rendu.destinataire:
        return None
    if config.courriel.serveur:
        return ExpediteurSmtp(
            serveur=config.courriel.serveur,
            port=config.courriel.port,
            utilisateur=config.courriel.utilisateur,
            expediteur=config.courriel.expediteur,
        )
    if platform.system() == "Darwin":
        return ExpediteurOutlook()
    return ExpediteurFichier(config.chemins.comptes_rendus)


def _enregistreur(config: Config) -> EnregistreurFfmpeg:
    """La capture audio. Une seule construction, trois appelants."""
    return EnregistreurFfmpeg(config.audio.entree, config.audio.duree_maximale)


def listeur(config: Config) -> ListeurCoreAudio:
    """Lecture du matériel audio, pour la veille et le diagnostic."""
    source = Path(__file__).resolve().parent.parent.parent / "macos/creer-peripheriques.swift"
    # Depuis le paquet macOS, l'exécutable est Contents/MacOS/Greffier : le
    # listeur compilé par construire.sh vit alors à côté, dans Resources, et
    # c'est lui qu'on exécute — jamais un binaire recompilé dans ~/.local,
    # qu'un garde du poste conteste à chaque relevé.
    prete = Path(sys.executable).resolve().parent.parent / "Resources/lister-peripheriques"
    return ListeurCoreAudio(
        source, config.chemins.donnees / "cache", prete if prete.exists() else None
    )


def enregistrement(config: Config) -> Enregistrement:
    """La machine à états de l'enregistrement, partagée entre deux commandes."""
    return Enregistrement(
        enregistreur=_enregistreur(config),
        dossier_audio=config.chemins.enregistrements,
        fichier_etat=config.chemins.donnees / "etat.json",
    )


def assembler(config: Config) -> Traitement:
    modeles = config.chemins.modeles
    diarisation = modeles / "diarisation"
    return Traitement(
        enregistreur=_enregistreur(config),
        transcripteur=_transcripteur(config),
        diariseur=DiariseurSherpa(
            segmentation=diarisation / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx",
            empreintes=diarisation / "nemo_en_titanet_large.onnx",
        ),
        extracteur=ExtracteurTitaNet(diarisation / "nemo_en_titanet_large.onnx"),
        banque=BanqueFichiers(config.chemins.banque_de_voix),
        redacteur=redacteur(config),
        expediteur=_expediteur(config),
        journal=enregistrement(config),
        notificateur=NotificateurSysteme(),
        # Câblés ici, donc pour tous les appelants : la fenêtre garde la
        # réunion comme la ligne de commande, ce qui n'était pas le cas.
        depot=depot(config),
        dossier_transcriptions=config.chemins.transcriptions,
        dossier_comptes_rendus=config.chemins.comptes_rendus,
        langue=config.transcription.langue,
        amorce=config.transcription.amorce,
        personnes=config.locuteurs.personnes,
        pas_des_prenoms=frozenset(m.lower() for m in config.locuteurs.pas_des_prenoms),
        destinataire=config.compte_rendu.destinataire,
    )
