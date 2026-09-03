"""Traiter une réunion enregistrée : de l'audio au compte rendu envoyé.

Ce module ne connaît aucun outil. Il reçoit des ports, les appelle dans l'ordre,
applique les règles du domaine et rend un résultat. C'est ce qui permet de le
tester entièrement avec des doublures, sans audio, sans modèle et sans réseau —
et de savoir que la logique est juste indépendamment de whisper ou d'Ollama.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from greffier.domaine import empreintes as voix_domaine
from greffier.domaine import noms as noms_domaine
from greffier.domaine.attribution import voix_de
from greffier.domaine.generiques import est_un_generique
from greffier.domaine.modeles import Intervalle, Phase, Replique, TourDeParole
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

    @property
    def mots(self) -> int:
        return sum(len(r.texte.split()) for r in self.repliques)

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
    personnes: int | None = None
    pas_des_prenoms: frozenset[str] = frozenset()
    destinataire: str = ""
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
                resultat.avertissements.append(
                    "Aucun son système capté : seule ta voix est transcrite."
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

    def _identifier_voix(self, audio: Path, tours: list[TourDeParole]) -> list[TourDeParole]:
        """Recolle les voix sur-découpées par la segmentation.

        La segmentation éclate volontiers une personne en plusieurs groupes —
        27 voix pour 6 participants sur une réunion réelle. Sans ce recollage,
        le compte rendu invente des participants.
        """
        if self.extracteur is None:
            return tours
        par_voix: dict[str, list[Intervalle]] = {}
        for tour in tours:
            par_voix.setdefault(tour.voix, []).append(tour.intervalle)
        empreintes = {
            voix: self.extracteur.extraire_intervalles(audio, intervalles)
            for voix, intervalles in par_voix.items()
        }
        appartenance = voix_domaine.fusionner_voix(empreintes)
        return [
            TourDeParole(t.intervalle, appartenance.get(t.voix, t.voix), t.source) for t in tours
        ]

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
        mentions = noms_domaine.reperer_mentions(repliques, self.pas_des_prenoms)
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
    ) -> Resultat:
        # Ce que la veille a constaté du matériel : le rédacteur doit le savoir
        # avant d'écrire, pas après.
        self.evenements_materiel = list(evenements_materiel or [])
        resultat = Resultat(audio=audio, evenements_materiel=self.evenements_materiel)

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
        resultat.repliques = [r for r in brutes if not est_un_generique(r.texte)]
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
        self._avertir_couverture(resultat)

        if self.redacteur is None:
            self._phase(Phase.TERMINE, "Transcription prête, aucun rédacteur configuré.")
            return resultat

        self._phase(Phase.REDACTION, f"{resultat.mots} mots transcrits. Rédaction…")
        # Le rédacteur apprend d'abord ce que la transcription a perdu : sans
        # cela, le compte rendu présente comme complet un texte qui ne l'est pas.
        from greffier.application.restituer import (
            entete_contexte,
            entete_fiabilite,
            entete_materiel,
            rendre_transcription,
        )

        duree = resultat.tours[-1].intervalle.fin if resultat.tours else 0.0
        # Les voix qui ont réellement porté la réunion, nommées ou non : sans ce
        # compte, un compte rendu dont aucune voix n'est nommée ne disait rien
        # de qui était présent — constaté à l'usage.
        entendues = {t.voix for t in resultat.tours if t.voix}
        entete = (
            entete_contexte(audio.stem, duree,
                            noms=[resultat.noms[v] for v in entendues if v in resultat.noms],
                            voix_entendues=len(entendues))
            + entete_materiel(self.evenements_materiel)
            + entete_fiabilite(resultat)
        )
        resultat.compte_rendu = self.redacteur.rediger(
            rendre_transcription(resultat, entete)
        )

        # Gardé **avant** l'envoi : un serveur de courriel indisponible ne doit
        # pas faire perdre une heure de transcription et sa rédaction.
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
            from greffier.adaptateurs.depot_fichiers import depuis_resultat

            resultat.fichier_maitre = self.depot.enregistrer(
                depuis_resultat(resultat, duree))
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
        from greffier.adaptateurs import gabarit_courriel

        assert self.expediteur is not None
        self.expediteur.envoyer(
            self.destinataire,
            gabarit_courriel.sujet(
                resultat.compte_rendu, f"Compte rendu de réunion — {audio.stem}"
            ),
            resultat.compte_rendu,
            [],
        )
