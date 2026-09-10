"""Décider si la capture avance encore, pendant que la réunion a lieu.

Le contrôle de silence de la chaîne de traitement arrive **après** : une réunion
de deux heures enregistrée à vide ne se découvrait qu'au moment de la
transcrire, quand il n'y a plus rien à rattraper. La veille du matériel, elle,
regardait les branchements et non le résultat — un périphérique parfaitement
présent peut ne rien capter.

Le signal retenu est le plus sûr qui existe : **le fichier grossit-il ?** Il ne
demande aucun traitement du son, il coûte un `stat`, et il couvre ce qui casse
vraiment une réunion — le processus de capture mort, le périphérique disparu, un
disque plein. Un micro branché mais muet est un autre problème, que le fil du
direct montre déjà en restant vide.

Ce module ne lit aucun fichier : il reçoit des tailles et rend une phrase.
"""

from __future__ import annotations

from dataclasses import dataclass

TOURS_AVANT_ALERTE = 3

@dataclass
class SurveillanceDeCapture:
    """Suit la taille du fichier en cours et dit quand la capture a cessé.

    Alerte **une seule fois** par épisode : répéter à chaque tour noierait le
    message dans son propre bruit. Si la capture reprend, la surveillance se
    réarme — un branchement peut l'avoir interrompue le temps d'un morceau.
    """

    tours_immobiles: int = 0
    alertee: bool = False
    _taille: int | None = None

    def observe(self, bytes_read: int) -> str:
        """Rend ce qu'il faut signaler, ou une chaîne vide s'il n'y a rien à dire."""
        precedente, self._taille = self._taille, bytes_read
        if precedente is None:
            return ""
        if bytes_read > precedente:
            self.tours_immobiles = 0
            self.alertee = False
            return ""

        self.tours_immobiles += 1
        if self.tours_immobiles < TOURS_AVANT_ALERTE or self.alertee:
            return ""
        self.alertee = True
        return (
            "L'enregistrement n'avance plus : aucun son n'a été écrit depuis "
            f"{self.tours_immobiles * 4} secondes. Vérifie le micro et "
            "l'autorisation d'accès, puis relance la réunion."
        )
