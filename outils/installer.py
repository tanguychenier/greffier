#!/usr/bin/env python3
"""Installe Greffier sur macOS, Linux ou Windows.

    python3 outils/installer.py            # vérifie, propose, installe
    python3 outils/installer.py --oui      # sans poser de question
    python3 outils/installer.py --verifier # ne fait que constater

Écrit uniquement avec la bibliothèque standard : il doit tourner *avant* que
quoi que ce soit ne soit installé, donc il ne peut dépendre de rien. Compatible
Python 3.9, la version encore livrée par défaut sur beaucoup de postes.

Le script détecte ce qui manque et l'installe, plutôt que d'afficher une liste
de commandes à recopier. Chaque installation est annoncée et, sauf « --oui »,
demande confirmation : personne n'aime qu'un script touche à sa machine sans
prévenir.
"""

import argparse
import contextlib
import importlib.util
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

DEPOT = Path(__file__).resolve().parent.parent
SYSTEME = platform.system()  # Darwin | Linux | Windows

# --------------------------------------------------------------------- sortie

# La console Windows par défaut est en cp1252 : elle ne sait écrire ni « ✓ » ni
# « é ». Sans ce basculement, l'installeur meurt sur un UnicodeEncodeError à sa
# toute première ligne — avant même d'avoir dit à quoi il sert.
for _flux in (sys.stdout, sys.stderr):
    if hasattr(_flux, "reconfigure"):
        with contextlib.suppress(OSError, ValueError):
            _flux.reconfigure(encoding="utf-8", errors="replace")


def _ecrivable(symbole):
    """Le symbole passe-t-il dans l'encodage de la console ?"""
    try:
        symbole.encode(sys.stdout.encoding or "utf-8")
        return True
    except (UnicodeEncodeError, LookupError):
        return False


# Repli en pur ASCII pour les consoles qui n'acceptent rien d'autre.
SYMBOLES = (
    {"ok": "✓", "alerte": "⚠", "erreur": "✗"}
    if _ecrivable("✓⚠✗")
    else {"ok": "[ok]", "alerte": "[!]", "erreur": "[X]"}
)

COULEURS = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _teinte(code, texte):
    return f"\033[{code}m{texte}\033[0m" if COULEURS else texte


def titre(texte):
    print(_teinte("1;34", f"\n{texte}"))


def ok(texte):
    print(_teinte("0;32", f"  {SYMBOLES['ok']} {texte}"))


def alerte(texte):
    print(_teinte("0;33", f"  {SYMBOLES['alerte']} {texte}"))


def erreur(texte):
    print(_teinte("0;31", f"  {SYMBOLES['erreur']} {texte}"), file=sys.stderr)


def info(texte):
    print(f"    {texte}")


class Abandon(Exception):
    """Interrompt l'installation avec un message actionnable."""


# ----------------------------------------------------------------- décisions

class Contexte:
    def __init__(self, args):
        self.oui = args.oui
        self.verifier_seulement = args.verifier
        self.modeles = Path(
            args.modeles or os.environ.get("GREFFIER_MODELES") or dossier_donnees() / "modeles"
        )
        self.config = Path(
            args.config or os.environ.get("GREFFIER_CONFIG") or dossier_config()
        )
        # Une chaîne d'origine peut déjà détenir les modèles : autant les
        # reprendre que retélécharger 1,6 Go. Vidable pour tester à blanc.
        reprise = os.environ.get("GREFFIER_MODELES_EXISTANTS", str(Path.home() / "reunions/models"))
        self.reprise = Path(reprise) if reprise else None
        self.a_faire = []

    def demander(self, question):
        if self.verifier_seulement:
            return False
        if self.oui:
            return True
        if not sys.stdin.isatty():
            # Sans terminal (CI, script), ne rien installer en douce.
            alerte(f"{question} — passé (pas de terminal ; utilise --oui)")
            return False
        return input(f"    {question} [o/N] ").strip().lower() in {"o", "oui", "y", "yes"}


# Les emplacements sont ceux de l'application, lus dans son module sans
# dépendance — l'installeur tourne avant que le paquet ne soit installé, d'où le
# chargement par chemin. Une seule définition : l'installeur et Greffier ne
# peuvent pas se contredire sur l'endroit où sont les modèles.
def _charger_emplacements():
    specification = importlib.util.spec_from_file_location(
        "greffier_emplacements", DEPOT / "src/greffier/emplacements.py"
    )
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


EMPLACEMENTS = _charger_emplacements()


def dossier_donnees():
    return EMPLACEMENTS.dossier_donnees(SYSTEME)


def dossier_config():
    return EMPLACEMENTS.dossier_config(SYSTEME)


def etape_emplacements():
    """Sort de ~/.config et ~/.local ce qu'une version précédente y a laissé.

    macOS seulement : les dossiers cachés du compte y sont surveillés par les
    gardes du poste, qui redemandaient une autorisation à chaque accès, jusqu'à
    refuser une écriture en pleine réunion. Tout vit désormais dans Application
    Support. Ne fait rien ailleurs, ni quand il n'y a rien à bouger.
    """
    deplaces = EMPLACEMENTS.demenager(SYSTEME)
    if not deplaces:
        return
    titre("0. Emplacements")
    for source, cible in deplaces:
        ok(f"{source} → {cible}")


def lancer(commande, **kwargs):
    """Exécute une commande en montrant ce qui est lancé."""
    info(f"$ {' '.join(commande)}")
    return subprocess.run(commande, check=False, **kwargs)


# ------------------------------------------------- gestionnaires de paquets

def gestionnaire():
    """Le gestionnaire de paquets du poste, ou None si aucun n'est reconnu."""
    if SYSTEME == "Darwin":
        return ("brew", ["brew", "install"]) if shutil.which("brew") else None
    if SYSTEME == "Windows":
        if shutil.which("winget"):
            return ("winget", ["winget", "install", "--accept-package-agreements",
                               "--accept-source-agreements", "-e", "--id"])
        if shutil.which("scoop"):
            return ("scoop", ["scoop", "install"])
        return None
    # En conteneur ou en intégration continue on tourne en root, où « sudo »
    # n'est souvent même pas installé.
    prefixe = [] if getattr(os, "geteuid", lambda: 1)() == 0 else ["sudo"]
    for outil, commande in (
        ("apt-get", ["apt-get", "install", "-y"]),
        ("dnf", ["dnf", "install", "-y"]),
        ("pacman", ["pacman", "-S", "--noconfirm"]),
        ("zypper", ["zypper", "install", "-y"]),
        ("apk", ["apk", "add"]),
    ):
        if shutil.which(outil):
            return (outil, prefixe + commande)
    return None


# Nom du paquet selon le gestionnaire : ffmpeg s'appelle pareil partout, mais
# ce n'est pas le cas de tout.
PAQUETS = {
    "ffmpeg": {
        "brew": "ffmpeg", "apt-get": "ffmpeg", "dnf": "ffmpeg", "pacman": "ffmpeg",
        "zypper": "ffmpeg", "apk": "ffmpeg",
        "winget": "Gyan.FFmpeg", "scoop": "ffmpeg",
    },
    "whisper-cpp": {
        # Empaqueté seulement par Homebrew. Ailleurs, la transcription passe
        # par faster-whisper, installé dans l'environnement Python.
        "brew": "whisper-cpp",
    },
    "ollama": {
        "brew": "ollama", "winget": "Ollama.Ollama", "scoop": "ollama",
    },
    "uv": {
        "brew": "uv", "winget": "astral-sh.uv", "scoop": "uv",
    },
}


def installer_paquet(ctx, nom, raison):
    gest = gestionnaire()
    if gest is None:
        alerte(f"{nom} absent, et aucun gestionnaire de paquets reconnu sur ce poste")
        info(f"Installe-le à la main : {raison}")
        return False
    outil, commande = gest
    paquet = PAQUETS.get(nom, {}).get(outil)
    if paquet is None:
        alerte(f"{nom} n'est pas empaqueté par {outil}")
        return False
    if not ctx.demander(f"Installer {nom} avec {outil} ? ({raison})"):
        ctx.a_faire.append(f"{' '.join(commande)} {paquet}")
        return False
    if outil == "apt-get":
        # Sans rafraîchissement, apt échoue sur une image ou un poste dont la
        # liste de paquets n'a jamais été mise à jour.
        lancer(commande[:-2] + ["update", "-qq"], stdout=subprocess.DEVNULL)
    return lancer(commande + [paquet]).returncode == 0


# ---------------------------------------------------------- 1. outils système

def etape_outils(ctx):
    titre("1. Outils système")

    if shutil.which("ffmpeg"):
        ok("ffmpeg")
    elif not installer_paquet(ctx, "ffmpeg", "enregistrement et conversion audio"):
        raise Abandon("ffmpeg est indispensable : sans lui, rien ne peut être enregistré.")

    # whisper.cpp accélère la transcription sur le processeur graphique, mais
    # n'existe en paquet que sur macOS. Son absence n'est pas bloquante :
    # faster-whisper prend le relais, en Python, sur les trois systèmes.
    if shutil.which("whisper-cli") or shutil.which("whisper"):
        ok("whisper.cpp (transcription accélérée)")
        return "whisper.cpp"
    if SYSTEME == "Darwin" and installer_paquet(
        ctx, "whisper-cpp", "transcription accélérée Metal"
    ):
        ok("whisper.cpp")
        return "whisper.cpp"
    alerte("whisper.cpp absent — la transcription passera par faster-whisper (Python)")
    return "faster-whisper"


# ---------------------------------------------------------- 2. capture audio

def etape_audio(ctx):
    """Vérifie de quoi capter le son des autres participants.

    C'est le seul point vraiment différent d'un système à l'autre : entendre sa
    propre voix est trivial, réenregistrer ce que les haut-parleurs jouent ne
    l'est pas.
    """
    titre("2. Capture du son des autres participants")

    if SYSTEME == "Darwin":
        sortie = subprocess.run(
            ["system_profiler", "SPAudioDataType"], capture_output=True, text=True, check=False
        ).stdout
        if "BlackHole" in sortie:
            ok("BlackHole (pilote audio virtuel)")
        else:
            alerte("BlackHole absent : sans lui, seule ta voix serait enregistrée")
            if ctx.demander("Installer BlackHole ? (mot de passe admin demandé)"):
                lancer(["brew", "install", "--cask", "blackhole-2ch"])
                info("Puis : sudo killall coreaudiod   (recharge le son, coupure de 1-2 s)")
            else:
                ctx.a_faire.append("brew install --cask blackhole-2ch")
                ctx.a_faire.append("sudo killall coreaudiod")
        return

    if SYSTEME == "Linux":
        # PipeWire et PulseAudio exposent déjà un « monitor » de la sortie :
        # rien à installer, contrairement à macOS.
        if shutil.which("pactl"):
            ok("PulseAudio/PipeWire — le moniteur de sortie sert de capture")
            info("Aucun pilote supplémentaire n'est nécessaire sur Linux.")
        else:
            alerte("pactl absent : le son des autres participants ne pourra pas être capté")
            info("Sur un poste de bureau, installe « pipewire-pulse » ou « pulseaudio-utils ».")
            info("En conteneur ou sur un serveur, c'est normal : seule l'analyse de")
            info("fichiers déjà enregistrés est possible.")
        return

    ok("WASAPI (capture de boucle intégrée à Windows)")
    info("ffmpeg capte la sortie via « -f dshow » ou la boucle WASAPI.")


# ---------------------------------------------------------------- 3. modèles

MODELES = [
    {
        "nom": "ggml-large-v3-turbo.bin",
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin",
        "taille_min": 1_000_000_000,
        "role": "transcription",
        "requis_si": "whisper.cpp",
    },
    {
        "nom": "ggml-silero-v5.1.2.bin",
        "url": "https://huggingface.co/ggml-org/whisper-vad/resolve/main/ggml-silero-v5.1.2.bin",
        "taille_min": 500_000,
        "role": "détection de la parole",
        "requis_si": "whisper.cpp",
    },
    {
        # Le modèle du direct. Il transcrit une tranche de dix secondes en une
        # fraction de seconde là où le grand en prend plusieurs : pendant la
        # réunion, il faut rendre une tranche avant que la suivante soit
        # enregistrée, sinon l'affichage prend un retard qu'il ne rattrape plus.
        # Facultatif — sans lui, le direct se replie sur le grand modèle.
        "nom": "ggml-small.bin",
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin",
        "taille_min": 400_000_000,
        "role": "transcription en direct",
        "requis_si": "whisper.cpp",
    },
    {
        "nom": "diarisation/nemo_en_titanet_large.onnx",
        "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
               "speaker-recongition-models/nemo_en_titanet_large.onnx",
        "taille_min": 20_000_000,
        "role": "empreintes vocales",
    },
]

SEGMENTATION = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
)


def relier_ou_copier(source, cible, dossier=False):
    """Relie la source à la cible, ou la copie si le système s'y refuse.

    Windows n'autorise les liens symboliques qu'en mode développeur ou en
    session élevée. Copier coûte de l'espace, mais un modèle de 98 Mo dupliqué
    vaut mieux qu'une installation qui échoue.
    """
    if cible.exists() or cible.is_symlink():
        if cible.is_dir() and not cible.is_symlink():
            shutil.rmtree(cible)
        else:
            cible.unlink()
    try:
        cible.symlink_to(source, target_is_directory=dossier)
        return "relié à"
    except (OSError, NotImplementedError):
        if dossier:
            shutil.copytree(source, cible)
        else:
            shutil.copy2(source, cible)
        return "copié depuis"


def telecharger(url, cible):
    """Télécharge en affichant la progression, sans laisser de fichier tronqué."""
    partiel = cible.with_suffix(cible.suffix + ".partiel")
    with urllib.request.urlopen(url) as flux, open(partiel, "wb") as sortie:
        total = int(flux.headers.get("Content-Length") or 0)
        recu = 0
        while True:
            morceau = flux.read(1 << 20)
            if not morceau:
                break
            sortie.write(morceau)
            recu += len(morceau)
            if total and sys.stdout.isatty():
                print(f"\r    {cible.name} {recu * 100 // total:3d} %", end="", flush=True)
    if sys.stdout.isatty():
        print("\r", end="")
    # Renommage seulement une fois complet : une coupure de réseau ne doit pas
    # laisser un modèle tronqué qui échouerait bien plus tard, à l'exécution.
    partiel.replace(cible)


def etape_modeles(ctx, moteur):
    titre("3. Modèles locaux")
    (ctx.modeles / "diarisation").mkdir(parents=True, exist_ok=True)

    for modele in MODELES:
        if modele.get("requis_si") and modele["requis_si"] != moteur:
            continue
        cible = ctx.modeles / modele["nom"]
        if cible.exists() and cible.stat().st_size >= modele["taille_min"]:
            ok(f"{cible.name} ({modele['role']})")
            continue
        ancien = ctx.reprise / modele["nom"] if ctx.reprise else None
        if ancien and ancien.exists() and ancien.stat().st_size >= modele["taille_min"]:
            comment = relier_ou_copier(ancien, cible)
            ok(f"{cible.name} {comment} {ancien}")
            continue
        if ctx.verifier_seulement:
            alerte(f"{cible.name} manquant ({modele['role']})")
            continue
        info(f"téléchargement de {cible.name} ({modele['role']})…")
        telecharger(modele["url"], cible)
        ok(cible.name)

    dossier = ctx.modeles / "diarisation/sherpa-onnx-pyannote-segmentation-3-0"
    if (dossier / "model.onnx").exists():
        ok("modèle de segmentation")
        return
    ancien = (
        ctx.reprise / "diarisation/sherpa-onnx-pyannote-segmentation-3-0"
        if ctx.reprise else None
    )
    if ancien and (ancien / "model.onnx").exists():
        comment = relier_ou_copier(ancien, dossier, dossier=True)
        ok(f"modèle de segmentation {comment} {ancien}")
        return
    if ctx.verifier_seulement:
        alerte("modèle de segmentation manquant")
        return
    archive = ctx.modeles / "diarisation/segmentation.tar.bz2"
    info("téléchargement du modèle de segmentation…")
    telecharger(SEGMENTATION, archive)
    with tarfile.open(archive, "r:bz2") as paquet:
        if sys.version_info >= (3, 12):
            paquet.extractall(ctx.modeles / "diarisation", filter="data")
        else:
            paquet.extractall(ctx.modeles / "diarisation")  # noqa: S202
    archive.unlink()
    ok("modèle de segmentation")


# ------------------------------------------------------- 4. rédaction du CR

# Modèles locaux acceptés, par ordre de préférence : on réutilise ce qui est
# déjà sur le poste avant de proposer un téléchargement de plusieurs gigaoctets.
# Le critère est la qualité de synthèse en français à taille raisonnable.
FAMILLES_OLLAMA = ("qwen3", "mistral-small", "gemma3", "llama3.1", "qwen2.5")
MODELE_OLLAMA = os.environ.get("GREFFIER_MODELE_OLLAMA", "qwen3:8b")


def modele_utilisable(disponibles):
    """Premier modèle présent appartenant à une famille reconnue.

    La comparaison porte sur le début du nom : « qwen3.8 », « qwen3:8b » et
    « qwen3:14b » sont la même famille, et l'un ou l'autre fera l'affaire.
    """
    for famille in FAMILLES_OLLAMA:
        for present in disponibles:
            if present.split(":")[0].replace(".", "").startswith(famille.replace(".", "")):
                return present
    return None


def modeles_ollama():
    try:
        sortie = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, check=False, timeout=20
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [ligne.split()[0] for ligne in sortie.splitlines()[1:] if ligne.strip()]


def etape_redaction(ctx):
    """Choisit qui rédige le compte rendu.

    Claude Code par défaut : distinguer une décision d'une hypothèse et
    rattacher une position à une personne reste hors de portée des modèles qui
    tournent sur un portable. C'est le seul maillon de la chaîne qui sort du
    poste, et c'est un choix assumé.

    Ollama reste branchable pour qui veut du 100 % local — l'architecture le
    permet sans rien changer d'autre — au prix d'une synthèse plus grossière.
    """
    titre("4. Rédaction du compte rendu")

    if shutil.which("claude"):
        ok("Claude Code — rédacteur par défaut")
        info("La transcription sort du poste vers l'API Anthropic ; le reste de la")
        info("chaîne demeure local. Pour ne rien laisser sortir : moteur « ollama ».")
        return {"moteur": "claude", "modele": ""}

    alerte("Claude Code absent : c'est le rédacteur par défaut")
    info("Installation : https://claude.com/claude-code")

    if shutil.which("ollama"):
        disponibles = modeles_ollama()
        trouve = modele_utilisable(disponibles)
        if trouve:
            ok(f"Ollama disponible en remplacement : {trouve} (tout reste local)")
            return {"moteur": "ollama", "modele": trouve}
        alerte(
            f"Ollama installé mais aucun modèle de synthèse reconnu "
            f"({len(disponibles)} présents)"
        )
        if ctx.demander(
            f"Télécharger {MODELE_OLLAMA} pour rédiger en local ? (~5 Go)"
        ) and lancer(["ollama", "pull", MODELE_OLLAMA]).returncode == 0:
            return {"moteur": "ollama", "modele": MODELE_OLLAMA}
        ctx.a_faire.append(f"ollama pull {MODELE_OLLAMA}")

    alerte("aucun rédacteur : transcription et voix fonctionneront, pas le compte rendu")
    return {"moteur": "aucun", "modele": ""}


MODELE_WHISPER = os.environ.get("GREFFIER_MODELE_WHISPER", "large-v3")


def etape_modele_whisper(ctx, moteur, python):
    """Récupère le modèle de faster-whisper, là où whisper.cpp n'existe pas.

    Sans cette étape, tout paraît installé et le téléchargement de 1,5 Go se
    déclenche au lancement de la première réunion — c'est-à-dire au pire moment.
    """
    if moteur != "faster-whisper" or ctx.verifier_seulement or not python.exists():
        return
    titre("5 bis. Modèle de transcription (faster-whisper)")
    info(f"préparation de « {MODELE_WHISPER} »…")
    resultat = subprocess.run(
        [str(python), "-c",
         "from faster_whisper import WhisperModel;"
         f"WhisperModel('{MODELE_WHISPER}', device='cpu', compute_type='int8')"],
        capture_output=True, text=True, cwd=DEPOT, check=False,
    )
    if resultat.returncode == 0:
        ok(f"modèle {MODELE_WHISPER} prêt")
    else:
        alerte(f"modèle {MODELE_WHISPER} non préparé : il sera récupéré au premier usage")
        derniere = resultat.stderr.strip().splitlines()
        if derniere:
            info(derniere[-1][:160])


# --------------------------------------------------------- 5. environnement

def etape_environnement(ctx, moteur):
    titre("5. Environnement Python")
    venv = DEPOT / ".venv"
    python = venv / ("Scripts/python.exe" if SYSTEME == "Windows" else "bin/python")

    extras = "dev,service" + (",transcription" if moteur == "faster-whisper" else "")

    if ctx.verifier_seulement:
        ok("environnement présent") if python.exists() else alerte("environnement absent")
        return python

    if SYSTEME == "Darwin" and not shutil.which("uv"):
        # L'application embarque un interpréteur relogeable : seul uv en
        # installe un (python-build-standalone), et seul uv sait le remplir.
        # Sans lui, la ligne de commande fonctionne mais pas le paquet .app.
        installer_paquet(ctx, "uv", "interpréteur relogeable, embarqué dans l'application")

    if shutil.which("uv"):
        if not venv.exists():
            lancer(["uv", "venv", "--python", "3.13"], cwd=DEPOT)
        lancer(["uv", "pip", "install", "-q", "-e", f".[{extras}]"], cwd=DEPOT)
    else:
        alerte("uv absent — repli sur venv + pip, plus lent")
        if not venv.exists():
            lancer([sys.executable, "-m", "venv", str(venv)])
        lancer([str(python), "-m", "pip", "install", "-q", "-e", f".[{extras}]"], cwd=DEPOT)
    ok(f"dépendances installées ({extras})")
    return python


# -------------------------------------------------------- 6. configuration

GABARIT = '''# Configuration de Greffier. Tout est facultatif : ce qui manque reprend la
# valeur par défaut.

[chemins]
modeles = {modeles!r}
donnees = {donnees!r}

[audio]
# Périphériques de capture. Sur macOS, à créer une fois (voir le README) ;
# sur Linux, le moniteur de sortie PipeWire/PulseAudio suffit.
entree = {entree!r}
sortie = {sortie!r}
duree_maximale = 14400        # 4 h : garde-fou contre une réunion oubliée

[transcription]
moteur = {moteur!r}           # whisper.cpp (macOS, accéléré) ou faster-whisper
langue = "fr"
# Noms propres du contexte : c'est ce qui améliore le plus la transcription
# des termes rares.
vocabulaire = ["Jira", "GitLab", "sprint", "merge request", "recette", "backlog"]

[locuteurs]
# Mots à ne jamais prendre pour des prénoms : projets, outils, produits.
pas_des_prenoms = ["Copernic", "Kanban", "Trello"]

[compte_rendu]
# claude : meilleure synthèse, la transcription sort vers l'API Anthropic.
# ollama : tout reste sur le poste, synthèse plus grossière.
moteur = {redacteur!r}
modele = {modele!r}
# Adresse à qui envoyer le compte rendu. Vide = pas d'envoi.
destinataire = ""
'''


def etape_configuration(ctx, moteur, redaction):
    titre("6. Configuration")
    ctx.config.mkdir(parents=True, exist_ok=True)
    fichier = ctx.config / "config.toml"
    if fichier.exists():
        ok(f"configuration existante conservée : {fichier}")
        return fichier
    if ctx.verifier_seulement:
        alerte(f"configuration absente : {fichier}")
        return fichier
    fichier.write_text(
        GABARIT.format(
            modeles=str(ctx.modeles),
            donnees=str(dossier_donnees()),
            entree="Reunion Entree" if SYSTEME == "Darwin" else "default",
            sortie="Reunion Sortie" if SYSTEME == "Darwin" else "default.monitor",
            moteur=moteur,
            redacteur=redaction["moteur"],
            modele=redaction["modele"],
        ),
        encoding="utf-8",
    )
    ok(f"configuration créée : {fichier}")
    alerte("renseigne « destinataire » pour recevoir les comptes rendus par mail")
    return fichier


# ------------------------------------------------------ 7. intégration bureau

def dossier_autodemarrage():
    """Où déposer ce qui doit se lancer à l'ouverture de session."""
    if SYSTEME == "Darwin":
        return Path.home() / "Library/LaunchAgents"
    if SYSTEME == "Windows":
        return (Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
                / "Microsoft/Windows/Start Menu/Programs/Startup")
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart"


AGENT_MACOS = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" \
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>              <string>com.reunions.greffier</string>
  <key>ProgramArguments</key>
  <array><string>/usr/bin/open</string><string>{cible}</string></array>
  <key>RunAtLoad</key>          <true/>
</dict>
</plist>
"""

RACCOURCI_LINUX = """[Desktop Entry]
Type=Application
Name=Greffier
Comment=Enregistre la réunion et en rédige le compte rendu
Exec={cible}
Terminal=false
Categories=Office;AudioVideo;
"""

# Un .cmd plutôt qu'un .lnk : un raccourci Windows est un format binaire qui
# demande PowerShell et COM pour être écrit, là où un script démarre aussi bien
# et reste lisible par qui veut savoir ce qui se lance à sa session.
DEMARRAGE_WINDOWS = """@echo off
rem Lance Greffier à l'ouverture de session. Supprime ce fichier pour l'annuler.
start "" /min {cible}
"""


def integrer_au_bureau(ctx, cible, ecrire=True):
    """Pose l'icône dans la barre et le lancement à l'ouverture de session.

    Renvoie le fichier écrit, ou None si le système n'est pas reconnu. La
    séparation « ecrire » permet de vérifier ce qui serait produit sur les trois
    systèmes depuis n'importe quel poste.
    """
    dossier = dossier_autodemarrage()
    if SYSTEME == "Darwin":
        fichier, gabarit = dossier / "com.reunions.greffier.plist", AGENT_MACOS
    elif SYSTEME == "Windows":
        fichier, gabarit = dossier / "Greffier.cmd", DEMARRAGE_WINDOWS
    elif SYSTEME == "Linux":
        fichier, gabarit = dossier / "greffier.desktop", RACCOURCI_LINUX
    else:
        return None
    if ecrire:
        dossier.mkdir(parents=True, exist_ok=True)
        fichier.write_text(gabarit.format(cible=cible), encoding="utf-8")
    return fichier


def etape_bureau(ctx):
    """Installe l'interface : icône dans la barre, lancée à l'ouverture de session."""
    titre("7. Intégration au bureau")

    if SYSTEME == "Darwin":
        if not (DEPOT / "macos/construire.sh").exists():
            alerte("script de construction introuvable dans ce dépôt")
            return
        # /Applications d'abord : ~/Applications n'est indexé ni par Spotlight ni
        # par le Launchpad, donc une application qui y est posée n'y apparaît
        # jamais. Constaté en usage : « je n'ai aucune icône pour la lancer ».
        candidates = [Path("/Applications/Greffier.app"),
                      Path.home() / "Applications/Greffier.app"]
        application = next((c for c in candidates if c.exists()), candidates[0])
        if ctx.verifier_seulement:
            ok(f"application présente ({application})") if application.exists() \
                else alerte("application absente")
            return
        # Autonome et signée de façon stable (voir macos/construire.sh) : les
        # autorisations micro et Outlook, données une fois, ne sont plus
        # redemandées à la reconstruction suivante.
        if lancer([str(DEPOT / "macos/construire.sh")]).returncode != 0:
            alerte("construction de l'application échouée")
            return
        pose = next((c for c in candidates if c.exists()), None)
        ok(f"application installée ({pose or application})")
        info("Double-clic, ou cherche « Greffier » dans le Launchpad.")
        return

    # Ailleurs, la fenêtre se lance par la ligne de commande. Rien à compiler :
    # Tkinter vient avec Python, et l'interface est la même sur les trois
    # systèmes.
    ok("interface disponible : « greffier fenetre »")
    if SYSTEME == "Linux":
        info("Si Tk manque : « apt install python3-tk ».")


# --------------------------------------------------- 7 bis. skill de dépannage

def dossier_skills():
    """Où Claude Code cherche les skills de l'utilisateur."""
    return Path.home() / ".claude/skills"


def etape_skill(ctx):
    """Pose le skill qui apprend à Claude Code à réparer une installation.

    Greffier dépend d'une instance Claude Code authentifiée — c'est elle qui
    rédige le compte rendu — donc c'est vers elle qu'on se tourne quand quelque
    chose casse. Sans ce document, elle tâtonne : elle ne peut pas devenir que
    les données vivent dans Application Support et non dans un dossier caché,
    que la signature du paquet doit rester stable, ni que le modèle par défaut
    est le second de la gamme à dessein.

    Une copie, pas un lien : le dépôt peut être déplacé ou supprimé, un skill
    qui pointerait dans le vide serait pire que pas de skill.
    """
    titre("7 bis. Dépannage assisté")
    source = DEPOT / "skills/greffier/SKILL.md"
    if not source.exists():
        alerte("skill introuvable dans ce dépôt")
        return
    if not shutil.which("claude"):
        info("Claude Code absent : le skill sera posé quand il le sera.")
        return
    cible = dossier_skills() / "greffier/SKILL.md"
    if ctx.verifier_seulement:
        ok(f"skill présent ({cible})") if cible.exists() else alerte("skill absent")
        return
    if cible.exists() and cible.read_text(encoding="utf-8") == source.read_text(encoding="utf-8"):
        ok(f"skill à jour ({cible})")
        return
    action = "mis à jour" if cible.exists() else "installé"
    if not ctx.demander(f"Installer le skill de dépannage pour Claude Code ? ({cible})"):
        ctx.a_faire.append(f"mkdir -p {cible.parent} && cp {source} {cible}")
        return
    cible.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, cible)
    ok(f"skill {action} ({cible})")
    info("Dis « répare Greffier » à Claude Code : il saura où regarder.")


# ---------------------------------------------------------- 8. vérification

def etape_verification(ctx, python):
    titre("8. Vérification")
    if not python.exists():
        alerte("environnement absent : vérification impossible")
        return False

    resultat = subprocess.run(
        [str(python), "-m", "pytest", str(DEPOT / "tests")],
        capture_output=True, text=True, cwd=DEPOT, check=False,
    )
    resume = [
        ligne for ligne in resultat.stdout.splitlines()
        if "passed" in ligne or "failed" in ligne
    ]
    if resultat.returncode != 0:
        erreur(resume[-1] if resume else "les tests ont échoué")
        return False
    ok(resume[-1] if resume else "tests passés")

    empreintes = ctx.modeles / "diarisation/nemo_en_titanet_large.onnx"
    if not empreintes.exists():
        alerte("modèle d'empreintes absent : identification des voix indisponible")
        return False
    controle = subprocess.run(
        [str(python), "-c",
         "import sys, pathlib;"
         "sys.path.insert(0, 'src');"
         "from greffier.adaptateurs.empreintes_titanet import ExtracteurTitaNet;"
         f"ExtracteurTitaNet(pathlib.Path(r'{empreintes}'))"],
        capture_output=True, text=True, cwd=DEPOT, check=False,
    )
    if controle.returncode != 0:
        erreur("le modèle d'empreintes ne se charge pas")
        info(controle.stderr.strip().splitlines()[-1] if controle.stderr.strip() else "")
        return False
    ok("modèle d'empreintes chargé")
    return True


# ---------------------------------------------------------------------- main

def main():
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--oui", action="store_true",
                           help="installe sans poser de question")
    analyseur.add_argument("--verifier", action="store_true",
                           help="constate l'état sans rien installer")
    analyseur.add_argument("--modeles", help="dossier où ranger les modèles")
    analyseur.add_argument("--config", help="dossier de configuration")
    args = analyseur.parse_args()

    print(_teinte("1;37", f"Greffier — installation sur {SYSTEME} {platform.machine()}"))
    if sys.version_info < (3, 9):
        erreur(f"Python 3.9 minimum, trouvé {platform.python_version()}")
        return 1
    # Avant de calculer le moindre chemin : ce qui traîne dans les dossiers
    # cachés doit être rangé, sinon l'installeur le retrouverait là-bas et
    # continuerait d'y écrire.
    if not args.verifier:
        etape_emplacements()
    ctx = Contexte(args)

    try:
        moteur = etape_outils(ctx)
        etape_audio(ctx)
        etape_modeles(ctx, moteur)
        redaction = etape_redaction(ctx)
        python = etape_environnement(ctx, moteur)
        etape_modele_whisper(ctx, moteur, python)
        etape_configuration(ctx, moteur, redaction)
        etape_bureau(ctx)
        etape_skill(ctx)
        saine = etape_verification(ctx, python)
    except Abandon as raison:
        erreur(str(raison))
        return 1
    except KeyboardInterrupt:
        erreur("interrompu")
        return 130

    if ctx.a_faire:
        titre("Reste à faire")
        for commande in ctx.a_faire:
            info(commande)

    titre("Installé." if saine else "Installé, avec des réserves.")
    info(f"modèles       {ctx.modeles}")

    # L'installation pose les outils ; l'assistant décide de comment on s'en
    # sert. Enchaîner les deux évite qu'un poste reste installé mais muet.
    if not ctx.verifier_seulement and python.exists():
        if ctx.oui or ctx.demander("Configurer maintenant (rédacteur, courriel, vocabulaire) ?"):
            greffier = python.parent / ("greffier.exe" if SYSTEME == "Windows" else "greffier")
            if greffier.exists():
                subprocess.run([str(greffier), "configurer"], cwd=DEPOT, check=False)
            else:
                info("Lance « greffier configurer » quand tu voudras.")
        else:
            info("À faire plus tard : greffier configurer")
    return 0 if saine else 1


if __name__ == "__main__":
    sys.exit(main())
