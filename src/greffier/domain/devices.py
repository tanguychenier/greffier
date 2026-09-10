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

    name: str
    uid: str
    entrees: int = 0
    sorties: int = 0

    @property
    def captured(self) -> bool:
        return self.entrees > 0

@dataclass(frozen=True)
class Materiel:
    """L'état du matériel audio à un instant donné."""

    devices: tuple[Peripherique, ...] = ()

    def by_name(self, name: str) -> Peripherique | None:
        return next((p for p in self.devices if p.name == name), None)

    def present(self, name: str) -> bool:
        return self.by_name(name) is not None

    @property
    def mics(self) -> tuple[Peripherique, ...]:
        return tuple(p for p in self.devices if p.captured)

class Action(Enum):
    """Ce que l'enregistrement doit faire du changement constaté."""

    RIEN = "rien"
    RECONSTRUIRE = "reconstruire"
    ALERTER = "alerter"

@dataclass(frozen=True)
class Decision:
    action: Action
    because: str = ""
    mic: str = ""
    audio_suspect: bool = False

# Un casque USB expose micro et écouteurs sous le même nom : c'est le cas le plus
# fréquent en réunion, et celui qu'il faut privilégier dès qu'il apparaît.
def _headset_usable(materiel: Materiel, prefere: str) -> Peripherique | None:
    attendu = materiel.by_name(prefere)
    if attendu is not None and attendu.captured:
        return attendu
    return None

def _fallback_mic(materiel: Materiel, exclus: tuple[str, ...]) -> Peripherique | None:
    """Le meilleur micro disponible, hors ceux qu'on veut éviter.

    « Meilleur » veut dire : un micro qui n'est pas une boucle logicielle. Choisir
    BlackHole comme micro produirait un enregistrement où la personne qui parle
    n'est jamais captée, ce qui est exactement le défaut qu'on corrige.
    """
    candidats = [
        p for p in materiel.mics
        if p.name not in exclus and not _is_loopback(p.name) and not _is_aggregated(p)
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
    casques = [p for p in candidats if not _est_integre(p.name) and p.entrees == 1]
    integres = [p for p in candidats if _est_integre(p.name)]
    return (casques or integres or candidats)[0]

def _is_aggregated(peripherique: Peripherique) -> bool:
    """Les périphériques que Greffier fabrique lui-même.

    L'agrégé expose trois entrées et n'est ni une boucle ni un appareil intégré :
    sans ce filtre il passait pour le meilleur micro externe disponible, et
    Greffier se proposait de se mettre lui-même dans son propre agrégé.
    """
    return peripherique.uid.startswith("com.reunions.")

def _is_loopback(name: str) -> bool:
    return any(marque in name.lower() for marque in ("blackhole", "loopback", "soundflower"))

def _est_integre(name: str) -> bool:
    return any(marque in name.lower() for marque in ("macbook", "built-in", "intégré", "integre"))

@dataclass
class WatchRules:
    """Suit le matériel pendant un enregistrement et dit quand réagir.

    `micro_voulu` est le micro que l'agrégé est censé porter. `agrege` est le nom
    du périphérique que ffmpeg ouvre.
    """

    micro_voulu: str
    agrege: str = "Reunion Entree"
    events: list[str] = field(default_factory=list)

    def examine(self, avant: Materiel, apres: Materiel) -> Decision:
        """Compare deux états du matériel et décide."""
        if avant.devices == apres.devices:
            return Decision(Action.RIEN)

        voulu_avant = avant.present(self.micro_voulu)
        voulu_apres = apres.present(self.micro_voulu)

        # Le micro attendu revient : on le reprend, quoi qu'on ait fait entre-temps.
        if voulu_apres and not voulu_avant:
            self.events.append(f"{self.micro_voulu} branché en cours de réunion")
            return Decision(
                Action.RECONSTRUIRE,
                f"« {self.micro_voulu} » vient d'être branché : "
                "la capture reprend dessus, le début de la réunion ne l'a pas eu.",
                mic=self.micro_voulu,
                audio_suspect=True,
            )

        # Le micro attendu disparaît : sans repli, l'agrégé n'a plus de micro.
        if voulu_avant and not voulu_apres:
            self.events.append(f"{self.micro_voulu} débranché en cours de réunion")
            repli = _fallback_mic(apres, exclus=(self.micro_voulu, self.agrege))
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
                f"« {repli.name} ».",
                mic=repli.name,
                audio_suspect=True,
            )

        # Le micro attendu est absent depuis le début, et un casque apparaît.
        if not voulu_apres:
            repli = _fallback_mic(apres, exclus=(self.micro_voulu, self.agrege))
            avant_repli = _fallback_mic(avant, exclus=(self.micro_voulu, self.agrege))
            if repli is not None and (avant_repli is None or repli.name != avant_repli.name):
                self.events.append(f"{repli.name} branché en cours de réunion")
                return Decision(
                    Action.RECONSTRUIRE,
                    f"« {repli.name} » vient d'être branché : la capture reprend dessus.",
                    mic=repli.name,
                    audio_suspect=True,
                )

        # Le reste du matériel a bougé sans toucher au micro : un écran, une
        # enceinte. Rien à faire, mais on le note : la sortie a pu changer.
        return Decision(Action.RIEN)

PLANCHER_MUET_DB = -68.0

@dataclass(frozen=True)
class ChoixMicro:
    """Le micro retenu après écoute, et ce qu'il faut en dire."""

    name: str
    niveau_db: float
    ecartes: tuple[tuple[str, float], ...] = ()
    tous_muets: bool = False
    casque_prefere: bool = False

def choose_by_listening(
    essais: dict[str, float], casques: frozenset[str] = frozenset()
) -> ChoixMicro | None:
    """Retient le micro qui captera le mieux **la réunion**, après écoute.

    On compare plutôt que de trancher sur un seuil absolu : le bruit d'une pièce
    varie trop d'un lieu à l'autre pour qu'un chiffre fixe décide seul. Le
    plancher ne sert qu'à prévenir quand *aucun* candidat ne capte.

    Mesuré sur un poste réel : un casque Jabra branché, reconnu, gain à 1,0,
    rendait -78 dB parce que le bouton de sourdine de son boîtier était enfoncé,
    quand le micro intégré rendait -58 dB. Greffier retenait le casque et
    enregistrait une heure de silence, puis accusait l'autorisation micro. D'où
    l'écoute.

    **Mais le plus fort à froid n'est pas le meilleur en réunion.** Le
    2026-09-09, le même Jabra a été écarté à -68 dB au profit du micro intégré
    à -49 dB : le casque était simplement posé sur le bureau, à un mètre de la
    bouche. Une fois porté, il aurait été de loin le meilleur — il l'est
    toujours, un micro de casque étant à trois centimètres de la bouche là où
    celui d'un portable est à cinquante et capte toute la pièce.

    La règle est donc : **un casque qui capte quelque chose l'emporte**, même
    plus faible. On ne se rabat sur l'intégré que si le casque est muet, ce que
    l'écoute sait dire — et c'était tout son objet.
    """
    if not essais:
        return None
    ranking = sorted(essais.items(), key=lambda x: -x[1])
    name, level = ranking[0]
    # Un casque qui n'est pas déjà premier, et qui capte : il passe devant.
    if casques:
        vivants = [
            (autre, db) for autre, db in ranking
            if autre in casques and db >= PLANCHER_MUET_DB
        ]
        if vivants and vivants[0][0] != name:
            name, level = vivants[0]
            ranking = [(name, level)] + [
                pair for pair in ranking if pair[0] != name
            ]
    return ChoixMicro(
        name=name,
        niveau_db=level,
        ecartes=tuple(ranking[1:]),
        tous_muets=max(essais.values()) < PLANCHER_MUET_DB,
        casque_prefere=bool(casques) and name in casques,
    )

def candidates_to_listen_to(materiel: Materiel, prefere: str) -> list[str]:
    """Les micros qui valent une écoute, le préféré d'abord.

    BlackHole et les agrégés de Greffier sont exclus : le premier ne capte
    jamais une bouche, le second est ce qu'on est en train de construire.
    """
    utiles = [
        p.name for p in materiel.mics
        if not _is_loopback(p.name) and not _is_aggregated(p)
    ]
    if prefere and prefere in utiles:
        utiles.remove(prefere)
        utiles.insert(0, prefere)
    # Un micro externe mono d'abord, puis l'intégré, puis le reste : même ordre
    # que le repli, pour que l'écoute confirme ou infirme ce choix.
    return sorted(
        utiles,
        key=lambda name: (
            name != prefere,
            _est_integre(name),
            name not in {p.name for p in materiel.mics if p.entrees == 1},
        ),
    )

def headset_present(materiel: Materiel, name: str) -> bool:
    """Raccourci lisible pour les vérifications d'avant-enregistrement."""
    return _headset_usable(materiel, name) is not None

def headsets_among(materiel: Materiel) -> frozenset[str]:
    """Les micros qui sont, selon toute vraisemblance, des micros de casque.

    L'indice est qu'un **même nom** capte et restitue : un casque a un écouteur
    et un micro, un micro de table n'a que le micro. Le rapprochement se fait
    par le nom et non par périphérique, parce qu'un casque USB est souvent
    présenté comme deux appareils distincts — sur ce poste, le Jabra apparaît en
    « jabra:1 » pour l'entrée et « jabra:2 » pour la sortie. Un critère
    « capte et restitue » sur un seul appareil ne l'aurait jamais reconnu.

    L'entrée doit être **mono**, et c'est ce qui sépare un casque d'une carte
    son générique. Mesuré sur ce poste : le Jabra expose une entrée à 1 canal et
    une sortie à 2, tandis qu'une « Realtek USB2.0 Audio » — station d'accueil ou
    écran — expose une entrée à 2 canaux et une sortie à 4. Sans ce critère,
    cette carte passait pour un casque et serait préférée au micro intégré alors
    que rien n'est branché dessus. `_micro_de_repli` dit déjà la même chose : une
    entrée USB stéréo est presque toujours une entrée ligne.

    Sont exclus les boucles logicielles, les agrégés fabriqués par l'outil, et
    le matériel intégré : sur un portable, le micro et les haut-parleurs portent
    des noms différents, mais l'ensemble n'est pas un casque pour autant.
    """
    sorties = {
        p.name for p in materiel.devices
        if p.sorties > 0 and not _is_loopback(p.name) and not _is_aggregated(p)
    }
    return frozenset(
        p.name for p in materiel.mics
        if p.name in sorties
        and p.entrees == 1
        and not _is_loopback(p.name) and not _is_aggregated(p)
        and not _est_integre(p.name)
    )

def advised_mic(materiel: Materiel, prefere: str) -> str:
    """Micro à mettre dans l'agrégé, maintenant, au vu de ce qui est branché.

    Sert au démarrage : plutôt que de refuser de démarrer parce que le casque
    habituel est absent, on prend le meilleur micro réellement présent.
    """
    if headset_present(materiel, prefere):
        return prefere
    repli = _fallback_mic(materiel, exclus=(prefere,))
    return repli.name if repli else ""
