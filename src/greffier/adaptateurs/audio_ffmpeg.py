"""Enregistrement et mesure du son, par ffmpeg.

Le seul adaptateur vraiment différent d'un système à l'autre : macOS passe par
avfoundation, Linux par PulseAudio, Windows par dshow. Le reste — mesurer les
niveaux, arrêter proprement — est commun.
"""

from __future__ import annotations

import platform
import re
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path

SYSTEME = platform.system()

# Sous ce niveau, un canal est muet. Le bruit de fond d'un micro ouvert dans une
# pièce vide tourne autour de -55 dB RMS.
SILENCE_NUMERIQUE = -120.0

_NIVEAU = re.compile(r"RMS level dB: (-?[\d.]+|-inf)")


class EnregistreurFfmpeg:
    def __init__(self, peripherique: str, duree_maximale: int = 14_400) -> None:
        self.peripherique = peripherique
        self.duree_maximale = duree_maximale

    # ------------------------------------------------------------- capture

    def _entree(self) -> list[str]:
        if SYSTEME == "Darwin":
            return ["-f", "avfoundation", "-i", f":{self._index_avfoundation()}"]
        if SYSTEME == "Linux":
            # PulseAudio et PipeWire exposent un « moniteur » de la sortie :
            # réenregistrer ce que jouent les haut-parleurs ne demande aucun
            # pilote supplémentaire, contrairement à macOS.
            return ["-f", "pulse", "-i", self.peripherique]
        return ["-f", "dshow", "-i", f"audio={self.peripherique}"]

    def _index_de(self, peripherique: str) -> str:
        """Index avfoundation d'une entrée nommée."""
        sortie = subprocess.run(
            ["ffmpeg", "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
            capture_output=True, text=True, check=False,
        ).stderr
        audio = sortie.split("AVFoundation audio devices")[-1]
        for ligne in audio.splitlines():
            trouve = re.search(r"\[(\d+)\] (.+)$", ligne)
            if trouve and trouve.group(2).strip() == peripherique:
                return trouve.group(1)
        raise RuntimeError(f"Périphérique « {peripherique} » introuvable.")

    def _index_avfoundation(self) -> str:
        """Index du périphérique dans la liste d'avfoundation, qui varie.

        ffmpeg ne sait pas ouvrir une entrée par son nom sur macOS : il faut
        traduire le nom en numéro, et ce numéro change dès qu'on branche ou
        débranche un appareil.
        """
        sortie = subprocess.run(
            ["ffmpeg", "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
            capture_output=True, text=True, check=False,
        ).stderr
        audio = sortie.split("AVFoundation audio devices")[-1]
        for ligne in audio.splitlines():
            trouve = re.search(r"\[(\d+)\] (.+)$", ligne)
            if trouve and trouve.group(2).strip() == self.peripherique:
                return trouve.group(1)
        raise RuntimeError(
            f"Périphérique « {self.peripherique} » introuvable. "
            "Crée-le dans Configuration audio et MIDI, ou change « audio.entree »."
        )

    def demarrer(self, destination: Path) -> int:
        destination.parent.mkdir(parents=True, exist_ok=True)
        processus = subprocess.Popen(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
             *self._entree(), "-t", str(self.duree_maximale),
             "-ar", "16000", "-c:a", "pcm_s16le", str(destination)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return processus.pid

    def arreter(self, processus: int) -> None:
        """Arrête par SIGINT, jamais par SIGKILL.

        ffmpeg écrit l'en-tête du fichier WAV en sortant : le tuer brutalement
        laisse un fichier que rien ne sait relire.
        """
        import os
        import time

        try:
            os.kill(processus, signal.SIGINT)
        except ProcessLookupError:
            return
        for _ in range(60):
            time.sleep(0.25)
            try:
                os.kill(processus, 0)
            except ProcessLookupError:
                return
        os.kill(processus, signal.SIGKILL)

    def preparer_transcription(self, audio: Path, destination: Path) -> Path:
        """Normalise chaque canal, puis les mélange, pour la transcription.

        Mesuré sur un enregistrement réel de treize secondes, micro à -43 dB :
        whisper rendait « Merci d'avoir regardé cette vidéo ! », une phrase qui
        n'a jamais été prononcée. Normalisé à -20 LUFS, il rend « Test, test de
        réunion, test, test, test. »

        Canal par canal, parce que le déséquilibre entre le micro et la boucle
        système atteint 12 dB en usage réel : normaliser le mélange laisserait
        la voix faible aussi faible, relativement, et c'est celle-là que le
        modèle invente.

        -20 LUFS et non -14 : à -14, la même phrase devenait « Teste au
        réunion ». Pousser trop haut écrase les transitoires.
        """
        canaux = self._canaux(audio) or 1
        if canaux == 1:
            filtre = "loudnorm=I=-20:TP=-1.5:LRA=11"
        else:
            # Chaque canal est extrait, mis à niveau, puis tout est remélangé.
            parts = "".join(
                f"[0:a]pan=mono|c0=c{i},loudnorm=I=-20:TP=-1.5:LRA=11[c{i}];"
                for i in range(canaux)
            )
            entrees = "".join(f"[c{i}]" for i in range(canaux))
            filtre = f"{parts}{entrees}amix=inputs={canaux}:normalize=0,loudnorm=I=-20:TP=-1.5"
        destination.parent.mkdir(parents=True, exist_ok=True)
        drapeau = "-filter_complex" if canaux > 1 else "-af"
        fait = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(audio),
             drapeau, filtre, "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
             str(destination)],
            capture_output=True, text=True, check=False,
        )
        if fait.returncode != 0 or not destination.exists():
            # Une normalisation ratée ne doit pas coûter la réunion : on
            # transcrit l'original, quitte à ce que le résultat soit moins bon.
            return audio
        return destination

    def assembler(self, morceaux: list[Path], destination: Path) -> Path:
        """Recolle les morceaux, en uniformisant le nombre de canaux.

        Changer de micro change le nombre de canaux du périphérique agrégé : un
        micro mono plus BlackHole en donne trois, une entrée ligne stéréo en
        donne quatre. On ramène tout au plus petit compte commun, perte assumée
        et bien inférieure à celle de jeter les morceaux qui ne correspondent pas.

        **Chaque morceau est converti avant** d'être recollé. Le démultiplexeur
        « concat » ne convertit rien : il enchaîne les paquets bruts. Trois
        secondes de quatre canaux relues comme trois canaux en donnent quatre,
        et toute la réunion se retrouve dilatée — horodatages décalés, tours de
        parole faux. Mesuré : 6 s là où 5 étaient attendues.
        """
        presents = [m for m in morceaux if m.exists() and m.stat().st_size > 0]
        if not presents:
            raise RuntimeError("aucun morceau exploitable à recoller")
        if len(presents) == 1:
            if presents[0] != destination:
                destination.parent.mkdir(parents=True, exist_ok=True)
                presents[0].replace(destination)
            return destination

        canaux = min((self._canaux(m) for m in presents), default=1) or 1
        with tempfile.TemporaryDirectory() as dossier:
            atelier = Path(dossier)
            uniformes: list[Path] = []
            for rang, morceau in enumerate(presents):
                if self._canaux(morceau) == canaux:
                    uniformes.append(morceau)
                    continue
                converti = atelier / f"{rang:02d}.wav"
                self._executer(
                    ["-i", str(morceau), "-ac", str(canaux), "-ar", "16000",
                     "-c:a", "pcm_s16le", str(converti)],
                    "conversion d'un morceau impossible",
                )
                uniformes.append(converti)

            liste = atelier / "morceaux.txt"
            # Les chemins passent par un fichier : une apostrophe dans un nom de
            # réunion suffirait à casser une ligne de commande.
            liste.write_text(
                "".join(f"file '{m.resolve()}'\n" for m in uniformes), encoding="utf-8"
            )
            recolle = atelier / "recolle.wav"
            self._executer(
                ["-f", "concat", "-safe", "0", "-i", str(liste), "-c", "copy", str(recolle)],
                "recollage impossible",
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(recolle), str(destination))
        return destination

    def _executer(self, arguments: list[str], echec: str) -> None:
        fait = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *arguments],
            capture_output=True, text=True, check=False,
        )
        if fait.returncode != 0:
            derniere = (fait.stderr or fait.stdout).strip().splitlines()
            raise RuntimeError(echec + (f" : {derniere[-1]}" if derniere else ""))

    def _canaux(self, audio: Path) -> int:
        fait = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=channels", "-of", "csv=p=0", str(audio)],
            capture_output=True, text=True, check=False,
        )
        try:
            return int(fait.stdout.strip().split(",")[0])
        except (ValueError, IndexError):
            return 0

    # -------------------------------------------------------------- mesure

    def essayer(self, peripherique: str, secondes: float = 1.5) -> float:
        """Écoute brièvement une entrée et rend son niveau, en décibels.

        Mesuré sur un poste réel : un casque Jabra branché, reconnu, gain à 1,0,
        rendait -71,9 dB, tandis que le micro intégré rendait -48,8 dB. Le micro
        du casque était coupé par le bouton de son boîtier. Sans cette écoute,
        Greffier retenait le casque et enregistrait une heure de silence.
        """
        if SYSTEME != "Darwin":
            # Ailleurs, la capture passe par un moniteur de sortie que rien ne
            # coupe silencieusement : l'essai n'apporterait rien.
            return 0.0
        try:
            index = self._index_de(peripherique)
        except RuntimeError:
            return SILENCE_NUMERIQUE
        with tempfile.TemporaryDirectory() as dossier:
            essai = Path(dossier) / "essai.wav"
            fait = subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                 "-f", "avfoundation", "-i", f":{index}", "-t", f"{secondes}",
                 "-ar", "16000", str(essai)],
                capture_output=True, text=True, check=False,
            )
            if fait.returncode != 0 or not essai.exists():
                return SILENCE_NUMERIQUE
            mesures = self.niveaux(essai)
        return max(mesures) if mesures else SILENCE_NUMERIQUE

    def niveaux(self, audio: Path) -> list[float]:
        """Niveau RMS de chaque canal, en dB.

        Sert au garde-fou : deux canaux muets, et il n'y a rien à transcrire.
        """
        sortie = subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostats", "-v", "info", "-i", str(audio),
             "-af", "astats=measure_overall=none:measure_perchannel=RMS_level",
             "-f", "null", "-"],
            capture_output=True, text=True, check=False,
        ).stderr
        mesures = []
        for valeur in _NIVEAU.findall(sortie):
            mesures.append(
                SILENCE_NUMERIQUE if valeur == "-inf"
                else max(float(valeur), SILENCE_NUMERIQUE)
            )
        return mesures
