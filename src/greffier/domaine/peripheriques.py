"""Ce qu'il faut faire quand le matériel audio change pendant une réunion.

Un périphérique agrégé macOS référence un **matériel précis**. Brancher un
casque en cours de réunion ne le fait pas entrer dans l'agrégé, et le débrancher
en retire le micro maître : dans les deux cas la capture continue, sur le mauvais
appareil ou sur rien, sans que rien ne l'annonce.

C'est arrivé sur une réunion réelle : le casque a été branché après le début, la
voix de la personne qui enregistrait est restée 12 dB sous celle des autres,
puis a été effacée au mixage. Le compte rendu ne l'a jamais mentionnée.

Ce module ne parle ni à CoreAudio ni à ffmpeg : il compare deux états du matériel
et dit quoi faire. C'est ce qui permet d'éprouver les onze situations ci-dessous
sans brancher un seul câble.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


@dataclass(frozen=True)
class Peripherique:
    """Une entrée ou une sortie audio, telle que le système la présente."""

    nom: str
    uid: str
    entrees: int = 0
    sorties: int = 0

    @property
    def capte(self) -> bool:
        return self.entrees > 0


@dataclass(frozen=True)
class Materiel:
    """L'état du matériel audio à un instant donné."""

    peripheriques: tuple[Peripherique, ...] = ()

    def par_nom(self, nom: str) -> Peripherique | None:
        return next((p for p in self.peripheriques if p.nom == nom), None)

    def present(self, nom: str) -> bool:
        return self.par_nom(nom) is not None

    @property
    def micros(self) -> tuple[Peripherique, ...]:
        return tuple(p for p in self.peripheriques if p.capte)


class Action(Enum):
    """Ce que l'enregistrement doit faire du changement constaté."""

    RIEN = "rien"
    #: Reconstruire l'agrégé, puis reprendre la capture sur un nouveau segment.
    RECONSTRUIRE = "reconstruire"
    #: Le micro attendu a disparu et rien ne le remplace : prévenir, ne pas couper.
    ALERTER = "alerter"


@dataclass(frozen=True)
class Decision:
    action: Action
    raison: str = ""
    #: Micro à placer dans l'agrégé quand il faut le reconstruire.
    micro: str = ""
    #: Vrai quand le changement a probablement dégradé ce qui a déjà été capté.
    audio_suspect: bool = False


# Un casque USB expose micro et écouteurs sous le même nom : c'est le cas le plus
# fréquent en réunion, et celui qu'il faut privilégier dès qu'il apparaît.
def _casque_utilisable(materiel: Materiel, prefere: str) -> Peripherique | None:
    attendu = materiel.par_nom(prefere)
    if attendu is not None and attendu.capte:
        return attendu
    return None


def _micro_de_repli(materiel: Materiel, exclus: tuple[str, ...]) -> Peripherique | None:
    """Le meilleur micro disponible, hors ceux qu'on veut éviter.

    « Meilleur » veut dire : un micro qui n'est pas une boucle logicielle. Choisir
    BlackHole comme micro produirait un enregistrement où la personne qui parle
    n'est jamais captée, ce qui est exactement le défaut qu'on corrige.
    """
    candidats = [
        p for p in materiel.micros
        if p.nom not in exclus and not _est_boucle(p.nom) and not _est_agrege(p)
    ]
    if not candidats:
        return None
    # Ordre de préférence, du plus au moins probable comme micro de réunion :
    #
    #   1. un micro externe mono : c'est la forme d'un micro de casque ;
    #   2. le micro intégré : toujours là, toujours branché ;
    #   3. le reste, faute de mieux.
    #
    # Une entrée USB stéréo est presque toujours une entrée ligne de station
    # d'accueil ou d'écran, sur laquelle rien n'est branché. La préférer au
    # micro intégré donnait un enregistrement muet là où le portable aurait
    # capté la voix : constaté en débranchant un casque sur un poste réel.
    casques = [p for p in candidats if not _est_integre(p.nom) and p.entrees == 1]
    integres = [p for p in candidats if _est_integre(p.nom)]
    return (casques or integres or candidats)[0]


def _est_agrege(peripherique: Peripherique) -> bool:
    """Les périphériques que Greffier fabrique lui-même.

    L'agrégé expose trois entrées et n'est ni une boucle ni un appareil intégré :
    sans ce filtre il passait pour le meilleur micro externe disponible, et
    Greffier se proposait de se mettre lui-même dans son propre agrégé.
    """
    return peripherique.uid.startswith("com.reunions.")


def _est_boucle(nom: str) -> bool:
    return any(marque in nom.lower() for marque in ("blackhole", "loopback", "soundflower"))


def _est_integre(nom: str) -> bool:
    return any(marque in nom.lower() for marque in ("macbook", "built-in", "intégré", "integre"))


@dataclass
class Veille:
    """Suit le matériel pendant un enregistrement et dit quand réagir.

    `micro_voulu` est le micro que l'agrégé est censé porter. `agrege` est le nom
    du périphérique que ffmpeg ouvre.
    """

    micro_voulu: str
    agrege: str = "Reunion Entree"
    #: Historique des changements, pour le compte rendu et le journal.
    evenements: list[str] = field(default_factory=list)

    def examiner(self, avant: Materiel, apres: Materiel) -> Decision:
        """Compare deux états du matériel et décide."""
        if avant.peripheriques == apres.peripheriques:
            return Decision(Action.RIEN)

        voulu_avant = avant.present(self.micro_voulu)
        voulu_apres = apres.present(self.micro_voulu)

        # Le micro attendu revient : on le reprend, quoi qu'on ait fait entre-temps.
        if voulu_apres and not voulu_avant:
            self.evenements.append(f"{self.micro_voulu} branché en cours de réunion")
            return Decision(
                Action.RECONSTRUIRE,
                f"« {self.micro_voulu} » vient d'être branché : "
                "la capture reprend dessus, le début de la réunion ne l'a pas eu.",
                micro=self.micro_voulu,
                audio_suspect=True,
            )

        # Le micro attendu disparaît : sans repli, l'agrégé n'a plus de micro.
        if voulu_avant and not voulu_apres:
            self.evenements.append(f"{self.micro_voulu} débranché en cours de réunion")
            repli = _micro_de_repli(apres, exclus=(self.micro_voulu, self.agrege))
            if repli is None:
                return Decision(
                    Action.ALERTER,
                    f"« {self.micro_voulu} » a été débranché et aucun autre micro "
                    "n'est disponible : ta voix n'est plus enregistrée.",
                    audio_suspect=True,
                )
            return Decision(
                Action.RECONSTRUIRE,
                f"« {self.micro_voulu} » a été débranché : la capture reprend sur "
                f"« {repli.nom} ».",
                micro=repli.nom,
                audio_suspect=True,
            )

        # Le micro attendu est absent depuis le début, et un casque apparaît.
        if not voulu_apres:
            repli = _micro_de_repli(apres, exclus=(self.micro_voulu, self.agrege))
            avant_repli = _micro_de_repli(avant, exclus=(self.micro_voulu, self.agrege))
            if repli is not None and (avant_repli is None or repli.nom != avant_repli.nom):
                self.evenements.append(f"{repli.nom} branché en cours de réunion")
                return Decision(
                    Action.RECONSTRUIRE,
                    f"« {repli.nom} » vient d'être branché : la capture reprend dessus.",
                    micro=repli.nom,
                    audio_suspect=True,
                )

        # Le reste du matériel a bougé sans toucher au micro : un écran, une
        # enceinte. Rien à faire, mais on le note : la sortie a pu changer.
        return Decision(Action.RIEN)


#: Sous ce niveau, une entrée ne porte même pas le bruit d'une pièce calme.
#: Mesuré : un casque au micro coupé rend -78 dB, le micro intégré de la même
#: machine -58 dB dans le même silence.
PLANCHER_MUET_DB = -68.0


@dataclass(frozen=True)
class ChoixMicro:
    """Le micro retenu après écoute, et ce qu'il faut en dire."""

    nom: str
    niveau_db: float
    #: Micros écoutés et écartés, avec leur niveau, pour pouvoir l'expliquer.
    ecartes: tuple[tuple[str, float], ...] = ()
    #: Vrai quand même le meilleur candidat semble coupé.
    tous_muets: bool = False


def choisir_par_ecoute(essais: dict[str, float]) -> ChoixMicro | None:
    """Retient le micro qui capte le mieux, parmi ceux qu'on a écoutés.

    On compare plutôt que de trancher sur un seuil absolu : le bruit d'une pièce
    varie trop d'un lieu à l'autre pour qu'un chiffre fixe décide seul. Le
    plancher ne sert qu'à prévenir quand *aucun* candidat ne capte.

    Mesuré sur un poste réel : un casque Jabra branché, reconnu, gain à 1,0,
    rendait -78 dB parce que le bouton de sourdine de son boîtier était enfoncé,
    quand le micro intégré rendait -58 dB. Greffier retenait le casque et
    enregistrait une heure de silence, puis accusait l'autorisation micro.
    """
    if not essais:
        return None
    classement = sorted(essais.items(), key=lambda x: -x[1])
    nom, niveau = classement[0]
    return ChoixMicro(
        nom=nom,
        niveau_db=niveau,
        ecartes=tuple(classement[1:]),
        tous_muets=niveau < PLANCHER_MUET_DB,
    )


def candidats_a_ecouter(materiel: Materiel, prefere: str) -> list[str]:
    """Les micros qui valent une écoute, le préféré d'abord.

    BlackHole et les agrégés de Greffier sont exclus : le premier ne capte
    jamais une bouche, le second est ce qu'on est en train de construire.
    """
    utiles = [
        p.nom for p in materiel.micros
        if not _est_boucle(p.nom) and not _est_agrege(p)
    ]
    if prefere and prefere in utiles:
        utiles.remove(prefere)
        utiles.insert(0, prefere)
    # Un micro externe mono d'abord, puis l'intégré, puis le reste : même ordre
    # que le repli, pour que l'écoute confirme ou infirme ce choix.
    return sorted(
        utiles,
        key=lambda nom: (
            nom != prefere,
            _est_integre(nom),
            nom not in {p.nom for p in materiel.micros if p.entrees == 1},
        ),
    )


def casque_present(materiel: Materiel, nom: str) -> bool:
    """Raccourci lisible pour les vérifications d'avant-enregistrement."""
    return _casque_utilisable(materiel, nom) is not None


def micro_conseille(materiel: Materiel, prefere: str) -> str:
    """Micro à mettre dans l'agrégé, maintenant, au vu de ce qui est branché.

    Sert au démarrage : plutôt que de refuser de démarrer parce que le casque
    habituel est absent, on prend le meilleur micro réellement présent.
    """
    if casque_present(materiel, prefere):
        return prefere
    repli = _micro_de_repli(materiel, exclus=(prefere,))
    return repli.nom if repli else ""
