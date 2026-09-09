"""Ligne de commande de Greffier.

    greffier traiter <audio>     transcrit, identifie les voix, rédige
    greffier rediger             reprend la rédaction d'une réunion transcrite
    greffier renommer <sujet>    donne un sujet lisible à une réunion
    greffier oublier             efface une réunion et tout ce qui va avec
    greffier contexte            ce que l'outil sait des sigles et des personnes
    greffier ranger              applique la rétention aux enregistrements
    greffier sauvegarder         copie les données, sans l'audio
    greffier recuperer           reconstruit une réunion depuis le fil du direct
    greffier deposer <fichiers>  classe des audios, vidéos et documents
    greffier niveau              dit si le micro suffit à transcrire
    greffier sources             les sources extérieures inscrites, et leur état
    greffier carte               construit la carte d'un sujet depuis une réunion
    greffier verifier            dit ce qui est prêt et ce qui manque

Volontairement mince : elle lit la configuration, demande à la composition
d'assembler la chaîne, et affiche. Toute la logique est ailleurs.
"""

from __future__ import annotations

import contextlib
import platform
import shutil
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import typer

from greffier.adaptateurs.banque_fichiers import BanqueFichiers
from greffier.adaptateurs.configuration import Config
from greffier.adaptateurs.notifications import NotificateurSysteme
from greffier.application import ranger as ranger_module
from greffier.application.nommer import VoixANommer, extraire_audio, voix_a_nommer
from greffier.application.restituer import regenerer_compte_rendu
from greffier.application.traiter import ChaineInterrompue
from greffier.composition import (
    assembler,
    cartographe,
    contexte,
    depot,
    enregistrement,
    listeur,
    nommage,
    participant,
    redacteur,
    suivi,
    transcripteur_leger,
)
from greffier.domaine.compte_rendu import titre
from greffier.emplacements import dossier_config

application = typer.Typer(
    add_completion=False, help="Enregistre, transcrit et résume tes réunions."
)


def _nommeur(
    le_suivi: Any, config: Config, identifiant: str
) -> Callable[[str, str], bool]:
    """Donne à l'assistant le pouvoir de poser un nom sur une voix du fil.

    Sans lui, demander « qui vient de parler » n'est qu'une politesse : la
    réponse s'affiche et se perd. Avec lui, elle nomme la voix, entre en banque
    et sert le compte rendu — c'est ce qui justifie d'avoir interrompu.
    """
    from greffier.application.suivre import demander, fichiers

    _, demandes = fichiers(config.chemins.direct, identifiant)

    def nommer(voix: str, prenom: str) -> bool:
        tour = next(
            (t for t in reversed(le_suivi.fil.tours) if t.voix == voix), None)
        if tour is None:
            return False
        try:
            le_suivi.fil.corriger(tour.numero, prenom, toute_la_voix=True)
            demander(demandes, tour.numero, prenom, toute_la_voix=True)
        except (KeyError, ValueError, OSError):
            return False
        return True

    return nommer


def _reunion_visee(config: Config, demandee: str | None) -> str:
    """La réunion nommée, ou la dernière traitée.

    Sortir ici plutôt que de laisser un « None » se propager : toutes les
    commandes qui travaillent sur une réunion ont besoin du même message quand
    il n'y en a aucune.
    """
    if demandee:
        return demandee
    connues = depot(config).lister()
    if not connues:
        typer.secho("Aucune réunion traitée. « greffier traiter <audio> » pour commencer.",
                    fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    return connues[0]


def _heures_de(config: Config, audio: Path) -> tuple[datetime | None, datetime | None]:
    """Les heures d'horloge de cette réunion, si l'état les a retenues.

    Vérifie que l'état parle bien de **cet** enregistrement : traiter un vieux
    fichier audio ne doit pas lui coller les heures de la dernière réunion. Sans
    correspondance, le rédacteur retombe sur l'horodatage de l'identifiant.
    """
    try:
        etat = enregistrement(config).lire()
    except (OSError, ValueError):
        return (None, None)
    if etat.identifiant != audio.stem:
        return (None, None)
    return (etat.debut, etat.terminee_le)


def _emplacements(config: Config) -> ranger_module.Emplacements:
    """Où vivent les morceaux d'une réunion, d'après la configuration."""
    return ranger_module.Emplacements(
        reunions=config.chemins.donnees / "reunions",
        enregistrements=config.chemins.enregistrements,
        transcriptions=config.chemins.transcriptions,
        comptes_rendus=config.chemins.comptes_rendus,
        direct=config.chemins.direct,
        propositions=config.chemins.propositions,
        questions=config.chemins.questions,
        conversations=config.chemins.conversations,
        pieces=config.chemins.pieces,
    )


def _refuser_pendant_une_reunion(config: Config, quand_meme: bool) -> None:
    """Refuse de traiter tant qu'une réunion s'enregistre.

    Le fichier d'état est **unique** : c'est par lui que la fenêtre suit la
    réunion en cours. Un traitement lancé en parallèle y publiait ses propres
    phases, jusqu'à « terminé », et la fenêtre en concluait que la réunion était
    finie — le fil du direct s'arrêtait, les processus d'écoute se retiraient,
    alors que la capture continuait. Constaté deux fois en réunion réelle, dont
    le 2026-09-09 où une réunion entière a été perdue sans laisser un octet.

    **Le danger est désarmé depuis** : le journal de la chaîne n'écrit plus que
    si l'état porte la réunion qu'il traite (`Enregistrement.pour`). Ce refus
    reste, parce qu'il y a une seconde raison de ne pas traiter pendant une
    réunion — transcrire mobilise le processeur que la capture et le direct se
    partagent déjà — mais « --quand-meme » ne détruit plus rien.
    """
    if quand_meme:
        return
    from greffier.composition import enregistrement
    from greffier.domaine.modeles import Phase

    try:
        etat = enregistrement(config).lire()
    except (OSError, ValueError):
        return
    if etat.phase not in (Phase.ENREGISTREMENT, Phase.PAUSE):
        return
    typer.secho(
        f"Une réunion est en cours ({etat.identifiant}) : traiter maintenant "
        "arrêterait son affichage en direct.",
        fg=typer.colors.YELLOW,
    )
    typer.echo("Termine-la d'abord, ou relance avec « --quand-meme » : le "
               "traitement n'arrêtera plus la capture, mais il lui prendra du "
               "processeur.")
    raise typer.Exit(1)


@application.command()
def traiter(
    audio: Path = typer.Argument(..., exists=True, readable=True, help="Enregistrement à traiter"),
    sans_envoi: bool = typer.Option(
        False, "--sans-envoi", help="Ne pas envoyer, même si un destinataire est configuré"
    ),
    sans_cr: bool = typer.Option(False, "--sans-compte-rendu", help="S'arrêter après les voix"),
    evenements: list[str] = typer.Option(
        None, "--evenement", hidden=True,
        help="Constat de la veille sur le matériel, répétable",
    ),
    config_fichier: Path = typer.Option(None, "--config", help="Fichier de configuration"),
    quand_meme: bool = typer.Option(
        False, "--quand-meme",
        help="Traiter même si une réunion est en cours d'enregistrement",
    ),
) -> None:
    """Transcrit un enregistrement, identifie qui parle, rédige le compte rendu."""
    config = Config.charger(config_fichier)
    _refuser_pendant_une_reunion(config, quand_meme)
    chaine = assembler(config)
    # Le journal ne publie que si l'état porte **cette** réunion : sans cela,
    # un traitement lancé pendant qu'une autre s'enregistre y publiait
    # « terminé » et arrêtait la capture.
    chaine.journal = enregistrement(config).pour(audio.stem)
    if sans_cr:
        chaine.redacteur = None

    # Le journal câblé par la composition écrit le fichier d'état, que lit
    # l'icône de la barre de menus. Le remplacer par un simple afficheur la
    # rendait aveugle : pendant les quinze minutes d'un retraitement, elle
    # montrait encore la phase précédente. On affiche **et** on publie.
    publieur = chaine.journal

    def avancement(phase: str, message: str = "") -> None:
        typer.secho(f"  {phase:<14} {message}", fg=typer.colors.BLUE)
        if publieur is not None:
            # L'affichage ne doit pas dépendre de l'écriture de l'état.
            with contextlib.suppress(OSError, ValueError):
                publieur.publier(phase, message)

    chaine.journal = type("Journal", (), {"publier": staticmethod(avancement)})()

    try:
        # Un destinataire renseigné vaut demande d'envoi : c'est la raison
        # d'être de l'outil, et le redemander à chaque réunion n'apporte rien.
        commencee_le, terminee_le = _heures_de(config, audio)
        resultat = chaine.executer(
            audio,
            envoyer=not sans_envoi and bool(config.compte_rendu.destinataire),
            evenements_materiel=evenements,
            commencee_le=commencee_le,
            terminee_le=terminee_le,
        )
    except ChaineInterrompue as arret:
        typer.secho(f"✗ {arret.raison}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from arret

    for avertissement in resultat.avertissements:
        typer.secho(f"⚠ {avertissement}", fg=typer.colors.YELLOW)

    significatives = resultat.voix_significatives()
    # Une voix nommée reste affichée même brève : la masquer sous le seuil des
    # fragments cachait le résultat qu'on cherchait. Constaté sur un jeu d'essai
    # à trois locuteurs : deux noms trouvés, un seul montré. Une proposition
    # (nom deviné, pas encore confirmé) suit la même règle : sans elle, un
    # prénom prononcé dans une réponse brève ne s'affichait jamais.
    for voix, duree in resultat.temps_de_parole().items():
        deja_montree = voix in resultat.noms or voix in resultat.propositions
        if deja_montree and voix not in significatives:
            significatives[voix] = duree
    fragments = len(resultat.temps_de_parole()) - len(significatives)
    resume = f"\n{resultat.mots} mots · {len(significatives)} voix"
    if fragments:
        resume += f" ({fragments} fragments trop courts, ignorés)"
    typer.echo(resume)

    total = sum(significatives.values()) or 1
    for voix, duree in significatives.items():
        part = f"{duree / 60:4.1f} min ({duree / total * 100:4.1f} %)"
        if voix in resultat.noms:
            typer.secho(f"  {part}  {resultat.noms[voix]}", fg=typer.colors.GREEN)
        elif voix in resultat.propositions:
            # Proposé, jamais affirmé : c'est à l'utilisateur de trancher.
            typer.secho(f"  {part}  ≈ {resultat.propositions[voix]} (à confirmer)",
                        fg=typer.colors.YELLOW)
        else:
            typer.echo(f"  {part}  Personne {voix}")

    # L'écriture est faite par la chaîne, pour tous ses appelants : ici on ne
    # fait que dire où. La faire une seconde fois écrasait le même fichier avec
    # le même contenu, et laissait croire que la fenêtre écrivait aussi.
    if resultat.transcription_ecrite:
        typer.echo(f"\nTranscription : {resultat.transcription_ecrite}")
    if resultat.fichier_maitre:
        typer.echo(f"Fichier maître: {resultat.fichier_maitre}")
    manque_des_noms = resultat.propositions or any(
        v not in resultat.noms for v in significatives
    )
    if manque_des_noms and not _demander_les_noms(config, audio.stem):
        typer.echo(f"\nPour nommer les voix : greffier voix {audio.stem}")

    if resultat.compte_rendu_ecrit:
        typer.echo(f"Compte rendu  : {resultat.compte_rendu_ecrit}")
    if resultat.envoye:
        typer.secho("Envoyé par mail.", fg=typer.colors.GREEN)


def _demander_les_noms(config: Config, identifiant: str) -> bool:
    """Réclame les noms manquants, tout de suite. Faux si on ne peut pas demander.

    Le rappel « greffier voix … » ne suffit pas : une voix qu'on ne nomme pas
    aujourd'hui n'entre pas en banque, donc n'est pas reconnue à la réunion
    suivante, et le compte rendu continue de parler de « Personne 3 ». Autant
    demander pendant que la réunion est fraîche.

    Rien n'est demandé quand l'entrée n'est pas un terminal : le traitement peut
    tourner détaché, lancé par l'icône de la barre de menus, et une question
    posée à personne bloquerait la chaîne indéfiniment.
    """
    if not sys.stdin.isatty():
        return False
    try:
        detail = depot(config).lire(identifiant)
    except (OSError, ValueError, KeyError):
        return False
    restantes = [v for v in voix_a_nommer(detail) if not v.nom]
    if not restantes:
        return False

    typer.echo()
    combien = "une voix" if len(restantes) == 1 else f"{len(restantes)} voix"
    typer.secho(f"{combien} sans nom. Les nommer maintenant les fait entrer en "
                "banque, et elles seront reconnues seules ensuite.",
                fg=typer.colors.YELLOW)
    if not typer.confirm("Les nommer ?", default=True):
        return False

    magasin = nommage(config)
    nommees = 0
    for candidate in restantes:
        part = f"{candidate.duree / 60:.1f} min ({candidate.part * 100:.0f} %)"
        typer.echo()
        typer.secho(f"  voix {candidate.voix} — {part}", bold=True)
        if candidate.proposition:
            # Proposé, jamais affirmé : c'est à l'utilisateur de trancher.
            typer.secho(f"  entendu dans la réunion : {candidate.proposition}",
                        fg=typer.colors.CYAN)
        if candidate.extrait:
            typer.echo(f"  extrait : {candidate.extrait.debut:.0f}s → "
                       f"{candidate.extrait.fin:.0f}s")
            if typer.confirm("  écouter ?", default=False):
                _ecouter(config, identifiant, candidate)
        propose = candidate.proposition or ""
        nom = typer.prompt("  nom (Entrée pour passer)", default=propose,
                           show_default=bool(propose)).strip()
        if not nom:
            continue
        try:
            magasin.nommer(identifiant, candidate.voix, nom)
        except (RuntimeError, ValueError, OSError) as souci:
            typer.secho(f"  ✗ {souci}", fg=typer.colors.RED, err=True)
            continue
        typer.secho(f"  ✓ {nom}, empreinte en banque", fg=typer.colors.GREEN)
        nommees += 1

    if nommees:
        typer.echo()
        typer.secho(f"{nommees} voix en banque.", fg=typer.colors.GREEN)
        _regenerer(config, identifiant)
    return True


def _ecouter(config: Config, identifiant: str, candidate: VoixANommer) -> None:
    """Joue l'extrait d'une voix, quand le système sait le faire."""
    lecteur = shutil.which("afplay") or shutil.which("aplay") or shutil.which("ffplay")
    if not lecteur:
        typer.echo("  (aucun lecteur audio disponible)")
        return
    if candidate.extrait is None:
        typer.echo("  (aucun extrait exploitable pour cette voix)")
        return
    try:
        detail = depot(config).lire(identifiant)
        sortie = config.chemins.donnees / "extraits" / f"{identifiant}-{candidate.voix}.wav"
        extrait = extraire_audio(detail.audio, candidate.extrait, sortie)
    except (RuntimeError, OSError, ValueError) as souci:
        typer.secho(f"  ✗ extrait indisponible : {souci}", fg=typer.colors.RED, err=True)
        return
    arguments = [lecteur, str(extrait)]
    if lecteur.endswith("ffplay"):
        arguments = [lecteur, "-nodisp", "-autoexit", "-loglevel", "error", str(extrait)]
    subprocess.run(arguments, check=False)


def _regenerer(config: Config, identifiant: str) -> bool:
    """Rejoue la rédaction si un compte rendu existait déjà pour cette réunion.

    Nommer une voix ne change ni la segmentation ni la transcription : pas
    besoin de relancer tout le traitement pour que le compte rendu porte les
    bonnes étiquettes.
    """
    chemin = config.chemins.comptes_rendus / f"{identifiant}.md"
    if not chemin.exists():
        return False
    moteur = redacteur(config)
    if moteur is None:
        return False
    reunion = depot(config).lire(identifiant)
    chemin.write_text(
        regenerer_compte_rendu(reunion, moteur, config.conversation.information),
        encoding="utf-8",
    )
    typer.secho(f"Compte rendu régénéré : {chemin}", fg=typer.colors.GREEN)
    return True


@application.command()
def verifier(
    config_fichier: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Dit ce qui est prêt et ce qui manque, sans rien traiter."""
    config = Config.charger(config_fichier)
    typer.echo(f"configuration : {config_fichier or dossier_config() / 'config.toml'}")
    typer.echo(f"modèles       : {config.chemins.modeles}")
    typer.echo(f"transcription : {config.transcription.moteur} ({config.transcription.langue})")
    typer.echo(f"compte rendu  : {config.compte_rendu.moteur} {config.compte_rendu.modele}")
    try:
        assembler(config)
    except (FileNotFoundError, RuntimeError, ImportError) as manque:
        typer.secho(f"✗ {manque}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from manque
    typer.secho("✓ chaîne assemblée, tout est en place", fg=typer.colors.GREEN)


if __name__ == "__main__":
    application()


@application.command()
def configurer(
    fichier: Path = typer.Option(None, "--fichier", help="Où écrire la configuration"),
) -> None:
    """Assistant de première configuration : questionne, installe, vérifie.

    À lancer au premier usage, et à relancer quand quelque chose change — de
    machine, de casque, d'adresse mail.
    """
    from greffier.adaptateurs import assistant_terminal as assistant
    from greffier.adaptateurs import diagnostic_systeme as diagnostic

    def choisir(question: str, options: list[tuple[str, str]], defaut: int) -> str:
        typer.echo(f"\n{question} :")
        for numero, (_, libelle) in enumerate(options, 1):
            marque = "→" if numero - 1 == defaut else " "
            typer.echo(f"  {marque} {numero}. {libelle}")
        while True:
            saisie = typer.prompt("Numéro", default=str(defaut + 1))
            if saisie.isdigit() and 1 <= int(saisie) <= len(options):
                return options[int(saisie) - 1][0]
            typer.secho("Choisis un numéro de la liste.", fg=typer.colors.YELLOW)

    dialogue = assistant.Dialogue(
        demander=lambda question, defaut: typer.prompt(question, default=defaut),
        confirmer=lambda question, defaut: typer.confirm(question, default=defaut),
        afficher=typer.echo,
        choisir=choisir,
    )

    typer.secho("Configuration de Greffier\n", fg=typer.colors.BRIGHT_WHITE, bold=True)
    etat = diagnostic.examiner()
    reponses = assistant.executer(dialogue, etat)
    cible = assistant.ecrire(reponses, fichier)

    typer.secho(f"\n✓ Configuration écrite : {cible}", fg=typer.colors.GREEN)
    if reponses.installations:
        typer.echo(f"  installés : {', '.join(reponses.installations)}")
    if reponses.a_faire:
        typer.secho("\nIl te reste à :", fg=typer.colors.YELLOW)
        for action in reponses.a_faire:
            typer.echo(f"  • {action}")
    typer.echo("\n« greffier diagnostic » pour vérifier, « greffier enregistrer » pour commencer.")


@application.command(name="diagnostic")
def diagnostic_(
    config_fichier: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Constate ce qui est en place et ce qui manque, sans rien modifier."""
    from greffier.adaptateurs import diagnostic_systeme as verificateur

    etat = verificateur.examiner()
    machine = etat.machine
    typer.echo(
        f"{machine.systeme} {machine.architecture} · {machine.memoire_go:.0f} Go · "
        f"calcul {machine.acceleration}\n"
    )
    for constat in etat.constats:
        if constat.present:
            typer.secho(f"  ✓ {constat.nom:<38} {constat.detail}", fg=typer.colors.GREEN)
        else:
            couleur = typer.colors.RED if constat.bloquant else typer.colors.YELLOW
            typer.secho(f"  ✗ {constat.nom:<38} {constat.detail}", fg=couleur)
            if constat.remede:
                typer.echo(f"      → {constat.remede}")
    if not etat.pret:
        typer.secho("\nIl manque l'essentiel. « greffier configurer » t'accompagne.",
                    fg=typer.colors.RED)
        raise typer.Exit(1)
    typer.secho("\nTout est en place.", fg=typer.colors.GREEN)


@application.command()
def peripheriques(
    lister: bool = typer.Option(False, "--lister", help="Montrer les périphériques disponibles"),
    micro: str = typer.Option(None, "--micro", help="Micro à intégrer au périphérique agrégé"),
    casque: str = typer.Option(None, "--casque", help="Sortie à dupliquer vers BlackHole"),
) -> None:
    """Crée les deux périphériques audio macOS nécessaires à l'enregistrement.

    Un périphérique agrégé référence un **matériel précis** : casque débranché =
    micro absent de l'agrégé = enregistrement muet. Relance cette commande quand
    le matériel change.

    Inutile sur Linux et Windows, qui exposent déjà de quoi réenregistrer leur
    propre sortie.
    """
    if platform.system() != "Darwin":
        typer.echo("Inutile ici : le système expose déjà un moniteur de sortie.")
        return
    source = Path(__file__).resolve().parent.parent.parent / "macos/creer-peripheriques.swift"
    if not source.exists():
        typer.secho(f"✗ {source} introuvable", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    arguments = ["swift", str(source)]
    if lister:
        arguments.append("--list")
    if micro:
        arguments += ["--mic", micro]
    if casque:
        arguments += ["--casque", casque]
    raise typer.Exit(subprocess.run(arguments, check=False).returncode)


@application.command()
def enregistrer(
    nom: str = typer.Argument("reunion", help="Sujet de la réunion"),
    config_fichier: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Démarre l'enregistrement. « greffier arreter » quand la réunion est finie.

    Le périphérique de capture est reconstruit autour du micro réellement
    branché : un casque habituel absent ne doit pas faire perdre la réunion.
    Une veille est ensuite lancée pour suivre le matériel pendant la séance.
    """
    config = Config.charger(config_fichier)
    precedente = _preparer_capture(config)
    try:
        etat = enregistrement(config).demarrer(nom, sortie_precedente=precedente)
    except (RuntimeError, FileNotFoundError) as souci:
        typer.secho(f"✗ {souci}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from souci
    typer.secho(f"● Enregistrement de « {etat.nom} »", fg=typer.colors.RED)
    typer.echo(f"  {etat.audio}")
    if _lancer_veille(config, config_fichier):
        typer.echo("  Le matériel est surveillé : branche ou débranche ton casque sans crainte.")
    if _lancer_direct(config, config_fichier):
        typer.echo("  Ce qui se dit s'affiche dans la fenêtre, et s'y corrige.")
    typer.echo("  « greffier arreter » pour arrêter et traiter.")


def _peripheriques_swift() -> Path | None:
    source = Path(__file__).resolve().parent.parent.parent / "macos/creer-peripheriques.swift"
    return source if source.exists() else None


def _swift(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Appelle l'utilitaire CoreAudio du dépôt."""
    source = _peripheriques_swift()
    if source is None:
        return subprocess.CompletedProcess([], 1, "", "utilitaire absent")
    return subprocess.run(
        ["swift", str(source), *arguments], capture_output=True, text=True, check=False
    )


#: En dessous, un micro donne un signal que la transcription n'entend pas. Sur un
#: poste réel réglé à 0,59, la voix arrivait 12 dB sous celle des autres.
_GAIN_MINIMAL = 0.85


def _preparer_capture(config: Config) -> str:
    """Met le poste dans le meilleur état possible, sans rien demander.

    Trois réglages, tous constatés manquants en usage réel :

    - le micro de l'agrégé doit être celui qui est **réellement branché**. Le
      défaut est codé sur un modèle de casque : démarrer avec ce casque
      débranché donne une capture qui n'entend pas la personne qui enregistre.
    - la sortie système doit passer par « Reunion Sortie ». Sans cela, le son
      des autres ne traverse pas la boucle de capture : mesuré, les canaux
      système restaient à -240 dB, donc muets.
    - le gain du micro doit être haut. À 0,59 sur un poste réel, la voix
      arrivait si bas que le modèle inventait des phrases.

    Rend la sortie d'avant, pour qu'on puisse la rendre à la fin.
    """
    if platform.system() != "Darwin" or _peripheriques_swift() is None:
        return ""

    materiel = listeur(config).lire()
    if not materiel.peripheriques:
        return ""

    micro = _micro_par_ecoute(config, materiel)
    if micro and micro != config.audio.micro:
        # Le micro et la sortie sont deux appareils distincts : le micro intégré
        # d'un portable n'est pas une sortie, et passer son nom aux deux faisait
        # échouer la construction de l'agrégé.
        if _swift("--mic", micro, "--casque", _sortie_ecoute(materiel)).returncode == 0:
            typer.secho(f"  micro : {micro}", fg=typer.colors.CYAN)
        else:
            typer.secho(f"⚠ « {micro} » n'a pas pu être installé comme micro.",
                        fg=typer.colors.YELLOW)

    if micro:
        _relever_le_gain(micro)

    precedente = _swift("--get-output").stdout.strip()
    if precedente and precedente != config.audio.sortie:
        if _swift("--set-output", config.audio.sortie).returncode == 0:
            typer.secho(f"  sortie : {config.audio.sortie} "
                        f"(au lieu de {precedente})", fg=typer.colors.CYAN)
        else:
            typer.secho(
                f"⚠ La sortie système est restée sur « {precedente} ». Le son des "
                "autres participants risque de ne pas être enregistré.",
                fg=typer.colors.YELLOW,
            )
            return ""
    return precedente


def _sortie_ecoute(materiel: object) -> str:
    """Par où la personne écoute la réunion, à dupliquer vers la boucle.

    Un casque d'abord : c'est là qu'on écoute quand il est branché, et cela évite
    que le micro réentende les enceintes. Les haut-parleurs sinon.
    """
    sorties = [p for p in getattr(materiel, "peripheriques", ()) if p.sorties > 0]
    utiles = [
        p.nom for p in sorties
        if "blackhole" not in p.nom.lower() and not p.uid.startswith("com.reunions.")
    ]
    if not utiles:
        return "BlackHole 2ch"
    externes = [nom for nom in utiles if "macbook" not in nom.lower()]
    return str((externes or utiles)[0])


def _micro_par_ecoute(config: Config, materiel: object) -> str:
    """Écoute les micros disponibles et retient celui qui capte le mieux.

    Un micro peut être branché, reconnu, réglé au maximum, et muet : les casques
    USB ont un bouton de sourdine sur leur boîtier. Mesuré sur un poste réel, un
    Jabra rendait -78 dB quand le micro intégré rendait -58 dB dans le même
    silence. Sans cette écoute, Greffier retenait le casque, enregistrait une
    heure de silence, puis accusait l'autorisation micro.
    """
    from greffier.composition import _enregistreur
    from greffier.domaine.peripheriques import (
        candidats_a_ecouter,
        casques_parmi,
        choisir_par_ecoute,
    )

    candidats = candidats_a_ecouter(materiel, config.audio.micro)  # type: ignore[arg-type]
    if not candidats:
        return ""
    enregistreur = _enregistreur(config)
    essais = {nom: enregistreur.essayer(nom) for nom in candidats}
    choix = choisir_par_ecoute(
        essais, casques_parmi(materiel)  # type: ignore[arg-type]
    )
    if choix is None:
        return ""
    if choix.tous_muets:
        typer.secho(
            f"⚠ Aucun micro ne capte : le meilleur, « {choix.nom} », rend "
            f"{choix.niveau_db:.0f} dB. Vérifie le bouton de sourdine de ton "
            "casque, puis l'autorisation micro dans Réglages Système.",
            fg=typer.colors.YELLOW,
        )
    if choix.casque_prefere:
        # Le dire : au vu des seuls niveaux, le choix paraît faux. Un casque
        # posé sur le bureau capte moins qu'un micro de portable, et devient de
        # loin le meilleur dès qu'on le porte.
        plus_fort = [nom for nom, db in choix.ecartes if db > choix.niveau_db]
        if plus_fort:
            typer.secho(
                f"  « {choix.nom} » retenu bien que « {plus_fort[0]} » capte plus "
                f"fort : un micro de casque est à trois centimètres de la bouche.\n"
                "  Pense à le porter avant de démarrer.",
                fg=typer.colors.BLUE,
            )
    for nom, niveau in choix.ecartes:
        if niveau < choix.niveau_db - 10:
            typer.secho(f"  « {nom} » écarté : {niveau:.0f} dB contre "
                        f"{choix.niveau_db:.0f} dB", fg=typer.colors.YELLOW)
    return choix.nom


def _relever_le_gain(micro: str) -> None:
    """Monte le gain du micro s'il est trop bas pour la transcription."""
    lecture = _swift("--get-gain", micro)
    if lecture.returncode != 0:
        return
    try:
        gain = float(lecture.stdout.strip())
    except ValueError:
        return
    if gain >= _GAIN_MINIMAL:
        return
    if _swift("--set-gain", micro, "0.95").returncode == 0:
        typer.secho(f"  gain du micro relevé : {gain:.2f} → 0.95", fg=typer.colors.CYAN)
    else:
        typer.secho(
            f"⚠ Le gain de « {micro} » est à {gain:.2f} et n'a pas pu être relevé. "
            "Ta voix risque d'être trop faible pour être transcrite.",
            fg=typer.colors.YELLOW,
        )


def _rendre_la_sortie(precedente: str) -> None:
    """Remet la sortie système d'avant la réunion."""
    if not precedente or platform.system() != "Darwin":
        return
    _swift("--set-output", precedente)


def _lancer_veille(config: Config, config_fichier: Path | None) -> bool:
    """Lance la veille du matériel, détachée. Faux si elle n'a pas pu partir.

    Détachée : « greffier enregistrer » doit rendre la main tout de suite, et la
    veille doit survivre à la fermeture du terminal. Son échec ne compromet que
    l'adaptation au matériel, jamais la capture.
    """
    if platform.system() != "Darwin":
        return False
    commande = [sys.executable, "-m", "greffier", "veiller"]
    if config_fichier:
        commande += ["--config", str(config_fichier)]
    journal = config.chemins.donnees / "veille.log"
    try:
        journal.parent.mkdir(parents=True, exist_ok=True)
        with journal.open("a", encoding="utf-8") as trace:
            subprocess.Popen(
                commande, stdin=subprocess.DEVNULL, stdout=trace, stderr=trace,
                start_new_session=True,
            )
    except OSError:
        return False
    return True


def _lancer_direct(config: Config, config_fichier: Path | None) -> bool:
    """Lance la transcription en direct, détachée. Faux si elle ne part pas.

    Un processus séparé, comme la veille du matériel : whisper occupe plusieurs
    secondes par tranche, ce qui gèlerait la fenêtre, et un modèle qui tombe ne
    doit pas emporter l'interface. C'est ce qui manquait — la commande existait,
    mais rien ne la lançait, donc personne ne l'a jamais vue tourner.
    """
    if not config.direct.actif:
        return False
    commande = [sys.executable, "-m", "greffier", "assister"]
    if config_fichier:
        commande += ["--config", str(config_fichier)]
    journal = config.chemins.donnees / "direct.log"
    try:
        journal.parent.mkdir(parents=True, exist_ok=True)
        with journal.open("a", encoding="utf-8") as trace:
            subprocess.Popen(
                commande, stdin=subprocess.DEVNULL, stdout=trace, stderr=trace,
                start_new_session=True,
            )
    except OSError:
        return False
    return True


@application.command()
def arreter(
    sans_traiter: bool = typer.Option(False, "--sans-traiter",
                                      help="Arrêter sans lancer la transcription"),
    sans_envoi: bool = typer.Option(
        False, "--sans-envoi", help="Ne pas envoyer, même si un destinataire est configuré"
    ),
    config_fichier: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Arrête l'enregistrement, puis enchaîne transcription et compte rendu."""
    config = Config.charger(config_fichier)
    try:
        etat = enregistrement(config).arreter()
    except RuntimeError as souci:
        typer.secho(f"✗ {souci}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from souci
    audio = etat.audio
    if audio is None:  # pragma: no cover - « arreter » lève déjà dans ce cas
        raise typer.Exit(1)
    _rendre_la_sortie(etat.sortie_precedente)
    typer.secho(f"■ Enregistrement arrêté : {audio.name}", fg=typer.colors.GREEN)
    if sans_traiter:
        typer.echo(f"  « greffier traiter {audio} » pour le traiter plus tard.")
        return
    if etat.evenements:
        for evenement in etat.evenements:
            typer.secho(f"  matériel : {evenement}", fg=typer.colors.YELLOW)
    traiter(
        audio=audio, sans_envoi=sans_envoi, sans_cr=False,
        config_fichier=config_fichier, evenements=etat.evenements,
    )


@application.command()
def annuler(
    config_fichier: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Interrompt le traitement en cours. L'audio est conservé."""
    try:
        enregistrement(Config.charger(config_fichier)).interrompre()
    except RuntimeError as souci:
        typer.secho(f"✗ {souci}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from souci
    typer.secho("■ Traitement interrompu, l'audio est conservé.", fg=typer.colors.YELLOW)


@application.command()
def assister(
    mot_cle: str = typer.Option("greffier", "--mot-cle", help="Mot d'activation"),
    sans_transcription: bool = typer.Option(
        False, "--sans-transcription", help="Ne surveiller que le presse-papier"),
    config_fichier: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Veille pendant la réunion : affiche ce qui se dit, et propose des actions.

    Deux choses en une boucle, parce qu'elles partagent la même transcription et
    que la refaire deux fois doublerait le calcul pris à la réunion :

    - **le fil de ce qui se dit**, avec qui parle, publié dans un journal que la
      fenêtre lit au fil de l'eau et où elle dépose ses corrections. C'est là
      qu'un locuteur mal attribué se corrige **pendant** la réunion, au lieu de
      se découvrir dans le compte rendu ;
    - **les propositions** : les liens collés dans le presse-papier, exact, et
      les décisions entendues, faillibles. Rien n'est exécuté, c'est toi qui
      déclenches.
    """
    import tempfile

    from greffier.adaptateurs.niveaux_direct import duree_ecrite
    from greffier.application.suivre import position
    from greffier.application.veiller import Veilleur
    from greffier.composition import _enregistreur
    from greffier.domaine.instructions import Veille

    config = Config.charger(config_fichier)
    machine = enregistrement(config)
    etat = machine.lire()
    if etat.phase.value not in {"enregistrement", "pause"}:
        typer.secho("Aucun enregistrement en cours. « greffier enregistrer » d'abord.",
                    fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    journal = config.chemins.propositions / f"{etat.identifiant}.jsonl"
    transcripteur = None if sans_transcription else transcripteur_leger(config)

    # Les questions sur les termes mal entendus, déposées au fil de la réunion.
    # Les clefs déjà posées sont relues du fichier : le processus qui écoute
    # peut être relancé en cours de réunion, et redemander serait pire que rien.
    from greffier.adaptateurs import questions_fichier
    from greffier.domaine.questions import Interrogateur

    le_contexte = contexte(config)
    fichier_questions = questions_fichier.fichier_des_questions(
        config.chemins.questions, etat.identifiant
    )
    interrogateur = Interrogateur(
        connus=tuple(t.ecriture for t in le_contexte.termes)
        + tuple(i.nom for i in le_contexte.intervenants),
        posees=questions_fichier.clefs_deja_posees(fichier_questions),
    )

    def interroger(texte: str) -> None:
        for question in interrogateur.examiner(texte):
            questions_fichier.deposer(fichier_questions, question)
    le_suivi = suivi(config, etat.identifiant) if config.direct.actif else None
    lui = participant(config, etat.identifiant)
    if lui is not None and le_suivi is not None:
        lui.nommer = _nommeur(le_suivi, config, etat.identifiant)
        # Ce qui s'est dit jusqu'ici, pour que sa réponse porte sur la réunion
        # en cours et non sur des généralités.
        lui.contexte = le_suivi.fil.rendu
    veilleur = Veilleur(
        veille=Veille(mot_cle=mot_cle),
        journal=journal,
        transcripteur=transcripteur,
        # La position vient des octets écrits, pas de l'horloge : après une
        # pause, les deux ont divergé de tout le temps d'arrêt.
        situer=lambda: position(machine.lire().morceaux, duree_ecrite),
        suivi=le_suivi,
        # Les canaux de la tranche sont mis à niveau avant d'être transcrits :
        # sans cela, la voix la plus faible du mélange n'est pas transcrite.
        preparateur=_enregistreur(config),
        langue=config.transcription.langue,
        # Le même contexte que la transcription définitive : c'est le fil qu'on
        # lit pendant la réunion, et c'est dessus qu'on corrige.
        amorce=le_contexte.amorce(),
        # Relue à chaque tranche : un terme ajouté en pleine réunion doit
        # servir à la phrase suivante, pas à la réunion d'après.
        relire_l_amorce=lambda: contexte(config).amorce(),
        interroger=interroger,
        participant=lui,
        relire_la_participation=lambda: Config().assistant.actif,
        periode_tranche=config.direct.periode,
    )
    if le_suivi is not None:
        le_suivi.annoncer(
            "Transcription en direct active." if transcripteur is not None
            else "Aucun modèle de transcription : le fil restera vide.",
            actif=transcripteur is not None,
        )
    typer.secho(f"Veille sur « {etat.nom} ». Ctrl+C pour arrêter.", fg=typer.colors.BLUE)
    typer.echo(f"  mot d'activation : « {mot_cle} »")
    if lui is not None:
        comment = "à voix haute" if lui.voix is not None else "par écrit"
        typer.echo(f"  assistant        : « {lui.nom} », {comment}")
    typer.echo(f"  propositions     : {journal}")
    if le_suivi is not None:
        typer.echo(f"  fil du direct    : {le_suivi.journal}")
    typer.echo("")

    def encore() -> bool:
        return machine.lire().phase.value in {"enregistrement", "pause"}

    with tempfile.TemporaryDirectory() as travail:
        try:
            veilleur.boucler(encore=encore, depuis=lambda: machine.lire().secondes,
                             travail=Path(travail))
        except KeyboardInterrupt:
            typer.echo("")
    total = len(veilleur.veille.propositions)
    tours = len(le_suivi.fil.tours) if le_suivi else 0
    typer.secho(
        f"✓ {tours} phrase(s) affichée(s), {total} proposition(s) relevée(s).",
        fg=typer.colors.GREEN,
    )


@application.command()
def propositions(
    reunion: str = typer.Argument(None, help="Réunion (défaut : la dernière)"),
    config_fichier: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Ce que la veille a relevé pendant une réunion."""
    import json as _json

    config = Config.charger(config_fichier)
    identifiant = _reunion_visee(config, reunion)
    journal = config.chemins.propositions / f"{identifiant}.jsonl"
    if not journal.exists():
        typer.echo("Aucune proposition pour cette réunion.")
        return
    couleurs = {"lien": typer.colors.CYAN, "instruction": typer.colors.MAGENTA,
                "decision": typer.colors.YELLOW}
    for ligne in journal.read_text(encoding="utf-8").splitlines():
        if not ligne.strip():
            continue
        item = _json.loads(ligne)
        instant = int(item["instant"])
        typer.secho(
            f"  {instant // 60:02d}:{instant % 60:02d}  "
            f"{item['genre']:<12} {item['texte'][:88]}",
            fg=couleurs.get(item["genre"]),
        )


@application.command()
def statut(
    config_fichier: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Où en est la chaîne — ce que lit aussi l'icône de la barre."""
    etat = enregistrement(Config.charger(config_fichier)).lire()
    if etat.phase.value == "repos":
        typer.echo("Rien en cours. « greffier enregistrer <nom> » pour démarrer.")
        return
    duree = f" — {etat.secondes // 60:.0f} min" if etat.phase.value == "enregistrement" else ""
    typer.echo(f"{etat.phase.value}{duree}")
    if etat.nom:
        typer.echo(f"  réunion : {etat.nom}")
    if etat.message:
        typer.echo(f"  {etat.message}")


@application.command()
def reunions(
    config_fichier: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Liste les réunions déjà traitées, les plus récentes d'abord."""
    config = Config.charger(config_fichier)
    magasin = depot(config)
    identifiants = magasin.lister()
    if not identifiants:
        typer.echo("Aucune réunion traitée. « greffier traiter <audio> » pour commencer.")
        return
    for identifiant in identifiants:
        reunion = magasin.lire(identifiant)
        nommees = sum(1 for v in reunion.temps_de_parole() if v in reunion.noms)
        total = len(voix_a_nommer(reunion))
        couverture = f"{reunion.couverture * 100:.0f} %"
        typer.echo(
            f"{identifiant:<44} {reunion.duree / 60:5.1f} min  "
            f"{nommees}/{total} voix nommées  couverture {couverture}"
        )


@application.command()
def voix(
    reunion: str = typer.Argument(None, help="Réunion à annoter (défaut : la dernière)"),
    ecouter: str = typer.Option(None, "--ecouter", help="Extraire un extrait de cette voix"),
    nommer_voix: str = typer.Option(None, "--nommer", help="Voix à nommer"),
    nom: str = typer.Option(None, "--nom", help="Nom à lui donner"),
    accepter: bool = typer.Option(False, "--accepter-propositions",
                                  help="Valider d'un coup les noms devinés"),
    config_fichier: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Montre les voix d'une réunion, et permet de les nommer.

    Personne n'est prié de se présenter pendant la réunion : on écoute dix
    secondes après coup, une seule fois par personne. Ensuite l'empreinte est en
    banque et la reconnaissance se fait seule.
    """
    config = Config.charger(config_fichier)
    magasin = depot(config)
    identifiant = _reunion_visee(config, reunion)

    if accepter:
        acceptes = nommage(config).accepter_propositions(identifiant)
        for voix_id, nom_accepte in acceptes.items():
            typer.secho(f"✓ voix {voix_id} = {nom_accepte}", fg=typer.colors.GREEN)
        if not acceptes:
            typer.echo("Aucune proposition à valider.")
        else:
            _regenerer(config, identifiant)
        return

    if nommer_voix and nom:
        nommage(config).nommer(identifiant, nommer_voix, nom)
        typer.secho(f"✓ voix {nommer_voix} = {nom}, empreinte en banque",
                    fg=typer.colors.GREEN)
        typer.echo("Cette personne sera reconnue aux prochaines réunions.")
        _regenerer(config, identifiant)
        return
    if nommer_voix or nom:
        typer.secho("--nommer et --nom vont ensemble.", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)

    detail = magasin.lire(identifiant)
    if ecouter:
        candidates = [v for v in voix_a_nommer(detail) if v.voix == ecouter]
        if not candidates or candidates[0].extrait is None:
            typer.secho(f"Aucun extrait pour la voix « {ecouter} ».",
                        fg=typer.colors.RED, err=True)
            raise typer.Exit(1)
        sortie = config.chemins.donnees / "extraits" / f"{identifiant}-{ecouter}.wav"
        extraire_audio(detail.audio, candidates[0].extrait, sortie)
        typer.echo(f"Extrait : {sortie}")
        return

    typer.echo(f"{identifiant} — {detail.duree / 60:.1f} min\n")
    for candidate in voix_a_nommer(detail):
        etat = (
            typer.style(candidate.nom, fg=typer.colors.GREEN) if candidate.nom
            else typer.style(f"≈ {candidate.proposition} (à confirmer)", fg=typer.colors.YELLOW)
            if candidate.proposition
            else typer.style("à nommer", fg=typer.colors.BRIGHT_BLACK)
        )
        typer.echo(
            f"  voix {candidate.voix:<4} {candidate.duree / 60:5.1f} min "
            f"({candidate.part * 100:4.1f} %)  {etat}"
        )
    typer.echo(
        "\n  écouter : greffier voix "
        f"{identifiant} --ecouter <voix>\n"
        f"  nommer  : greffier voix {identifiant} --nommer <voix> --nom Josiane"
    )
    if detail.propositions:
        typer.echo(f"  valider : greffier voix {identifiant} --accepter-propositions")


@application.command()
def connus(
    oublier: str = typer.Option(None, "--oublier", help="Effacer une personne de la banque"),
    renommer: str = typer.Option(None, "--renommer", help="Personne à renommer"),
    en: str = typer.Option(None, "--en", help="Nouveau nom"),
    nettoyer: str = typer.Option(
        None, "--nettoyer",
        help="Retirer les empreintes de cette personne qui sont d'une autre",
    ),
    oublier_reunion: str = typer.Option(
        None, "--oublier-reunion",
        help="Retirer de toute la banque ce qu'une réunion y a versé",
    ),
    config_fichier: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Les voix déjà connues, et de quoi les corriger.

    Une empreinte vocale nominative est une donnée biométrique : il doit être
    aussi simple de l'effacer que de l'ajouter.
    """
    config = Config.charger(config_fichier)
    banque = BanqueFichiers(config.chemins.banque_de_voix)

    if oublier:
        if banque.oublier(oublier):
            typer.secho(f"✓ {oublier} effacé de la banque de voix", fg=typer.colors.GREEN)
        else:
            typer.secho(f"« {oublier} » n'est pas dans la banque.",
                        fg=typer.colors.RED, err=True)
            raise typer.Exit(1)
        return

    if renommer and en:
        banque.renommer(renommer, en)
        typer.secho(f"✓ {renommer} → {en}", fg=typer.colors.GREEN)
        return

    if nettoyer:
        _nettoyer_une_entree(banque, nettoyer)
        return

    if oublier_reunion:
        retires = banque.oublier_une_reunion(oublier_reunion)
        if not retires:
            typer.echo(
                f"Aucune empreinte ne vient de « {oublier_reunion} ». Les "
                "empreintes déposées avant que cette trace n'existe ne portent "
                "pas leur origine : « greffier connus » dit lesquelles sont "
                "suspectes."
            )
            return
        for nom, combien in sorted(retires.items()):
            typer.secho(f"✓ {combien} empreinte(s) retirée(s) de {nom}",
                        fg=typer.colors.GREEN)
        _dire_la_sante_de_la_banque(banque.personnes())
        return

    personnes = banque.personnes()
    if not personnes:
        typer.echo("Banque de voix vide. « greffier voix » pour nommer une première voix.")
        return
    for personne in personnes:
        vue = personne.vu_le.strftime("%Y-%m-%d") if personne.vu_le else "—"
        typer.echo(
            f"  {personne.nom:<20} {len(personne.empreintes)} empreinte(s)  "
            f"vue le {vue}"
        )

    _dire_la_sante_de_la_banque(personnes)


def _nettoyer_une_entree(banque: BanqueFichiers, nom: str) -> None:
    """Retire d'une personne les empreintes qui désignent quelqu'un d'autre.

    Effacer la personne entière pour une empreinte fautive perdait tout le
    reste. Le grain qui décide de la reconnaissance est l'empreinte : c'est
    donc à ce grain qu'on corrige.
    """
    from greffier.domaine.empreintes import empreintes_intruses

    personnes = banque.personnes()
    cette = next((p for p in personnes if p.nom.casefold() == nom.casefold()), None)
    if cette is None:
        typer.secho(f"« {nom} » n'est pas dans la banque.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    suspectes = empreintes_intruses(cette, personnes)
    if not suspectes:
        typer.echo(f"Rien à retirer : les empreintes de {cette.nom} se ressemblent "
                   "entre elles plus qu'à quiconque.")
        return
    for intruse in suspectes:
        typer.echo(
            f"  empreinte {intruse.rang} ({intruse.duree:.0f} s) : "
            f"ressemble à {intruse.qui} ({intruse.ailleurs:.2f}) plus qu'à "
            f"{cette.nom} ({intruse.chez_elle:.2f})"
        )
    if not typer.confirm(
        f"Retirer ces {len(suspectes)} empreinte(s) de {cette.nom} ?", default=False
    ):
        typer.echo("Rien n'a été touché.")
        return
    combien = banque.retirer_empreintes(cette.nom, [i.rang for i in suspectes])
    typer.secho(f"✓ {combien} empreinte(s) retirée(s) de {cette.nom}",
                fg=typer.colors.GREEN)
    _dire_la_sante_de_la_banque(banque.personnes())


def _dire_la_sante_de_la_banque(personnes: list) -> None:  # type: ignore[type-arg]
    """Dit quelles entrées se ressemblent trop, et ce que ça coûte.

    Une entrée déposée sous le nom d'un collègue mais portant une autre voix
    empoisonne toute la banque : les deux noms deviennent inreconnaissables,
    et rien ne le dit. C'est arrivé le 2026-09-02, découvert seulement parce
    qu'un prénom avait été affirmé à tort en réunion.
    """
    import itertools

    from greffier.domaine.empreintes import (
        SEUIL_CONFLIT,
        SEUIL_RECONNAISSANCE,
        agreger,
        similarite,
    )

    agregats = {
        personne.nom: (
            agreger(personne.empreintes) if len(personne.empreintes) > 1
            else personne.empreintes[0]
        )
        for personne in personnes if personne.empreintes
    }
    conflits: list[tuple[float, str, str]] = []
    proches: list[tuple[float, str, str]] = []
    for un, autre in itertools.combinations(sorted(agregats), 2):
        valeur = similarite(agregats[un], agregats[autre])
        if valeur >= SEUIL_CONFLIT:
            conflits.append((valeur, un, autre))
        elif valeur >= SEUIL_RECONNAISSANCE:
            proches.append((valeur, un, autre))

    if conflits:
        typer.secho(
            f"\n⚠ {len(conflits)} paire(s) trop ressemblante(s) : ces personnes "
            "ne sont plus reconnues du tout.",
            fg=typer.colors.RED,
        )
        for valeur, un, autre in sorted(conflits, reverse=True):
            typer.secho(f"    {valeur:.3f}  {un} / {autre}", fg=typer.colors.RED)
        typer.echo(
            "  Une des deux entrées porte probablement la voix de l'autre. "
            "Réécoute\n  un extrait de chacune, puis « greffier connus "
            "--oublier <nom> » et renomme\n  la voix à la prochaine réunion."
        )
    _dire_les_intruses(personnes)
    if proches:
        typer.secho(
            f"\n· {len(proches)} paire(s) proche(s), au-dessus du seuil de "
            f"reconnaissance ({SEUIL_RECONNAISSANCE:.2f}) :",
            fg=typer.colors.YELLOW,
        )
        for valeur, un, autre in sorted(proches, reverse=True):
            typer.echo(f"    {valeur:.3f}  {un} / {autre}")
        typer.echo(
            "  C'est l'écart avec le second qui les sépare. Une entrée d'une "
            "seule\n  empreinte est fragile : renommer la même personne sur une "
            "autre réunion\n  ajoute une empreinte et écarte les voix les unes "
            "des autres."
        )
    maigres = [p.nom for p in personnes if len(p.empreintes) < 2]
    if maigres:
        typer.echo(
            f"\n  {len(maigres)} entrée(s) d'une seule empreinte : "
            f"{', '.join(maigres)}"
        )


def _dire_les_intruses(personnes: list) -> None:  # type: ignore[type-arg]
    """Nomme les empreintes fautives, une par une.

    Savoir que deux entrées sont en conflit ne dit pas laquelle réparer, et
    effacer une personne entière pour une empreinte perd tout le reste. La
    question se pose empreinte par empreinte, et elle a une réponse.
    """
    from greffier.domaine.empreintes import empreintes_intruses

    trouvees = [
        (personne.nom, intruse)
        for personne in personnes
        for intruse in empreintes_intruses(personne, personnes)
    ]
    if not trouvees:
        return
    typer.secho(
        f"\n  {len(trouvees)} empreinte(s) désignent quelqu'un d'autre que "
        "la personne sous laquelle elles sont rangées :",
        fg=typer.colors.YELLOW,
    )
    for nom, intruse in sorted(trouvees, key=lambda x: -x[1].ecart):
        typer.echo(
            f"    {nom} n° {intruse.rang} ({intruse.duree:.0f} s) : "
            f"{intruse.qui} {intruse.ailleurs:.2f} contre {nom} "
            f"{intruse.chez_elle:.2f}"
        )
    noms = sorted({nom for nom, _ in trouvees})
    typer.echo(
        f"  « greffier connus --nettoyer {noms[0]} » les retire sans effacer "
        "le reste."
    )


@application.command()
def montage(
    reunion: str = typer.Argument(None, help="Réunion (défaut : la dernière)"),
    minutes: float = typer.Option(5.0, "--minutes", help="Durée visée du montage"),
    config_fichier: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Recolle les passages marquants — les vraies voix, rien de synthétisé.

    Le temps est réparti entre les intervenants proportionnellement à leur temps
    de parole : un montage qui ne ferait entendre que la personne la plus
    bavarde ne restituerait pas la réunion.
    """
    from greffier.application.restituer import monter, passages_marquants

    config = Config.charger(config_fichier)
    magasin = depot(config)
    identifiant = _reunion_visee(config, reunion)
    detail = magasin.lire(identifiant)
    passages = passages_marquants(detail, duree_visee=minutes * 60)
    if not passages:
        typer.secho("Pas assez de parole pour un montage.", fg=typer.colors.YELLOW)
        raise typer.Exit(1)
    sortie = config.chemins.donnees / "montages" / f"{identifiant}.m4a"
    monter(detail.audio, passages, sortie)
    total = sum(p.duree for p in passages)
    typer.secho(f"✓ {len(passages)} passages, {total / 60:.1f} min : {sortie}",
                fg=typer.colors.GREEN)


@application.command(name="contexte")
def contexte_(
    ouvrir: bool = typer.Option(False, "--ouvrir", help="Ouvrir le fichier pour l'éditer"),
    config_fichier: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Montre ce que Greffier sait de votre milieu, et d'où il le sait.

    Un sigle absent d'ici sera transcrit par le mot le plus proche que le modèle
    connaît : « déploiement » devient « exploitement ». Cette commande sert à
    vérifier ce qui est effectivement transmis, et ce que l'amorce a dû écarter.
    """
    from greffier.adaptateurs import contexte_fichier

    config = Config.charger(config_fichier)
    fichier = config.chemins.contexte
    if contexte_fichier.poser_le_gabarit(fichier):
        typer.secho(f"Fichier de contexte créé : {fichier}", fg=typer.colors.GREEN)

    le_contexte = contexte(config)
    typer.echo(f"\n{len(le_contexte.termes)} terme(s), "
               f"{len(le_contexte.intervenants)} personne(s)")
    typer.echo(f"  fichier      {fichier}")
    typer.echo(f"  vocabulaire  config.toml, {len(config.transcription.vocabulaire)} mot(s)")
    typer.echo(f"  banque       {config.chemins.banque_de_voix}")

    typer.secho("\nTermes", fg=typer.colors.BRIGHT_WHITE, bold=True)
    for terme in le_contexte.termes:
        typer.echo(f"  {terme.glose}")
    typer.secho("\nPersonnes", fg=typer.colors.BRIGHT_WHITE, bold=True)
    for personne in le_contexte.intervenants:
        typer.echo(f"  {personne.glose}")

    amorce = le_contexte.amorce()
    typer.secho(f"\nAmorce de transcription ({len(amorce)} caractères)",
                fg=typer.colors.BRIGHT_WHITE, bold=True)
    typer.echo(f"  {amorce or '(aucune)'}")
    ecartes = le_contexte.ecartes()
    if ecartes:
        # whisper tronque sans prévenir : le dire est tout l'intérêt.
        typer.secho(
            f"\n⚠ {len(ecartes)} terme(s) écarté(s), l'amorce est pleine : "
            + ", ".join(ecartes[:8]) + ("…" if len(ecartes) > 8 else ""),
            fg=typer.colors.YELLOW,
        )
        typer.echo("  Retire les moins utiles : ce qui dépasse ne sert à personne.")

    if ouvrir:
        ouvreur = {"darwin": "open", "win32": "start"}.get(sys.platform, "xdg-open")
        subprocess.run([ouvreur, str(fichier)], check=False)


@application.command()
def renommer(
    sujet: str = typer.Argument(..., help="Le sujet de la réunion, en clair"),
    reunion: str = typer.Argument(None, help="Réunion (défaut : la dernière)"),
    config_fichier: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Donne un sujet à une réunion, celui qui s'affichera dans la liste.

    Un libellé, pas un renommage de fichiers : l'identifiant porte la date, qui
    ordonne les réunions, date le compte rendu et sert de clé à l'audio comme à
    la transcription. Le remplacer par « point du lundi » perdrait tout cela.
    """
    config = Config.charger(config_fichier)
    identifiant = _reunion_visee(config, reunion)
    magasin = depot(config)
    try:
        gardee = magasin.lire(identifiant)
    except (OSError, ValueError) as souci:
        typer.secho(f"✗ {souci}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from souci
    gardee.sujet = sujet.strip()
    magasin.enregistrer(gardee)
    typer.secho(f"✓ {identifiant} → « {gardee.intitule} »", fg=typer.colors.GREEN)


@application.command()
def carte(
    sujet: str = typer.Argument(None, help="Sujet à cartographier (défaut : ceux détectés)"),
    reunion: str = typer.Argument(None, help="Réunion (défaut : la dernière)"),
    publier: bool = typer.Option(False, "--publier", help="Écrire sur Miro"),
    config_fichier: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Construit la carte d'un sujet depuis une réunion. Constate d'abord.

    Sans « --publier », rien ne sort du poste : la commande dit ce qu'elle
    ajouterait. Une carte se partage largement, la voir avant coûte peu.
    """
    from greffier.adaptateurs import sujets_fichier
    from greffier.application.cartographier import RenduIllisible, extraire
    from greffier.application.restituer import rendre_transcription
    from greffier.domaine.carte import Carte, fusionner

    config = Config.charger(config_fichier)
    identifiant = _reunion_visee(config, reunion)
    sujets_fichier.poser_le_gabarit(config.chemins.sujets)
    registre = sujets_fichier.lire(config.chemins.sujets)

    try:
        gardee = depot(config).lire(identifiant)
    except (OSError, ValueError) as souci:
        typer.secho(f"✗ {souci}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from souci
    matiere = rendre_transcription(gardee)

    vises = [sujet] if sujet else registre.sujets_de(matiere)
    if not vises:
        typer.echo("Aucun sujet suivi n'est assez présent dans cette réunion.")
        typer.echo(f"Les sujets se déclarent dans {config.chemins.sujets}.")
        raise typer.Exit(1)

    moteur = cartographe(config)
    if moteur is None:
        typer.secho("Aucun rédacteur configuré.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    for nom in vises:
        typer.secho(f"\n— {nom} —", fg=typer.colors.BRIGHT_WHITE, bold=True)
        # Ce qui est déjà sur la carte, donné au rédacteur : sans cela il
        # reformule et chaque reformulation crée une branche de plus.
        deja = _libelles_de_la_carte(registre, nom) if publier else ()
        # Ce que des humains ont ajouté sur la carte depuis la dernière fois :
        # c'est tout l'intérêt d'une carte partagée, et cela n'était jamais relu.
        des_autres = _apports_des_autres(registre, nom) if publier else ()
        if des_autres:
            typer.secho(
                f"  {len(des_autres)} point(s) ajouté(s) à la main sur la carte :",
                fg=typer.colors.BLUE,
            )
            for libelle in des_autres[:5]:
                typer.echo(f"    · {libelle}")
        try:
            apports = extraire(moteur, nom, matiere, deja=deja)
        except RenduIllisible as souci:
            # Distinct de « rien à ajouter » : une panne ne doit pas se lire
            # comme un résultat.
            typer.secho(f"  ✗ extraction illisible : {souci}", fg=typer.colors.RED)
            continue
        if not apports:
            typer.echo("  rien à ajouter")
            continue
        la_carte = Carte(nom)
        bilan = fusionner(la_carte, apports, reunion=identifiant)
        for apport in apports:
            marque = "✓" if str(apport.etat) == "acté" else "·"
            sous = f"  ← {apport.sous}" if apport.sous else ""
            typer.echo(f"  {marque} [{apport.genre}] {apport.texte}{sous}")
        if not publier:
            typer.echo(f"  ({len(bilan.ajoutes)} point(s), « --publier » pour l'écrire)")
            continue
        _publier_la_carte(config, registre, nom, la_carte, identifiant)


def _libelles_de_la_carte(registre: object, nom: str) -> tuple[str, ...]:
    """Les libellés déjà sur la carte de ce sujet, s'il en a une."""
    from greffier.adaptateurs import carte_miro

    connu = registre.par_nom(nom)  # type: ignore[attr-defined]
    if connu is None or not connu.carte:
        return ()
    try:
        return tuple(carte_miro.libelles_presents(connu.carte))
    except carte_miro.MiroRefuse:
        # Ne pas pouvoir relire n'empêche pas d'extraire ; on risque seulement
        # des doublons, ce qui se corrige, là où ne rien produire ne se corrige
        # pas.
        return ()


def _textes_actes(carte: object) -> list[str]:
    """Les libellés des points que le groupe a tranchés.

    La racine est écartée : le sujet n'est ni acté ni en discussion, il est.
    """
    from greffier.domaine.carte import Etat, Genre, Noeud

    trouves: list[str] = []

    def parcourir(noeud: Noeud) -> None:
        if noeud.etat is Etat.ACTE and noeud.genre is not Genre.SUJET:
            trouves.append(noeud.texte)
        for enfant in noeud.enfants:
            parcourir(enfant)

    racine = getattr(carte, "racine", None)
    if racine is not None:
        parcourir(racine)
    return trouves


def _apports_des_autres(registre: object, nom: str) -> tuple[str, ...]:
    """Ce que des humains ont écrit sur la carte, et que l'outil n'a pas posé."""
    from greffier.adaptateurs import carte_miro

    connu = registre.par_nom(nom)  # type: ignore[attr-defined]
    if connu is None or not connu.carte:
        return ()
    try:
        return tuple(carte_miro.apports_des_autres(connu.carte))
    except carte_miro.MiroRefuse:
        return ()


def _publier_la_carte(
    config: Config, registre: object, nom: str, la_carte: object, identifiant: str
) -> None:
    """Écrit la carte sur Miro, en créant le tableau à la première fois."""
    from greffier.adaptateurs import carte_miro, sujets_fichier

    connu = registre.par_nom(nom)  # type: ignore[attr-defined]
    tableau = connu.carte if connu and connu.carte else ""
    try:
        if not tableau:
            tableau, adresse = carte_miro.creer_le_tableau(nom)
            sujets_fichier.noter_la_carte(config.chemins.sujets, nom, tableau)
            typer.secho(f"  tableau créé : {adresse or tableau}", fg=typer.colors.GREEN)
        ecrit = carte_miro.publier(la_carte, tableau, reunion=identifiant)  # type: ignore[arg-type]
    except carte_miro.MiroRefuse as souci:
        typer.secho(f"  ✗ {souci}", fg=typer.colors.RED, err=True)
        return
    typer.secho(
        f"  ✓ {len(ecrit.poses)} posé(s), {len(ecrit.deja)} déjà présent(s), "
        f"{ecrit.liens} lien(s)",
        fg=typer.colors.GREEN,
    )
    # Les points tranchés reçoivent une pastille à côté d'eux : sans elle, une
    # piste retenue restait jaune indéfiniment.
    actes = _textes_actes(la_carte)
    if actes:
        marques = carte_miro.marquer_actes(tableau, actes, reunion=identifiant)
        if marques:
            typer.secho(f"  ✓ {len(marques)} point(s) marqué(s) « acté »",
                        fg=typer.colors.GREEN)
    if ecrit.liens_manques:
        # Dit, et non avalé : une carte a été publiée sans un seul trait sans
        # que rien ne le signale.
        typer.secho(
            f"  ⚠ {ecrit.liens_manques} lien(s) n'ont pas pu être tracés",
            fg=typer.colors.YELLOW,
        )


@application.command(name="sources")
def sources_(
    config_fichier: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Les sources extérieures inscrites, et si leur jeton répond.

    Ce qui n'est pas inscrit est inatteignable : l'outil ne découvre aucun
    projet de lui-même, et c'est ce qui borne le risque à ce qui a été listé.
    """
    from greffier.adaptateurs import sources_fichier

    config = Config.charger(config_fichier)
    if sources_fichier.poser_le_gabarit(config.chemins.sources):
        typer.secho(f"Fichier créé : {config.chemins.sources}", fg=typer.colors.GREEN)

    registre = sources_fichier.lire(config.chemins.sources)
    if not registre.sources:
        typer.echo("\nAucune source inscrite. Le fichier dit comment faire :")
        typer.echo(f"  {config.chemins.sources}")
        raise typer.Exit(1)

    typer.echo("")
    for source in registre.sources:
        jeton = sources_fichier.jeton_de(source)
        marque = "✓" if jeton else "✗"
        couleur = typer.colors.GREEN if jeton else typer.colors.YELLOW
        typer.secho(f"  {marque} {source.dire()}", fg=couleur)
        if not jeton:
            typer.echo(f"      jeton introuvable en « {source.jeton} »")
            continue
        try:
            _essayer_la_source(source, jeton)
        except RuntimeError as souci:
            typer.secho(f"      ✗ {souci}", fg=typer.colors.RED)

    ecrivables = [s.nom for s in registre.sources if s.peut_ecrire]
    if ecrivables:
        typer.secho(
            f"\n⚠ {len(ecrivables)} source(s) en écriture : {', '.join(ecrivables)}.\n"
            "  Chaque écriture demande confirmation, mais le jeton est atteignable.",
            fg=typer.colors.YELLOW,
        )
    typer.echo(f"\n  registre  {config.chemins.sources}")


def _essayer_la_source(source: object, jeton: str) -> None:
    """Un appel de lecture, pour dire si l'accès fonctionne vraiment.

    Un registre qui se contente de dire « configuré » ne sert à rien : le
    jeton peut être expiré, sa portée insuffisante, le projet invisible. Mieux
    vaut l'apprendre ici qu'en pleine réunion.
    """
    from greffier.domaine.sources import Genre, Source

    assert isinstance(source, Source)
    if source.genre is Genre.GITLAB:
        from greffier.adaptateurs.gitlab_api import tickets

        trouves = tickets(source, jeton)
        typer.echo(f"      {len(trouves)} ticket(s) ouvert(s) lisible(s)")
        return
    from greffier.adaptateurs.jira_api import demandes

    trouvees = demandes(source, jeton)
    typer.echo(f"      {len(trouvees)} demande(s) lisible(s)")


@application.command(name="niveau")
def niveau_(
    secondes: float = typer.Option(4.0, "--secondes", help="Durée d'écoute"),
    config_fichier: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Écoute, et dit si le niveau suffit à transcrire. **Parle pendant l'écoute.**

    Le contrôle existant mesure le silence, ce qui repère un micro coupé mais ne
    dit rien de la parole. Or c'est la parole qui décide : à -43 dB, mesuré, le
    modèle n'écrit pas moins bien, il invente.
    """
    from greffier.composition import _enregistreur
    from greffier.domaine.niveau import Verdict, dire, juger

    config = Config.charger(config_fichier)
    lecteur = listeur(config)
    materiel = lecteur.lire()
    micro = config.audio.micro or _micro_par_ecoute(config, materiel)
    if not micro:
        typer.secho("Aucun micro utilisable.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    typer.secho(f"\nParle maintenant, {secondes:.0f} secondes — micro « {micro} »",
                fg=typer.colors.BRIGHT_WHITE, bold=True)
    db = _enregistreur(config).essayer(micro, secondes)
    verdict = juger(db)
    couleur = {
        Verdict.BON: typer.colors.GREEN,
        Verdict.FAIBLE: typer.colors.YELLOW,
        Verdict.INSUFFISANT: typer.colors.RED,
        Verdict.MUET: typer.colors.RED,
    }[verdict]
    typer.secho(f"\n{dire(db)}", fg=couleur)
    if verdict in (Verdict.INSUFFISANT, Verdict.MUET):
        raise typer.Exit(1)


@application.command()
def deposer(
    fichiers: list[Path] = typer.Argument(..., help="Fichiers à déposer"),
    faire: bool = typer.Option(
        False, "--faire", help="Exécuter, au lieu de seulement proposer"
    ),
    config_fichier: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Classe des fichiers déposés : réunions, vidéos, contexte.

    Sans « --faire », rien n'est touché : la commande dit ce qu'elle ferait de
    chaque fichier et pourquoi. Une vidéo de deux heures mal classée coûte une
    transcription pour rien, et un document classé en réunion produit un compte
    rendu d'un texte que personne n'a prononcé.
    """
    from greffier.application import deposer as travail
    from greffier.domaine.depot import Destin, proposer, resumer

    config = Config.charger(config_fichier)
    outils = travail.outils_presents()
    propositions = []
    for fichier in fichiers:
        if not fichier.exists():
            typer.secho(f"  ✗ introuvable : {fichier}", fg=typer.colors.RED)
            continue
        taille = fichier.stat().st_size if fichier.is_file() else None
        propositions.append(proposer(fichier, taille, outils))

    if not propositions:
        raise typer.Exit(1)

    typer.echo("")
    for proposition in propositions:
        couleur = (
            typer.colors.GREEN if proposition.faisable
            else (typer.colors.YELLOW if proposition.bloque_par else typer.colors.BRIGHT_BLACK)
        )
        typer.secho(
            f"  {str(proposition.destin):9} {proposition.fichier.name}",
            fg=couleur,
        )
        typer.echo(f"            {proposition.parce_que}")
        if proposition.bloque_par:
            typer.secho(f"            ⚠ {proposition.bloque_par}", fg=typer.colors.YELLOW)
    typer.echo(f"\n  {resumer(propositions)}")

    if not faire:
        typer.echo("\n« greffier deposer --faire » pour le faire.")
        return

    redacteur_document = cartographe(config)
    if any(p.destin is Destin.CONTEXTE and p.faisable for p in propositions):
        from greffier.adaptateurs.redaction_claude import RedacteurClaude
        from greffier.application.deposer import CONSIGNES_DOCUMENT

        if isinstance(redacteur_document, RedacteurClaude):
            redacteur_document.consignes_propres = CONSIGNES_DOCUMENT

    typer.echo("")
    a_traiter: list[Path] = []
    for proposition in propositions:
        fait = travail.executer(
            proposition, config.chemins.enregistrements, redacteur_document
        )
        if fait.souci:
            typer.secho(f"  ✗ {proposition.fichier.name} : {fait.souci}",
                        fg=typer.colors.RED)
            continue
        if fait.produit is not None:
            typer.secho(f"  ✓ {fait.produit.name}", fg=typer.colors.GREEN)
            a_traiter.append(fait.produit)
        for ecriture, sens, genre in fait.appris:
            typer.echo(f"    · {genre:8} {ecriture}"
                       + (f" — {sens}" if sens else ""))
        if fait.appris:
            typer.secho(
                f"  {len(fait.appris)} entrée(s) proposée(s) depuis "
                f"{proposition.fichier.name}", fg=typer.colors.GREEN,
            )
            _proposer_au_contexte(config, fait.appris)

    if a_traiter:
        typer.echo("\nÀ transcrire :")
        for chemin in a_traiter:
            typer.echo(f"  greffier traiter {chemin}")


def _proposer_au_contexte(
    config: Config, appris: tuple[tuple[str, str, str], ...]
) -> None:
    """Demande avant d'écrire dans le contexte, comme partout ailleurs.

    Un document apporte vingt entrées d'un coup : les valider en bloc est le
    seul geste raisonnable, mais il doit rester un geste.
    """
    from greffier.adaptateurs import contexte_fichier

    if not typer.confirm("\n  Ajouter ces entrées au contexte ?", default=True):
        typer.echo("  Rien n'a été ajouté.")
        return
    poses = 0
    for ecriture, sens, genre in appris:
        ajout = (
            contexte_fichier.ajouter_une_personne
            if genre == "personne" else contexte_fichier.ajouter_un_terme
        )
        if ajout(config.chemins.contexte, ecriture, sens):
            poses += 1
    typer.secho(f"  ✓ {poses} ajoutée(s), {len(appris) - poses} déjà connue(s)",
                fg=typer.colors.GREEN)


@application.command()
def recuperer(
    reunion: str = typer.Argument(None, help="Réunion (défaut : celle du dernier fil)"),
    config_fichier: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Reconstruit une réunion depuis le fil du direct, faute de traitement.

    À employer quand une réunion n'apparaît nulle part alors qu'elle a bien eu
    lieu : le fil du direct existe, mais rien ne l'a jamais converti en réunion.
    Le résultat est moins bon qu'un traitement — modèle rapide, voix non
    recollées — et c'est la différence entre approximatif et perdu.
    """
    from greffier.application.recuperer import depuis_le_fil
    from greffier.application.suivre import lire_depuis

    config = Config.charger(config_fichier)
    dossier = config.chemins.direct
    if reunion:
        journal = dossier / f"{reunion}.jsonl"
        identifiant = reunion
    else:
        fils = sorted(dossier.glob("*.jsonl"), key=lambda c: c.stat().st_mtime)
        if not fils:
            typer.secho(f"Aucun fil de direct dans {dossier}.",
                        fg=typer.colors.RED, err=True)
            raise typer.Exit(1)
        journal = fils[-1]
        identifiant = journal.stem
    if not journal.exists():
        typer.secho(f"Aucun fil pour « {identifiant} ».", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    magasin = depot(config)
    if identifiant in magasin.lister():
        typer.secho(
            f"« {identifiant} » est déjà une réunion : « greffier rediger » "
            "reprend son compte rendu.",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(1)

    lignes, _ = lire_depuis(journal, 0)
    audio = config.chemins.enregistrements / f"{identifiant}.wav"
    reconstruite = depuis_le_fil(
        identifiant, lignes, audio if audio.exists() else None
    )
    if not reconstruite.repliques:
        typer.secho("Le fil ne contient aucune parole transcrite.",
                    fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    chemin = magasin.enregistrer(reconstruite)
    mots = sum(len(r.texte.split()) for r in reconstruite.repliques)
    typer.secho(f"✓ {identifiant} reconstruite : {mots} mots, "
                f"{len(reconstruite.tours)} tours", fg=typer.colors.GREEN)
    typer.echo(f"  fichier  {chemin}")
    if reconstruite.noms:
        typer.echo(f"  voix nommées  {', '.join(sorted(reconstruite.noms.values()))}")
    typer.secho(f"\n⚠ {reconstruite.avertissements[0]}", fg=typer.colors.YELLOW)
    if audio.exists():
        typer.echo(f"\nL'enregistrement existe : « greffier traiter {audio} » "
                   "donnera un bien meilleur résultat.")
    else:
        typer.echo("\n« greffier rediger » écrit le compte rendu.")


@application.command()
def sauvegarder(
    restaurer_depuis: str = typer.Option(
        None, "--restaurer", help="Nom de l'archive à remettre en place"
    ),
    ecraser: bool = typer.Option(
        False, "--ecraser", help="Restaurer par-dessus ce qui existe déjà"
    ),
    lister_seulement: bool = typer.Option(
        False, "--lister", help="Montrer les sauvegardes présentes"
    ),
    config_fichier: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Copie les données, sans l'audio. Restaure aussi.

    3 Mo contre 1,1 Go d'enregistrements : c'est ce qui rend une sauvegarde
    possible. Une réunion transcrite reste utilisable sans son audio ; l'inverse
    n'est pas vrai, un enregistrement dont on a perdu la transcription et le
    compte rendu est un fichier que personne ne réécoutera.
    """
    from greffier.application import sauvegarder as travail
    from greffier.emplacements import dossier_config

    config = Config.charger(config_fichier)
    destination = (
        Path(config.sauvegarde.dossier).expanduser()
        if config.sauvegarde.dossier else config.chemins.sauvegardes
    )

    if lister_seulement:
        trouvees = travail.lister(destination)
        if not trouvees:
            typer.echo(f"Aucune sauvegarde dans {destination}.")
            raise typer.Exit(1)
        typer.echo(f"\n{len(trouvees)} sauvegarde(s) dans {destination} :\n")
        for nom, octets, quand in trouvees:
            typer.echo(f"  {quand:%Y-%m-%d %H:%M}  {octets / 1024**2:6.1f} Mo  {nom}")
        return

    if restaurer_depuis:
        archive = destination / restaurer_depuis
        if not archive.exists() and not restaurer_depuis.endswith(".tar.gz"):
            archive = destination / f"{restaurer_depuis}.tar.gz"
        try:
            remis = travail.restaurer(archive, config.chemins.donnees, ecraser)
        except (FileNotFoundError, FileExistsError) as souci:
            typer.secho(f"✗ {souci}", fg=typer.colors.RED, err=True)
            raise typer.Exit(1) from souci
        typer.secho(f"✓ restauré : {', '.join(remis)}", fg=typer.colors.GREEN)
        return

    try:
        faite = travail.faire(
            config.chemins.donnees, dossier_config(), destination,
            gardees=config.sauvegarde.gardees,
        )
    except OSError as souci:
        typer.secho(f"✗ sauvegarde impossible : {souci}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from souci

    typer.secho(
        f"✓ {faite.archive.name} — {faite.fichiers} fichier(s), "
        f"{faite.octets / 1024**2:.1f} Mo",
        fg=typer.colors.GREEN,
    )
    typer.echo(f"  contenu  {', '.join(faite.dossiers)}")
    typer.echo(f"  écrit    {faite.archive.parent}")
    if faite.effacees:
        typer.echo(f"  rotation {len(faite.effacees)} ancienne(s) effacée(s)")
    if faite.sur_le_meme_disque:
        # Le dire à chaque fois : confondre « une copie existe » et « le travail
        # est à l'abri » est la façon habituelle de n'avoir aucune sauvegarde le
        # jour où il en faut une.
        typer.secho(
            "\n⚠ Cette copie est sur le même disque que les données : elle protège\n"
            "  d'un effacement, pas d'une panne de disque. Règle "
            "« sauvegarde.dossier »\n  vers un disque externe ou un espace "
            "synchronisé.",
            fg=typer.colors.YELLOW,
        )


@application.command()
def ranger(
    pour_de_vrai: bool = typer.Option(
        False, "--faire", help="Appliquer, au lieu de seulement dire ce qui se passerait"
    ),
    config_fichier: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Applique la règle de rétention aux enregistrements. Constate d'abord.

    Sans « --faire », rien n'est modifié : la commande dit ce qu'elle
    emporterait. Effacer un enregistrement ne se rattrape pas, et le voir avant
    coûte trois secondes.
    """
    from datetime import UTC, datetime

    from greffier.application import ranger as rangement
    from greffier.application.restituer import archiver as compresser
    from greffier.domaine.retention import Regle

    config = Config.charger(config_fichier)
    magasin = depot(config)
    try:
        regle = Regle(
            compresser_apres=config.retention.compresser_apres_jours,
            effacer_apres=config.retention.effacer_apres_jours,
        )
    except ValueError as souci:
        typer.secho(f"✗ règle de rétention invalide : {souci}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from souci

    maintenant = datetime.now(UTC)
    reunions: list[tuple[str, float, bool]] = []
    for identifiant in magasin.lister():
        try:
            detail = magasin.lire(identifiant)
        except (OSError, ValueError):
            continue
        # L'âge se compte depuis la tenue de la réunion quand on la connaît :
        # retraiter une vieille réunion ne doit pas la rajeunir.
        reference = detail.commencee_le or detail.traitee_le
        jours = (maintenant - reference).total_seconds() / 86400
        reunions.append((identifiant, jours, bool(detail.repliques)))

    faits = rangement.ranger(
        _emplacements(config), regle, reunions, compresser, pour_de_vrai=pour_de_vrai
    )
    if not faits:
        typer.echo("Rien à ranger : tout est déjà dans l'état voulu.")
        return

    for fait in faits:
        if fait.souci:
            typer.secho(f"  ⚠ {fait.identifiant} : {fait.souci}", fg=typer.colors.YELLOW)
            continue
        typer.echo(f"  {fait.geste:<12} {fait.identifiant}  "
                   f"{rangement.lisible(fait.gagne)}")
    total = rangement.lisible(sum(f.gagne for f in faits))
    if pour_de_vrai:
        typer.secho(f"✓ {total} libérés", fg=typer.colors.GREEN)
    else:
        typer.echo(f"\n{total} seraient libérés. « greffier ranger --faire » pour le faire.")


@application.command()
def oublier(
    reunion: str = typer.Argument(None, help="Réunion (défaut : la dernière)"),
    oui: bool = typer.Option(False, "--oui", help="Effacer sans confirmation"),
    config_fichier: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Efface une réunion et tout ce qui va avec, après confirmation.

    L'audio est le seul morceau qu'on ne puisse pas refaire : la transcription
    et le compte rendu se reconstituent depuis lui, l'inverse est faux. La liste
    de ce qui part s'affiche donc avant, avec son poids.
    """
    from greffier.application import ranger

    config = Config.charger(config_fichier)
    identifiant = _reunion_visee(config, reunion)
    ou = _emplacements(config)
    pieces = ranger.pieces_de(ou, identifiant)
    if not pieces:
        typer.secho(f"Rien à effacer pour {identifiant}.", fg=typer.colors.YELLOW)
        raise typer.Exit(1)

    typer.echo(f"\nÀ effacer pour « {identifiant} » :")
    for piece in pieces:
        typer.echo(f"  {ranger.lisible(piece.octets):>8}  {piece.quoi}")
    total = sum(p.octets for p in pieces)
    typer.echo(f"  {'─' * 8}")
    typer.echo(f"  {ranger.lisible(total):>8}  au total\n")

    if not oui and not typer.confirm("Effacer définitivement ?", default=False):
        typer.echo("Rien n'a été effacé.")
        raise typer.Exit(1)

    effacees = ranger.oublier(ou, identifiant)
    typer.secho(
        f"✓ {len(effacees)} fichier(s) effacé(s), "
        f"{ranger.lisible(sum(p.octets for p in effacees))} libérés",
        fg=typer.colors.GREEN,
    )
    reste = ranger.pieces_de(ou, identifiant)
    for piece in reste:
        typer.secho(f"⚠ {piece.chemin} n'a pas pu être effacé", fg=typer.colors.YELLOW)


@application.command()
def revoir(
    reunion: str = typer.Argument(None, help="Réunion (défaut : la dernière)"),
    rediger_aussi: bool = typer.Option(
        True, "--rediger/--sans-rediger",
        help="Réécrire le compte rendu avec les voix revues",
    ),
    config_fichier: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Rejoue le recollage des voix sur une réunion déjà traitée.

    Le recollage décide combien de personnes le compte rendu annonce, et ses
    seuils bougent quand on les mesure. En profiter demandait jusqu'ici de tout
    retranscrire : une heure quarante d'audio pour un calcul qui en prend trois
    minutes, et un compte rendu refait alors que la transcription était bonne.

    Rien n'est réécouté ni retranscrit. Les noms déjà posés suivent les voix
    qu'ils désignaient, et la banque est réinterrogée sur les voix recollées —
    c'est là qu'elle a le plus de matière pour reconnaître.
    """
    from greffier.adaptateurs.empreintes_titanet import ExtracteurTitaNet
    from greffier.application.restituer import revoir_les_voix

    config = Config.charger(config_fichier)
    identifiant = _reunion_visee(config, reunion)
    le_depot = depot(config)
    try:
        gardee = le_depot.lire(identifiant)
    except (OSError, ValueError) as souci:
        typer.secho(f"✗ {souci}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from souci
    if not gardee.audio.exists():
        typer.secho(f"✗ l'enregistrement {gardee.audio} n'est plus là : le "
                    "recollage a besoin du son.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    typer.secho(f"  empreintes     {identifiant}…", fg=typer.colors.BLUE)
    extracteur = ExtracteurTitaNet(
        config.chemins.modeles / "diarisation/nemo_en_titanet_large.onnx")
    avant, apres = revoir_les_voix(
        gardee, extracteur, BanqueFichiers(config.chemins.banque_de_voix))
    le_depot.enregistrer(gardee)
    portantes = len(gardee.participants())
    typer.secho(f"✓ {avant} voix ramenées à {apres}, dont {portantes} au-dessus "
                "de dix secondes", fg=typer.colors.GREEN)
    if gardee.noms:
        typer.echo("  " + ", ".join(f"{v} → {n}" for v, n in sorted(gardee.noms.items())))

    if not rediger_aussi:
        return
    moteur = redacteur(config)
    if moteur is None:
        typer.echo("  Aucun rédacteur : le compte rendu n'est pas réécrit.")
        return
    typer.secho(f"  rédaction      {identifiant}…", fg=typer.colors.BLUE)
    texte = regenerer_compte_rendu(gardee, moteur, config.conversation.information)
    chemin = config.chemins.comptes_rendus / f"{identifiant}.md"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(texte, encoding="utf-8")
    typer.secho(f"✓ {chemin}", fg=typer.colors.GREEN)


@application.command()
def rediger(
    reunion: str = typer.Argument(None, help="Réunion (défaut : la dernière)"),
    config_fichier: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Rédige le compte rendu d'une réunion déjà transcrite.

    La reprise quand le rédacteur a échoué — expiration, quota, réseau coupé.
    Rien n'est réécouté ni retranscrit : le fichier maître porte déjà le texte
    et les voix, seule la rédaction est rejouée. « _regenerer » ne pouvait pas
    servir ici, elle exige un compte rendu déjà écrit ; l'échec est justement
    le cas où il n'y en a pas.
    """
    config = Config.charger(config_fichier)
    identifiant = _reunion_visee(config, reunion)
    moteur = redacteur(config)
    if moteur is None:
        typer.secho(
            "Aucun rédacteur configuré : « compte_rendu.moteur » vaut « aucun ».",
            fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(1)
    try:
        gardee = depot(config).lire(identifiant)
    except (OSError, ValueError) as souci:
        typer.secho(f"✗ {souci}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from souci

    typer.secho(f"  rédaction      {identifiant}…", fg=typer.colors.BLUE)
    try:
        texte = regenerer_compte_rendu(
            gardee, moteur, config.conversation.information
        )
    except (RuntimeError, subprocess.SubprocessError) as souci:
        typer.secho(f"✗ {souci}", fg=typer.colors.RED, err=True)
        typer.echo(
            "La transcription reste gardée : relance « greffier rediger » "
            "quand la cause est levée."
        )
        raise typer.Exit(1) from souci

    chemin = config.chemins.comptes_rendus / f"{identifiant}.md"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(texte, encoding="utf-8")
    typer.secho(f"✓ {chemin}", fg=typer.colors.GREEN)
    typer.echo("« greffier envoyer » pour l'expédier.")


@application.command(name="lire")
def lire_cr(
    reunion: str = typer.Argument(None, help="Réunion (défaut : la dernière)"),
    config_fichier: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Enregistre le compte rendu lu à voix haute, pour l'écouter en voiture."""
    from greffier.application.restituer import lire_a_voix_haute

    config = Config.charger(config_fichier)
    identifiant = _reunion_visee(config, reunion)
    source = config.chemins.comptes_rendus / f"{identifiant}.md"
    if not source.exists():
        typer.secho(f"Aucun compte rendu pour {identifiant}.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    sortie = config.chemins.donnees / "lectures" / f"{identifiant}.m4a"
    try:
        produit = lire_a_voix_haute(source.read_text(encoding="utf-8"), sortie)
    except (RuntimeError, subprocess.CalledProcessError) as souci:
        typer.secho(f"✗ {souci}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from souci
    typer.secho(f"✓ {produit}", fg=typer.colors.GREEN)


@application.command()
def tickets(
    reunion: str = typer.Argument(None, help="Réunion (défaut : la dernière)"),
    config_fichier: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Propose les tickets à créer à partir du compte rendu.

    Proposés, **pas créés** : un ticket ouvert à tort dans un outil partagé coûte
    plus cher à retirer qu'à ne pas créer. La relecture est le garde-fou.
    """
    from greffier.application.tickets import proposer

    config = Config.charger(config_fichier)
    identifiant = _reunion_visee(config, reunion)
    source = config.chemins.comptes_rendus / f"{identifiant}.md"
    if not source.exists():
        typer.secho(f"Aucun compte rendu pour {identifiant}.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    moteur = redacteur(config)
    if moteur is None:
        typer.secho("Aucun rédacteur configuré. « greffier configurer ».",
                    fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    proposition = proposer(source.read_text(encoding="utf-8"), moteur)
    sortie = config.chemins.donnees / "tickets" / f"{identifiant}.md"
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(proposition.en_markdown(identifiant), encoding="utf-8")

    for ticket in proposition.tickets:
        details = " · ".join(x for x in (ticket.assigne, ticket.echeance) if x)
        typer.secho(f"  • {ticket.titre}", fg=typer.colors.GREEN)
        if details:
            typer.echo(f"    {details}")
    if not proposition.tickets:
        typer.echo("Aucune action décidée dans ce compte rendu.")
    typer.echo(f"\n{sortie}")


@application.command()
def archiver(
    tout: bool = typer.Option(False, "--tout", help="Tous les enregistrements traités"),
    config_fichier: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Compresse les enregistrements déjà transcrits.

    Un WAV de réunion pèse 115 Mo par heure ; en Opus, une dizaine. La
    transcription étant faite, l'audio ne sert plus qu'à réécouter un passage.
    """
    from greffier.application.restituer import archiver as compresser

    config = Config.charger(config_fichier)
    magasin = depot(config)
    identifiants = magasin.lister() if tout else magasin.lister()[:1]
    gagne = 0
    for identifiant in identifiants:
        detail = magasin.lire(identifiant)
        if not detail.audio.exists() or detail.audio.suffix == ".opus":
            continue
        avant = detail.audio.stat().st_size
        produit = compresser(detail.audio)
        gagne += avant - produit.stat().st_size
        typer.echo(f"  {identifiant} → {produit.name}")
    if gagne:
        typer.secho(f"✓ {gagne / 1024**2:.0f} Mo libérés", fg=typer.colors.GREEN)
    else:
        typer.echo("Rien à compresser.")


@application.command()
def envoyer(
    reunion: str = typer.Argument(None, help="Réunion (défaut : la dernière)"),
    destinataire: str = typer.Option(None, "--a", help="À qui envoyer ce compte rendu"),
    sans_demander: bool = typer.Option(False, "--oui", help="Envoyer sans confirmation"),
    avec_transcription: bool = typer.Option(
        False, "--avec-transcription", help="Joindre la transcription intégrale"
    ),
    config_fichier: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Envoie par courriel un compte rendu déjà rédigé, après relecture.

    Rien ne part avant que tu aies vu à qui, avec quel objet et quelles pièces.
    Un compte rendu de réunion cite des personnes et des décisions : l'expédier
    au mauvais destinataire ne se rattrape pas, et un envoi silencieux au fil du
    traitement ne laisse aucune occasion de relire.
    """
    from greffier.composition import _expediteur

    config = Config.charger(config_fichier)
    identifiant = _reunion_visee(config, reunion)
    source = config.chemins.comptes_rendus / f"{identifiant}.md"
    if not source.exists():
        typer.secho(f"Aucun compte rendu pour {identifiant}.", fg=typer.colors.RED, err=True)
        typer.echo("« greffier traiter » d'abord, ou « greffier reunions » pour la liste.")
        raise typer.Exit(1)

    compte_rendu = source.read_text(encoding="utf-8")
    cible = destinataire or config.compte_rendu.destinataire
    if not cible:
        cible = typer.prompt("À qui envoyer ce compte rendu ?").strip()
    if "@" not in cible:
        typer.secho(f"« {cible} » n'est pas une adresse.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    expediteur = _expediteur(config, exiger_destinataire=False)
    if expediteur is None:
        typer.secho("Aucun moyen d'envoi. « greffier configurer ».",
                    fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    objet = titre(compte_rendu, f"Compte rendu de réunion — {identifiant}")
    # Le corps du message est déjà le compte rendu : rien à joindre par défaut.
    # La transcription intégrale fait circuler les propos de chacun mot à mot,
    # ce qui ne se décide pas à la place du lecteur.
    transcription = config.chemins.transcriptions / f"{identifiant}.txt"
    pieces = [transcription] if avec_transcription and transcription.exists() else []

    typer.echo()
    typer.secho("  À        ", nl=False, bold=True)
    typer.secho(cible, fg=typer.colors.CYAN)
    typer.secho("  Objet    ", nl=False, bold=True)
    typer.echo(objet)
    typer.secho("  Par      ", nl=False, bold=True)
    typer.echo(type(expediteur).__name__.replace("Expediteur", ""))
    typer.secho("  Pièces   ", nl=False, bold=True)
    typer.echo(", ".join(p.name for p in pieces) or "aucune (le message porte le compte rendu)")
    typer.secho("  Format   ", nl=False, bold=True)
    typer.echo("HTML mis en forme, Markdown en repli")

    # Les intertitres suffisent à reconnaître un compte rendu : inutile de
    # dérouler trois pages dans un terminal pour vérifier qu'on tient le bon.
    sections = [x.strip().lstrip("#").strip() for x in compte_rendu.splitlines()
                if x.strip().startswith("## ")]
    if sections:
        typer.secho("  Sections ", nl=False, bold=True)
        typer.echo(" · ".join(sections))
    typer.echo()

    if not sans_demander and not typer.confirm("Envoyer ?", default=False):
        typer.echo("Rien n'a été envoyé.")
        raise typer.Exit(0)

    try:
        expediteur.envoyer(cible, objet, compte_rendu, pieces)
    except Exception as echec:
        typer.secho(f"✗ Envoi impossible : {echec}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from echec
    typer.secho(f"✓ Envoyé à {cible}", fg=typer.colors.GREEN)


@application.command(hidden=True)
def veiller(
    config_fichier: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Surveille le matériel audio pendant l'enregistrement, et s'adapte.

    Lancée seule par « greffier enregistrer », détachée : rien d'autre de
    Greffier ne tourne pendant une réunion, donc personne ne verrait un casque
    apparaître. Elle meurt avec l'enregistrement.

    Utile à la main pour observer ce qu'elle décide, d'où la commande.
    """
    from greffier.application.veiller_materiel import VeilleMateriel
    from greffier.domaine.peripheriques import Veille, micro_conseille

    config = Config.charger(config_fichier)
    if platform.system() != "Darwin":
        typer.echo("Rien à surveiller ici : aucun périphérique agrégé à reconstruire.")
        return

    lecteur = listeur(config)
    machine = enregistrement(config)
    source = Path(__file__).resolve().parent.parent.parent / "macos/creer-peripheriques.swift"

    def reconstruire(micro: str) -> bool:
        if not micro or not source.exists():
            return False
        fait = subprocess.run(
            ["swift", str(source), "--mic", micro, "--casque", micro],
            capture_output=True, text=True, check=False,
        )
        return fait.returncode == 0

    def prevenir(message: str) -> None:
        NotificateurSysteme().notifier("Greffier", message)

    depart = lecteur.lire()
    voulu = config.audio.micro or micro_conseille(depart, config.audio.micro or "")
    def taille_captee() -> int | None:
        """Les octets écrits dans le morceau en cours, pour savoir si ça avance.

        Le dernier morceau et non le premier : un changement de matériel en
        rouvre un, et c'est celui-là que ffmpeg alimente.
        """
        try:
            etat_courant = machine.lire()
        except (OSError, ValueError):
            return None
        morceaux = etat_courant.morceaux or ([etat_courant.audio] if etat_courant.audio else [])
        if not morceaux:
            return None
        try:
            return morceaux[-1].stat().st_size
        except OSError:
            return None

    def niveau_capte() -> float | None:
        """Le niveau du micro sur ce qui vient d'être écrit.

        Lu dans le fichier plutôt qu'en ouvrant le micro : celui-ci est déjà
        pris par la capture, et l'ouvrir une seconde fois pour le mesurer est
        le meilleur moyen de perdre les deux.
        """
        from greffier.adaptateurs.niveaux_direct import relever

        try:
            etat_courant = machine.lire()
        except (OSError, ValueError):
            return None
        morceaux = etat_courant.morceaux or (
            [etat_courant.audio] if etat_courant.audio else []
        )
        if not morceaux:
            return None
        releve = relever(morceaux[-1])
        return None if releve is None else releve.micro_db

    veilleuse = VeilleMateriel(
        machine=machine,
        listeur=lecteur,
        veille=Veille(micro_voulu=voulu, agrege=config.audio.entree),
        reconstruire=reconstruire,
        prevenir=prevenir,
        taille_captee=taille_captee,
        niveau_capte=niveau_capte,
    )
    tours = veilleuse.boucler()
    typer.echo(f"Veille terminée après {tours} tours.")


@application.command()
def fenetre(
    config_fichier: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Ouvre la fenêtre de Greffier : enregistrer, nommer les voix, envoyer.

    C'est l'interface complète, et la même sur les trois systèmes. Elle remplace
    l'icône de barre de menus, qui ne montrait qu'une partie de l'état et
    demandait un comportement différent par système.
    """
    from greffier.interface.demarrage import disponible

    ouvrable, message = disponible()
    if not ouvrable:
        typer.secho(f"✗ {message}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    from greffier.interface.fenetre import ouvrir

    ouvrir(Config.charger(config_fichier))
