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

from greffier.adaptateurs import diagnostic_systeme as diagnostic
from greffier.adaptateurs.configuration import MODELES_CLAUDE, Config, sauver
from greffier.adaptateurs.redaction_ollama import modeles_disponibles
from greffier.domaine.langues import LANGUES, eprouvee, libelle, nom_de
from greffier.domaine.machine import Diagnostic
from greffier.emplacements import dossier_config, dossier_donnees

SYSTEME = platform.system()


@dataclass
class Reponses:
    """Ce que l'assistant a retenu, prêt à devenir un `.env`."""

    valeurs: dict[str, str] = field(default_factory=dict)
    #: Ce qui va dans `config.toml`, et surtout PAS dans le `.env`.
    #:
    #: L'ordre de priorité est environnement, puis `.env`, puis `config.toml`.
    #: Une valeur écrite ici dans le `.env` primerait donc pour toujours, et la
    #: liste déroulante de l'onglet Réglages — qui écrit le TOML — deviendrait
    #: inerte sans que rien ne le dise. Un test l'interdit.
    reglages: dict[str, dict[str, str]] = field(default_factory=dict)
    a_faire: list[str] = field(default_factory=list)
    installations: list[str] = field(default_factory=list)

    def poser(self, clef: str, valeur: str) -> None:
        self.valeurs[clef] = valeur

    def regler(self, section: str, champ: str, valeur: str) -> None:
        """Un réglage que la fenêtre doit pouvoir changer ensuite."""
        self.reglages.setdefault(section, {})[champ] = valeur

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

def etape_langue(dialogue: Dialogue, etat: Diagnostic, reponses: Reponses) -> None:
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
    titre = "\n— Dans quelle langue ? —"
    dialogue.afficher(titre)
    defaut = _langue_du_poste()
    choix = [(code, libelle(code)) for code, _ in LANGUES]
    rang = next((i for i, (code, _) in enumerate(choix) if code == defaut), 0)
    langue = dialogue.choisir("Langue des réunions", choix, rang)
    reponses.regler("transcription", "langue", langue)

    if langue and not eprouvee(langue):
        dialogue.afficher(
            f"\n{nom_de(langue)} se transcrit et son compte rendu s'écrit, mais la\n"
            "reconnaissance des prénoms n'y est pas éprouvée : elle reste éteinte,\n"
            "et les voix se nomment une fois dans l'onglet Voix. Les motifs\n"
            "français, laissés actifs, n'échoueraient pas — ils inventeraient des\n"
            "participants."
        )

    document = dialogue.choisir(
        "Langue du compte rendu",
        [("", "La même que la réunion")] + [(code, nom_de(code)) for code, _ in LANGUES if code],
        0,
    )
    reponses.regler("compte_rendu", "langue", document)


def _langue_du_poste() -> str:
    """Le code à deux lettres que le système annonce, s'il est au catalogue."""
    for variable in ("LC_ALL", "LC_MESSAGES", "LANG"):
        valeur = os.environ.get(variable, "")
        if valeur:
            code = valeur.split(".")[0].split("_")[0].lower()
            if code in dict(LANGUES):
                return code
    return "fr"


def etape_materiel(dialogue: Dialogue, etat: Diagnostic, reponses: Reponses) -> None:
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


def etape_redacteur(dialogue: Dialogue, etat: Diagnostic, reponses: Reponses) -> None:
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


def _modele_ollama(dialogue: Dialogue, reponses: Reponses) -> str:
    presents = modeles_disponibles()
    if presents:
        dialogue.afficher(f"Modèles déjà présents : {', '.join(presents[:5])}")
        return dialogue.demander("Lequel utiliser", presents[0])
    reponses.a_faire.append("ollama pull qwen3:8b")
    return "qwen3:8b"


def etape_livraison(dialogue: Dialogue, etat: Diagnostic, reponses: Reponses) -> None:
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


def etape_vocabulaire(dialogue: Dialogue, etat: Diagnostic, reponses: Reponses) -> None:
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


ETAPES = [etape_langue, etape_materiel, etape_redacteur, etape_livraison, etape_vocabulaire]


def executer(dialogue: Dialogue, etat: Diagnostic | None = None) -> Reponses:
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
    appliquer_les_reglages(reponses)
    return cible


def appliquer_les_reglages(reponses: Reponses) -> None:
    """Écrit dans `config.toml` ce que la fenêtre doit pouvoir rechanger.

    Séparé du `.env` à dessein : l'ordre de priorité est environnement, puis
    `.env`, puis `config.toml`. Une langue écrite dans le `.env` primerait pour
    toujours, et la liste déroulante de l'onglet Réglages n'y pourrait rien.
    """
    if not reponses.reglages:
        return
    config = Config.charger()
    for section, champs in reponses.reglages.items():
        objet = getattr(config, section, None)
        if objet is None:
            continue
        for champ, valeur in champs.items():
            if hasattr(objet, champ):
                setattr(objet, champ, valeur)
    sauver(config)
