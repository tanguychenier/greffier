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

from greffier.adapters.configuration import Config
from greffier.adapters.notifications import NotificateurSysteme
from greffier.adapters.voice_bank_files import BanqueFichiers
from greffier.application import tidy as ranger_module
from greffier.application.name_voice import VoixANommer, extract_audio, voices_to_name
from greffier.application.process import ChainStopped
from greffier.application.render import regenerate_minutes
from greffier.domain.minutes import title
from greffier.locations import config_folder
from greffier.wiring import (
    assistant_of,
    assistant_voice,
    cartographe,
    context,
    follower,
    light_transcriber,
    lister,
    naming,
    recording,
    store,
    wire_up,
    writer,
)

application = typer.Typer(
    add_completion=False, help="Enregistre, transcrit et résume tes réunions."
)

def _resume_the_thread(config: Config, identifier: str, the_follower: Any) -> float:
    """Rejoue le fil déjà publié, et dit jusqu'où il va.

    Deux effets, tous deux nécessaires pour qu'une relance en cours de réunion
    ne se voie pas : le `Fil` retrouve ses voix et ses noms, et la veille sait
    à quelle seconde reprendre la transcription.

    Rend 0 quand il n'y a rien à reprendre, ce qui est le cas normal — une
    réunion qui commence.
    """
    from greffier.application.follow import files, read_from, replay

    log, _ = files(config.paths.live, identifier)
    if not log.exists():
        return 0.0
    try:
        lines, _ = read_from(log)
    except OSError:
        return 0.0
    if not lines:
        return 0.0
    thread = replay(lines, the_follower.thread if the_follower is not None else None)
    if not thread.turns:
        return 0.0
    jusqu_ou = max(t.span.end for t in thread.turns)
    typer.echo(f"  reprise          : {len(thread.turns)} tours déjà publiés, "
               f"transcription reprise à {jusqu_ou / 60:.0f} min")
    return jusqu_ou

def _reread_the_buttons() -> tuple[bool, bool]:
    """Où en sont les deux boutons de l'onglet En direct : la voix, l'initiative.

    Relus à chaque tranche : la fenêtre et la veille sont deux processus, et le
    seul canal entre eux est le fichier de configuration. Un réglage que la
    veille ne lit qu'à son démarrage est un bouton sans effet — et c'est ce
    qu'était l'initiative.

    L'assistant participe **toujours** : il écoute, prend des notes, pose ses
    questions par écrit. Ce qui se règle, c'est s'il se fait entendre, et s'il
    peut parler sans qu'on l'ait appelé. `actif` n'est plus consulté : ne pas
    l'avoir retiré en même temps que son bouton a coûté une réunion, où le
    fichier gardait `actif = false` sans que rien ne puisse le remettre à vrai.
    """
    reglages = Config().assistant
    return reglages.voice != "aucun", reglages.initiative

def _live_material(
    config: Config, identifier: str, the_follower: Any
) -> Callable[[], str]:
    """Ce que l'assistant a sous les yeux : le fil, et les documents fournis.

    Relue à chaque appel plutôt que figée au démarrage : c'est en séance qu'on
    dépose un document, et il doit servir à la question qui suit, pas à la
    réunion d'après.
    """
    from greffier.adapters import attachments_file

    def material() -> str:
        thread = str(the_follower.thread.rendered())
        try:
            documents = attachments_file.material(config.paths.pieces, identifier)
        except OSError:
            documents = ""
        if not documents:
            return thread
        return (f"{thread}\n\n--- Documents fournis pour cette réunion ---\n"
                f"{documents}")

    return material

def _namer(
    the_follower: Any, config: Config, identifier: str
) -> Callable[[str, str], bool]:
    """Donne à l'assistant le pouvoir de poser un nom sur une voix du fil.

    Sans lui, demander « qui vient de parler » n'est qu'une politesse : la
    réponse s'affiche et se perd. Avec lui, elle nomme la voix, entre en banque
    et sert le compte rendu — c'est ce qui justifie d'avoir interrompu.
    """
    from greffier.application.follow import ask, files

    _, requests = files(config.paths.live, identifier)

    def name_voice(voice: str, first_name: str) -> bool:
        turn = next(
            (t for t in reversed(the_follower.thread.turns) if t.voice == voice), None)
        if turn is None:
            return False
        try:
            the_follower.thread.correct(turn.number, first_name, whole_voice=True)
            ask(requests, turn.number, first_name, whole_voice=True)
        except (KeyError, ValueError, OSError):
            return False
        return True

    return name_voice

def _reunion_visee(config: Config, demandee: str | None) -> str:
    """La réunion nommée, ou la dernière traitée.

    Sortir ici plutôt que de laisser un « None » se propager : toutes les
    commandes qui travaillent sur une réunion ont besoin du même message quand
    il n'y en a aucune.
    """
    if demandee:
        return demandee
    connues = store(config).lister()
    if not connues:
        typer.secho("Aucune réunion traitée. « greffier traiter <audio> » pour commencer.",
                    fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    return connues[0]

def _hours_of(config: Config, audio: Path) -> tuple[datetime | None, datetime | None]:
    """Les heures d'horloge de cette réunion, si l'état les a retenues.

    Vérifie que l'état parle bien de **cet** enregistrement : traiter un vieux
    fichier audio ne doit pas lui coller les heures de la dernière réunion. Sans
    correspondance, le rédacteur retombe sur l'horodatage de l'identifiant.
    """
    try:
        state = recording(config).read()
    except (OSError, ValueError):
        return (None, None)
    if state.identifier != audio.stem:
        return (None, None)
    return (state.start, state.terminee_le)

def _locations(config: Config) -> ranger_module.Emplacements:
    """Où vivent les morceaux d'une réunion, d'après la configuration."""
    return ranger_module.Emplacements(
        meetings=config.paths.data / "reunions",
        recordings=config.paths.recordings,
        transcripts=config.paths.transcripts,
        minutes_folder=config.paths.minutes_folder,
        live=config.paths.live,
        propositions=config.paths.propositions,
        questions=config.paths.questions,
        conversations=config.paths.conversations,
        pieces=config.paths.pieces,
    )

def _refuse_during_a_meeting(config: Config, quand_meme: bool) -> None:
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
    from greffier.domain.models import Phase
    from greffier.wiring import recording

    try:
        state = recording(config).read()
    except (OSError, ValueError):
        return
    if state.phase not in (Phase.RECORDING, Phase.PAUSE):
        return
    typer.secho(
        f"Une réunion est en cours ({state.identifier}) : traiter maintenant "
        "arrêterait son affichage en direct.",
        fg=typer.colors.YELLOW,
    )
    typer.echo("Termine-la d'abord, ou relance avec « --quand-meme » : le "
               "traitement n'arrêtera plus la capture, mais il lui prendra du "
               "processeur.")
    raise typer.Exit(1)

@application.command("traiter")
def process(
    audio: Path = typer.Argument(..., exists=True, readable=True, help="Enregistrement à traiter"),
    without_sending: bool = typer.Option(
        False, "--sans-envoi", help="Ne pas envoyer, même si un destinataire est configuré"
    ),
    sans_cr: bool = typer.Option(False, "--sans-compte-rendu", help="S'arrêter après les voix"),
    events: list[str] = typer.Option(
        None, "--evenement", hidden=True,
        help="Constat de la veille sur le matériel, répétable",
    ),
    config_file: Path = typer.Option(None, "--config", help="Fichier de configuration"),
    quand_meme: bool = typer.Option(
        False, "--quand-meme",
        help="Traiter même si une réunion est en cours d'enregistrement",
    ),
) -> None:
    """Transcrit un enregistrement, identifie qui parle, rédige le compte rendu."""
    config = Config.load(config_file)
    _refuse_during_a_meeting(config, quand_meme)
    chaine = wire_up(config)
    chaine.log = recording(config).pour(audio.stem)
    if sans_cr:
        chaine.writer = None

    publisher = chaine.log

    def progress(phase: str, message: str = "") -> None:
        typer.secho(f"  {phase:<14} {message}", fg=typer.colors.BLUE)
        if publisher is not None:
            with contextlib.suppress(OSError, ValueError):
                publisher.publish(phase, message)

    chaine.log = type("Journal", (), {"publish": staticmethod(progress)})()

    try:
        commencee_le, terminee_le = _hours_of(config, audio)
        outcome = chaine.run_chain(
            audio,
            send=not without_sending and bool(config.minutes.recipient),
            hardware_events=events,
            commencee_le=commencee_le,
            terminee_le=terminee_le,
        )
    except ChainStopped as arret:
        typer.secho(f"✗ {arret.because}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from arret

    for warning in outcome.warnings:
        typer.secho(f"⚠ {warning}", fg=typer.colors.YELLOW)

    significatives = outcome.significant_voices()
    for voice, duration in outcome.speaking_time().items():
        deja_montree = voice in outcome.names or voice in outcome.propositions
        if deja_montree and voice not in significatives:
            significatives[voice] = duration
    fragments = len(outcome.speaking_time()) - len(significatives)
    resume = f"\n{outcome.words} mots · {len(significatives)} voix"
    if fragments:
        resume += f" ({fragments} fragments trop courts, ignorés)"
    typer.echo(resume)

    total = sum(significatives.values()) or 1
    for voice, duration in significatives.items():
        part = f"{duration / 60:4.1f} min ({duration / total * 100:4.1f} %)"
        if voice in outcome.names:
            typer.secho(f"  {part}  {outcome.names[voice]}", fg=typer.colors.GREEN)
        elif voice in outcome.propositions:
            typer.secho(f"  {part}  ≈ {outcome.propositions[voice]} (à confirmer)",
                        fg=typer.colors.YELLOW)
        else:
            typer.echo(f"  {part}  Personne {voice}")

    if outcome.transcript_written:
        typer.echo(f"\nTranscription : {outcome.transcript_written}")
    if outcome.fichier_maitre:
        typer.echo(f"Fichier maître: {outcome.fichier_maitre}")
    manque_des_noms = outcome.propositions or any(
        v not in outcome.names for v in significatives
    )
    if manque_des_noms and not _ask_for_names(config, audio.stem):
        typer.echo(f"\nPour nommer les voix : greffier voix {audio.stem}")

    if outcome.compte_rendu_ecrit:
        typer.echo(f"Compte rendu  : {outcome.compte_rendu_ecrit}")
    if outcome.envoye:
        typer.secho("Envoyé par mail.", fg=typer.colors.GREEN)

def _ask_for_names(config: Config, identifier: str) -> bool:
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
        detail = store(config).read(identifier)
    except (OSError, ValueError, KeyError):
        return False
    restantes = [v for v in voices_to_name(detail) if not v.name]
    if not restantes:
        return False

    typer.echo()
    combien = "une voix" if len(restantes) == 1 else f"{len(restantes)} voix"
    typer.secho(f"{combien} sans nom. Les nommer maintenant les fait entrer en "
                "banque, et elles seront reconnues seules ensuite.",
                fg=typer.colors.YELLOW)
    if not typer.confirm("Les nommer ?", default=True):
        return False

    magasin = naming(config)
    nommees = 0
    for candidate in restantes:
        part = f"{candidate.duration / 60:.1f} min ({candidate.part * 100:.0f} %)"
        typer.echo()
        typer.secho(f"  voix {candidate.voice} — {part}", bold=True)
        if candidate.proposition:
            typer.secho(f"  entendu dans la réunion : {candidate.proposition}",
                        fg=typer.colors.CYAN)
        if candidate.extrait:
            typer.echo(f"  extrait : {candidate.extrait.start:.0f}s → "
                       f"{candidate.extrait.end:.0f}s")
            if typer.confirm("  écouter ?", default=False):
                _listen(config, identifier, candidate)
        propose = candidate.proposition or ""
        name = typer.prompt("  nom (Entrée pour passer)", default=propose,
                           show_default=bool(propose)).strip()
        if not name:
            continue
        try:
            magasin.name_voice(identifier, candidate.voice, name)
        except (RuntimeError, ValueError, OSError) as trouble:
            typer.secho(f"  ✗ {trouble}", fg=typer.colors.RED, err=True)
            continue
        typer.secho(f"  ✓ {name}, empreinte en banque", fg=typer.colors.GREEN)
        nommees += 1

    if nommees:
        typer.echo()
        typer.secho(f"{nommees} voix en banque.", fg=typer.colors.GREEN)
        _regenerate(config, identifier)
    return True

def _listen(config: Config, identifier: str, candidate: VoixANommer) -> None:
    """Joue l'extrait d'une voix, quand le système sait le faire."""
    player = shutil.which("afplay") or shutil.which("aplay") or shutil.which("ffplay")
    if not player:
        typer.echo("  (aucun lecteur audio disponible)")
        return
    if candidate.extrait is None:
        typer.echo("  (aucun extrait exploitable pour cette voix)")
        return
    try:
        detail = store(config).read(identifier)
        output = config.paths.data / "extraits" / f"{identifier}-{candidate.voice}.wav"
        extrait = extract_audio(detail.audio, candidate.extrait, output)
    except (RuntimeError, OSError, ValueError) as trouble:
        typer.secho(f"  ✗ extrait indisponible : {trouble}", fg=typer.colors.RED, err=True)
        return
    arguments = [player, str(extrait)]
    if player.endswith("ffplay"):
        arguments = [player, "-nodisp", "-autoexit", "-loglevel", "error", str(extrait)]
    subprocess.run(arguments, check=False)

def _regenerate(config: Config, identifier: str) -> bool:
    """Rejoue la rédaction si un compte rendu existait déjà pour cette réunion.

    Nommer une voix ne change ni la segmentation ni la transcription : pas
    besoin de relancer tout le traitement pour que le compte rendu porte les
    bonnes étiquettes.
    """
    path = config.paths.minutes_folder / f"{identifier}.md"
    if not path.exists():
        return False
    engine = writer(config)
    if engine is None:
        return False
    meeting = store(config).read(identifier)
    path.write_text(
        regenerate_minutes(meeting, engine, config.conversation.disclosure),
        encoding="utf-8",
    )
    typer.secho(f"Compte rendu régénéré : {path}", fg=typer.colors.GREEN)
    return True

@application.command("verifier")
def check(
    config_file: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Dit ce qui est prêt et ce qui manque, sans rien traiter."""
    config = Config.load(config_file)
    typer.echo(f"configuration : {config_file or config_folder() / 'config.toml'}")
    typer.echo(f"modèles       : {config.paths.models}")
    typer.echo(f"transcription : {config.transcription.engine} ({config.transcription.language})")
    typer.echo(f"compte rendu  : {config.minutes.engine} {config.minutes.model}")
    try:
        wire_up(config)
    except (FileNotFoundError, RuntimeError, ImportError) as manque:
        typer.secho(f"✗ {manque}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from manque
    typer.secho("✓ chaîne assemblée, tout est en place", fg=typer.colors.GREEN)

if __name__ == "__main__":
    application()

@application.command("configurer")
def configure(
    file: Path = typer.Option(None, "--fichier", help="Où écrire la configuration"),
) -> None:
    """Assistant de première configuration : questionne, installe, vérifie.

    À lancer au premier usage, et à relancer quand quelque chose change — de
    machine, de casque, d'adresse mail.
    """
    from greffier.adapters import assistant_terminal as assistant
    from greffier.adapters import system_diagnostic as diagnostic

    def choose(question: str, options: list[tuple[str, str]], defaut: int) -> str:
        typer.echo(f"\n{question} :")
        for number, (_, label_text) in enumerate(options, 1):
            marque = "→" if number - 1 == defaut else " "
            typer.echo(f"  {marque} {number}. {label_text}")
        while True:
            entry = typer.prompt("Numéro", default=str(defaut + 1))
            if entry.isdigit() and 1 <= int(entry) <= len(options):
                return options[int(entry) - 1][0]
            typer.secho("Choisis un numéro de la liste.", fg=typer.colors.YELLOW)

    dialogue = assistant.Dialogue(
        ask=lambda question, defaut: typer.prompt(question, default=defaut),
        confirmer=lambda question, defaut: typer.confirm(question, default=defaut),
        show=typer.echo,
        choose=choose,
    )

    typer.secho("Configuration de Greffier\n", fg=typer.colors.BRIGHT_WHITE, bold=True)
    state = diagnostic.examine()
    answers = assistant.run_chain(dialogue, state)
    target = assistant.write(answers, file)

    typer.secho(f"\n✓ Configuration écrite : {target}", fg=typer.colors.GREEN)
    if answers.installations:
        typer.echo(f"  installés : {', '.join(answers.installations)}")
    if answers.to_do:
        typer.secho("\nIl te reste à :", fg=typer.colors.YELLOW)
        for action in answers.to_do:
            typer.echo(f"  • {action}")
    typer.echo("\n« greffier diagnostic » pour vérifier, « greffier enregistrer » pour commencer.")

@application.command(name="diagnostic")
def diagnostic_(
    config_file: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Constate ce qui est en place et ce qui manque, sans rien modifier."""
    from greffier.adapters import system_diagnostic as verificateur

    state = verificateur.examine()
    recorder = state.recorder
    typer.echo(
        f"{recorder.system} {recorder.architecture} · {recorder.memory_gb:.0f} Go · "
        f"calcul {recorder.speedup}\n"
    )
    for constat in state.constats:
        if constat.present:
            typer.secho(f"  ✓ {constat.name:<38} {constat.detail}", fg=typer.colors.GREEN)
        else:
            colour = typer.colors.RED if constat.bloquant else typer.colors.YELLOW
            typer.secho(f"  ✗ {constat.name:<38} {constat.detail}", fg=colour)
            if constat.remede:
                typer.echo(f"      → {constat.remede}")
    if not state.ready:
        typer.secho("\nIl manque l'essentiel. « greffier configurer » t'accompagne.",
                    fg=typer.colors.RED)
        raise typer.Exit(1)
    typer.secho("\nTout est en place.", fg=typer.colors.GREEN)

@application.command("peripheriques")
def devices(
    lister: bool = typer.Option(False, "--lister", help="Montrer les périphériques disponibles"),
    mic: str = typer.Option(None, "--micro", help="Micro à intégrer au périphérique agrégé"),
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
    if mic:
        arguments += ["--mic", mic]
    if casque:
        arguments += ["--casque", casque]
    raise typer.Exit(subprocess.run(arguments, check=False).returncode)

@application.command("enregistrer")
def record(
    name: str = typer.Argument("reunion", help="Sujet de la réunion"),
    config_file: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Démarre l'enregistrement. « greffier arreter » quand la réunion est finie.

    Le périphérique de capture est reconstruit autour du micro réellement
    branché : un casque habituel absent ne doit pas faire perdre la réunion.
    Une veille est ensuite lancée pour suivre le matériel pendant la séance.
    """
    config = Config.load(config_file)
    precedente = _prepare_capture(config)
    try:
        state = recording(config).start_recording(name, sortie_precedente=precedente)
    except (RuntimeError, FileNotFoundError) as trouble:
        typer.secho(f"✗ {trouble}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from trouble
    typer.secho(f"● Enregistrement de « {state.name} »", fg=typer.colors.RED)
    typer.echo(f"  {state.audio}")
    if _lancer_veille(config, config_file):
        typer.echo("  Le matériel est surveillé : branche ou débranche ton casque sans crainte.")
    if _lancer_direct(config, config_file):
        typer.echo("  Ce qui se dit s'affiche dans la fenêtre, et s'y corrige.")
    typer.echo("  « greffier arreter » pour arrêter et traiter.")

def _devices_swift() -> Path | None:
    source = Path(__file__).resolve().parent.parent.parent / "macos/creer-peripheriques.swift"
    return source if source.exists() else None

def _swift(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Appelle l'utilitaire CoreAudio du dépôt."""
    source = _devices_swift()
    if source is None:
        return subprocess.CompletedProcess([], 1, "", "utilitaire absent")
    return subprocess.run(
        ["swift", str(source), *arguments], capture_output=True, text=True, check=False
    )

_GAIN_MINIMAL = 0.85

def _prepare_capture(config: Config) -> str:
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
    if platform.system() != "Darwin" or _devices_swift() is None:
        return ""

    materiel = lister(config).read()
    if not materiel.devices:
        return ""

    mic = _mic_by_listening(config, materiel)
    if mic and mic != config.audio.mic:
        if _swift("--mic", mic, "--casque", _listening_output(materiel)).returncode == 0:
            typer.secho(f"  micro : {mic}", fg=typer.colors.CYAN)
        else:
            typer.secho(f"⚠ « {mic} » n'a pas pu être installé comme micro.",
                        fg=typer.colors.YELLOW)

    if mic:
        _raise_the_gain(mic)

    precedente = _swift("--get-output").stdout.strip()
    if precedente and precedente != config.audio.output:
        if _swift("--set-output", config.audio.output).returncode == 0:
            typer.secho(f"  sortie : {config.audio.output} "
                        f"(au lieu de {precedente})", fg=typer.colors.CYAN)
        else:
            typer.secho(
                f"⚠ La sortie système est restée sur « {precedente} ». Le son des "
                "autres participants risque de ne pas être enregistré.",
                fg=typer.colors.YELLOW,
            )
            return ""
    return precedente

def _listening_output(materiel: object) -> str:
    """Par où la personne écoute la réunion, à dupliquer vers la boucle.

    Un casque d'abord : c'est là qu'on écoute quand il est branché, et cela évite
    que le micro réentende les enceintes. Les haut-parleurs sinon.
    """
    sorties = [p for p in getattr(materiel, "peripheriques", ()) if p.sorties > 0]
    utiles = [
        p.name for p in sorties
        if "blackhole" not in p.name.lower() and not p.uid.startswith("com.reunions.")
    ]
    if not utiles:
        return "BlackHole 2ch"
    externes = [name for name in utiles if "macbook" not in name.lower()]
    return str((externes or utiles)[0])

def _mic_by_listening(config: Config, materiel: object) -> str:
    """Écoute les micros disponibles et retient celui qui capte le mieux.

    Un micro peut être branché, reconnu, réglé au maximum, et muet : les casques
    USB ont un bouton de sourdine sur leur boîtier. Mesuré sur un poste réel, un
    Jabra rendait -78 dB quand le micro intégré rendait -58 dB dans le même
    silence. Sans cette écoute, Greffier retenait le casque, enregistrait une
    heure de silence, puis accusait l'autorisation micro.
    """
    from greffier.domain.devices import (
        candidates_to_listen_to,
        choose_by_listening,
        headsets_among,
    )
    from greffier.wiring import _audio_recorder

    candidats = candidates_to_listen_to(materiel, config.audio.mic)  # type: ignore[arg-type]
    if not candidats:
        return ""
    audio_recorder = _audio_recorder(config)
    essais = {name: audio_recorder.try_it(name) for name in candidats}
    choix = choose_by_listening(
        essais, headsets_among(materiel)  # type: ignore[arg-type]
    )
    if choix is None:
        return ""
    if choix.tous_muets:
        typer.secho(
            f"⚠ Aucun micro ne capte : le meilleur, « {choix.name} », rend "
            f"{choix.niveau_db:.0f} dB. Vérifie le bouton de sourdine de ton "
            "casque, puis l'autorisation micro dans Réglages Système.",
            fg=typer.colors.YELLOW,
        )
    if choix.casque_prefere:
        plus_fort = [name for name, db in choix.ecartes if db > choix.niveau_db]
        if plus_fort:
            typer.secho(
                f"  « {choix.name} » retenu bien que « {plus_fort[0]} » capte plus "
                f"fort : un micro de casque est à trois centimètres de la bouche.\n"
                "  Pense à le porter avant de démarrer.",
                fg=typer.colors.BLUE,
            )
    for name, level in choix.ecartes:
        if level < choix.niveau_db - 10:
            typer.secho(f"  « {name} » écarté : {level:.0f} dB contre "
                        f"{choix.niveau_db:.0f} dB", fg=typer.colors.YELLOW)
    return choix.name

def _raise_the_gain(mic: str) -> None:
    """Monte le gain du micro s'il est trop bas pour la transcription."""
    lecture = _swift("--get-gain", mic)
    if lecture.returncode != 0:
        return
    try:
        gain = float(lecture.stdout.strip())
    except ValueError:
        return
    if gain >= _GAIN_MINIMAL:
        return
    if _swift("--set-gain", mic, "0.95").returncode == 0:
        typer.secho(f"  gain du micro relevé : {gain:.2f} → 0.95", fg=typer.colors.CYAN)
    else:
        typer.secho(
            f"⚠ Le gain de « {mic} » est à {gain:.2f} et n'a pas pu être relevé. "
            "Ta voix risque d'être trop faible pour être transcrite.",
            fg=typer.colors.YELLOW,
        )

def _restore_the_output(precedente: str) -> None:
    """Remet la sortie système d'avant la réunion."""
    if not precedente or platform.system() != "Darwin":
        return
    _swift("--set-output", precedente)

def _lancer_veille(config: Config, config_file: Path | None) -> bool:
    """Lance la veille du matériel, détachée. Faux si elle n'a pas pu partir.

    Détachée : « greffier enregistrer » doit rendre la main tout de suite, et la
    veille doit survivre à la fermeture du terminal. Son échec ne compromet que
    l'adaptation au matériel, jamais la capture.
    """
    if platform.system() != "Darwin":
        return False
    command = [sys.executable, "-m", "greffier", "veiller"]
    if config_file:
        command += ["--config", str(config_file)]
    log = config.paths.data / "veille.log"
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as trace:
            subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=trace, stderr=trace,
                start_new_session=True,
            )
    except OSError:
        return False
    return True

def _lancer_direct(config: Config, config_file: Path | None) -> bool:
    """Lance la transcription en direct, détachée. Faux si elle ne part pas.

    Un processus séparé, comme la veille du matériel : whisper occupe plusieurs
    secondes par tranche, ce qui gèlerait la fenêtre, et un modèle qui tombe ne
    doit pas emporter l'interface. C'est ce qui manquait — la commande existait,
    mais rien ne la lançait, donc personne ne l'a jamais vue tourner.
    """
    if not config.live.active:
        return False
    command = [sys.executable, "-m", "greffier", "assister"]
    if config_file:
        command += ["--config", str(config_file)]
    log = config.paths.data / "direct.log"
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as trace:
            subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=trace, stderr=trace,
                start_new_session=True,
            )
    except OSError:
        return False
    return True

@application.command("arreter")
def stop_recording(
    sans_traiter: bool = typer.Option(False, "--sans-traiter",
                                      help="Arrêter sans lancer la transcription"),
    without_sending: bool = typer.Option(
        False, "--sans-envoi", help="Ne pas envoyer, même si un destinataire est configuré"
    ),
    config_file: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Arrête l'enregistrement, puis enchaîne transcription et compte rendu."""
    config = Config.load(config_file)
    try:
        state = recording(config).stop_recording()
    except RuntimeError as trouble:
        typer.secho(f"✗ {trouble}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from trouble
    audio = state.audio
    if audio is None:  # pragma: no cover - « arreter » lève déjà dans ce cas
        raise typer.Exit(1)
    _restore_the_output(state.sortie_precedente)
    typer.secho(f"■ Enregistrement arrêté : {audio.name}", fg=typer.colors.GREEN)
    if sans_traiter:
        typer.echo(f"  « greffier traiter {audio} » pour le traiter plus tard.")
        return
    if state.events:
        for event in state.events:
            typer.secho(f"  matériel : {event}", fg=typer.colors.YELLOW)
    process(
        audio=audio, without_sending=without_sending, sans_cr=False,
        config_file=config_file, events=state.events,
    )

@application.command("annuler")
def cancel(
    config_file: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Interrompt le traitement en cours. L'audio est conservé."""
    try:
        recording(Config.load(config_file)).abandon()
    except RuntimeError as trouble:
        typer.secho(f"✗ {trouble}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from trouble
    typer.secho("■ Traitement interrompu, l'audio est conservé.", fg=typer.colors.YELLOW)

@application.command("assister")
def assist(
    mot_cle: str = typer.Option("greffier", "--mot-cle", help="Mot d'activation"),
    sans_transcription: bool = typer.Option(
        False, "--sans-transcription", help="Ne surveiller que le presse-papier"),
    config_file: Path = typer.Option(None, "--config", help="Fichier de configuration"),
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

    from greffier.adapters.live_levels import written_duration
    from greffier.application.follow import position
    from greffier.application.watch import Watcher
    from greffier.domain.instructions import WatchRules
    from greffier.wiring import _audio_recorder

    config = Config.load(config_file)
    recorder = recording(config)
    state = recorder.read()
    if state.phase.value not in {"enregistrement", "pause"}:
        typer.secho("Aucun enregistrement en cours. « greffier enregistrer » d'abord.",
                    fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    log = config.paths.propositions / f"{state.identifier}.jsonl"
    transcriber = None if sans_transcription else light_transcriber(config)

    from greffier.adapters import questions_file
    from greffier.domain.questions import Questioner

    the_context = context(config)
    fichier_questions = questions_file.questions_file(
        config.paths.questions, state.identifier
    )
    questioner = Questioner(
        known=tuple(t.ecriture for t in the_context.termes)
        + tuple(i.name for i in the_context.intervenants),
        posees=questions_file.keys_already_placed(fichier_questions),
    )

    def interrogate(text: str) -> None:
        for question in questioner.examine(text):
            questions_file.publish(fichier_questions, question)
    the_follower = follower(config, state.identifier) if config.live.active else None
    reprise = _resume_the_thread(config, state.identifier, the_follower)
    lui = assistant_of(config, state.identifier)
    if lui is not None and the_follower is not None:
        lui.name_voice = _namer(the_follower, config, state.identifier)
        lui.context = _live_material(config, state.identifier, the_follower)
    watcher = Watcher(
        watch_rules=WatchRules(mot_cle=mot_cle),
        log=log,
        transcriber=transcriber,
        situer=lambda: position(recorder.read().chunks, written_duration),
        follower=the_follower,
        preparateur=_audio_recorder(config),
        language=config.transcription.language,
        prompt_seed=the_context.prompt_seed(),
        relire_l_amorce=lambda: context(config).prompt_seed(),
        interrogate=interrogate,
        traite=reprise,
        assistant_of=lui,
        initiative=config.assistant.initiative,
        reread_participation=_reread_the_buttons,
        give_voice_back=lambda: assistant_voice(Config()),
        slice_period=config.live.period,
    )
    if the_follower is not None:
        the_follower.annoncer(
            "Transcription en direct active." if transcriber is not None
            else "Aucun modèle de transcription : le fil restera vide.",
            active=transcriber is not None,
        )
    typer.secho(f"Veille sur « {state.name} ». Ctrl+C pour arrêter.", fg=typer.colors.BLUE)
    typer.echo(f"  mot d'activation : « {mot_cle} »")
    if lui is not None:
        comment = "à voix haute" if lui.voice is not None else "par écrit"
        typer.echo(f"  assistant        : « {lui.name} », {comment}")
    typer.echo(f"  propositions     : {log}")
    if the_follower is not None:
        typer.echo(f"  fil du direct    : {the_follower.log}")
    typer.echo("")

    def still_running() -> bool:
        return recorder.read().phase.value in {"enregistrement", "pause"}

    with tempfile.TemporaryDirectory() as job:
        try:
            watcher.loop(still_running=still_running, depuis=lambda: recorder.read().seconds,
                             job=Path(job))
        except KeyboardInterrupt:
            typer.echo("")
    total = len(watcher.watch_rules.propositions)
    turns = len(the_follower.thread.turns) if the_follower else 0
    typer.secho(
        f"✓ {turns} phrase(s) affichée(s), {total} proposition(s) relevée(s).",
        fg=typer.colors.GREEN,
    )

@application.command()
def propositions(
    meeting: str = typer.Argument(None, help="Réunion (défaut : la dernière)"),
    config_file: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Ce que la veille a relevé pendant une réunion."""
    import json as _json

    config = Config.load(config_file)
    identifier = _reunion_visee(config, meeting)
    log = config.paths.propositions / f"{identifier}.jsonl"
    if not log.exists():
        typer.echo("Aucune proposition pour cette réunion.")
        return
    colours = {"lien": typer.colors.CYAN, "instruction": typer.colors.MAGENTA,
                "decision": typer.colors.YELLOW}
    for line in log.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = _json.loads(line)
        at_instant = int(item["instant"])
        typer.secho(
            f"  {at_instant // 60:02d}:{at_instant % 60:02d}  "
            f"{item['genre']:<12} {item['texte'][:88]}",
            fg=colours.get(item["genre"]),
        )

@application.command()
def statut(
    config_file: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Où en est la chaîne — ce que lit aussi l'icône de la barre."""
    state = recording(Config.load(config_file)).read()
    if state.phase.value == "repos":
        typer.echo("Rien en cours. « greffier enregistrer <nom> » pour démarrer.")
        return
    duration = f" — {state.seconds // 60:.0f} min" if state.phase.value == "enregistrement" else ""
    typer.echo(f"{state.phase.value}{duration}")
    if state.name:
        typer.echo(f"  réunion : {state.name}")
    if state.message:
        typer.echo(f"  {state.message}")

@application.command("reunions")
def meetings(
    config_file: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Liste les réunions déjà traitées, les plus récentes d'abord."""
    config = Config.load(config_file)
    magasin = store(config)
    identifiers = magasin.lister()
    if not identifiers:
        typer.echo("Aucune réunion traitée. « greffier traiter <audio> » pour commencer.")
        return
    for identifier in identifiers:
        meeting = magasin.read(identifier)
        nommees = sum(1 for v in meeting.speaking_time() if v in meeting.names)
        total = len(voices_to_name(meeting))
        coverage = f"{meeting.coverage * 100:.0f} %"
        typer.echo(
            f"{identifier:<44} {meeting.duration / 60:5.1f} min  "
            f"{nommees}/{total} voix nommées  couverture {coverage}"
        )

@application.command("voix")
def voice(
    meeting: str = typer.Argument(None, help="Réunion à annoter (défaut : la dernière)"),
    listen: str = typer.Option(None, "--ecouter", help="Extraire un extrait de cette voix"),
    nommer_voix: str = typer.Option(None, "--nommer", help="Voix à nommer"),
    name: str = typer.Option(None, "--nom", help="Nom à lui donner"),
    accept: bool = typer.Option(False, "--accepter-propositions",
                                  help="Valider d'un coup les noms devinés"),
    config_file: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Montre les voix d'une réunion, et permet de les nommer.

    Personne n'est prié de se présenter pendant la réunion : on écoute dix
    secondes après coup, une seule fois par personne. Ensuite l'empreinte est en
    banque et la reconnaissance se fait seule.
    """
    config = Config.load(config_file)
    magasin = store(config)
    identifier = _reunion_visee(config, meeting)

    if accept:
        acceptes = naming(config).accepter_propositions(identifier)
        for voix_id, nom_accepte in acceptes.items():
            typer.secho(f"✓ voix {voix_id} = {nom_accepte}", fg=typer.colors.GREEN)
        if not acceptes:
            typer.echo("Aucune proposition à valider.")
        else:
            _regenerate(config, identifier)
        return

    if nommer_voix and name:
        naming(config).name_voice(identifier, nommer_voix, name)
        typer.secho(f"✓ voix {nommer_voix} = {name}, empreinte en banque",
                    fg=typer.colors.GREEN)
        typer.echo("Cette personne sera reconnue aux prochaines réunions.")
        _regenerate(config, identifier)
        return
    if nommer_voix or name:
        typer.secho("--nommer et --nom vont ensemble.", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)

    detail = magasin.read(identifier)
    if listen:
        candidates = [v for v in voices_to_name(detail) if v.voice == listen]
        if not candidates or candidates[0].extrait is None:
            typer.secho(f"Aucun extrait pour la voix « {listen} ».",
                        fg=typer.colors.RED, err=True)
            raise typer.Exit(1)
        output = config.paths.data / "extraits" / f"{identifier}-{listen}.wav"
        extract_audio(detail.audio, candidates[0].extrait, output)
        typer.echo(f"Extrait : {output}")
        return

    typer.echo(f"{identifier} — {detail.duration / 60:.1f} min\n")
    for candidate in voices_to_name(detail):
        state = (
            typer.style(candidate.name, fg=typer.colors.GREEN) if candidate.name
            else typer.style(f"≈ {candidate.proposition} (à confirmer)", fg=typer.colors.YELLOW)
            if candidate.proposition
            else typer.style("à nommer", fg=typer.colors.BRIGHT_BLACK)
        )
        typer.echo(
            f"  voix {candidate.voice:<4} {candidate.duration / 60:5.1f} min "
            f"({candidate.part * 100:4.1f} %)  {state}"
        )
    typer.echo(
        "\n  écouter : greffier voix "
        f"{identifier} --ecouter <voix>\n"
        f"  nommer  : greffier voix {identifier} --nommer <voix> --nom Josiane"
    )
    if detail.propositions:
        typer.echo(f"  valider : greffier voix {identifier} --accepter-propositions")

@application.command("connus")
def known(
    forget: str = typer.Option(None, "--oublier", help="Effacer une personne de la banque"),
    rename: str = typer.Option(None, "--renommer", help="Personne à renommer"),
    en: str = typer.Option(None, "--en", help="Nouveau nom"),
    clean: str = typer.Option(
        None, "--nettoyer",
        help="Retirer les empreintes de cette personne qui sont d'une autre",
    ),
    oublier_reunion: str = typer.Option(
        None, "--oublier-reunion",
        help="Retirer de toute la banque ce qu'une réunion y a versé",
    ),
    config_file: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Les voix déjà connues, et de quoi les corriger.

    Une empreinte vocale nominative est une donnée biométrique : il doit être
    aussi simple de l'effacer que de l'ajouter.
    """
    config = Config.load(config_file)
    bank = BanqueFichiers(config.paths.voice_bank)

    if forget:
        if bank.forget(forget):
            typer.secho(f"✓ {forget} effacé de la banque de voix", fg=typer.colors.GREEN)
        else:
            typer.secho(f"« {forget} » n'est pas dans la banque.",
                        fg=typer.colors.RED, err=True)
            raise typer.Exit(1)
        return

    if rename and en:
        bank.rename(rename, en)
        typer.secho(f"✓ {rename} → {en}", fg=typer.colors.GREEN)
        return

    if clean:
        _clean_an_entry(bank, clean)
        return

    if oublier_reunion:
        retires = bank.forget_a_meeting(oublier_reunion)
        if not retires:
            typer.echo(
                f"Aucune empreinte ne vient de « {oublier_reunion} ». Les "
                "empreintes déposées avant que cette trace n'existe ne portent "
                "pas leur origine : « greffier connus » dit lesquelles sont "
                "suspectes."
            )
            return
        for name, combien in sorted(retires.items()):
            typer.secho(f"✓ {combien} empreinte(s) retirée(s) de {name}",
                        fg=typer.colors.GREEN)
        _say_the_bank_health(bank.people())
        return

    people = bank.people()
    if not people:
        typer.echo("Banque de voix vide. « greffier voix » pour nommer une première voix.")
        return
    for personne in people:
        vue = personne.vu_le.strftime("%Y-%m-%d") if personne.vu_le else "—"
        typer.echo(
            f"  {personne.name:<20} {len(personne.voiceprints)} empreinte(s)  "
            f"vue le {vue}"
        )

    _say_the_bank_health(people)

def _clean_an_entry(bank: BanqueFichiers, name: str) -> None:
    """Retire d'une personne les empreintes qui désignent quelqu'un d'autre.

    Effacer la personne entière pour une empreinte fautive perdait tout le
    reste. Le grain qui décide de la reconnaissance est l'empreinte : c'est
    donc à ce grain qu'on corrige.
    """
    from greffier.domain.voiceprints import intruding_voiceprints

    people = bank.people()
    cette = next((p for p in people if p.name.casefold() == name.casefold()), None)
    if cette is None:
        typer.secho(f"« {name} » n'est pas dans la banque.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    suspectes = intruding_voiceprints(cette, people)
    if not suspectes:
        typer.echo(f"Rien à retirer : les empreintes de {cette.name} se ressemblent "
                   "entre elles plus qu'à quiconque.")
        return
    for intruse in suspectes:
        typer.echo(
            f"  empreinte {intruse.rank} ({intruse.duration:.0f} s) : "
            f"ressemble à {intruse.qui} ({intruse.elsewhere:.2f}) plus qu'à "
            f"{cette.name} ({intruse.at_home:.2f})"
        )
    if not typer.confirm(
        f"Retirer ces {len(suspectes)} empreinte(s) de {cette.name} ?", default=False
    ):
        typer.echo("Rien n'a été touché.")
        return
    combien = bank.remove_voiceprints(cette.name, [i.rank for i in suspectes])
    typer.secho(f"✓ {combien} empreinte(s) retirée(s) de {cette.name}",
                fg=typer.colors.GREEN)
    _say_the_bank_health(bank.people())

def _say_the_bank_health(people: list) -> None:  # type: ignore[type-arg]
    """Dit quelles entrées se ressemblent trop, et ce que ça coûte.

    Une entrée déposée sous le nom d'un collègue mais portant une autre voix
    empoisonne toute la banque : les deux noms deviennent inreconnaissables,
    et rien ne le dit. C'est arrivé le 2026-09-02, découvert seulement parce
    qu'un prénom avait été affirmé à tort en réunion.
    """
    import itertools

    from greffier.domain.voiceprints import (
        SEUIL_CONFLIT,
        SEUIL_RECONNAISSANCE,
        aggregate,
        similarity,
    )

    agregats = {
        personne.name: (
            aggregate(personne.voiceprints) if len(personne.voiceprints) > 1
            else personne.voiceprints[0]
        )
        for personne in people if personne.voiceprints
    }
    conflits: list[tuple[float, str, str]] = []
    near_ones: list[tuple[float, str, str]] = []
    for un, autre in itertools.combinations(sorted(agregats), 2):
        value = similarity(agregats[un], agregats[autre])
        if value >= SEUIL_CONFLIT:
            conflits.append((value, un, autre))
        elif value >= SEUIL_RECONNAISSANCE:
            near_ones.append((value, un, autre))

    if conflits:
        typer.secho(
            f"\n⚠ {len(conflits)} paire(s) trop ressemblante(s) : ces personnes "
            "ne sont plus reconnues du tout.",
            fg=typer.colors.RED,
        )
        for value, un, autre in sorted(conflits, reverse=True):
            typer.secho(f"    {value:.3f}  {un} / {autre}", fg=typer.colors.RED)
        typer.echo(
            "  Une des deux entrées porte probablement la voix de l'autre. "
            "Réécoute\n  un extrait de chacune, puis « greffier connus "
            "--oublier <nom> » et renomme\n  la voix à la prochaine réunion."
        )
    _say_the_intruders(people)
    if near_ones:
        typer.secho(
            f"\n· {len(near_ones)} paire(s) proche(s), au-dessus du seuil de "
            f"reconnaissance ({SEUIL_RECONNAISSANCE:.2f}) :",
            fg=typer.colors.YELLOW,
        )
        for value, un, autre in sorted(near_ones, reverse=True):
            typer.echo(f"    {value:.3f}  {un} / {autre}")
        typer.echo(
            "  C'est l'écart avec le second qui les sépare. Une entrée d'une "
            "seule\n  empreinte est fragile : renommer la même personne sur une "
            "autre réunion\n  ajoute une empreinte et écarte les voix les unes "
            "des autres."
        )
    maigres = [p.name for p in people if len(p.voiceprints) < 2]
    if maigres:
        typer.echo(
            f"\n  {len(maigres)} entrée(s) d'une seule empreinte : "
            f"{', '.join(maigres)}"
        )

def _say_the_intruders(people: list) -> None:  # type: ignore[type-arg]
    """Nomme les empreintes fautives, une par une.

    Savoir que deux entrées sont en conflit ne dit pas laquelle réparer, et
    effacer une personne entière pour une empreinte perd tout le reste. La
    question se pose empreinte par empreinte, et elle a une réponse.
    """
    from greffier.domain.voiceprints import intruding_voiceprints

    trouvees = [
        (personne.name, intruse)
        for personne in people
        for intruse in intruding_voiceprints(personne, people)
    ]
    if not trouvees:
        return
    typer.secho(
        f"\n  {len(trouvees)} empreinte(s) désignent quelqu'un d'autre que "
        "la personne sous laquelle elles sont rangées :",
        fg=typer.colors.YELLOW,
    )
    for name, intruse in sorted(trouvees, key=lambda x: -x[1].gap):
        typer.echo(
            f"    {name} n° {intruse.rank} ({intruse.duration:.0f} s) : "
            f"{intruse.qui} {intruse.elsewhere:.2f} contre {name} "
            f"{intruse.at_home:.2f}"
        )
    names = sorted({name for name, _ in trouvees})
    typer.echo(
        f"  « greffier connus --nettoyer {names[0]} » les retire sans effacer "
        "le reste."
    )

@application.command("montage")
def assembly(
    meeting: str = typer.Argument(None, help="Réunion (défaut : la dernière)"),
    minutes: float = typer.Option(5.0, "--minutes", help="Durée visée du montage"),
    config_file: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Recolle les passages marquants — les vraies voix, rien de synthétisé.

    Le temps est réparti entre les intervenants proportionnellement à leur temps
    de parole : un montage qui ne ferait entendre que la personne la plus
    bavarde ne restituerait pas la réunion.
    """
    from greffier.application.render import assemble, notable_passages

    config = Config.load(config_file)
    magasin = store(config)
    identifier = _reunion_visee(config, meeting)
    detail = magasin.read(identifier)
    passages = notable_passages(detail, duree_visee=minutes * 60)
    if not passages:
        typer.secho("Pas assez de parole pour un montage.", fg=typer.colors.YELLOW)
        raise typer.Exit(1)
    output = config.paths.data / "montages" / f"{identifier}.m4a"
    assemble(detail.audio, passages, output)
    total = sum(p.duration for p in passages)
    typer.secho(f"✓ {len(passages)} passages, {total / 60:.1f} min : {output}",
                fg=typer.colors.GREEN)

@application.command(name="contexte")
def contexte_(
    open_it: bool = typer.Option(False, "--ouvrir", help="Ouvrir le fichier pour l'éditer"),
    config_file: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Montre ce que Greffier sait de votre milieu, et d'où il le sait.

    Un sigle absent d'ici sera transcrit par le mot le plus proche que le modèle
    connaît : « déploiement » devient « exploitement ». Cette commande sert à
    vérifier ce qui est effectivement transmis, et ce que l'amorce a dû écarter.
    """
    from greffier.adapters import context_file

    config = Config.load(config_file)
    file = config.paths.context
    if context_file.lay_the_template(file):
        typer.secho(f"Fichier de contexte créé : {file}", fg=typer.colors.GREEN)

    the_context = context(config)
    typer.echo(f"\n{len(the_context.termes)} terme(s), "
               f"{len(the_context.intervenants)} personne(s)")
    typer.echo(f"  fichier      {file}")
    typer.echo(f"  vocabulaire  config.toml, {len(config.transcription.vocabulary)} mot(s)")
    typer.echo(f"  banque       {config.paths.voice_bank}")

    typer.secho("\nTermes", fg=typer.colors.BRIGHT_WHITE, bold=True)
    for terme in the_context.termes:
        typer.echo(f"  {terme.gloss}")
    typer.secho("\nPersonnes", fg=typer.colors.BRIGHT_WHITE, bold=True)
    for personne in the_context.intervenants:
        typer.echo(f"  {personne.gloss}")

    prompt_seed = the_context.prompt_seed()
    typer.secho(f"\nAmorce de transcription ({len(prompt_seed)} caractères)",
                fg=typer.colors.BRIGHT_WHITE, bold=True)
    typer.echo(f"  {prompt_seed or '(aucune)'}")
    ecartes = the_context.ecartes()
    if ecartes:
        typer.secho(
            f"\n⚠ {len(ecartes)} terme(s) écarté(s), l'amorce est pleine : "
            + ", ".join(ecartes[:8]) + ("…" if len(ecartes) > 8 else ""),
            fg=typer.colors.YELLOW,
        )
        typer.echo("  Retire les moins utiles : ce qui dépasse ne sert à personne.")

    if open_it:
        opener = {"darwin": "open", "win32": "start"}.get(sys.platform, "xdg-open")
        subprocess.run([opener, str(file)], check=False)

@application.command("renommer")
def rename(
    subject: str = typer.Argument(..., help="Le sujet de la réunion, en clair"),
    meeting: str = typer.Argument(None, help="Réunion (défaut : la dernière)"),
    config_file: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Donne un sujet à une réunion, celui qui s'affichera dans la liste.

    Un libellé, pas un renommage de fichiers : l'identifiant porte la date, qui
    ordonne les réunions, date le compte rendu et sert de clé à l'audio comme à
    la transcription. Le remplacer par « point du lundi » perdrait tout cela.
    """
    config = Config.load(config_file)
    identifier = _reunion_visee(config, meeting)
    magasin = store(config)
    try:
        gardee = magasin.read(identifier)
    except (OSError, ValueError) as trouble:
        typer.secho(f"✗ {trouble}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from trouble
    gardee.subject = subject.strip()
    magasin.record(gardee)
    typer.secho(f"✓ {identifier} → « {gardee.caption} »", fg=typer.colors.GREEN)

@application.command("carte")
def board(
    subject: str = typer.Argument(None, help="Sujet à cartographier (défaut : ceux détectés)"),
    meeting: str = typer.Argument(None, help="Réunion (défaut : la dernière)"),
    publish: bool = typer.Option(False, "--publier", help="Écrire sur Miro"),
    config_file: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Construit la carte d'un sujet depuis une réunion. Constate d'abord.

    Sans « --publier », rien ne sort du poste : la commande dit ce qu'elle
    ajouterait. Une carte se partage largement, la voir avant coûte peu.
    """
    from greffier.adapters import subjects_file
    from greffier.application.map_subjects import RenduIllisible, extract
    from greffier.application.render import render_transcript
    from greffier.domain.board import Carte, join

    config = Config.load(config_file)
    identifier = _reunion_visee(config, meeting)
    subjects_file.lay_the_template(config.paths.subjects)
    registre = subjects_file.read(config.paths.subjects)

    try:
        gardee = store(config).read(identifier)
    except (OSError, ValueError) as trouble:
        typer.secho(f"✗ {trouble}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from trouble
    material = render_transcript(gardee)

    vises = [subject] if subject else registre.subjects_of(material)
    if not vises:
        typer.echo("Aucun sujet suivi n'est assez présent dans cette réunion.")
        typer.echo(f"Les sujets se déclarent dans {config.paths.subjects}.")
        raise typer.Exit(1)

    engine = cartographe(config)
    if engine is None:
        typer.secho("Aucun rédacteur configuré.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    for name in vises:
        typer.secho(f"\n— {name} —", fg=typer.colors.BRIGHT_WHITE, bold=True)
        deja = _board_labels(registre, name) if publish else ()
        des_autres = _contributions_of_others(registre, name) if publish else ()
        if des_autres:
            typer.secho(
                f"  {len(des_autres)} point(s) ajouté(s) à la main sur la carte :",
                fg=typer.colors.BLUE,
            )
            for label_text in des_autres[:5]:
                typer.echo(f"    · {label_text}")
        try:
            apports = extract(engine, name, material, deja=deja)
        except RenduIllisible as trouble:
            typer.secho(f"  ✗ extraction illisible : {trouble}", fg=typer.colors.RED)
            continue
        if not apports:
            typer.echo("  rien à ajouter")
            continue
        the_board = Carte(name)
        bilan = join(the_board, apports, meeting=identifier)
        for contribution in apports:
            marque = "✓" if str(contribution.state) == "acté" else "·"
            sous = f"  ← {contribution.sous}" if contribution.sous else ""
            typer.echo(f"  {marque} [{contribution.kind}] {contribution.text}{sous}")
        if not publish:
            typer.echo(f"  ({len(bilan.ajoutes)} point(s), « --publier » pour l'écrire)")
            continue
        _publier_la_carte(config, registre, name, the_board, identifier)

def _board_labels(registre: object, name: str) -> tuple[str, ...]:
    """Les libellés déjà sur la carte de ce sujet, s'il en a une."""
    from greffier.adapters import board_miro

    connu = registre.by_name(name)  # type: ignore[attr-defined]
    if connu is None or not connu.board:
        return ()
    try:
        return tuple(board_miro.labels_present(connu.board))
    except board_miro.MiroRefuse:
        return ()

def _action_texts(board: object) -> list[str]:
    """Les libellés des points que le groupe a tranchés.

    La racine est écartée : le sujet n'est ni acté ni en discussion, il est.
    """
    from greffier.domain.board import Genre, Noeud, RecorderState

    trouves: list[str] = []

    def walk(noeud: Noeud) -> None:
        if noeud.state is RecorderState.ACTE and noeud.kind is not Genre.SUBJECT:
            trouves.append(noeud.text)
        for enfant in noeud.enfants:
            walk(enfant)

    racine = getattr(board, "racine", None)
    if racine is not None:
        walk(racine)
    return trouves

def _contributions_of_others(registre: object, name: str) -> tuple[str, ...]:
    """Ce que des humains ont écrit sur la carte, et que l'outil n'a pas posé."""
    from greffier.adapters import board_miro

    connu = registre.by_name(name)  # type: ignore[attr-defined]
    if connu is None or not connu.board:
        return ()
    try:
        return tuple(board_miro.contributions_of_others(connu.board))
    except board_miro.MiroRefuse:
        return ()

def _publier_la_carte(
    config: Config, registre: object, name: str, the_board: object, identifier: str
) -> None:
    """Écrit la carte sur Miro, en créant le tableau à la première fois."""
    from greffier.adapters import board_miro, subjects_file

    connu = registre.by_name(name)  # type: ignore[attr-defined]
    tableau = connu.board if connu and connu.board else ""
    try:
        if not tableau:
            tableau, adresse = board_miro.creer_le_tableau(name)
            subjects_file.noter_la_carte(config.paths.subjects, name, tableau)
            typer.secho(f"  tableau créé : {adresse or tableau}", fg=typer.colors.GREEN)
        ecrit = board_miro.publish(the_board, tableau, meeting=identifier)  # type: ignore[arg-type]
    except board_miro.MiroRefuse as trouble:
        typer.secho(f"  ✗ {trouble}", fg=typer.colors.RED, err=True)
        return
    typer.secho(
        f"  ✓ {len(ecrit.poses)} posé(s), {len(ecrit.deja)} déjà présent(s), "
        f"{ecrit.liens} lien(s)",
        fg=typer.colors.GREEN,
    )
    actes = _action_texts(the_board)
    if actes:
        marques = board_miro.mark_actions(tableau, actes, meeting=identifier)
        if marques:
            typer.secho(f"  ✓ {len(marques)} point(s) marqué(s) « acté »",
                        fg=typer.colors.GREEN)
    if ecrit.liens_manques:
        typer.secho(
            f"  ⚠ {ecrit.liens_manques} lien(s) n'ont pas pu être tracés",
            fg=typer.colors.YELLOW,
        )

@application.command(name="sources")
def sources_(
    config_file: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Les sources extérieures inscrites, et si leur jeton répond.

    Ce qui n'est pas inscrit est inatteignable : l'outil ne découvre aucun
    projet de lui-même, et c'est ce qui borne le risque à ce qui a été listé.
    """
    from greffier.adapters import sources_file

    config = Config.load(config_file)
    if sources_file.lay_the_template(config.paths.sources):
        typer.secho(f"Fichier créé : {config.paths.sources}", fg=typer.colors.GREEN)

    registre = sources_file.read(config.paths.sources)
    if not registre.sources:
        typer.echo("\nAucune source inscrite. Le fichier dit comment faire :")
        typer.echo(f"  {config.paths.sources}")
        raise typer.Exit(1)

    typer.echo("")
    for source in registre.sources:
        token = sources_file.token_for(source)
        marque = "✓" if token else "✗"
        colour = typer.colors.GREEN if token else typer.colors.YELLOW
        typer.secho(f"  {marque} {source.say()}", fg=colour)
        if not token:
            typer.echo(f"      jeton introuvable en « {source.token} »")
            continue
        try:
            _try_the_source(source, token)
        except RuntimeError as trouble:
            typer.secho(f"      ✗ {trouble}", fg=typer.colors.RED)

    ecrivables = [s.name for s in registre.sources if s.can_write]
    if ecrivables:
        typer.secho(
            f"\n⚠ {len(ecrivables)} source(s) en écriture : {', '.join(ecrivables)}.\n"
            "  Chaque écriture demande confirmation, mais le jeton est atteignable.",
            fg=typer.colors.YELLOW,
        )
    typer.echo(f"\n  registre  {config.paths.sources}")

def _try_the_source(source: object, token: str) -> None:
    """Un appel de lecture, pour dire si l'accès fonctionne vraiment.

    Un registre qui se contente de dire « configuré » ne sert à rien : le
    jeton peut être expiré, sa portée insuffisante, le projet invisible. Mieux
    vaut l'apprendre ici qu'en pleine réunion.
    """
    from greffier.domain.sources import Genre, Source

    assert isinstance(source, Source)
    if source.kind is Genre.GITLAB:
        from greffier.adapters.gitlab_api import tickets

        trouves = tickets(source, token)
        typer.echo(f"      {len(trouves)} ticket(s) ouvert(s) lisible(s)")
        return
    from greffier.adapters.jira_api import requests

    trouvees = requests(source, token)
    typer.echo(f"      {len(trouvees)} demande(s) lisible(s)")

@application.command(name="niveau")
def niveau_(
    seconds: float = typer.Option(4.0, "--secondes", help="Durée d'écoute"),
    config_file: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Écoute, et dit si le niveau suffit à transcrire. **Parle pendant l'écoute.**

    Le contrôle existant mesure le silence, ce qui repère un micro coupé mais ne
    dit rien de la parole. Or c'est la parole qui décide : à -43 dB, mesuré, le
    modèle n'écrit pas moins bien, il invente.
    """
    from greffier.domain.level import Verdict, judge, say
    from greffier.wiring import _audio_recorder

    config = Config.load(config_file)
    player = lister(config)
    materiel = player.read()
    mic = config.audio.mic or _mic_by_listening(config, materiel)
    if not mic:
        typer.secho("Aucun micro utilisable.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    typer.secho(f"\nParle maintenant, {seconds:.0f} secondes — micro « {mic} »",
                fg=typer.colors.BRIGHT_WHITE, bold=True)
    db = _audio_recorder(config).try_it(mic, seconds)
    verdict = judge(db)
    colour = {
        Verdict.BON: typer.colors.GREEN,
        Verdict.FAIBLE: typer.colors.YELLOW,
        Verdict.INSUFFISANT: typer.colors.RED,
        Verdict.MUET: typer.colors.RED,
    }[verdict]
    typer.secho(f"\n{say(db)}", fg=colour)
    if verdict in (Verdict.INSUFFISANT, Verdict.MUET):
        raise typer.Exit(1)

@application.command("deposer")
def publish(
    files: list[Path] = typer.Argument(..., help="Fichiers à déposer"),
    do_it: bool = typer.Option(
        False, "--faire", help="Exécuter, au lieu de seulement proposer"
    ),
    config_file: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Classe des fichiers déposés : réunions, vidéos, contexte.

    Sans « --faire », rien n'est touché : la commande dit ce qu'elle ferait de
    chaque fichier et pourquoi. Une vidéo de deux heures mal classée coûte une
    transcription pour rien, et un document classé en réunion produit un compte
    rendu d'un texte que personne n'a prononcé.
    """
    from greffier.application import publish as job
    from greffier.domain.store import Destin, offer, summarise

    config = Config.load(config_file)
    outils = job.tools_present()
    propositions = []
    for file in files:
        if not file.exists():
            typer.secho(f"  ✗ introuvable : {file}", fg=typer.colors.RED)
            continue
        taille = file.stat().st_size if file.is_file() else None
        propositions.append(offer(file, taille, outils))

    if not propositions:
        raise typer.Exit(1)

    typer.echo("")
    for proposition in propositions:
        colour = (
            typer.colors.GREEN if proposition.feasible
            else (typer.colors.YELLOW if proposition.bloque_par else typer.colors.BRIGHT_BLACK)
        )
        typer.secho(
            f"  {str(proposition.destin):9} {proposition.file.name}",
            fg=colour,
        )
        typer.echo(f"            {proposition.parce_que}")
        if proposition.bloque_par:
            typer.secho(f"            ⚠ {proposition.bloque_par}", fg=typer.colors.YELLOW)
    typer.echo(f"\n  {summarise(propositions)}")

    if not do_it:
        typer.echo("\n« greffier deposer --faire » pour le faire.")
        return

    redacteur_document = cartographe(config)
    if any(p.destin is Destin.CONTEXT and p.feasible for p in propositions):
        from greffier.adapters.writer_claude import RedacteurClaude
        from greffier.application.publish import CONSIGNES_DOCUMENT

        if isinstance(redacteur_document, RedacteurClaude):
            redacteur_document.consignes_propres = CONSIGNES_DOCUMENT

    typer.echo("")
    a_traiter: list[Path] = []
    for proposition in propositions:
        fait = job.run_chain(
            proposition, config.paths.recordings, redacteur_document
        )
        if fait.trouble:
            typer.secho(f"  ✗ {proposition.file.name} : {fait.trouble}",
                        fg=typer.colors.RED)
            continue
        if fait.produit is not None:
            typer.secho(f"  ✓ {fait.produit.name}", fg=typer.colors.GREEN)
            a_traiter.append(fait.produit)
        for ecriture, sens, kind in fait.appris:
            typer.echo(f"    · {kind:8} {ecriture}"
                       + (f" — {sens}" if sens else ""))
        if fait.appris:
            typer.secho(
                f"  {len(fait.appris)} entrée(s) proposée(s) depuis "
                f"{proposition.file.name}", fg=typer.colors.GREEN,
            )
            _offer_to_the_context(config, fait.appris)

    if a_traiter:
        typer.echo("\nÀ transcrire :")
        for path in a_traiter:
            typer.echo(f"  greffier traiter {path}")

def _offer_to_the_context(
    config: Config, appris: tuple[tuple[str, str, str], ...]
) -> None:
    """Demande avant d'écrire dans le contexte, comme partout ailleurs.

    Un document apporte vingt entrées d'un coup : les valider en bloc est le
    seul geste raisonnable, mais il doit rester un geste.
    """
    from greffier.adapters import context_file

    if not typer.confirm("\n  Ajouter ces entrées au contexte ?", default=True):
        typer.echo("  Rien n'a été ajouté.")
        return
    poses = 0
    for ecriture, sens, kind in appris:
        ajout = (
            context_file.add_a_person
            if kind == "personne" else context_file.add_a_term
        )
        if ajout(config.paths.context, ecriture, sens):
            poses += 1
    typer.secho(f"  ✓ {poses} ajoutée(s), {len(appris) - poses} déjà connue(s)",
                fg=typer.colors.GREEN)

@application.command("recuperer")
def recover(
    meeting: str = typer.Argument(None, help="Réunion (défaut : celle du dernier fil)"),
    config_file: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Reconstruit une réunion depuis le fil du direct, faute de traitement.

    À employer quand une réunion n'apparaît nulle part alors qu'elle a bien eu
    lieu : le fil du direct existe, mais rien ne l'a jamais converti en réunion.
    Le résultat est moins bon qu'un traitement — modèle rapide, voix non
    recollées — et c'est la différence entre approximatif et perdu.
    """
    from greffier.application.follow import read_from
    from greffier.application.recover import depuis_le_fil

    config = Config.load(config_file)
    folder = config.paths.live
    if meeting:
        log = folder / f"{meeting}.jsonl"
        identifier = meeting
    else:
        fils = sorted(folder.glob("*.jsonl"), key=lambda c: c.stat().st_mtime)
        if not fils:
            typer.secho(f"Aucun fil de direct dans {folder}.",
                        fg=typer.colors.RED, err=True)
            raise typer.Exit(1)
        log = fils[-1]
        identifier = log.stem
    if not log.exists():
        typer.secho(f"Aucun fil pour « {identifier} ».", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    magasin = store(config)
    if identifier in magasin.lister():
        typer.secho(
            f"« {identifier} » est déjà une réunion : « greffier rediger » "
            "reprend son compte rendu.",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(1)

    lines, _ = read_from(log, 0)
    audio = config.paths.recordings / f"{identifier}.wav"
    reconstruite = depuis_le_fil(
        identifier, lines, audio if audio.exists() else None
    )
    if not reconstruite.utterances:
        typer.secho("Le fil ne contient aucune parole transcrite.",
                    fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    path = magasin.record(reconstruite)
    words = sum(len(r.text.split()) for r in reconstruite.utterances)
    typer.secho(f"✓ {identifier} reconstruite : {words} mots, "
                f"{len(reconstruite.turns)} tours", fg=typer.colors.GREEN)
    typer.echo(f"  fichier  {path}")
    if reconstruite.names:
        typer.echo(f"  voix nommées  {', '.join(sorted(reconstruite.names.values()))}")
    typer.secho(f"\n⚠ {reconstruite.warnings[0]}", fg=typer.colors.YELLOW)
    if audio.exists():
        typer.echo(f"\nL'enregistrement existe : « greffier traiter {audio} » "
                   "donnera un bien meilleur résultat.")
    else:
        typer.echo("\n« greffier rediger » écrit le compte rendu.")

@application.command("sauvegarder")
def back_up(
    restaurer_depuis: str = typer.Option(
        None, "--restaurer", help="Nom de l'archive à remettre en place"
    ),
    ecraser: bool = typer.Option(
        False, "--ecraser", help="Restaurer par-dessus ce qui existe déjà"
    ),
    lister_seulement: bool = typer.Option(
        False, "--lister", help="Montrer les sauvegardes présentes"
    ),
    config_file: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Copie les données, sans l'audio. Restaure aussi.

    3 Mo contre 1,1 Go d'enregistrements : c'est ce qui rend une sauvegarde
    possible. Une réunion transcrite reste utilisable sans son audio ; l'inverse
    n'est pas vrai, un enregistrement dont on a perdu la transcription et le
    compte rendu est un fichier que personne ne réécoutera.
    """
    from greffier.application import back_up as job
    from greffier.locations import config_folder

    config = Config.load(config_file)
    destination = (
        Path(config.backup.folder).expanduser()
        if config.backup.folder else config.paths.backups
    )

    if lister_seulement:
        trouvees = job.lister(destination)
        if not trouvees:
            typer.echo(f"Aucune sauvegarde dans {destination}.")
            raise typer.Exit(1)
        typer.echo(f"\n{len(trouvees)} sauvegarde(s) dans {destination} :\n")
        for name, bytes_read, quand in trouvees:
            typer.echo(f"  {quand:%Y-%m-%d %H:%M}  {bytes_read / 1024**2:6.1f} Mo  {name}")
        return

    if restaurer_depuis:
        archive = destination / restaurer_depuis
        if not archive.exists() and not restaurer_depuis.endswith(".tar.gz"):
            archive = destination / f"{restaurer_depuis}.tar.gz"
        try:
            remis = job.restore(archive, config.paths.data, ecraser)
        except (FileNotFoundError, FileExistsError) as trouble:
            typer.secho(f"✗ {trouble}", fg=typer.colors.RED, err=True)
            raise typer.Exit(1) from trouble
        typer.secho(f"✓ restauré : {', '.join(remis)}", fg=typer.colors.GREEN)
        return

    try:
        faite = job.do_it(
            config.paths.data, config_folder(), destination,
            kept=config.backup.kept,
        )
    except OSError as trouble:
        typer.secho(f"✗ sauvegarde impossible : {trouble}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from trouble

    typer.secho(
        f"✓ {faite.archive.name} — {faite.files} fichier(s), "
        f"{faite.bytes_read / 1024**2:.1f} Mo",
        fg=typer.colors.GREEN,
    )
    typer.echo(f"  contenu  {', '.join(faite.dossiers)}")
    typer.echo(f"  écrit    {faite.archive.parent}")
    if faite.effacees:
        typer.echo(f"  rotation {len(faite.effacees)} ancienne(s) effacée(s)")
    if faite.on_the_same_disk:
        typer.secho(
            "\n⚠ Cette copie est sur le même disque que les données : elle protège\n"
            "  d'un effacement, pas d'une panne de disque. Règle "
            "« sauvegarde.dossier »\n  vers un disque externe ou un espace "
            "synchronisé.",
            fg=typer.colors.YELLOW,
        )

@application.command("ranger")
def tidy(
    for_real: bool = typer.Option(
        False, "--faire", help="Appliquer, au lieu de seulement dire ce qui se passerait"
    ),
    config_file: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Applique la règle de rétention aux enregistrements. Constate d'abord.

    Sans « --faire », rien n'est modifié : la commande dit ce qu'elle
    emporterait. Effacer un enregistrement ne se rattrape pas, et le voir avant
    coûte trois secondes.
    """
    from datetime import UTC, datetime

    from greffier.application import tidy as rangement
    from greffier.application.render import archiver as compresser
    from greffier.domain.retention import Regle

    config = Config.load(config_file)
    magasin = store(config)
    try:
        regle = Regle(
            compresser_apres=config.retention.compresser_apres_jours,
            effacer_apres=config.retention.effacer_apres_jours,
        )
    except ValueError as trouble:
        typer.secho(f"✗ règle de rétention invalide : {trouble}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from trouble

    now = datetime.now(UTC)
    meetings: list[tuple[str, float, bool]] = []
    for identifier in magasin.lister():
        try:
            detail = magasin.read(identifier)
        except (OSError, ValueError):
            continue
        reference = detail.commencee_le or detail.traitee_le
        jours = (now - reference).total_seconds() / 86400
        meetings.append((identifier, jours, bool(detail.utterances)))

    faits = rangement.tidy(
        _locations(config), regle, meetings, compresser, for_real=for_real
    )
    if not faits:
        typer.echo("Rien à ranger : tout est déjà dans l'état voulu.")
        return

    for fait in faits:
        if fait.trouble:
            typer.secho(f"  ⚠ {fait.identifier} : {fait.trouble}", fg=typer.colors.YELLOW)
            continue
        typer.echo(f"  {fait.geste:<12} {fait.identifier}  "
                   f"{rangement.readable(fait.gagne)}")
    total = rangement.readable(sum(f.gagne for f in faits))
    if for_real:
        typer.secho(f"✓ {total} libérés", fg=typer.colors.GREEN)
    else:
        typer.echo(f"\n{total} seraient libérés. « greffier ranger --faire » pour le faire.")

@application.command("oublier")
def forget(
    meeting: str = typer.Argument(None, help="Réunion (défaut : la dernière)"),
    oui: bool = typer.Option(False, "--oui", help="Effacer sans confirmation"),
    config_file: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Efface une réunion et tout ce qui va avec, après confirmation.

    L'audio est le seul morceau qu'on ne puisse pas refaire : la transcription
    et le compte rendu se reconstituent depuis lui, l'inverse est faux. La liste
    de ce qui part s'affiche donc avant, avec son poids.
    """
    from greffier.application import tidy

    config = Config.load(config_file)
    identifier = _reunion_visee(config, meeting)
    ou = _locations(config)
    pieces = tidy.pieces_de(ou, identifier)
    if not pieces:
        typer.secho(f"Rien à effacer pour {identifier}.", fg=typer.colors.YELLOW)
        raise typer.Exit(1)

    typer.echo(f"\nÀ effacer pour « {identifier} » :")
    for piece in pieces:
        typer.echo(f"  {tidy.readable(piece.bytes_read):>8}  {piece.quoi}")
    total = sum(p.bytes_read for p in pieces)
    typer.echo(f"  {'─' * 8}")
    typer.echo(f"  {tidy.readable(total):>8}  au total\n")

    if not oui and not typer.confirm("Effacer définitivement ?", default=False):
        typer.echo("Rien n'a été effacé.")
        raise typer.Exit(1)

    effacees = tidy.forget(ou, identifier)
    typer.secho(
        f"✓ {len(effacees)} fichier(s) effacé(s), "
        f"{tidy.readable(sum(p.bytes_read for p in effacees))} libérés",
        fg=typer.colors.GREEN,
    )
    reste = tidy.pieces_de(ou, identifier)
    for piece in reste:
        typer.secho(f"⚠ {piece.path} n'a pas pu être effacé", fg=typer.colors.YELLOW)

@application.command()
def revoir(
    meeting: str = typer.Argument(None, help="Réunion (défaut : la dernière)"),
    rediger_aussi: bool = typer.Option(
        True, "--rediger/--sans-rediger",
        help="Réécrire le compte rendu avec les voix revues",
    ),
    config_file: Path = typer.Option(None, "--config", help="Fichier de configuration"),
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
    from greffier.adapters.voiceprints_titanet import ExtracteurTitaNet
    from greffier.application.render import review_voices

    config = Config.load(config_file)
    identifier = _reunion_visee(config, meeting)
    le_depot = store(config)
    try:
        gardee = le_depot.read(identifier)
    except (OSError, ValueError) as trouble:
        typer.secho(f"✗ {trouble}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from trouble
    if not gardee.audio.exists():
        typer.secho(f"✗ l'enregistrement {gardee.audio} n'est plus là : le "
                    "recollage a besoin du son.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    typer.secho(f"  empreintes     {identifier}…", fg=typer.colors.BLUE)
    extractor = ExtracteurTitaNet(
        config.paths.models / "diarisation/nemo_en_titanet_large.onnx")
    avant, apres = review_voices(
        gardee, extractor, BanqueFichiers(config.paths.voice_bank))
    le_depot.record(gardee)
    portantes = len(gardee.attendees())
    typer.secho(f"✓ {avant} voix ramenées à {apres}, dont {portantes} au-dessus "
                "de dix secondes", fg=typer.colors.GREEN)
    if gardee.names:
        typer.echo("  " + ", ".join(f"{v} → {n}" for v, n in sorted(gardee.names.items())))

    if not rediger_aussi:
        return
    engine = writer(config)
    if engine is None:
        typer.echo("  Aucun rédacteur : le compte rendu n'est pas réécrit.")
        return
    typer.secho(f"  rédaction      {identifier}…", fg=typer.colors.BLUE)
    text = regenerate_minutes(gardee, engine, config.conversation.disclosure)
    path = config.paths.minutes_folder / f"{identifier}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    typer.secho(f"✓ {path}", fg=typer.colors.GREEN)

@application.command("rediger")
def write_up(
    meeting: str = typer.Argument(None, help="Réunion (défaut : la dernière)"),
    config_file: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Rédige le compte rendu d'une réunion déjà transcrite.

    La reprise quand le rédacteur a échoué — expiration, quota, réseau coupé.
    Rien n'est réécouté ni retranscrit : le fichier maître porte déjà le texte
    et les voix, seule la rédaction est rejouée. « _regenerer » ne pouvait pas
    servir ici, elle exige un compte rendu déjà écrit ; l'échec est justement
    le cas où il n'y en a pas.
    """
    config = Config.load(config_file)
    identifier = _reunion_visee(config, meeting)
    engine = writer(config)
    if engine is None:
        typer.secho(
            "Aucun rédacteur configuré : « compte_rendu.moteur » vaut « aucun ».",
            fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(1)
    try:
        gardee = store(config).read(identifier)
    except (OSError, ValueError) as trouble:
        typer.secho(f"✗ {trouble}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from trouble

    typer.secho(f"  rédaction      {identifier}…", fg=typer.colors.BLUE)
    try:
        text = regenerate_minutes(
            gardee, engine, config.conversation.disclosure
        )
    except (RuntimeError, subprocess.SubprocessError) as trouble:
        typer.secho(f"✗ {trouble}", fg=typer.colors.RED, err=True)
        typer.echo(
            "La transcription reste gardée : relance « greffier rediger » "
            "quand la cause est levée."
        )
        raise typer.Exit(1) from trouble

    path = config.paths.minutes_folder / f"{identifier}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    typer.secho(f"✓ {path}", fg=typer.colors.GREEN)
    typer.echo("« greffier envoyer » pour l'expédier.")

@application.command(name="lire")
def read_minutes(
    meeting: str = typer.Argument(None, help="Réunion (défaut : la dernière)"),
    config_file: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Enregistre le compte rendu lu à voix haute, pour l'écouter en voiture."""
    from greffier.application.render import speak_aloud

    config = Config.load(config_file)
    identifier = _reunion_visee(config, meeting)
    source = config.paths.minutes_folder / f"{identifier}.md"
    if not source.exists():
        typer.secho(f"Aucun compte rendu pour {identifier}.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    output = config.paths.data / "lectures" / f"{identifier}.m4a"
    try:
        produit = speak_aloud(source.read_text(encoding="utf-8"), output)
    except (RuntimeError, subprocess.CalledProcessError) as trouble:
        typer.secho(f"✗ {trouble}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from trouble
    typer.secho(f"✓ {produit}", fg=typer.colors.GREEN)

@application.command()
def tickets(
    meeting: str = typer.Argument(None, help="Réunion (défaut : la dernière)"),
    config_file: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Propose les tickets à créer à partir du compte rendu.

    Proposés, **pas créés** : un ticket ouvert à tort dans un outil partagé coûte
    plus cher à retirer qu'à ne pas créer. La relecture est le garde-fou.
    """
    from greffier.application.tickets import offer

    config = Config.load(config_file)
    identifier = _reunion_visee(config, meeting)
    source = config.paths.minutes_folder / f"{identifier}.md"
    if not source.exists():
        typer.secho(f"Aucun compte rendu pour {identifier}.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    engine = writer(config)
    if engine is None:
        typer.secho("Aucun rédacteur configuré. « greffier configurer ».",
                    fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    proposition = offer(source.read_text(encoding="utf-8"), engine)
    output = config.paths.data / "tickets" / f"{identifier}.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(proposition.as_markdown(identifier), encoding="utf-8")

    for ticket in proposition.tickets:
        details = " · ".join(x for x in (ticket.assigne, ticket.echeance) if x)
        typer.secho(f"  • {ticket.title}", fg=typer.colors.GREEN)
        if details:
            typer.echo(f"    {details}")
    if not proposition.tickets:
        typer.echo("Aucune action décidée dans ce compte rendu.")
    typer.echo(f"\n{output}")

@application.command()
def archiver(
    tout: bool = typer.Option(False, "--tout", help="Tous les enregistrements traités"),
    config_file: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Compresse les enregistrements déjà transcrits.

    Un WAV de réunion pèse 115 Mo par heure ; en Opus, une dizaine. La
    transcription étant faite, l'audio ne sert plus qu'à réécouter un passage.
    """
    from greffier.application.render import archiver as compresser

    config = Config.load(config_file)
    magasin = store(config)
    identifiers = magasin.lister() if tout else magasin.lister()[:1]
    gagne = 0
    for identifier in identifiers:
        detail = magasin.read(identifier)
        if not detail.audio.exists() or detail.audio.suffix == ".opus":
            continue
        avant = detail.audio.stat().st_size
        produit = compresser(detail.audio)
        gagne += avant - produit.stat().st_size
        typer.echo(f"  {identifier} → {produit.name}")
    if gagne:
        typer.secho(f"✓ {gagne / 1024**2:.0f} Mo libérés", fg=typer.colors.GREEN)
    else:
        typer.echo("Rien à compresser.")

@application.command("envoyer")
def send(
    meeting: str = typer.Argument(None, help="Réunion (défaut : la dernière)"),
    recipient: str = typer.Option(None, "--a", help="À qui envoyer ce compte rendu"),
    sans_demander: bool = typer.Option(False, "--oui", help="Envoyer sans confirmation"),
    avec_transcription: bool = typer.Option(
        False, "--avec-transcription", help="Joindre la transcription intégrale"
    ),
    config_file: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Envoie par courriel un compte rendu déjà rédigé, après relecture.

    Rien ne part avant que tu aies vu à qui, avec quel objet et quelles pièces.
    Un compte rendu de réunion cite des personnes et des décisions : l'expédier
    au mauvais destinataire ne se rattrape pas, et un envoi silencieux au fil du
    traitement ne laisse aucune occasion de relire.
    """
    from greffier.wiring import _sender

    config = Config.load(config_file)
    identifier = _reunion_visee(config, meeting)
    source = config.paths.minutes_folder / f"{identifier}.md"
    if not source.exists():
        typer.secho(f"Aucun compte rendu pour {identifier}.", fg=typer.colors.RED, err=True)
        typer.echo("« greffier traiter » d'abord, ou « greffier reunions » pour la liste.")
        raise typer.Exit(1)

    minutes = source.read_text(encoding="utf-8")
    target = recipient or config.minutes.recipient
    if not target:
        target = typer.prompt("À qui envoyer ce compte rendu ?").strip()
    if "@" not in target:
        typer.secho(f"« {target} » n'est pas une adresse.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    sender = _sender(config, exiger_destinataire=False)
    if sender is None:
        typer.secho("Aucun moyen d'envoi. « greffier configurer ».",
                    fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    objet = title(minutes, f"Compte rendu de réunion — {identifier}")
    transcription = config.paths.transcripts / f"{identifier}.txt"
    pieces = [transcription] if avec_transcription and transcription.exists() else []

    typer.echo()
    typer.secho("  À        ", nl=False, bold=True)
    typer.secho(target, fg=typer.colors.CYAN)
    typer.secho("  Objet    ", nl=False, bold=True)
    typer.echo(objet)
    typer.secho("  Par      ", nl=False, bold=True)
    typer.echo(type(sender).__name__.replace("Expediteur", ""))
    typer.secho("  Pièces   ", nl=False, bold=True)
    typer.echo(", ".join(p.name for p in pieces) or "aucune (le message porte le compte rendu)")
    typer.secho("  Format   ", nl=False, bold=True)
    typer.echo("HTML mis en forme, Markdown en repli")

    sections = [x.strip().lstrip("#").strip() for x in minutes.splitlines()
                if x.strip().startswith("## ")]
    if sections:
        typer.secho("  Sections ", nl=False, bold=True)
        typer.echo(" · ".join(sections))
    typer.echo()

    if not sans_demander and not typer.confirm("Envoyer ?", default=False):
        typer.echo("Rien n'a été envoyé.")
        raise typer.Exit(0)

    try:
        sender.send(target, objet, minutes, pieces)
    except Exception as echec:
        typer.secho(f"✗ Envoi impossible : {echec}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from echec
    typer.secho(f"✓ Envoyé à {target}", fg=typer.colors.GREEN)

@application.command(hidden=True)
def watch(
    config_file: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Surveille le matériel audio pendant l'enregistrement, et s'adapte.

    Lancée seule par « greffier enregistrer », détachée : rien d'autre de
    Greffier ne tourne pendant une réunion, donc personne ne verrait un casque
    apparaître. Elle meurt avec l'enregistrement.

    Utile à la main pour observer ce qu'elle décide, d'où la commande.
    """
    from greffier.application.watch_hardware import VeilleMateriel
    from greffier.domain.devices import WatchRules, advised_mic

    config = Config.load(config_file)
    if platform.system() != "Darwin":
        typer.echo("Rien à surveiller ici : aucun périphérique agrégé à reconstruire.")
        return

    player = lister(config)
    recorder = recording(config)
    source = Path(__file__).resolve().parent.parent.parent / "macos/creer-peripheriques.swift"

    def reconstruire(mic: str) -> bool:
        if not mic or not source.exists():
            return False
        fait = subprocess.run(
            ["swift", str(source), "--mic", mic, "--casque", mic],
            capture_output=True, text=True, check=False,
        )
        return fait.returncode == 0

    def notify_user(message: str) -> None:
        NotificateurSysteme().notify("Greffier", message)

    depart = player.read()
    voulu = config.audio.mic or advised_mic(depart, config.audio.mic or "")
    def captured_size() -> int | None:
        """Les octets écrits dans le morceau en cours, pour savoir si ça avance.

        Le dernier morceau et non le premier : un changement de matériel en
        rouvre un, et c'est celui-là que ffmpeg alimente.
        """
        try:
            etat_courant = recorder.read()
        except (OSError, ValueError):
            return None
        chunks = etat_courant.chunks or ([etat_courant.audio] if etat_courant.audio else [])
        if not chunks:
            return None
        try:
            return chunks[-1].stat().st_size
        except OSError:
            return None

    def captured_level() -> float | None:
        """Le niveau du micro sur ce qui vient d'être écrit.

        Lu dans le fichier plutôt qu'en ouvrant le micro : celui-ci est déjà
        pris par la capture, et l'ouvrir une seconde fois pour le mesurer est
        le meilleur moyen de perdre les deux.
        """
        from greffier.adapters.live_levels import read_level

        try:
            etat_courant = recorder.read()
        except (OSError, ValueError):
            return None
        chunks = etat_courant.chunks or (
            [etat_courant.audio] if etat_courant.audio else []
        )
        if not chunks:
            return None
        releve = read_level(chunks[-1])
        return None if releve is None else releve.micro_db

    veilleuse = VeilleMateriel(
        recorder=recorder,
        lister=player,
        watch_rules=WatchRules(micro_voulu=voulu, agrege=config.audio.input),
        reconstruire=reconstruire,
        notify_user=notify_user,
        captured_size=captured_size,
        captured_level=captured_level,
    )
    turns = veilleuse.loop()
    typer.echo(f"Veille terminée après {turns} tours.")

@application.command("fenetre")
def window(
    config_file: Path = typer.Option(None, "--config", help="Fichier de configuration"),
) -> None:
    """Ouvre la fenêtre de Greffier : enregistrer, nommer les voix, envoyer.

    C'est l'interface complète, et la même sur les trois systèmes. Elle remplace
    l'icône de barre de menus, qui ne montrait qu'une partie de l'état et
    demandait un comportement différent par système.
    """
    from greffier.interface.startup import available

    ouvrable, message = available()
    if not ouvrable:
        typer.secho(f"✗ {message}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    from greffier.interface.window import open_it

    open_it(Config.load(config_file))
