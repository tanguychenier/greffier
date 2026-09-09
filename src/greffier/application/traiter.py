"""Traiter une réunion enregistrée : de l'audio au compte rendu envoyé.

Ce module ne connaît aucun outil. Il reçoit des ports, les appelle dans l'ordre,
applique les règles du domaine et rend un résultat. C'est ce qui permet de le
tester entièrement avec des doublures, sans audio, sans modèle et sans réseau —
et de savoir que la logique est juste indépendamment de whisper ou d'Ollama.
"""

from __future__ import annotations

import contextlib
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from greffier.domaine import empreintes as voix_domaine
from greffier.domaine import noms as noms_domaine
from greffier.domaine import profils
from greffier.domaine.attribution import voix_de
from greffier.domaine.compte_rendu import titre as titre_du_compte_rendu
from greffier.domaine.generiques import est_un_generique, est_une_annotation
from greffier.domaine.langue import ProfilLinguistique
from greffier.domaine.modeles import (
    Empreinte,
    Intervalle,
    Phase,
    Replique,
    TourDeParole,
)
from greffier.domaine.profils.neutre import NEUTRE
from greffier.domaine.reunion import ReunionEnregistree
from greffier.ports import sortants

# En dessous, tous les canaux sont considérés muets et il n'y a rien à
# transcrire. Le bruit de fond d'un micro ouvert dans une pièce vide tourne
# autour de -55 dB ; -70 ne retient que le vrai silence numérique.
SEUIL_MUET_DB = -70.0

# Entre les deux, on prévient sans alarmer : une heure de réunion comporte des
# silences, et 80 % de couverture reste normal. En dessous, il manque du texte.
COUVERTURE_BASSE = 0.80
# Sous ce nombre de mots, rédiger un compte rendu ne produit que du bruit. Sans
# ce contrôle, un enregistrement inaudible donnait un « compte rendu » fabriqué
# de toutes pièces, expédié par mail (constaté le 2026-08-20).
MOTS_MINIMUM = 20

#: Posé quand la boucle système est muette, retiré ou précisé une fois qu'on
#: sait combien de voix le micro portait. Une constante parce que deux endroits
#: doivent désigner exactement le même message.
AVERTISSEMENT_SANS_BOUCLE = "· boucle système muette, à préciser"


class ChaineInterrompue(Exception):
    """Arrêt volontaire de la chaîne, avec une raison présentable."""

    def __init__(self, phase: Phase, raison: str) -> None:
        super().__init__(raison)
        self.phase = phase
        self.raison = raison


@dataclass
class Resultat:
    audio: Path
    repliques: list[Replique] = field(default_factory=list)
    tours: list[TourDeParole] = field(default_factory=list)
    # voix acoustique → nom retenu
    noms: dict[str, str] = field(default_factory=dict)
    # voix → nom proposé mais pas assez étayé pour être affirmé
    propositions: dict[str, str] = field(default_factory=dict)
    compte_rendu: str = ""
    envoye: bool = False
    #: Où la chaîne a écrit, quand elle a écrit. La fenêtre et la ligne de
    #: commande l'affichent au lieu de le recalculer chacune de son côté.
    fichier_maitre: Path | None = None
    transcription_ecrite: Path | None = None
    compte_rendu_ecrit: Path | None = None
    avertissements: list[str] = field(default_factory=list)
    #: Constats de la veille sur le matériel, pour que régénérer la rédaction
    #: plus tard n'y perde pas ce que la première rédaction savait.
    evenements_materiel: list[str] = field(default_factory=list)
    #: La langue dans laquelle la réunion s'est tenue, telle que la chaîne l'a
    #: résolue. Neutre tant que la transcription n'a pas eu lieu.
    profil: ProfilLinguistique = NEUTRE
    #: Les heures d'horloge de la réunion, quand l'enregistrement les a
    #: retenues. `duree` ne les remplace pas : elle s'arrête au dernier mot.
    commencee_le: datetime | None = None
    terminee_le: datetime | None = None
    #: Le sujet de la réunion, tiré du titre du compte rendu. Le rédacteur l'a
    #: écrit après avoir lu toute la transcription : personne n'est mieux placé.
    sujet: str = ""

    @property
    def mots(self) -> int:
        """Le nombre de mots, compté comme la langue les sépare.

        Compter les espaces refusait une transcription chinoise, japonaise ou
        thaï parfaitement valable : elle tombait sous le seuil et la chaîne
        s'interrompait sur « Transcription quasi vide », avant de rédiger.
        """
        return sum(self.profil.decoupage.compter(r.texte) for r in self.repliques)

    def nom_de(self, voix: str | None) -> str:
        if voix is None:
            return "Indéterminé"
        return self.noms.get(voix, f"Personne {voix}")

    def temps_de_parole(self) -> dict[str, float]:
        """Secondes parlées par voix, du plus bavard au moins bavard."""
        cumul: dict[str, float] = {}
        for tour in self.tours:
            cumul[tour.voix] = cumul.get(tour.voix, 0.0) + tour.intervalle.duree
        return dict(sorted(cumul.items(), key=lambda x: -x[1]))

    @property
    def duree(self) -> float:
        """Durée couverte par la réunion, d'après le dernier tour de parole."""
        return self.tours[-1].intervalle.fin if self.tours else 0.0

    @property
    def couverture(self) -> float:
        """Part de l'audio qui porte effectivement du texte."""
        if self.duree <= 0:
            return 0.0
        return min(1.0, sum(r.intervalle.duree for r in self.repliques) / self.duree)

    def trous(self, minimum: float = 5.0) -> list[Intervalle]:
        """Passages d'au moins `minimum` secondes sans une seule réplique.

        Un silence peut être un vrai silence — ou du texte perdu. On les liste
        sans trancher : c'est au compte rendu de le dire honnêtement.
        """
        if not self.repliques:
            return [Intervalle(0.0, self.duree)] if self.duree > minimum else []
        manques: list[Intervalle] = []
        precedent = 0.0
        for replique in sorted(self.repliques, key=lambda r: r.intervalle.debut):
            if replique.intervalle.debut - precedent >= minimum:
                manques.append(Intervalle(precedent, replique.intervalle.debut))
            precedent = max(precedent, replique.intervalle.fin)
        if self.duree - precedent >= minimum:
            manques.append(Intervalle(precedent, self.duree))
        return manques

    def voix_significatives(self, minimum: float = 10.0) -> dict[str, float]:
        """Voix ayant assez parlé pour être un participant.

        La segmentation laisse toujours une traîne de fragments d'une seconde,
        trop courts pour porter un timbre. Les compter comme des participants
        donnerait « 22 personnes » à une réunion qui en compte cinq.
        """
        return {v: d for v, d in self.temps_de_parole().items() if d >= minimum}


@dataclass
class Traitement:
    """Assemble les ports. La composition décide de qui est branché où."""

    enregistreur: sortants.Enregistreur
    transcripteur: sortants.Transcripteur
    diariseur: sortants.Diariseur
    extracteur: sortants.ExtracteurEmpreintes | None = None
    banque: sortants.BanqueDeVoix | None = None
    redacteur: sortants.Redacteur | None = None
    expediteur: sortants.Expediteur | None = None
    journal: sortants.JournalEtat | None = None
    notificateur: sortants.Notificateur | None = None
    #: Où la réunion est **gardée**. Sans lui, une réunion traitée depuis la
    #: fenêtre ne laissait rien sur le disque : le compte rendu partait par
    #: courriel puis disparaissait, la réunion n'apparaissait dans aucune liste,
    #: et nommer une voix après coup devenait impossible. L'écriture n'existait
    #: que dans la commande en ligne, donc seulement pour qui passait par elle.
    depot: sortants.DepotReunions | None = None
    #: Où écrire la transcription lisible et le compte rendu. Absents, la
    #: chaîne reste utilisable en mémoire — ce dont les tests profitent.
    dossier_transcriptions: Path | None = None
    dossier_comptes_rendus: Path | None = None

    langue: str = "fr"
    amorce: str = ""
    #: Le glossaire du milieu, dicté au rédacteur avant la transcription. Sans
    #: lui, un sigle reste nu dans un document lu par des absents, et le
    #: rédacteur n'a aucun moyen de rétablir un terme que la transcription a
    #: déformé — il ne peut pas deviner ce qu'il n'a jamais vu écrit.
    entete_contexte: str = ""
    personnes: int | None = None
    pas_des_prenoms: frozenset[str] = frozenset()
    destinataire: str = ""
    #: Ce qui a été fait vis-à-vis des participants. Porté au compte rendu :
    #: une voix est une donnée biométrique, et ce qui n'est pas écrit n'a pas eu
    #: lieu — une mention orale ne se retrouve pas six mois plus tard.
    information: str = "rien"
    #: Constats de la veille sur le matériel, remplis par « executer ».
    evenements_materiel: list[str] = field(default_factory=list)

    # ------------------------------------------------------------- avancement

    def _phase(self, phase: Phase, message: str = "") -> None:
        if self.journal:
            self.journal.publier(phase.value, message)

    def _prevenir(self, titre: str, message: str) -> None:
        if self.notificateur:
            self.notificateur.notifier(titre, message)

    # ---------------------------------------------------------------- étapes

    def _verifier_audio(self, audio: Path, resultat: Resultat) -> None:
        """Refuse de transcrire un enregistrement muet.

        Sans ce garde-fou, whisper rend un fichier vide, le compte rendu est
        rédigé à partir de rien, et il part quand même par mail.
        """
        niveaux = self.enregistreur.niveaux(audio)
        if not niveaux:
            return
        if all(niveau < SEUIL_MUET_DB for niveau in niveaux):
            raise ChaineInterrompue(
                Phase.ECHEC,
                "Enregistrement muet sur tous les canaux. "
                "Vérifie l'autorisation micro et le périphérique d'entrée.",
            )
        # Un seul canal muet est légitime en présentiel : le son système n'existe
        # pas. On le signale sans bloquer.
        if len(niveaux) >= 2:
            if niveaux[0] < SEUIL_MUET_DB:
                resultat.avertissements.append(
                    "Ton micro est resté muet : seuls les autres participants sont transcrits."
                )
            elif max(niveaux[1:]) < SEUIL_MUET_DB:
                # Deux situations donnent le même silence, et on ne peut pas les
                # distinguer ici : une réunion en salle, où tout passe par le
                # micro et où ce silence est normal ; une visio dont la boucle
                # système n'a pas été branchée, où les autres participants sont
                # perdus. La première est de loin la plus fréquente, et annoncer
                # « seule ta voix est transcrite » y était simplement faux — le
                # micro de table entend tout le monde. `_preciser_les_canaux`
                # tranche après le découpage, quand on sait combien de personnes
                # ce micro portait.
                resultat.avertissements.append(AVERTISSEMENT_SANS_BOUCLE)

    def _preciser_les_canaux(self, resultat: Resultat) -> None:
        """Dit ce que le silence de la boucle système voulait dire.

        Une seule voix sur le micro : la boucle manquait vraiment, et les autres
        participants sont perdus. Plusieurs voix : c'est une réunion en salle, le
        micro a tout entendu, et il n'y a rien à signaler. Le rédacteur lit ces
        avertissements ; lui laisser croire qu'il manque du monde lui fait écrire
        un compte rendu prudent sur une transcription complète.
        """
        if AVERTISSEMENT_SANS_BOUCLE not in resultat.avertissements:
            return
        resultat.avertissements.remove(AVERTISSEMENT_SANS_BOUCLE)
        if len(resultat.voix_significatives()) > 1:
            return
        resultat.avertissements.append(
            "Aucun son système capté et une seule voix entendue : si la réunion "
            "était en visio, les autres participants n'ont pas été enregistrés."
        )

    def _avertir_couverture(self, resultat: Resultat) -> None:
        """Dit à l'utilisateur ce que la transcription a perdu.

        Le taux était calculé, transmis au rédacteur, et jamais montré. Sur une
        réunion réelle, 22 % de l'audio ne portait aucun texte : le compte rendu
        l'a mentionné de lui-même, l'utilisateur n'a rien vu passer.
        """
        from greffier.application.restituer import COUVERTURE_SUSPECTE, TROU_SIGNIFICATIF

        couverture = resultat.couverture
        if couverture <= 0:
            return
        trous = [t for t in resultat.trous(TROU_SIGNIFICATIF) if t.duree >= TROU_SIGNIFICATIF]
        perdu = sum(t.duree for t in trous)
        if couverture < COUVERTURE_SUSPECTE:
            resultat.avertissements.append(
                f"Couverture de {couverture * 100:.0f} % seulement : le modèle a "
                "probablement décroché sur une partie de la réunion. Le compte rendu "
                "en est averti, mais réécoute les passages qui te paraissent absents."
            )
        elif couverture < COUVERTURE_BASSE:
            resultat.avertissements.append(
                f"Couverture de {couverture * 100:.0f} % : "
                f"{perdu / 60:.0f} min sans aucun texte. Des silences peuvent "
                "l'expliquer, mais vérifie qu'il ne manque rien d'important."
            )
        elif trous:
            resultat.avertissements.append(
                f"{len(trous)} passage(s) sans texte, {perdu / 60:.0f} min au total. "
                "Un silence, ou du texte perdu : le compte rendu ne tranche pas."
            )

    def _avertir_participants(self, resultat: Resultat) -> None:
        """Dit quand le nombre annoncé contredit ce que l'audio contient.

        Annoncer un nombre force **exactement** autant de groupes : une voix de
        plus est fondue dans une autre, en silence. Sur une réunion réelle du
        2026-09-09, « 4 participants » avait été laissé dans la configuration et
        la réunion en comptait davantage — deux personnes se sont retrouvées
        confondues sans que rien ne le signale, et le compte rendu leur a prêté
        les propos l'une de l'autre.

        On ne peut pas savoir laquelle des deux valeurs est juste : le nombre
        vient d'un humain, le recollage d'une mesure. On dit l'écart.
        """
        if self.personnes is None:
            return
        entendues = len(resultat.voix_significatives())
        if entendues == 0 or entendues == self.personnes:
            return
        resultat.avertissements.append(
            f"{self.personnes} participants sont annoncés dans la configuration, "
            f"mais {entendues} voix distinctes ont été entendues. Le nombre "
            "annoncé l'emporte, donc des personnes ont pu être confondues. "
            "Laisse « participants » vide pour que le nombre soit déduit."
        )

    def _identifier_voix(self, audio: Path, tours: list[TourDeParole]) -> list[TourDeParole]:
        """Recolle les voix sur-découpées par la segmentation.

        La segmentation éclate volontiers une personne en plusieurs groupes —
        **298 voix pour trois personnes** autour d'une table, mesuré sur une
        réunion réelle de 92 minutes. Sans ce recollage, le compte rendu invente
        des participants ; avec, il en reste 23, dont 3 portent plus de dix
        secondes.
        """
        if self.extracteur is None:
            return tours
        par_voix: dict[str, list[Intervalle]] = {}
        for tour in tours:
            par_voix.setdefault(tour.voix, []).append(tour.intervalle)
        empreintes = self._empreintes_par_voix(audio, par_voix)
        appartenance = voix_domaine.recoller(empreintes)
        return [
            TourDeParole(t.intervalle, appartenance.get(t.voix, t.voix), t.source) for t in tours
        ]

    def _empreintes_par_voix(
        self, audio: Path, par_voix: dict[str, list[Intervalle]]
    ) -> dict[str, list[Empreinte]]:
        """Les empreintes de chaque voix, en ne lisant l'audio qu'une fois."""
        from greffier.application.restituer import empreintes_par_voix

        if self.extracteur is None:
            return {}
        return empreintes_par_voix(self.extracteur, audio, par_voix)

    def _reconnaitre(self, audio: Path, tours: list[TourDeParole]) -> dict[str, str]:
        """Noms venus de la banque de voix, pour les personnes déjà connues."""
        if self.extracteur is None or self.banque is None:
            return {}
        connues = self.banque.personnes()
        if not connues:
            return {}
        trouves: dict[str, str] = {}
        par_voix: dict[str, list[Intervalle]] = {}
        for tour in tours:
            par_voix.setdefault(tour.voix, []).append(tour.intervalle)
        for voix, intervalles in par_voix.items():
            extraits = self.extracteur.extraire_intervalles(audio, intervalles)
            if not extraits:
                continue
            correspondance = voix_domaine.reconnaitre(voix_domaine.agreger(extraits), connues)
            if correspondance and correspondance.sure:
                trouves[voix] = correspondance.nom
        return trouves

    def _attribuer_noms(
        self,
        repliques: list[Replique],
        tours: list[TourDeParole],
        depuis_banque: dict[str, str],
        resultat: Resultat,
    ) -> None:
        """Croise les noms prononcés et les voix reconnues.

        Une voix à la fois reconnue par son empreinte *et* nommée par un
        collègue est une certitude. Une seule des deux reste une proposition :
        mieux vaut demander que d'écrire un nom inventé dans un compte rendu.
        """
        mentions = noms_domaine.reperer_mentions(
            repliques, resultat.profil, self.pas_des_prenoms
        )
        attribution = noms_domaine.attribuer(mentions, tours)

        for voix, nom in depuis_banque.items():
            resultat.noms[voix] = nom

        for voix, trouve in attribution.certitudes.items():
            connu = depuis_banque.get(voix)
            if connu and connu.lower() != trouve.nom.lower():
                # Désaccord : la banque a été validée par un humain, elle prime,
                # mais l'écart mérite d'être signalé plutôt qu'enterré.
                resultat.avertissements.append(
                    f"La voix {voix} est reconnue comme {connu} mais nommée {trouve.nom} "
                    "pendant la réunion."
                )
                continue
            resultat.noms[voix] = trouve.nom

        for proposition in attribution.propositions:
            if proposition.voix not in resultat.noms:
                resultat.propositions[proposition.voix] = proposition.nom

    def _attacher_voix(self, repliques: list[Replique], tours: list[TourDeParole]) -> None:
        """Donne à chaque réplique la voix qui la tient nettement, sinon aucune.

        Le « nettement » est la règle du domaine : une phrase qui enjambe un
        changement de locuteur ne désigne personne plutôt que le plus bavard.
        """
        for replique in repliques:
            replique.voix = voix_de(replique.intervalle, tours)

    # ------------------------------------------------------------- exécution

    def executer(
        self,
        audio: Path,
        envoyer: bool = True,
        evenements_materiel: list[str] | None = None,
        commencee_le: datetime | None = None,
        terminee_le: datetime | None = None,
    ) -> Resultat:
        # Ce que la veille a constaté du matériel : le rédacteur doit le savoir
        # avant d'écrire, pas après.
        self.evenements_materiel = list(evenements_materiel or [])
        resultat = Resultat(
            audio=audio,
            evenements_materiel=self.evenements_materiel,
            commencee_le=commencee_le,
            terminee_le=terminee_le,
        )

        self._phase(Phase.TRANSCRIPTION, "Vérification de l'enregistrement…")
        self._verifier_audio(audio, resultat)

        self._phase(Phase.TRANSCRIPTION, "Transcription…")
        # L'audio est mis à niveau avant d'être transcrit. Un signal faible ne
        # donne pas une transcription pauvre, il en donne une inventée : sur un
        # enregistrement réel à -43 dB, le modèle a rendu « Merci d'avoir
        # regardé cette vidéo ! » là où la personne disait « Test, test de
        # réunion ». La durée ne change pas, donc les horodatages restent justes.
        with tempfile.TemporaryDirectory() as dossier:
            prepare = self.enregistreur.preparer_transcription(
                audio, Path(dossier) / f"{audio.stem}-niveau.wav"
            )
            brutes = self.transcripteur.transcrire(
                prepare, self.langue, self.amorce
            )
        # Les génériques que le modèle invente sur signal faible — « Sous-titrage
        # réalisé par… » — n'ont été prononcés par personne. Les garder revenait
        # à les attribuer à quelqu'un dans le compte rendu.
        profil = profils.pour(self.langue)
        resultat.profil = profil
        resultat.repliques = [
            r for r in brutes
            if not est_un_generique(r.texte, profil) and not est_une_annotation(r.texte)
        ]
        if resultat.mots < MOTS_MINIMUM:
            raise ChaineInterrompue(
                Phase.ECHEC,
                f"Transcription quasi vide ({resultat.mots} mots) : "
                "aucun compte rendu n'a été rédigé.",
            )

        self._phase(Phase.LOCUTEURS, "Identification des locuteurs…")
        tours = self.diariseur.decouper(audio, self.personnes)
        tours = self._identifier_voix(audio, tours)
        resultat.tours = tours
        self._attacher_voix(resultat.repliques, tours)
        self._attribuer_noms(resultat.repliques, tours, self._reconnaitre(audio, tours), resultat)
        # Après le découpage : c'est le nombre de voix entendues qui dit si le
        # silence de la boucle système était normal ou coûteux.
        self._preciser_les_canaux(resultat)
        self._avertir_couverture(resultat)
        self._avertir_participants(resultat)

        # Gardée **avant** de rédiger, et non seulement quand aucun rédacteur
        # n'est branché. Rédiger est la seule étape qui dépende d'un outil hors
        # du poste, donc celle qui échoue : une expiration du rédacteur faisait
        # perdre la transcription et l'attribution des voix d'une réunion
        # entière — 32 minutes, le 2026-09-09 — alors que tout le calcul coûteux
        # était déjà fait et juste. Gardée ici, la réunion se reprend d'un
        # « greffier rediger », sans réécouter l'audio.
        self._garder(audio, resultat)

        if self.redacteur is None:
            self._phase(Phase.TERMINE, "Transcription prête, aucun rédacteur configuré.")
            return resultat

        self._phase(Phase.REDACTION, f"{resultat.mots} mots transcrits. Rédaction…")
        # Le rédacteur apprend d'abord ce que la transcription a perdu : sans
        # cela, le compte rendu présente comme complet un texte qui ne l'est pas.
        from greffier.application.restituer import (
            entete_contexte,
            entete_fiabilite,
            entete_information,
            entete_materiel,
            rendre_transcription,
        )

        duree = resultat.tours[-1].intervalle.fin if resultat.tours else 0.0
        # Les voix qui ont réellement porté la réunion, nommées ou non : sans ce
        # compte, un compte rendu dont aucune voix n'est nommée ne disait rien
        # de qui était présent — constaté à l'usage. Les fragments en sont
        # exclus, sans quoi la ligne annonce « et 295 voix non nommées » là où
        # trois personnes étaient présentes.
        entendues = [
            v for v in resultat.voix_significatives() if v
        ] + [v for v in resultat.noms if v not in resultat.voix_significatives()]
        entete = (
            entete_contexte(audio.stem, duree,
                            noms=[resultat.noms[v] for v in entendues if v in resultat.noms],
                            voix_entendues=len(entendues),
                            commencee_le=resultat.commencee_le,
                            terminee_le=resultat.terminee_le)
            + entete_materiel(self.evenements_materiel)
            + entete_fiabilite(resultat)
            + entete_information(self.information)
            + self.entete_contexte
        )
        resultat.compte_rendu = self.redacteur.rediger(
            rendre_transcription(resultat, entete)
        )
        # La réunion se nomme d'elle-même : le titre du compte rendu a été écrit
        # après lecture de toute la transcription, et « 2026-09-09_10h05_reunion »
        # ne dit rien de ce qui s'y est passé. Le préfixe « Compte rendu : » est
        # retiré — dans une liste de réunions, il ne distingue rien.
        titre_ecrit = titre_du_compte_rendu(resultat.compte_rendu, "")
        if titre_ecrit:
            resultat.sujet = (
                titre_ecrit.split(":", 1)[-1].strip() if ":" in titre_ecrit else titre_ecrit
            )

        # Le compte rendu rejoint ce qui était déjà gardé, **avant** l'envoi :
        # un serveur de courriel indisponible ne doit pas faire perdre une
        # heure de transcription et sa rédaction.
        self._garder(audio, resultat)

        if envoyer and self.expediteur and self.destinataire:
            self._phase(Phase.ENVOI, "Envoi du compte rendu…")
            self._envoyer(audio, resultat)
            resultat.envoye = True
        elif envoyer:
            # Sauter l'envoi sans le dire laissait croire à un compte rendu parti.
            # L'interface affichait même « Compte rendu envoyé ».
            manque = ("aucun destinataire n'est configuré" if not self.destinataire
                      else "aucun moyen d'envoi n'est configuré")
            resultat.avertissements.append(
                f"Compte rendu NON envoyé : {manque}. "
                "« greffier envoyer » pour l'expédier, ou renseigne "
                "compte_rendu.destinataire dans la configuration."
            )

        self._phase(
            Phase.TERMINE,
            "Compte rendu envoyé." if resultat.envoye else "Compte rendu prêt, non envoyé.",
        )
        self._prevenir("Greffier", "Compte rendu prêt.")
        return resultat

    def _garder(self, audio: Path, resultat: Resultat) -> None:
        """Écrit le fichier maître, la transcription et le compte rendu.

        Rien n'est écrit si l'appelant n'a pas fourni où : la chaîne reste
        utilisable en mémoire, ce dont les tests d'intégration profitent.
        """
        from greffier.application.restituer import rendre_transcription

        duree = resultat.tours[-1].intervalle.fin if resultat.tours else 0.0
        if self.depot is not None:
            # Un sujet saisi à la main l'emporte, et survit donc à un
            # retraitement : c'est une correction, et une correction que la
            # chaîne écraserait ne servirait à rien.
            with contextlib.suppress(Exception):
                garde = self.depot.lire(resultat.audio.stem).sujet
                if garde:
                    resultat.sujet = garde
            resultat.fichier_maitre = self.depot.enregistrer(
                _en_reunion_enregistree(resultat, duree))
        if self.dossier_transcriptions is None:
            return
        transcription = self.dossier_transcriptions / f"{audio.stem}.txt"
        transcription.parent.mkdir(parents=True, exist_ok=True)
        transcription.write_text(rendre_transcription(resultat), encoding="utf-8")
        resultat.transcription_ecrite = transcription
        if resultat.compte_rendu and self.dossier_comptes_rendus is not None:
            compte_rendu = self.dossier_comptes_rendus / f"{audio.stem}.md"
            compte_rendu.parent.mkdir(parents=True, exist_ok=True)
            compte_rendu.write_text(resultat.compte_rendu, encoding="utf-8")
            resultat.compte_rendu_ecrit = compte_rendu

    def _envoyer(self, audio: Path, resultat: Resultat) -> None:
        """Expédie le compte rendu, sans pièce jointe.

        Le corps du message **est** le compte rendu : le joindre une seconde fois
        en fichier n'apporte rien, et expédier la transcription intégrale ferait
        circuler par courriel les propos de chacun mot à mot. « greffier envoyer
        --avec-transcription » la joint quand elle est vraiment demandée.
        """
        assert self.expediteur is not None
        self.expediteur.envoyer(
            self.destinataire,
            titre_du_compte_rendu(
                resultat.compte_rendu, f"Compte rendu de réunion — {audio.stem}"
            ),
            resultat.compte_rendu,
            [],
        )


def _en_reunion_enregistree(resultat: Resultat, duree: float) -> ReunionEnregistree:
    """Le fichier maître, depuis ce que la chaîne a produit.

    Ici et non dans l'adaptateur de dépôt : la conversion appartient au cas
    d'usage qui produit le résultat. Elle y vivait derrière un `Protocol` écrit
    pour éviter que l'adaptateur importe le cas d'usage — un contournement qui
    n'avait plus lieu d'être une fois la dépendance remise à l'endroit.
    """
    return ReunionEnregistree(
        identifiant=resultat.audio.stem,
        audio=resultat.audio,
        traitee_le=datetime.now(UTC),
        duree=duree,
        repliques=resultat.repliques,
        tours=resultat.tours,
        noms=dict(resultat.noms),
        propositions=dict(resultat.propositions),
        avertissements=list(resultat.avertissements),
        evenements_materiel=list(resultat.evenements_materiel),
        sujet=resultat.sujet,
        commencee_le=resultat.commencee_le,
        terminee_le=resultat.terminee_le,
    )
