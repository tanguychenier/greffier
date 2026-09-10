"""L'assistant de première configuration.

Au premier lancement, personne ne sait ce que l'outil attend. Cet assistant pose
les questions dans l'ordre, propose à chaque fois la réponse qui convient à
*cette* machine — pas une valeur générique — installe ce qui manque, et se
termine par un `.env` valide et une vérification.

Il est en terminal et non en fenêtre graphique, délibérément : une fenêtre
supposerait une bibliothèque d'interface différente sur chacun des trois
systèmes, et donc trois fois plus de code à maintenir pour la même conversation.
Sur macOS, l'icône de barre de menus l'ouvre dans un terminal.

Chaque étape est une fonction qui rend un fragment de configuration. C'est ce
qui permet de les tester une par une, en simulant les réponses.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from greffier.adapters import system_diagnostic as diagnostic
from greffier.adapters.configuration import MODELES_CLAUDE, Config, save_settings
from greffier.adapters.writer_ollama import available_models
from greffier.domain.languages import LANGUAGES, eprouvee, label_text, nom_de
from greffier.domain.recorder import Diagnostic
from greffier.locations import config_folder, data_folder

SYSTEM = platform.system()

@dataclass
class Answers:
    """Ce que l'assistant a retenu, prêt à devenir un `.env`."""

    values: dict[str, str] = field(default_factory=dict)
    reglages: dict[str, dict[str, str]] = field(default_factory=dict)
    to_do: list[str] = field(default_factory=list)
    installations: list[str] = field(default_factory=list)

    def place(self, key: str, value: str) -> None:
        self.values[key] = value

    def set_up(self, section: str, champ: str, value: str) -> None:
        """Un réglage que la fenêtre doit pouvoir changer ensuite."""
        self.reglages.setdefault(section, {})[champ] = value

    def render_env(self) -> str:
        lines = [
            "# Configuration de Greffier, écrite par « greffier configurer ».",
            "# Relance cette commande à tout moment pour la revoir.",
            "",
        ]
        for key, value in self.values.items():
            lines.append(f"{key}={value}")
        return "\n".join(lines) + "\n"

@dataclass
class Dialogue:
    """Les entrées/sorties de l'assistant, remplaçables pour les tests."""

    ask: Callable[[str, str], str]
    confirmer: Callable[[str, bool], bool]
    show: Callable[[str], None]
    choose: Callable[[str, list[tuple[str, str]], int], str]

def language_step(dialogue: Dialogue, state: Diagnostic, answers: Answers) -> None:
    """Dans quelle langue se tiennent les réunions, et s'écrivent les comptes rendus.

    Première question, parce qu'elle change ce que tout le reste sait faire : la
    transcription, la reconnaissance des prénoms, et la langue du document.

    La langue du poste est proposée par défaut plutôt que le français : un
    renseignement gratuit, que rien ne lisait, et sans lequel un poste allemand
    ressortait réglé sur le français.

    Les réponses vont dans les réglages, jamais dans le `.env` : celui-ci prime
    sur `config.toml`, et la liste déroulante des Réglages ne pourrait plus rien
    changer.
    """
    title = "\n— Dans quelle langue ? —"
    dialogue.show(title)
    defaut = _system_language()
    choix = [(code, label_text(code)) for code, _ in LANGUAGES]
    rank = next((i for i, (code, _) in enumerate(choix) if code == defaut), 0)
    language = dialogue.choose("Langue des réunions", choix, rank)
    answers.set_up("transcription", "langue", language)

    if language and not eprouvee(language):
        dialogue.show(
            f"\n{nom_de(language)} se transcrit et son compte rendu s'écrit, mais la\n"
            "reconnaissance des prénoms n'y est pas éprouvée : elle reste éteinte,\n"
            "et les voix se nomment une fois dans l'onglet Voix. Les motifs\n"
            "français, laissés actifs, n'échoueraient pas — ils inventeraient des\n"
            "participants."
        )

    document = dialogue.choose(
        "Langue du compte rendu",
        [("", "La même que la réunion")] + [(code, nom_de(code)) for code, _ in LANGUAGES if code],
        0,
    )
    answers.set_up("compte_rendu", "langue", document)

def _system_language() -> str:
    """Le code à deux lettres que le système annonce, s'il est au catalogue."""
    for variable in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(variable, "")
        if value:
            code = value.split(".")[0].split("_")[0].lower()
            if code in dict(LANGUAGES):
                return code
    return "fr"

def hardware_step(dialogue: Dialogue, state: Diagnostic, answers: Answers) -> None:
    """Constate la machine et annonce ce qui en découle."""
    recorder = state.recorder
    dialogue.show(
        f"Machine : {recorder.system} {recorder.architecture}, "
        f"{recorder.memory_gb:.0f} Go de mémoire, calcul « {recorder.speedup} »."
    )
    for constat in state.constats:
        marque = "✓" if constat.present else ("✗" if constat.bloquant else "⚠")
        dialogue.show(f"  {marque} {constat.name} — {constat.detail}")

    if state.blocking:
        dialogue.show("\nÀ régler avant de continuer :")
        for constat in state.blocking:
            dialogue.show(f"  • {constat.name} : {constat.remede}")
            answers.to_do.append(constat.remede)

    answers.place("GREFFIER_TRANSCRIPTION__MODEL", recorder.advised_model)
    answers.place(
        "GREFFIER_TRANSCRIPTION__ENGINE",
        "whisper.cpp" if recorder.system == "Darwin" else "faster-whisper",
    )

def writer_step(dialogue: Dialogue, state: Diagnostic, answers: Answers) -> None:
    """Claude Code : installé ? authentifié ? sinon rien ne pourra être rédigé."""
    dialogue.show("\n— Qui rédige le compte rendu —")

    if not diagnostic.claude_installed():
        dialogue.show(
            "Claude Code n'est pas installé. C'est lui qui rédige : distinguer une\n"
            "décision d'une hypothèse dépasse ce qu'un modèle de portable sait faire."
        )
        command = diagnostic.COMMANDE_INSTALLER_CLAUDE.get(SYSTEM, "")
        if command and dialogue.confirmer(f"L'installer maintenant ? ({command})", True):
            dialogue.show(f"$ {command}")
            subprocess.run(command, shell=True, check=False)
            answers.installations.append("Claude Code")
        else:
            answers.to_do.append(command)

    if diagnostic.claude_installed() and not diagnostic.claude_signed_in():
        dialogue.show(
            "Claude Code est installé mais aucune session n'est ouverte.\n"
            "Lance « claude » une fois et connecte-toi à ton abonnement : sans cela,\n"
            "la transcription fonctionnera mais aucun compte rendu ne sera rédigé."
        )
        answers.to_do.append("claude   # puis se connecter à l'abonnement")

    choix = [
        ("claude", "Claude Code — meilleure synthèse, la transcription part vers l'API"),
        ("ollama", "Ollama — tout reste sur ce poste, synthèse plus grossière"),
        ("aucun", "Aucun — s'arrêter à la transcription attribuée"),
    ]
    defaut = 0 if diagnostic.claude_installed() else (1 if _ollama_usable() else 2)
    engine = dialogue.choose("Rédacteur du compte rendu", choix, defaut)
    answers.place("GREFFIER_MINUTES__ENGINE", engine)

    if engine == "ollama":
        model = _ollama_model(dialogue, answers)
        answers.place("GREFFIER_MINUTES__MODEL", model)
    elif engine == "claude":
        answers.place("GREFFIER_MINUTES__MODEL", _claude_model(dialogue))

def _claude_model(dialogue: Dialogue) -> str:
    """Quel modèle Claude Code doit rédiger. Le second de la gamme par défaut.

    Volontairement pas le premier. Rédiger à partir d'une transcription déjà
    découpée et attribuée est un travail de synthèse : le haut de gamme rend le
    même document en entamant un quota bien plus vite — une réunion par jour
    suffit à le sentir. Le réglage reste offert, dans les deux sens.
    """
    dialogue.show(
        "\nLe modèle est demandé explicitement, plutôt que laissé au réglage\n"
        "personnel de Claude Code : le compte rendu ne doit pas changer de\n"
        "rédacteur sans que personne ne l'ait décidé."
    )
    return dialogue.choose("Modèle qui rédige", MODELES_CLAUDE, 0)

def _ollama_usable() -> bool:
    import shutil

    return shutil.which("ollama") is not None

def _ollama_model(dialogue: Dialogue, answers: Answers) -> str:
    present_line = available_models()
    if present_line:
        dialogue.show(f"Modèles déjà présents : {', '.join(present_line[:5])}")
        return dialogue.ask("Lequel utiliser", present_line[0])
    answers.to_do.append("ollama pull qwen3:8b")
    return "qwen3:8b"

def delivery_step(dialogue: Dialogue, state: Diagnostic, answers: Answers) -> None:
    """Par courriel, ou dans un dossier ?"""
    dialogue.show("\n— Où arrive le compte rendu —")

    if not dialogue.confirmer("Le recevoir par courriel ?", True):
        defaut = str(data_folder() / "comptes-rendus")
        folder = dialogue.ask("Dans quel dossier l'enregistrer", defaut)
        answers.place("GREFFIER_PATHS__DATA", str(Path(folder).expanduser().parent))
        answers.place("GREFFIER_MINUTES__RECIPIENT", "")
        return

    adresse = ""
    for _ in range(3):
        adresse = dialogue.ask("À quelle adresse", "").strip()
        if "@" in adresse:
            break
        dialogue.show("Il faut une adresse contenant « @ ».")
    if "@" not in adresse:
        dialogue.show("Sans adresse, le compte rendu restera simplement sur le disque.")
        answers.place("GREFFIER_MINUTES__RECIPIENT", "")
        return
    answers.place("GREFFIER_MINUTES__RECIPIENT", adresse)

    if diagnostic.outlook_present():
        dialogue.show(
            "Outlook est installé : Greffier passera par lui. Aucun mot de passe\n"
            "à saisir, ton compte est déjà authentifié.\n"
            "macOS demandera une autorisation d'automatisation au premier envoi."
        )
        answers.to_do.append(
            "Autoriser Greffier dans Réglages ▸ Confidentialité ▸ Automatisation ▸ Outlook"
        )
        return

    dialogue.show("Pas d'Outlook détecté : il faut un serveur d'envoi (SMTP).")
    server = dialogue.ask("Serveur SMTP", "smtp.office365.com")
    answers.place("GREFFIER_EMAIL__SERVER", server)
    answers.place("GREFFIER_EMAIL__PORT", dialogue.ask("Port", "587"))
    user = dialogue.ask("Identifiant", adresse)
    answers.place("GREFFIER_EMAIL__USER", user)
    dialogue.show(
        "Le mot de passe n'est pas écrit dans la configuration. Fournis-le par\n"
        "l'environnement au moment de l'envoi :\n"
        "    export GREFFIER_SMTP_MOT_DE_PASSE='…'"
    )
    answers.to_do.append("export GREFFIER_SMTP_MOT_DE_PASSE='…'")

def vocabulary_step(dialogue: Dialogue, state: Diagnostic, answers: Answers) -> None:
    """Le réglage qui change le plus la qualité de la transcription."""
    dialogue.show("\n— Vocabulaire de tes réunions —")
    dialogue.show(
        "Les noms de projets, d'outils et d'acronymes que le modèle ne connaît pas.\n"
        "C'est ce qui améliore le plus la transcription des termes rares."
    )
    entry = dialogue.ask("Séparés par des virgules (vide pour passer)", "")
    words = [m.strip() for m in entry.split(",") if m.strip()]
    if words:
        answers.place("GREFFIER_TRANSCRIPTION__VOCABULARY", json.dumps(words, ensure_ascii=False))
        answers.place("GREFFIER_SPEAKERS__NOT_FIRST_NAMES",
                       json.dumps(words, ensure_ascii=False))

ETAPES = [language_step, hardware_step, writer_step, delivery_step, vocabulary_step]

def run_chain(dialogue: Dialogue, state: Diagnostic | None = None) -> Answers:
    """Déroule l'assistant et rend ce qu'il a retenu."""
    state = state or diagnostic.examine(data_folder())
    answers = Answers()
    for etape in ETAPES:
        etape(dialogue, state, answers)
    return answers

def write(answers: Answers, file: Path | None = None) -> Path:
    """Range la configuration là où toutes les commandes la liront."""
    target = file or config_folder() / ".env"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.replace(target.with_name(target.name + ".precedent"))
    target.write_text(answers.render_env(), encoding="utf-8")
    apply_settings(answers)
    return target

def apply_settings(answers: Answers) -> None:
    """Écrit dans `config.toml` ce que la fenêtre doit pouvoir rechanger.

    Séparé du `.env` à dessein : l'ordre de priorité est environnement, puis
    `.env`, puis `config.toml`. Une langue écrite dans le `.env` primerait pour
    toujours, et la liste déroulante de l'onglet Réglages n'y pourrait rien.
    """
    if not answers.reglages:
        return
    config = Config.load()
    for section, champs in answers.reglages.items():
        objet = getattr(config, section, None)
        if objet is None:
            continue
        for champ, value in champs.items():
            if hasattr(objet, champ):
                setattr(objet, champ, value)
    save_settings(config)
