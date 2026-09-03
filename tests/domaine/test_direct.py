"""Le fil de la réunion en direct, et sa correction.

Le défaut visé : pendant une réunion, rien ne s'affichait au fil de l'eau, donc
rien ne se corrigeait. Un nom mal attribué ne se découvrait qu'en relisant le
compte rendu, une heure trop tard.

Aucune empreinte réelle ici : des vecteurs à trois dimensions dont on connaît
les angles, ce qui rend chaque seuil vérifiable à la main.
"""

from __future__ import annotations

import pytest

from greffier.domaine.canaux import VOIX_LOCALE
from greffier.domaine.direct import (
    NOM_INDETERMINE,
    NOM_LOCAL,
    VOIX_INDETERMINEE,
    Certitude,
    Fil,
    TourDirect,
    VoixDirecte,
    blocs,
    retirer_repetition,
)
from greffier.domaine.empreintes import normaliser
from greffier.domaine.modeles import Empreinte, Intervalle, Personne, Replique


def empreinte(x: float, y: float, duree: float = 4.0) -> Empreinte:
    return normaliser([x, y, 0.0], duree_source=duree)


#: Deux vecteurs à 0,8 de cosinus : au-dessus du seuil de fusion (0,75), donc la
#: même personne aux yeux du fil.
MEME_VOIX = (empreinte(1, 0), empreinte(0.8, 0.6))
#: Cosinus nul : deux personnes, sans ambiguïté possible.
AUTRE_VOIX = empreinte(0, 1)


def replique(debut: float, fin: float, texte: str = "on cale la recette jeudi") -> Replique:
    return Replique(intervalle=Intervalle(debut, fin), texte=texte)


class TestQuiParleEnDirect:
    def test_le_micro_designe_la_personne_qui_enregistre(self) -> None:
        # Le canal, pas l'empreinte : aucun modèle n'est consulté, et la
        # certitude est celle du câblage.
        fil = Fil()
        assert fil.rattacher(empreinte=None, locale=True) == VOIX_LOCALE
        assert fil.etiquette(VOIX_LOCALE) == NOM_LOCAL
        assert fil.voix[VOIX_LOCALE].certitude is Certitude.CANAL

    def test_deux_extraits_proches_sont_la_meme_voix(self) -> None:
        fil = Fil()
        premiere = fil.rattacher(MEME_VOIX[0], locale=False)
        seconde = fil.rattacher(MEME_VOIX[1], locale=False)
        assert premiere == seconde
        assert fil.etiquette(premiere) == "Voix 1"

    def test_deux_extraits_eloignes_sont_deux_voix(self) -> None:
        fil = Fil()
        premiere = fil.rattacher(MEME_VOIX[0], locale=False)
        seconde = fil.rattacher(AUTRE_VOIX, locale=False)
        assert premiere != seconde
        assert {fil.etiquette(premiere), fil.etiquette(seconde)} == {"Voix 1", "Voix 2"}

    def test_une_bribe_trop_courte_ne_cree_pas_un_participant(self) -> None:
        # « oui », « d'accord » : trop court pour une empreinte. Les compter
        # comme des personnes ferait vingt participants à une réunion de cinq.
        fil = Fil()
        for _ in range(5):
            assert fil.rattacher(empreinte=None, locale=False) == VOIX_INDETERMINEE
        assert fil.etiquette(VOIX_INDETERMINEE) == NOM_INDETERMINE
        assert [v for v in fil.voix if v.startswith("v")] == []


class TestReconnaissanceParLaBanque:
    def test_une_voix_deja_en_banque_est_nommee_seule(self) -> None:
        marc = Personne(nom="Marc", empreintes=[empreinte(1, 0, duree=30)])
        fil = Fil(connues=[marc])
        voix = fil.rattacher(MEME_VOIX[0], locale=False)
        assert fil.voix[voix].nom == "Marc"

    def test_un_nom_venu_de_l_empreinte_s_affiche_avec_un_doute(self) -> None:
        # Le point d'interrogation est la seule chose qui distingue, à l'écran,
        # une reconnaissance d'une certitude. Sans lui, personne ne corrige.
        marc = Personne(nom="Marc", empreintes=[empreinte(1, 0, duree=30)])
        fil = Fil(connues=[marc])
        voix = fil.rattacher(MEME_VOIX[0], locale=False)
        assert fil.voix[voix].certitude is not Certitude.HUMAINE
        assert fil.etiquette(voix) == "Marc ?"

    def test_une_voix_inconnue_de_la_banque_reste_sans_nom(self) -> None:
        marc = Personne(nom="Marc", empreintes=[empreinte(1, 0, duree=30)])
        fil = Fil(connues=[marc])
        voix = fil.rattacher(AUTRE_VOIX, locale=False)
        assert fil.voix[voix].nom is None
        assert fil.etiquette(voix) == "Voix 1"

    def test_le_nom_est_redemande_quand_la_matiere_s_accumule(self) -> None:
        # Une voix reste souvent anonyme à sa première bribe : l'agrégat de deux
        # extraits peut franchir le seuil que le premier n'atteignait pas.
        # 0,65 de cosinus au premier extrait : sous le seuil de 0,70, donc rien
        # n'est affirmé. L'agrégat des deux monte à 0,83 et le franchit.
        julie = Personne(nom="Julie", empreintes=[empreinte(1, 0, duree=30)])
        fil = Fil(connues=[julie])
        voix = fil.rattacher(empreinte(0.65, 0.76), locale=False)
        assert fil.voix[voix].nom is None
        fil.rattacher(empreinte(0.95, 0.31), locale=False)
        assert fil.voix[voix].nom == "Julie"


class TestDecoupageEnBlocs:
    def test_les_phrases_qui_se_suivent_forment_un_bloc(self) -> None:
        # Une empreinte tirée de six mots ne vaut rien : on regroupe ce qui se
        # suit pour avoir de quoi reconnaître une voix.
        groupes = blocs([replique(0, 3), replique(3, 6)], locaux=[])
        assert len(groupes) == 1
        assert groupes[0].intervalle == Intervalle(0, 6)
        assert not groupes[0].locale

    def test_un_changement_de_canal_coupe_le_bloc(self) -> None:
        groupes = blocs(
            [replique(0, 3), replique(3, 6), replique(6, 9)],
            locaux=[Intervalle(2.9, 6.1)],
        )
        assert [g.locale for g in groupes] == [False, True, False]

    def test_une_phrase_a_moitie_couverte_est_locale(self) -> None:
        # Même critère que « canaux.retirer » : la moitié de la durée. Deux
        # règles différentes se contrediraient sur les chevauchements.
        groupes = blocs([replique(0, 4)], locaux=[Intervalle(0, 2.1)])
        assert groupes[0].locale
        groupes = blocs([replique(0, 4)], locaux=[Intervalle(0, 1.9)])
        assert not groupes[0].locale


class TestPasDeuxFoisLaMemePhrase:
    def test_le_recouvrement_des_tranches_n_affiche_pas_deux_fois(self) -> None:
        # Les tranches se recouvrent de 5 s pour qu'une phrase à cheval reste
        # entière dans l'une des deux. Sans ce filtre, elle s'affiche deux fois.
        fil = Fil()
        fil.inscrire(blocs([replique(0, 8)], [])[0], VOIX_LOCALE)
        gardees = fil.retenir([replique(0, 8), replique(8, 12)])
        assert [r.intervalle.debut for r in gardees] == [8]

    def test_une_phrase_recoupee_plus_tot_reste_une_phrase_neuve(self) -> None:
        # Le cas mesuré à l'essai : « Il en reste exactement deux » est datée
        # 13,60 dans une tranche et 12,80 dans la suivante. Filtrer sur le seul
        # début la jetait — une phrase perdue sur six.
        fil = Fil()
        fil.inscrire(blocs([replique(4.8, 13.2)], [])[0], VOIX_LOCALE)
        gardees = fil.retenir([replique(12.8, 19.3)])
        assert [r.intervalle.debut for r in gardees] == [12.8]

    def test_la_meme_phrase_redite_a_l_identique_ne_passe_pas_deux_fois(self) -> None:
        fil = Fil()
        fil.inscrire(blocs([replique(4.8, 9.4)], [])[0], VOIX_LOCALE)
        assert fil.retenir([replique(5.26, 9.4)]) == []

    def test_une_phrase_vide_n_encombre_pas_le_fil(self) -> None:
        fil = Fil()
        assert fil.retenir([replique(0, 2, texte="  ")]) == []


class TestRecouvrementDeTexte:
    """Une phrase à cheval sur deux tranches s'affichait avec la fin de la
    précédente collée devant : « dernier. » puis « dernier. Sandy, tu peux
    nous dire… ». Le locuteur est juste, seul le texte porte un fragment en
    trop."""

    def test_le_recouvrement_exact_est_retire(self) -> None:
        precedent = "On termine avec le point sur le budget, c'est notre dernier."
        nouveau = "dernier. Sandy, tu peux nous dire où on en est ?"
        assert (
            retirer_repetition(precedent, nouveau)
            == "Sandy, tu peux nous dire où on en est ?"
        )

    def test_un_recouvrement_de_plusieurs_mots_est_retire(self) -> None:
        precedent = "On y arrive tout doucement mais sûrement"
        nouveau = "mais sûrement vers la fin de la réunion."
        assert retirer_repetition(precedent, nouveau) == "vers la fin de la réunion."

    def test_un_mot_court_partage_par_hasard_n_est_pas_retire(self) -> None:
        # « et » seul ne porte pas assez de caractères pour être une vraie
        # répétition : le couper serait un accident, pas une correction.
        precedent = "On termine avec le point sur le budget et"
        nouveau = "Et voilà comment on procède pour la suite."
        assert retirer_repetition(precedent, nouveau) == nouveau

    def test_sans_recouvrement_le_texte_est_inchange(self) -> None:
        precedent = "Bonjour à tous"
        nouveau = "On commence par le point sur la recette."
        assert retirer_repetition(precedent, nouveau) == nouveau

    def test_un_precedent_vide_ne_change_rien(self) -> None:
        assert retirer_repetition("", "Bonjour à tous") == "Bonjour à tous"

    def test_le_fil_retire_le_recouvrement_a_l_affichage(self) -> None:
        fil = Fil()
        fil.inscrire(
            blocs([replique(0, 8, texte="c'est notre dernier.")], [])[0], VOIX_LOCALE
        )
        gardees = fil.retenir(
            [replique(8, 14, texte="dernier. Sandy, tu peux nous dire où on en est ?")]
        )
        assert gardees[0].texte == "Sandy, tu peux nous dire où on en est ?"


class TestCorrection:
    def _fil_avec_deux_voix(self) -> tuple[Fil, str, str]:
        """Une réunion où deux personnes ont parlé, sans qu'on sache qui."""
        fil = Fil()
        distante = fil.rattacher(MEME_VOIX[0], locale=False)
        fil.inscrire(blocs([replique(0, 5)], [])[0], distante)
        fil.inscrire(blocs([replique(5, 9)], [])[0], VOIX_LOCALE)
        fil.rattacher(MEME_VOIX[1], locale=False)
        fil.inscrire(blocs([replique(9, 14)], [])[0], distante)
        return fil, distante, VOIX_LOCALE

    def test_corriger_une_phrase_renomme_toute_la_voix(self) -> None:
        # C'est le cas courant : quand l'outil se trompe de personne, il se
        # trompe pour tous les passages de cette voix.
        fil, distante, _ = self._fil_avec_deux_voix()
        correction = fil.corriger(numero=1, nom="Marc")
        assert correction.numeros == (1, 3)
        assert fil.etiquette(distante) == "Marc"
        assert fil.voix[distante].certitude is Certitude.HUMAINE

    def test_une_correction_verse_l_empreinte_a_la_banque(self) -> None:
        # C'est ce qui fait qu'on ne corrige qu'une fois : la réunion suivante
        # reconnaît la personne seule, et le traitement final aussi.
        fil, _, _ = self._fil_avec_deux_voix()
        correction = fil.corriger(numero=1, nom="Marc")
        assert correction.empreinte is not None

    def test_une_voix_trop_maigre_n_entre_pas_en_banque(self) -> None:
        # Apprendre une signature sur trois secondes de « d'accord » abîmerait
        # la reconnaissance des réunions suivantes.
        fil = Fil()
        voix = fil.rattacher(empreinte(1, 0, duree=2.0), locale=False)
        fil.inscrire(blocs([replique(0, 2)], [])[0], voix)
        assert fil.corriger(numero=1, nom="Marc").empreinte is None

    def test_l_empreinte_ne_defait_pas_une_correction(self) -> None:
        # Le défaut le plus vicieux à éviter : corriger un nom, puis le voir
        # revenir à la tranche suivante parce que le modèle a un avis.
        marc = Personne(nom="Marc", empreintes=[empreinte(1, 0, duree=30)])
        fil = Fil(connues=[marc])
        voix = fil.rattacher(MEME_VOIX[0], locale=False)
        fil.inscrire(blocs([replique(0, 5)], [])[0], voix)
        fil.corriger(numero=1, nom="Julie")
        fil.rattacher(MEME_VOIX[1], locale=False)
        assert fil.voix[voix].nom == "Julie"
        assert fil.etiquette(voix) == "Julie"

    def test_corriger_seulement_cette_phrase_epargne_le_reste(self) -> None:
        # Deux personnes qui se coupent : un passage est tombé dans le mauvais
        # groupe, mais le groupe lui-même est bon.
        fil, distante, _ = self._fil_avec_deux_voix()
        correction = fil.corriger(numero=3, nom="Julie", toute_la_voix=False)
        assert correction.numeros == (3,)
        assert fil.tours[0].voix == distante
        assert fil.etiquette(fil.tours[2].voix) == "Julie"

    def test_une_phrase_deplacee_rejoint_la_voix_de_cette_personne(self) -> None:
        fil, distante, locale = self._fil_avec_deux_voix()
        fil.corriger(numero=1, nom="Marc")
        fil.corriger(numero=2, nom="Marc", toute_la_voix=False)
        assert fil.tours[1].voix == distante
        assert fil.etiquette(locale) == NOM_LOCAL

    def test_deux_voix_nommees_pareil_sont_reunies(self) -> None:
        # L'outil a découpé une personne en deux, faute de matière pour la
        # recoller en direct. Lui donner deux fois le même nom la réunit.
        fil = Fil()
        premiere = fil.rattacher(empreinte(1, 0), locale=False)
        fil.inscrire(blocs([replique(0, 5)], [])[0], premiere)
        seconde = fil.rattacher(AUTRE_VOIX, locale=False)
        fil.inscrire(blocs([replique(5, 10)], [])[0], seconde)

        fil.corriger(numero=1, nom="Marc")
        correction = fil.corriger(numero=2, nom="Marc")
        assert correction.numeros == (1, 2)
        assert len({t.voix for t in fil.tours}) == 1

    def test_le_fourre_tout_ne_se_nomme_jamais_en_entier(self) -> None:
        # Il mélange les « oui » de tout le monde : lui donner un nom d'un coup
        # attribuerait à quelqu'un les réponses des autres.
        fil = Fil()
        for debut in (0.0, 5.0):
            fil.inscrire(blocs([replique(debut, debut + 2)], [])[0], VOIX_INDETERMINEE)
        correction = fil.corriger(numero=1, nom="Marc", toute_la_voix=True)
        assert correction.numeros == (1,)
        assert fil.tours[1].voix == VOIX_INDETERMINEE

    def test_un_nom_vide_ne_corrige_rien(self) -> None:
        fil, _, _ = self._fil_avec_deux_voix()
        with pytest.raises(ValueError, match="nom vide"):
            fil.corriger(numero=1, nom="   ")

    def test_corriger_une_phrase_qui_n_existe_pas_se_dit(self) -> None:
        with pytest.raises(KeyError, match="numéro 7"):
            Fil().corriger(numero=7, nom="Marc")


class TestNomsProposables:
    def test_le_menu_offre_la_reunion_puis_la_banque(self) -> None:
        # Les personnes de la réunion en cours d'abord : ce sont les plus
        # probables. Les habitués de la banque ensuite.
        fil = Fil(connues=[Personne(nom="Bertrand"), Personne(nom="Marc")])
        voix = fil.rattacher(MEME_VOIX[0], locale=False)
        fil.inscrire(blocs([replique(0, 5)], [])[0], voix)
        fil.corriger(numero=1, nom="Marc")
        assert fil.noms_proposables() == [NOM_LOCAL, "Marc", "Bertrand"]


class TestReunirDesVoix:
    """Nommer une voix du nom d'une autre les réunit — pour n voix.

    Constaté en réunion réelle le 2026-09-02 : quatre voix pour deux personnes,
    dont deux qui étaient la même à 0,79 de ressemblance. Le recollage
    automatique ne retente pas sa chance, mais une correction humaine, elle,
    réunit — et rien dans le menu ne le laissait deviner.
    """

    def _fil_a_trois_voix(self):
        fil = Fil()
        for identifiant in ("v1", "v2", "v3"):
            fil.voix[identifiant] = VoixDirecte(identifiant=identifiant,
                                                rang=int(identifiant[1]))
        for numero, voix in enumerate(("v1", "v2", "v3", "v1", "v2"), start=1):
            fil.tours.append(TourDirect(numero=numero, intervalle=Intervalle(numero, numero + 1),
                                        texte=f"phrase {numero}", voix=voix))
        return fil

    def test_deux_voix_deviennent_une(self):
        fil = self._fil_a_trois_voix()
        fil.corriger(1, "Tanguy")
        fil.corriger(2, "Tanguy")
        restantes = {t.voix for t in fil.tours if t.numero in (1, 2, 4, 5)}
        assert len(restantes) == 1, "les tours des deux voix doivent tenir ensemble"
        nommees = {v.nom for v in fil.voix.values() if v.nom and v.nom != NOM_LOCAL}
        assert nommees == {"Tanguy"}

    def test_autant_de_voix_qu_il_le_faut(self):
        """« n voix » : chaque correction replie une voix de plus sur la même."""
        fil = self._fil_a_trois_voix()
        for numero in (1, 2, 3):
            fil.corriger(numero, "Tanguy")
        assert len({t.voix for t in fil.tours}) == 1, "une seule voix pour tous les tours"
        assert len([v for v in fil.voix.values() if v.nom == "Tanguy"]) == 1

    def test_les_empreintes_des_deux_voix_sont_gardees(self):
        """C'est ce qui enrichit l'entrée versée en banque."""
        fil = self._fil_a_trois_voix()
        fil.voix["v1"].empreintes.append(empreinte(1.0, 0.0, duree=8.0))
        fil.voix["v2"].empreintes.append(empreinte(0.9, 0.1, duree=6.0))
        fil.corriger(1, "Tanguy")
        fil.corriger(2, "Tanguy")
        survivante = next(v for v in fil.voix.values() if v.nom == "Tanguy")
        assert len(survivante.empreintes) == 2
        assert survivante.secondes == pytest.approx(14.0)

    def test_une_correction_humaine_ne_se_laisse_pas_redecider(self):
        fil = self._fil_a_trois_voix()
        fil.corriger(1, "Tanguy")
        voix = next(v for v in fil.voix.values() if v.nom == "Tanguy")
        assert voix.certitude is Certitude.HUMAINE
        assert voix.certitude.ferme


class TestRecollageEnDirect:
    """La seconde chance : rejouer le seuil sur la matière accumulée.

    Mesuré sur une réunion en présentiel du 2026-09-02 : phrase à phrase, deux
    prises de parole de la même personne se ressemblent à 0,69 en médiane, sous
    le seuil de 0,75 — donc chaque reprise créait une voix, quatre pour deux
    personnes. Sur les agrégats accumulés, la même paire monte à 0,79 et deux
    personnes différentes restent à 0,63 : le seuil était bon, il n'était pas
    rejoué.
    """

    def _fil_de_deux_voix_proches(self):
        fil = Fil()
        fil.voix["v1"] = VoixDirecte(identifiant="v1", rang=1, empreintes=[
            empreinte(1.0, 0.0, duree=12.0), empreinte(0.98, 0.2, duree=10.0)])
        fil.voix["v2"] = VoixDirecte(identifiant="v2", rang=2, empreintes=[
            empreinte(0.99, 0.14, duree=11.0)])
        fil.voix["v3"] = VoixDirecte(identifiant="v3", rang=3, empreintes=[
            empreinte(0.0, 1.0, duree=14.0)])
        for numero, voix in enumerate(("v1", "v2", "v3", "v1"), start=1):
            fil.tours.append(TourDirect(numero=numero, intervalle=Intervalle(numero, numero + 1),
                                        texte=f"phrase {numero}", voix=voix))
        return fil

    def test_deux_voix_proches_sont_reunies(self):
        fil = self._fil_de_deux_voix_proches()
        faits = fil.recoller()
        assert faits, "le recollage doit agir"
        assert len({t.voix for t in fil.tours if t.numero in (1, 2, 4)}) == 1
        assert "v3" in fil.voix, "une voix distincte reste distincte"

    def test_les_empreintes_suivent(self):
        fil = self._fil_de_deux_voix_proches()
        avant = sum(len(v.empreintes) for v in fil.voix.values())
        fil.recoller()
        assert sum(len(v.empreintes) for v in fil.voix.values()) == avant

    def test_deux_noms_humains_differents_ne_se_reunissent_jamais(self):
        """Une correction humaine ne se laisse pas défaire par une mesure."""
        fil = self._fil_de_deux_voix_proches()
        fil.voix["v1"].nom, fil.voix["v1"].certitude = "Sophie", Certitude.HUMAINE
        fil.voix["v2"].nom, fil.voix["v2"].certitude = "Kerann", Certitude.HUMAINE
        assert fil.recoller() == []
        assert {"v1", "v2"} <= set(fil.voix)

    def test_une_voix_nommee_absorbe_une_voix_anonyme(self):
        fil = self._fil_de_deux_voix_proches()
        fil.voix["v1"].nom, fil.voix["v1"].certitude = "Sophie", Certitude.HUMAINE
        fil.recoller()
        survivantes = {v.nom for v in fil.voix.values() if v.nom and v.nom != NOM_LOCAL}
        assert survivantes == {"Sophie"}, "le nom humain survit à la réunion"

    def test_rien_a_recoller_ne_casse_rien(self):
        fil = Fil()
        fil.voix["v1"] = VoixDirecte(identifiant="v1", empreintes=[empreinte(1.0, 0.0)])
        assert fil.recoller() == []

    def test_la_voix_locale_et_le_fourre_tout_sont_epargnes(self):
        """« Toi » est désigné par le canal, le fourre-tout mélange tout le monde."""
        fil = Fil()
        fil.voix[VOIX_LOCALE].empreintes.append(empreinte(1.0, 0.0, duree=12.0))
        fil.voix[VOIX_INDETERMINEE] = VoixDirecte(
            identifiant=VOIX_INDETERMINEE, empreintes=[empreinte(0.99, 0.14, duree=12.0)])
        assert fil.recoller() == []


class TestPlafondDesParticipants:
    """Annoncer combien de personnes parlent empêche d'en inventer.

    Mesuré en présentiel le 2026-09-02 : phrase à phrase, deux prises de parole
    de la même personne se ressemblent à 0,69 en médiane, sous le seuil de
    0,75. Chaque tour de parole créait donc une voix — vingt et une pour trois
    personnes. Le nombre de participants est la seule chose que la machine ne
    peut pas déduire de l'audio.
    """

    def _fil(self, personnes=None):
        fil = Fil(personnes=personnes)
        fil.voix["v1"] = VoixDirecte(identifiant="v1", rang=1,
                                     empreintes=[empreinte(1.0, 0.0, duree=8.0)])
        fil.voix["v2"] = VoixDirecte(identifiant="v2", rang=2,
                                     empreintes=[empreinte(0.0, 1.0, duree=8.0)])
        # Les voix sont posées à la main : sans avancer le compteur, la voix
        # suivante réutiliserait « v1 » et écraserait l'existante.
        fil.suite = 3
        return fil

    def test_sans_annonce_une_voix_de_plus_est_creee(self):
        """Le comportement d'avant, qu'il faut garder quand on ne sait pas."""
        fil = self._fil()
        etrangere = empreinte(0.62, 0.55, duree=3.0)
        assert fil.rattacher(etrangere, locale=False) not in ("v1", "v2")

    def test_au_complet_l_empreinte_rejoint_la_plus_proche(self):
        fil = self._fil(personnes=2)
        # Plus proche de v1 que de v2, sans atteindre le seuil de recollage.
        penchee = empreinte(0.9, 0.4, duree=3.0)
        assert fil.rattacher(penchee, locale=False) == "v1"
        assert len(fil._nommables()) == 2, "aucune voix de plus"

    def test_l_autre_cote_va_bien_a_l_autre_voix(self):
        fil = self._fil(personnes=2)
        assert fil.rattacher(empreinte(0.4, 0.9, duree=3.0), locale=False) == "v2"

    def test_sous_le_plafond_on_cree_encore(self):
        fil = self._fil(personnes=4)
        assert fil.rattacher(empreinte(0.62, 0.55, duree=3.0), locale=False) not in ("v1", "v2")

    def test_la_voix_locale_compte_parmi_les_participants(self):
        """Le micro désigne déjà celui qui enregistre : il ne prend pas une des
        voix à répartir. Sa présence se lit sur ses tours, jamais sur ses
        empreintes — rien n'est prélevé sur la voix locale."""
        fil = self._fil(personnes=3)
        fil.tours.append(TourDirect(numero=1, intervalle=Intervalle(0, 2),
                                    texte="je parle", voix=VOIX_LOCALE))
        # Trois participants dont celui qui enregistre : deux voix distantes
        # attendues, deux existent, le plafond est donc atteint.
        assert fil.rattacher(empreinte(0.9, 0.4, duree=3.0), locale=False) == "v1"

    def test_sans_la_voix_locale_le_plafond_laisse_une_place(self):
        fil = self._fil(personnes=3)
        assert fil.rattacher(empreinte(0.62, 0.55, duree=3.0), locale=False) \
            not in ("v1", "v2")

    def test_ni_la_voix_locale_ni_le_fourre_tout_ne_comptent(self):
        fil = self._fil(personnes=2)
        fil.voix[VOIX_INDETERMINEE] = VoixDirecte(identifiant=VOIX_INDETERMINEE)
        nommables = {v.identifiant for v in fil._nommables()}
        assert nommables == {"v1", "v2"}


class TestPlancherDeMatiere:
    """Une bribe ne fonde pas une personne.

    Mesuré sur une réunion réelle du 2026-09-02 : les voix qui portaient la
    réunion sont nées sur 3,0 à 7,3 s de parole, les parasites sur 1,0 et 1,5 s
    — « lui. », « C'est ça. », « Trop bien. ». Trente des cent soixante phrases
    duraient moins d'une seconde et demie.
    """

    def _fil(self):
        fil = Fil()
        fil.voix["v1"] = VoixDirecte(identifiant="v1", rang=1,
                                     empreintes=[empreinte(1.0, 0.0, duree=8.0)])
        fil.suite = 2
        return fil

    def test_une_bribe_rejoint_la_voix_la_plus_proche(self):
        fil = self._fil()
        bribe = empreinte(0.62, 0.55, duree=1.0)
        assert fil.rattacher(bribe, locale=False) == "v1", "aucune voix inventée"

    def test_une_prise_de_parole_franche_peut_fonder_une_voix(self):
        fil = self._fil()
        etrangere = empreinte(0.62, 0.55, duree=4.0)
        assert fil.rattacher(etrangere, locale=False) not in ("v1",)

    def test_une_bribe_sans_aucune_voix_va_au_fourre_tout(self):
        """Elle attend qu'une vraie voix existe, au lieu d'en fonder une."""
        fil = Fil()
        assert fil.rattacher(empreinte(1.0, 0.0, duree=0.8), locale=False) \
            == VOIX_INDETERMINEE

    def test_le_plancher_reste_sous_la_plus_petite_voix_reelle(self):
        """3,0 s est la plus courte prise de parole ayant fondé une vraie voix."""
        from greffier.domaine.direct import MATIERE_MINIMALE_VOIX

        assert 1.5 < MATIERE_MINIMALE_VOIX < 3.0
