"""Ligne de commande de Greffier.

    greffier traiter <audio>     transcrit, identifie les voix, rédige
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
from pathlib import Path

import typer

from greffier.adaptateurs.banque_fichiers import BanqueFichiers
from greffier.adaptateurs.notifications import NotificateurSysteme
from greffier.application.nommer import VoixANommer, extraire_audio, voix_a_nommer
from greffier.application.restituer import regenerer_compte_rendu
from greffier.application.traiter import ChaineInterrompue
from greffier.composition import (
    assembler,
    depot,
    enregistrement,
    listeur,
    nommage,
    redacteur,
    suivi,
    transcripteur_leger,
)
from greffier.config import Config
from greffier.emplacements import dossier_config

application = typer.Typer(
    add_completion=False, help="Enregistre, transcrit et résume tes réunions."
)


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


def _refuser_pendant_une_reunion(config: Config, quand_meme: bool) -> None:
    """Refuse de traiter tant qu'une réunion s'enregistre.

    Le fichier d'état est **unique** : c'est par lui que la fenêtre suit la
    réunion en cours. Un traitement lancé en parallèle y publie ses propres
    phases, jusqu'à « terminé », et la fenêtre en conclut que la réunion est
    finie — le fil du direct s'arrête, les processus d'écoute se retirent, alors
    que la capture continue. Constaté en réunion réelle, provoqué par un
    traitement lancé à côté : la réunion a paru s'arrêter d'elle-même.

    Traiter un enregistrement pendant qu'un autre se capte reste possible avec
    « --quand-meme », pour qui sait ce qu'il fait.
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
    typer.echo("Termine-la d'abord, ou relance avec « --quand-meme ».")
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
        resultat = chaine.executer(
            audio,
            envoyer=not sans_envoi and bool(config.compte_rendu.destinataire),
            evenements_materiel=evenements,
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
    chemin.write_text(regenerer_compte_rendu(reunion, moteur), encoding="utf-8")
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
    from greffier import assistant, diagnostic

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
    from greffier import diagnostic as verificateur

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
    from greffier.domaine.peripheriques import candidats_a_ecouter, choisir_par_ecoute

    candidats = candidats_a_ecouter(materiel, config.audio.micro)  # type: ignore[arg-type]
    if not candidats:
        return ""
    enregistreur = _enregistreur(config)
    essais = {nom: enregistreur.essayer(nom) for nom in candidats}
    choix = choisir_par_ecoute(essais)
    if choix is None:
        return ""
    if choix.tous_muets:
        typer.secho(
            f"⚠ Aucun micro ne capte : le meilleur, « {choix.nom} », rend "
            f"{choix.niveau_db:.0f} dB. Vérifie le bouton de sourdine de ton "
            "casque, puis l'autorisation micro dans Réglages Système.",
            fg=typer.colors.YELLOW,
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

    journal = config.chemins.donnees / "propositions" / f"{etat.identifiant}.jsonl"
    transcripteur = None if sans_transcription else transcripteur_leger(config)
    le_suivi = suivi(config, etat.identifiant) if config.direct.actif else None
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
    journal = config.chemins.donnees / "propositions" / f"{identifiant}.jsonl"
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
    from greffier.adaptateurs import gabarit_courriel
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

    objet = gabarit_courriel.sujet(compte_rendu, f"Compte rendu de réunion — {identifiant}")
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
    veilleuse = VeilleMateriel(
        machine=machine,
        listeur=lecteur,
        veille=Veille(micro_voulu=voulu, agrege=config.audio.entree),
        reconstruire=reconstruire,
        prevenir=prevenir,
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
