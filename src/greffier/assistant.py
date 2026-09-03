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
import platform
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from greffier import diagnostic
from greffier.emplacements import dossier_config, dossier_donnees

SYSTEME = platform.system()


@dataclass
class Reponses:
    """Ce que l'assistant a retenu, prêt à devenir un `.env`."""

    valeurs: dict[str, str] = field(default_factory=dict)
    a_faire: list[str] = field(default_factory=list)
    installations: list[str] = field(default_factory=list)

    def poser(self, clef: str, valeur: str) -> None:
        self.valeurs[clef] = valeur

    def rendre_env(self) -> str:
        lignes = [
            "# Configuration de Greffier, écrite par « greffier configurer ».",
            "# Relance cette commande à tout moment pour la revoir.",
            "",
        ]
        for clef, valeur in self.valeurs.items():
            lignes.append(f"{clef}={valeur}")
        return "\n".join(lignes) + "\n"


@dataclass
class Dialogue:
    """Les entrées/sorties de l'assistant, remplaçables pour les tests."""

    demander: Callable[[str, str], str]
    confirmer: Callable[[str, bool], bool]
    afficher: Callable[[str], None]
    choisir: Callable[[str, list[tuple[str, str]], int], str]


# --------------------------------------------------------------- les étapes

def etape_materiel(dialogue: Dialogue, etat: diagnostic.Diagnostic, reponses: Reponses) -> None:
    """Constate la machine et annonce ce qui en découle."""
    machine = etat.machine
    dialogue.afficher(
        f"Machine : {machine.systeme} {machine.architecture}, "
        f"{machine.memoire_go:.0f} Go de mémoire, calcul « {machine.acceleration} »."
    )
    for constat in etat.constats:
        marque = "✓" if constat.present else ("✗" if constat.bloquant else "⚠")
        dialogue.afficher(f"  {marque} {constat.nom} — {constat.detail}")

    if etat.bloquants:
        dialogue.afficher("\nÀ régler avant de continuer :")
        for constat in etat.bloquants:
            dialogue.afficher(f"  • {constat.nom} : {constat.remede}")
            reponses.a_faire.append(constat.remede)

    # Le modèle est choisi d'après la mémoire réelle : proposer le plus gros
    # partout ferait ramer la machine pendant toute la réunion.
    reponses.poser("GREFFIER_TRANSCRIPTION__MODELE", machine.modele_conseille)
    reponses.poser(
        "GREFFIER_TRANSCRIPTION__MOTEUR",
        "whisper.cpp" if machine.systeme == "Darwin" else "faster-whisper",
    )


def etape_redacteur(dialogue: Dialogue, etat: diagnostic.Diagnostic, reponses: Reponses) -> None:
    """Claude Code : installé ? authentifié ? sinon rien ne pourra être rédigé."""
    dialogue.afficher("\n— Qui rédige le compte rendu —")

    if not diagnostic.claude_installe():
        dialogue.afficher(
            "Claude Code n'est pas installé. C'est lui qui rédige : distinguer une\n"
            "décision d'une hypothèse dépasse ce qu'un modèle de portable sait faire."
        )
        commande = diagnostic.COMMANDE_INSTALLER_CLAUDE.get(SYSTEME, "")
        if commande and dialogue.confirmer(f"L'installer maintenant ? ({commande})", True):
            dialogue.afficher(f"$ {commande}")
            subprocess.run(commande, shell=True, check=False)
            reponses.installations.append("Claude Code")
        else:
            reponses.a_faire.append(commande)

    if diagnostic.claude_installe() and not diagnostic.claude_authentifie():
        # Sans cette vérification, l'échec n'apparaîtrait qu'après une heure de
        # transcription — c'est-à-dire au pire moment possible.
        dialogue.afficher(
            "Claude Code est installé mais aucune session n'est ouverte.\n"
            "Lance « claude » une fois et connecte-toi à ton abonnement : sans cela,\n"
            "la transcription fonctionnera mais aucun compte rendu ne sera rédigé."
        )
        reponses.a_faire.append("claude   # puis se connecter à l'abonnement")

    choix = [
        ("claude", "Claude Code — meilleure synthèse, la transcription part vers l'API"),
        ("ollama", "Ollama — tout reste sur ce poste, synthèse plus grossière"),
        ("aucun", "Aucun — s'arrêter à la transcription attribuée"),
    ]
    defaut = 0 if diagnostic.claude_installe() else (1 if _ollama_utilisable() else 2)
    moteur = dialogue.choisir("Rédacteur du compte rendu", choix, defaut)
    reponses.poser("GREFFIER_COMPTE_RENDU__MOTEUR", moteur)

    if moteur == "ollama":
        modele = _modele_ollama(dialogue, reponses)
        reponses.poser("GREFFIER_COMPTE_RENDU__MODELE", modele)
    elif moteur == "claude":
        reponses.poser("GREFFIER_COMPTE_RENDU__MODELE", _modele_claude(dialogue))


#: Les modèles que Claude Code accepte comme alias, du plus puissant au plus
#: léger. Le libellé dit à quoi sert chacun ici, pas ce que vaut le modèle en
#: général : c'est le choix « pour rédiger un compte rendu » qu'on présente.
MODELES_CLAUDE: list[tuple[str, str]] = [
    ("opus", "Opus — recommandé : la synthèse est excellente et le quota tient"),
    ("fable", "Fable — le haut de la gamme, plus coûteux pour un compte rendu identique"),
    ("sonnet", "Sonnet — plus léger et plus rapide, synthèse un peu moins fine"),
    ("haiku", "Haiku — le plus économique, à réserver aux réunions courtes"),
]


def _modele_claude(dialogue: Dialogue) -> str:
    """Quel modèle Claude Code doit rédiger. Le second de la gamme par défaut.

    Volontairement pas le premier. Rédiger à partir d'une transcription déjà
    découpée et attribuée est un travail de synthèse : le haut de gamme rend le
    même document en entamant un quota bien plus vite — une réunion par jour
    suffit à le sentir. Le réglage reste offert, dans les deux sens.
    """
    dialogue.afficher(
        "\nLe modèle est demandé explicitement, plutôt que laissé au réglage\n"
        "personnel de Claude Code : le compte rendu ne doit pas changer de\n"
        "rédacteur sans que personne ne l'ait décidé."
    )
    return dialogue.choisir("Modèle qui rédige", MODELES_CLAUDE, 0)


def _ollama_utilisable() -> bool:
    import shutil

    return shutil.which("ollama") is not None


def _modeles_ollama() -> list[str]:
    try:
        sortie = subprocess.run(["ollama", "list"], capture_output=True, text=True,
                                check=False, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [ligne.split()[0] for ligne in sortie.splitlines()[1:] if ligne.strip()]


def _modele_ollama(dialogue: Dialogue, reponses: Reponses) -> str:
    presents = _modeles_ollama()
    if presents:
        dialogue.afficher(f"Modèles déjà présents : {', '.join(presents[:5])}")
        return dialogue.demander("Lequel utiliser", presents[0])
    reponses.a_faire.append("ollama pull qwen3:8b")
    return "qwen3:8b"


def etape_livraison(dialogue: Dialogue, etat: diagnostic.Diagnostic, reponses: Reponses) -> None:
    """Par courriel, ou dans un dossier ?"""
    dialogue.afficher("\n— Où arrive le compte rendu —")

    if not dialogue.confirmer("Le recevoir par courriel ?", True):
        defaut = str(dossier_donnees() / "comptes-rendus")
        dossier = dialogue.demander("Dans quel dossier l'enregistrer", defaut)
        reponses.poser("GREFFIER_CHEMINS__DONNEES", str(Path(dossier).expanduser().parent))
        reponses.poser("GREFFIER_COMPTE_RENDU__DESTINATAIRE", "")
        return

    # Une adresse vide vaut « pas d'envoi » : accepter les deux à la fois
    # produirait une configuration qui prétend envoyer et n'envoie rien.
    adresse = ""
    for _ in range(3):
        adresse = dialogue.demander("À quelle adresse", "").strip()
        if "@" in adresse:
            break
        dialogue.afficher("Il faut une adresse contenant « @ ».")
    if "@" not in adresse:
        dialogue.afficher("Sans adresse, le compte rendu restera simplement sur le disque.")
        reponses.poser("GREFFIER_COMPTE_RENDU__DESTINATAIRE", "")
        return
    reponses.poser("GREFFIER_COMPTE_RENDU__DESTINATAIRE", adresse)

    if diagnostic.outlook_present():
        # Outlook est déjà authentifié sur le poste : aucun mot de passe à
        # stocker, ce qui vaut mieux que n'importe quelle configuration SMTP.
        dialogue.afficher(
            "Outlook est installé : Greffier passera par lui. Aucun mot de passe\n"
            "à saisir, ton compte est déjà authentifié.\n"
            "macOS demandera une autorisation d'automatisation au premier envoi."
        )
        reponses.a_faire.append(
            "Autoriser Greffier dans Réglages ▸ Confidentialité ▸ Automatisation ▸ Outlook"
        )
        return

    dialogue.afficher("Pas d'Outlook détecté : il faut un serveur d'envoi (SMTP).")
    serveur = dialogue.demander("Serveur SMTP", "smtp.office365.com")
    reponses.poser("GREFFIER_COURRIEL__SERVEUR", serveur)
    reponses.poser("GREFFIER_COURRIEL__PORT", dialogue.demander("Port", "587"))
    utilisateur = dialogue.demander("Identifiant", adresse)
    reponses.poser("GREFFIER_COURRIEL__UTILISATEUR", utilisateur)
    # Le mot de passe ne va pas dans le fichier : il reste dans l'environnement,
    # où un gestionnaire de secrets peut le fournir.
    dialogue.afficher(
        "Le mot de passe n'est pas écrit dans la configuration. Fournis-le par\n"
        "l'environnement au moment de l'envoi :\n"
        "    export GREFFIER_SMTP_MOT_DE_PASSE='…'"
    )
    reponses.a_faire.append("export GREFFIER_SMTP_MOT_DE_PASSE='…'")


def etape_vocabulaire(dialogue: Dialogue, etat: diagnostic.Diagnostic, reponses: Reponses) -> None:
    """Le réglage qui change le plus la qualité de la transcription."""
    dialogue.afficher("\n— Vocabulaire de tes réunions —")
    dialogue.afficher(
        "Les noms de projets, d'outils et d'acronymes que le modèle ne connaît pas.\n"
        "C'est ce qui améliore le plus la transcription des termes rares."
    )
    saisie = dialogue.demander("Séparés par des virgules (vide pour passer)", "")
    mots = [m.strip() for m in saisie.split(",") if m.strip()]
    if mots:
        reponses.poser("GREFFIER_TRANSCRIPTION__VOCABULAIRE", json.dumps(mots, ensure_ascii=False))
        # Les mêmes mots ne doivent jamais être pris pour des prénoms : sans
        # cela, « merci Copernic » créerait un participant.
        reponses.poser("GREFFIER_LOCUTEURS__PAS_DES_PRENOMS",
                       json.dumps(mots, ensure_ascii=False))


ETAPES = [etape_materiel, etape_redacteur, etape_livraison, etape_vocabulaire]


def executer(dialogue: Dialogue, etat: diagnostic.Diagnostic | None = None) -> Reponses:
    """Déroule l'assistant et rend ce qu'il a retenu."""
    etat = etat or diagnostic.examiner(dossier_donnees())
    reponses = Reponses()
    for etape in ETAPES:
        etape(dialogue, etat, reponses)
    return reponses


def ecrire(reponses: Reponses, fichier: Path | None = None) -> Path:
    """Range la configuration là où toutes les commandes la liront."""
    cible = fichier or dossier_config() / ".env"
    cible.parent.mkdir(parents=True, exist_ok=True)
    if cible.exists():
        # On ne détruit pas une configuration existante sans laisser de trace.
        # « with_name » et non « with_suffix » : un fichier caché comme « .env »
        # n'a pas de suffixe, et la sauvegarde serait partie sous un autre nom.
        cible.replace(cible.with_name(cible.name + ".precedent"))
    cible.write_text(reponses.rendre_env(), encoding="utf-8")
    return cible
