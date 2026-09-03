"""Suivre la réunion pendant qu'elle a lieu, et se laisser corriger.

Deux processus, un fichier. Celui qui écoute transcrit, attribue et **ajoute** au
journal ; la fenêtre le lit au fil de l'eau et y dépose ses corrections. Aucun
démon, aucun port réseau : le même choix que pour l'état de l'enregistrement, et
pour la même raison — un fichier survit à tout, et se relit après un plantage.

Pourquoi deux processus plutôt qu'un fil dans la fenêtre : whisper occupe
plusieurs secondes de calcul par tranche, ce qui gèlerait l'interface, et un
modèle qui tombe ne doit pas emporter la fenêtre avec lui. C'est arrivé — voir
le rapport de plantage cité dans `fenetre`.

Le journal est **en ajout seul**, y compris pour les corrections : une
correction ne réécrit pas les lignes passées, elle en publie une qui dit ce
qu'elle change. La fenêtre applique la même règle à son propre exemplaire du
fil, ce qui la rend réactive au clic sans attendre la tranche suivante.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from greffier.domaine.canaux import soustraire
from greffier.domaine.direct import (
    Bloc,
    Certitude,
    Correction,
    Fil,
    TourDirect,
    VoixDirecte,
    blocs,
)
from greffier.domaine.empreintes import agreger
from greffier.domaine.modeles import Empreinte, Intervalle, Personne, Replique
from greffier.ports import sortants

#: Sous cette durée, une tranche ne porte pas de quoi transcrire : le modèle y
#: invente plus qu'il n'entend.
TRANCHE_MINIMALE_S = 3.0

#: Genres de lignes du journal. Un flux d'événements, pas un état : c'est ce qui
#: permet de n'écrire qu'en ajout et de relire à n'importe quel moment.
GENRE_TOUR = "tour"
GENRE_CORRECTION = "correction"
GENRE_ETAT = "etat"
#: Deux voix reconnues comme la même personne, une fois la matière accumulée.
GENRE_REUNION = "reunion"


@dataclass(frozen=True, slots=True)
class Position:
    """Où en est l'enregistrement, d'après ce qui est réellement écrit.

    L'horloge de la réunion ne convient pas : elle retire les pauses, alors que
    le fichier, lui, ne contient que ce qui a été capté. Les deux divergent de
    tout le temps d'arrêt, et transcrire à la position de l'horloge relit un
    passage déjà vu — ou lit au-delà du fichier, donc rien.
    """

    morceau: Path
    #: Secondes présentes dans ce morceau.
    ecrit: float
    #: Secondes cumulées des morceaux précédents, pour un horodatage de réunion.
    decalage: float

    @property
    def globale(self) -> float:
        return self.decalage + self.ecrit


def position(
    morceaux: list[Path], duree: Callable[[Path], float | None]
) -> Position | None:
    """La position dans le dernier morceau, et le temps déjà enregistré avant.

    Un enregistrement se coupe en plusieurs morceaux dès qu'on met en pause ou
    qu'on branche un casque. Le direct suit **le dernier**, et cumule les
    précédents pour que l'horodatage affiché reste celui de la réunion.
    """
    presents = [m for m in morceaux if duree(m) is not None]
    if not presents:
        return None
    decalage = 0.0
    for morceau in presents[:-1]:
        decalage += duree(morceau) or 0.0
    dernier = presents[-1]
    return Position(morceau=dernier, ecrit=duree(dernier) or 0.0, decalage=decalage)


# ------------------------------------------------------------------ le journal


def fichiers(dossier: Path, identifiant: str) -> tuple[Path, Path]:
    """Le journal du direct et le dépôt des corrections, pour une réunion.

    Deux fichiers plutôt qu'un : celui qui écoute écrit dans le premier et lit le
    second, la fenêtre fait l'inverse. Aucun des deux n'écrit là où l'autre écrit,
    donc aucun verrou à poser.
    """
    return (
        dossier / f"{identifiant}.jsonl",
        dossier / f"{identifiant}.corrections.jsonl",
    )


def _ligne_tour(tour: TourDirect, voix: VoixDirecte) -> dict[str, Any]:
    """Ce qu'une phrase publie d'elle-même.

    L'état de la voix voyage avec chaque phrase : la fenêtre peut alors se
    reconstruire depuis n'importe quel point du journal, sans supposer avoir vu
    les lignes précédentes.
    """
    return {
        "genre": GENRE_TOUR,
        "numero": tour.numero,
        "debut": round(tour.intervalle.debut, 2),
        "fin": round(tour.intervalle.fin, 2),
        "texte": tour.texte,
        "voix": tour.voix,
        "nom": voix.nom,
        "certitude": voix.certitude.value,
        "rang": voix.rang,
    }


def _ligne_correction(correction: Correction) -> dict[str, Any]:
    return {
        "genre": GENRE_CORRECTION,
        "nom": correction.nom,
        "voix": correction.voix,
        "numeros": list(correction.numeros),
    }


def _ligne_reunion(source: str, cible: str) -> dict[str, Any]:
    return {"genre": GENRE_REUNION, "voix": source, "vers": cible}


def ajouter(journal: Path, lignes: list[dict[str, Any]]) -> None:
    """Ajoute au journal, une ligne par événement.

    En ajout et non réécrit : la fenêtre peut le suivre sans jamais tomber sur
    un fichier à moitié écrit, et une interruption ne perd pas ce qui précède.
    """
    if not lignes:
        return
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open("a", encoding="utf-8") as flux:
        for ligne in lignes:
            flux.write(json.dumps(ligne, ensure_ascii=False) + "\n")


def lire_depuis(journal: Path, position_octets: int = 0) -> tuple[list[dict[str, Any]], int]:
    """Les lignes ajoutées depuis la dernière lecture, et où reprendre.

    Une lecture incrémentale, parce que la fenêtre relit quatre fois par
    seconde : relire une heure de réunion à chaque fois coûterait pour rien.
    Une ligne incomplète — le fichier est en cours d'écriture — est laissée pour
    la fois suivante.
    """
    if not journal.exists():
        return [], position_octets
    try:
        with journal.open("rb") as flux:
            flux.seek(position_octets)
            brut = flux.read()
    except OSError:
        return [], position_octets
    if not brut:
        return [], position_octets
    complet = brut.rfind(b"\n")
    if complet < 0:
        return [], position_octets
    lignes: list[dict[str, Any]] = []
    for texte in brut[: complet + 1].decode("utf-8", errors="replace").splitlines():
        if not texte.strip():
            continue
        try:
            ligne = json.loads(texte)
        except json.JSONDecodeError:
            continue
        if isinstance(ligne, dict):
            lignes.append(ligne)
    return lignes, position_octets + complet + 1


def rejouer(lignes: list[dict[str, Any]], fil: Fil | None = None) -> Fil:
    """Reconstruit le fil depuis le journal, pour l'afficher.

    La fenêtre travaille ainsi sur les mêmes objets que le processus qui écoute,
    donc avec les mêmes règles de correction — sans jamais charger un modèle.
    """
    fil = fil if fil is not None else Fil()
    for ligne in lignes:
        genre = ligne.get("genre")
        if genre == GENRE_TOUR:
            _rejouer_tour(fil, ligne)
        elif genre == GENRE_CORRECTION:
            _rejouer_correction(fil, ligne)
        elif genre == GENRE_REUNION:
            _rejouer_reunion(fil, ligne)
    return fil


def _rejouer_reunion(fil: Fil, ligne: dict[str, Any]) -> None:
    """Rejoue une réunion de voix : les tours de la source passent à la cible.

    La fenêtre reconstruit le fil depuis le journal, sans jamais calculer
    d'empreinte : il lui faut donc le **résultat** du recollage, pas de quoi le
    refaire.
    """
    source, cible = str(ligne.get("voix", "")), str(ligne.get("vers", ""))
    if not source or not cible or source == cible:
        return
    for tour in fil.tours:
        if tour.voix == source:
            tour.voix = cible
    avalee = fil.voix.pop(source, None)
    gardee = fil.voix.get(cible)
    if avalee is not None and gardee is not None:
        gardee.empreintes.extend(avalee.empreintes)
        # Le nom le plus sûr des deux survit : une voix anonyme absorbée par une
        # voix nommée ne doit pas effacer ce nom, ni l'inverse.
        if not gardee.certitude.ferme and avalee.certitude.ferme:
            gardee.nom, gardee.certitude = avalee.nom, avalee.certitude


def _rejouer_tour(fil: Fil, ligne: dict[str, Any]) -> None:
    identifiant = str(ligne.get("voix", ""))
    if not identifiant:
        return
    voix = fil.voix.get(identifiant)
    if voix is None:
        voix = VoixDirecte(identifiant=identifiant)
        fil.voix[identifiant] = voix
    # Une correction déjà appliquée ne se laisse pas défaire par une ligne plus
    # ancienne : c'est la règle du domaine, la fenêtre ne la contourne pas.
    if not voix.certitude.ferme:
        voix.nom = ligne.get("nom")
        voix.certitude = Certitude(ligne.get("certitude", Certitude.INCONNUE.value))
        voix.rang = int(ligne.get("rang", 0))
    numero = int(ligne.get("numero", len(fil.tours) + 1))
    if any(t.numero == numero for t in fil.tours):
        return
    debut, fin = float(ligne.get("debut", 0.0)), float(ligne.get("fin", 0.0))
    fil.tours.append(TourDirect(
        numero=numero,
        intervalle=Intervalle(debut, max(debut, fin)),
        texte=str(ligne.get("texte", "")),
        voix=identifiant,
    ))
    fil.jusqu_a = max(fil.jusqu_a, fin)


def _rejouer_correction(fil: Fil, ligne: dict[str, Any]) -> None:
    numeros = [int(n) for n in ligne.get("numeros", [])]
    nom = str(ligne.get("nom", "")).strip()
    if not nom or not numeros:
        return
    connus = {t.numero for t in fil.tours}
    for numero in numeros:
        if numero in connus:
            fil.corriger(numero, nom, toute_la_voix=len(numeros) > 1)
            return


# ----------------------------------------------------- les corrections humaines


def demander(demandes: Path, numero: int, nom: str, toute_la_voix: bool = True) -> None:
    """Dépose une correction pour le processus qui écoute.

    La fenêtre l'applique déjà à son propre affichage : ce fichier sert à ce que
    les tranches suivantes en tiennent compte, et à ce que l'empreinte entre en
    banque de voix.
    """
    demandes.parent.mkdir(parents=True, exist_ok=True)
    with demandes.open("a", encoding="utf-8") as flux:
        flux.write(json.dumps(
            {"numero": numero, "nom": nom, "toute_la_voix": toute_la_voix},
            ensure_ascii=False,
        ) + "\n")


# ------------------------------------------------------------------- le suivi


@dataclass
class Suivi:
    """Attribue et publie ce qui se dit, tranche après tranche.

    Ne transcrit pas lui-même : les répliques lui arrivent, parce que la veille
    des propositions les utilise aussi et qu'il serait absurde de transcrire deux
    fois la même tranche.
    """

    fil: Fil
    journal: Path
    demandes: Path
    canaux: sortants.LecteurDeCanaux | None = None
    extracteur: sortants.ExtracteurEmpreintes | None = None
    banque: sortants.BanqueDeVoix | None = None
    #: Position déjà lue dans le fichier des demandes.
    _lues: int = field(default=0, repr=False)
    #: Voix déjà versées en banque, et sous quel nom. Une correction est souvent
    #: saisie avant que la voix ait de quoi être apprise : on repasse.
    _appris: dict[str, str] = field(default_factory=dict, repr=False)

    def accueillir(
        self, tranche: Path, repliques: list[Replique], decalage: float
    ) -> list[TourDirect]:
        """Attribue les phrases d'une tranche et les publie.

        `repliques` est daté dans la tranche ; `decalage` remet à l'heure de la
        réunion. Les deux repères sont nécessaires : l'empreinte se prélève dans
        la tranche, l'affichage se fait à l'heure de la réunion.
        """
        self.appliquer_les_demandes()
        locaux = self.canaux.passages_locaux(tranche) if self.canaux else []
        globaux = [
            Intervalle(x.debut + decalage, x.fin + decalage) for x in locaux
        ]
        recalees = [
            Replique(
                intervalle=Intervalle(
                    r.intervalle.debut + decalage, r.intervalle.fin + decalage
                ),
                texte=r.texte, voix=r.voix, source=r.source,
            )
            for r in repliques
        ]
        gardees = self.fil.retenir(recalees)
        if not gardees:
            return []

        nouveaux: list[TourDirect] = []
        lignes: list[dict[str, Any]] = []
        for bloc in blocs(gardees, globaux):
            empreinte = self._empreinte(tranche, bloc, locaux, decalage)
            voix = self.fil.rattacher(empreinte, bloc.locale)
            for tour in self.fil.inscrire(bloc, voix):
                nouveaux.append(tour)
                lignes.append(_ligne_tour(tour, self.fil.voix[voix]))
        # Le recollage, maintenant que la tranche a versé sa matière : c'est là
        # que deux voix nées d'empreintes courtes se révèlent être la même
        # personne. Sans cette seconde chance, chaque reprise de parole créait
        # une voix — mesuré, 0,69 de ressemblance phrase à phrase contre 0,79
        # sur les agrégats, pour un seuil à 0,75.
        for source, cible in self.fil.recoller():
            lignes.append(_ligne_reunion(source, cible))
        ajouter(self.journal, lignes)
        self.apprendre_les_voix_nommees()
        return nouveaux

    def _empreinte(
        self, tranche: Path, bloc: Bloc, locaux: list[Intervalle], decalage: float
    ) -> Empreinte | None:
        """L'empreinte d'un passage distant, prélevée sur ce qui est vraiment distant.

        Rien n'est prélevé sur la voix locale : le micro l'a déjà identifiée, et
        dépenser du calcul pour confirmer ce qui est certain n'apporte rien.

        Les portions locales sont **ôtées** de l'extrait avant le prélèvement.
        La transcription coupe à la phrase, pas au changement de locuteur : sans
        ce nettoyage, 0,6 s de voix locale restée en tête d'un extrait de 1,5 s
        suffisait à faire de la même personne deux participants — mesuré, et
        c'est ce qui empêchait une correction de se propager.
        """
        if bloc.locale or self.extracteur is None:
            return None
        dans_la_tranche = Intervalle(
            max(0.0, bloc.intervalle.debut - decalage),
            max(0.0, bloc.intervalle.fin - decalage),
        )
        morceaux = soustraire(dans_la_tranche, locaux)
        if not morceaux:
            return None
        try:
            trouvees = self.extracteur.extraire_intervalles(tranche, morceaux)
        except (RuntimeError, OSError, ValueError):
            # Un extrait que le modèle refuse ne doit pas interrompre la
            # réunion : la phrase s'affiche sans nom, et se corrige d'un clic.
            return None
        if not trouvees:
            return None
        return trouvees[0] if len(trouvees) == 1 else agreger(trouvees)

    # ------------------------------------------------------------ corrections

    def appliquer_les_demandes(self) -> list[Correction]:
        """Prend en compte ce que la fenêtre a corrigé depuis la dernière fois.

        Deux conséquences, et la seconde est celle qui compte : les tranches
        suivantes portent le bon nom, et l'empreinte entre en **banque de voix**.
        C'est ce qui fait que le compte rendu final retrouve la personne tout
        seul, sans qu'on ait à recorriger après la réunion.
        """
        lignes, self._lues = lire_depuis(self.demandes, self._lues)
        faites: list[Correction] = []
        confirmations: list[dict[str, Any]] = []
        for ligne in lignes:
            correction = self._appliquer(ligne)
            if correction is None:
                continue
            faites.append(correction)
            confirmations.append(_ligne_correction(correction))
        ajouter(self.journal, confirmations)
        self.apprendre_les_voix_nommees()
        return faites

    def _appliquer(self, ligne: dict[str, Any]) -> Correction | None:
        try:
            return self.fil.corriger(
                numero=int(ligne["numero"]),
                nom=str(ligne["nom"]),
                toute_la_voix=bool(ligne.get("toute_la_voix", True)),
            )
        except (KeyError, ValueError, TypeError):
            # Une demande qui ne correspond à rien — journal effacé, numéro
            # inconnu — est ignorée : la réunion continue.
            return None

    def apprendre_les_voix_nommees(self) -> list[str]:
        """Verse en banque les voix qu'un humain a nommées, dès qu'elles ont de quoi.

        Une correction se saisit dès la première phrase — c'est bien le but —
        alors que l'empreinte n'a pas encore la matière du seuil. Refuser une
        fois pour toutes revenait à perdre la correction : elle s'affichait,
        puis ne servait ni à la réunion suivante, ni au compte rendu. On repasse
        donc à chaque tranche, jusqu'à ce qu'il y ait de quoi apprendre.
        """
        if self.banque is None:
            return []
        appris: list[str] = []
        for voix in self.fil.voix.values():
            if voix.certitude is not Certitude.HUMAINE or voix.nom is None:
                continue
            if self._appris.get(voix.identifiant) == voix.nom:
                continue
            empreinte = self.fil.empreinte_a_apprendre(voix)
            if empreinte is None:
                continue
            with contextlib.suppress(OSError):
                self.banque.enregistrer(voix.nom, empreinte)
                self._appris[voix.identifiant] = voix.nom
                appris.append(voix.nom)
        return appris

    def annoncer(self, message: str, actif: bool = True) -> None:
        """Dit à la fenêtre ce que le direct peut faire, ou pourquoi il ne peut pas.

        Sans cela, un modèle absent se traduisait par un onglet vide, qui se lit
        comme « personne ne parle » plutôt que comme « rien n'écoute ».
        """
        ajouter(self.journal, [{"genre": GENRE_ETAT, "message": message, "actif": actif}])


def personnes_connues(banque: sortants.BanqueDeVoix | None) -> list[Personne]:
    """La banque de voix, ou rien si elle n'est pas lisible.

    Le direct doit démarrer même sans banque : c'est le cas de la première
    réunion, où personne n'est encore connu.
    """
    if banque is None:
        return []
    try:
        return banque.personnes()
    except OSError:
        return []
