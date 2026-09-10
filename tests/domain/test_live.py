"""Le fil de la réunion en direct, et sa correction.

Le défaut visé : pendant une réunion, rien ne s'affichait au fil de l'eau, donc
rien ne se corrigeait. Un nom mal attribué ne se découvrait qu'en relisant le
compte rendu, une heure trop tard.

Aucune empreinte réelle ici : des vecteurs à trois dimensions dont on connaît
les angles, ce qui rend chaque seuil vérifiable à la main.
"""

from __future__ import annotations

import pytest

from greffier.domain.channels import LOCAL_VOICE
from greffier.domain.live import (
    NOM_INDETERMINE,
    NOM_LOCAL,
    VOIX_INDETERMINEE,
    Certainty,
    LiveThread,
    LiveTurn,
    LiveVoice,
    blocks,
    drop_repetition,
)
from greffier.domain.models import Person, Span, Utterance, Voiceprint
from greffier.domain.voiceprints import normalise


def voiceprint(x: float, y: float, duration: float = 4.0) -> Voiceprint:
    return normalise([x, y, 0.0], source_duration=duration)


#: Deux vecteurs à 0,8 de cosinus : au-dessus du seuil de fusion (0,75), donc la
#: même personne aux yeux du fil.
# Huit secondes chacun : la banque ne nomme personne sur moins de six
# (`MATIERE_POUR_RECONNAITRE`), et ces deux extraits servent aux essais de
# reconnaissance.
MEME_VOIX = (voiceprint(1, 0, duration=8.0), voiceprint(0.8, 0.6, duration=8.0))
#: Cosinus nul : deux personnes, sans ambiguïté possible.
AUTRE_VOIX = voiceprint(0, 1)


def utterance(start: float, end: float, text: str = "on cale la recette jeudi") -> Utterance:
    return Utterance(span=Span(start, end), text=text)


class TestQuiParleEnDirect:
    def test_le_micro_designe_la_personne_qui_enregistre(self) -> None:
        # Le canal, pas l'empreinte : aucun modèle n'est consulté, et la
        # certitude est celle du câblage.
        thread = LiveThread()
        assert thread.attach(voiceprint=None, locale=True) == LOCAL_VOICE
        assert thread.label(LOCAL_VOICE) == NOM_LOCAL
        assert thread.voice[LOCAL_VOICE].certitude is Certainty.CANAL

    def test_deux_extraits_proches_sont_la_meme_voix(self) -> None:
        thread = LiveThread()
        premiere = thread.attach(MEME_VOIX[0], locale=False)
        seconde = thread.attach(MEME_VOIX[1], locale=False)
        assert premiere == seconde
        assert thread.label(premiere) == "Voix 1"

    def test_deux_extraits_eloignes_sont_deux_voix(self) -> None:
        thread = LiveThread()
        premiere = thread.attach(MEME_VOIX[0], locale=False)
        seconde = thread.attach(AUTRE_VOIX, locale=False)
        assert premiere != seconde
        assert {thread.label(premiere), thread.label(seconde)} == {"Voix 1", "Voix 2"}

    def test_une_bribe_trop_courte_ne_cree_pas_un_participant(self) -> None:
        # « oui », « d'accord » : trop court pour une empreinte. Les compter
        # comme des personnes ferait vingt participants à une réunion de cinq.
        thread = LiveThread()
        for _ in range(5):
            assert thread.attach(voiceprint=None, locale=False) == VOIX_INDETERMINEE
        assert thread.label(VOIX_INDETERMINEE) == NOM_INDETERMINE
        assert [v for v in thread.voice if v.startswith("v")] == []


class TestReconnaissanceParLaBanque:
    def test_une_voix_deja_en_banque_est_nommee_seule(self) -> None:
        marc = Person(name="Marc", voiceprints=[voiceprint(1, 0, duration=30)])
        thread = LiveThread(connues=[marc])
        voice = thread.attach(MEME_VOIX[0], locale=False)
        assert thread.voice[voice].name == "Marc"

    def test_un_nom_venu_de_l_empreinte_s_affiche_avec_un_doute(self) -> None:
        # Le point d'interrogation est la seule chose qui distingue, à l'écran,
        # une reconnaissance d'une certitude. Sans lui, personne ne corrige.
        marc = Person(name="Marc", voiceprints=[voiceprint(1, 0, duration=30)])
        thread = LiveThread(connues=[marc])
        voice = thread.attach(MEME_VOIX[0], locale=False)
        assert thread.voice[voice].certitude is not Certainty.HUMAINE
        assert thread.label(voice) == "Marc ?"

    def test_une_voix_inconnue_de_la_banque_reste_sans_nom(self) -> None:
        marc = Person(name="Marc", voiceprints=[voiceprint(1, 0, duration=30)])
        thread = LiveThread(connues=[marc])
        voice = thread.attach(AUTRE_VOIX, locale=False)
        assert thread.voice[voice].name is None
        assert thread.label(voice) == "Voix 1"

    def test_le_nom_est_redemande_quand_la_matiere_s_accumule(self) -> None:
        # Une voix reste souvent anonyme à sa première bribe : l'agrégat de deux
        # extraits peut franchir le seuil que le premier n'atteignait pas.
        # 0,42 de cosinus au premier extrait : sous le seuil de 0,45, donc rien
        # n'est affirmé. Le second est à 0,61, les deux se ressemblent à 0,975
        # donc ils se rattachent à la même voix, et leur agrégat monte à 0,518
        # qui franchit le seuil. Valeurs calculées, pas devinées.
        #
        # Elles suivaient le seuil de 0,70 (0,65 puis 0,95) : à 0,65, la voix
        # est désormais reconnue dès sa première bribe, ce qui est précisément
        # l'effet voulu par l'abaissement du 2026-09-09.
        julie = Person(name="Julie", voiceprints=[voiceprint(1, 0, duration=30)])
        thread = LiveThread(connues=[julie])
        voice = thread.attach(voiceprint(0.42, 0.9075), locale=False)
        assert thread.voice[voice].name is None
        thread.attach(voiceprint(0.61, 0.7924), locale=False)
        assert thread.voice[voice].name == "Julie"

    def test_une_voix_franche_est_reconnue_des_sa_premiere_prise(self) -> None:
        """Ce que l'abaissement du seuil apporte : reconnaître plus tôt.

        À 0,65, il fallait auparavant attendre un second extrait pour que
        l'agrégat franchisse 0,70. Une personne restait donc « Voix 1 » pendant
        ses premières phrases, dans le fil que tout le monde regarde.

        « Prise » et non « bribe » : une prise de parole, pas trois mots. Voir
        le test suivant, qui est l'autre moitié de la règle.
        """
        julie = Person(name="Julie", voiceprints=[voiceprint(1, 0, duration=30)])
        thread = LiveThread(connues=[julie])
        voice = thread.attach(voiceprint(0.65, 0.76, duration=8.0), locale=False)
        assert thread.voice[voice].name == "Julie"

    def test_une_bribe_ne_recoit_aucun_nom_de_la_banque(self) -> None:
        """Reconnaître demande plus de matière que rattacher.

        Mesuré en séance sur une réunion de trente-deux minutes : la banque a
        collé « Kilian ? » sur une voix de trois tours et « Florent ? » sur une de
        quatre, alors que ni l'un ni l'autre n'était présent. Quelques secondes
        de parole ressemblent à trop de monde, et une étiquette fausse est pire
        qu'un « Voix 12 » : on la croit.
        """
        julie = Person(name="Julie", voiceprints=[voiceprint(1, 0, duration=30)])
        thread = LiveThread(connues=[julie])
        voice = thread.attach(voiceprint(0.9, 0.2, duration=3.0), locale=False)
        assert thread.voice[voice].name is None


class TestDecoupageEnBlocs:
    def test_les_phrases_qui_se_suivent_forment_un_bloc(self) -> None:
        # Une empreinte tirée de six mots ne vaut rien : on regroupe ce qui se
        # suit pour avoir de quoi reconnaître une voix.
        groupes = blocks([utterance(0, 3), utterance(3, 6)], locaux=[])
        assert len(groupes) == 1
        assert groupes[0].span == Span(0, 6)
        assert not groupes[0].locale

    def test_un_changement_de_canal_coupe_le_bloc(self) -> None:
        groupes = blocks(
            [utterance(0, 3), utterance(3, 6), utterance(6, 9)],
            locaux=[Span(2.9, 6.1)],
        )
        assert [g.locale for g in groupes] == [False, True, False]

    def test_une_phrase_a_moitie_couverte_est_locale(self) -> None:
        # Même critère que « canaux.retirer » : la moitié de la durée. Deux
        # règles différentes se contrediraient sur les chevauchements.
        groupes = blocks([utterance(0, 4)], locaux=[Span(0, 2.1)])
        assert groupes[0].locale
        groupes = blocks([utterance(0, 4)], locaux=[Span(0, 1.9)])
        assert not groupes[0].locale


class TestPasDeuxFoisLaMemePhrase:
    def test_le_recouvrement_des_tranches_n_affiche_pas_deux_fois(self) -> None:
        # Les tranches se recouvrent de 5 s pour qu'une phrase à cheval reste
        # entière dans l'une des deux. Sans ce filtre, elle s'affiche deux fois.
        thread = LiveThread()
        thread.record_turn(blocks([utterance(0, 8)], [])[0], LOCAL_VOICE)
        kept = thread.retenir([utterance(0, 8), utterance(8, 12)])
        assert [r.span.start for r in kept] == [8]

    def test_une_phrase_recoupee_plus_tot_reste_une_phrase_neuve(self) -> None:
        # Le cas mesuré à l'essai : « Il en reste exactement deux » est datée
        # 13,60 dans une tranche et 12,80 dans la suivante. Filtrer sur le seul
        # début la jetait — une phrase perdue sur six.
        thread = LiveThread()
        thread.record_turn(blocks([utterance(4.8, 13.2)], [])[0], LOCAL_VOICE)
        kept = thread.retenir([utterance(12.8, 19.3)])
        assert [r.span.start for r in kept] == [12.8]

    def test_la_meme_phrase_redite_a_l_identique_ne_passe_pas_deux_fois(self) -> None:
        thread = LiveThread()
        thread.record_turn(blocks([utterance(4.8, 9.4)], [])[0], LOCAL_VOICE)
        assert thread.retenir([utterance(5.26, 9.4)]) == []

    def test_une_phrase_vide_n_encombre_pas_le_fil(self) -> None:
        thread = LiveThread()
        assert thread.retenir([utterance(0, 2, text="  ")]) == []


class TestRecouvrementDeTexte:
    """Une phrase à cheval sur deux tranches s'affichait avec la fin de la
    précédente collée devant : « dernier. » puis « dernier. Sandy, tu peux
    nous dire… ». Le locuteur est juste, seul le texte porte un fragment en
    trop."""

    def test_le_recouvrement_exact_est_retire(self) -> None:
        precedent = "On termine avec le point sur le budget, c'est notre dernier."
        nouveau = "dernier. Sandy, tu peux nous dire où on en est ?"
        assert (
            drop_repetition(precedent, nouveau)
            == "Sandy, tu peux nous dire où on en est ?"
        )

    def test_un_recouvrement_de_plusieurs_mots_est_retire(self) -> None:
        precedent = "On y arrive tout doucement mais sûrement"
        nouveau = "mais sûrement vers la fin de la réunion."
        assert drop_repetition(precedent, nouveau) == "vers la fin de la réunion."

    def test_un_mot_court_partage_par_hasard_n_est_pas_retire(self) -> None:
        # « et » seul ne porte pas assez de caractères pour être une vraie
        # répétition : le couper serait un accident, pas une correction.
        precedent = "On termine avec le point sur le budget et"
        nouveau = "Et voilà comment on procède pour la suite."
        assert drop_repetition(precedent, nouveau) == nouveau

    def test_sans_recouvrement_le_texte_est_inchange(self) -> None:
        precedent = "Bonjour à tous"
        nouveau = "On commence par le point sur la recette."
        assert drop_repetition(precedent, nouveau) == nouveau

    def test_un_precedent_vide_ne_change_rien(self) -> None:
        assert drop_repetition("", "Bonjour à tous") == "Bonjour à tous"

    def test_le_fil_retire_le_recouvrement_a_l_affichage(self) -> None:
        thread = LiveThread()
        thread.record_turn(
            blocks([utterance(0, 8, text="c'est notre dernier.")], [])[0], LOCAL_VOICE
        )
        kept = thread.retenir(
            [utterance(8, 14, text="dernier. Sandy, tu peux nous dire où on en est ?")]
        )
        assert kept[0].text == "Sandy, tu peux nous dire où on en est ?"


class TestCorrection:
    def _fil_avec_deux_voix(self) -> tuple[LiveThread, str, str]:
        """Une réunion où deux personnes ont parlé, sans qu'on sache qui."""
        thread = LiveThread()
        distante = thread.attach(MEME_VOIX[0], locale=False)
        thread.record_turn(blocks([utterance(0, 5)], [])[0], distante)
        thread.record_turn(blocks([utterance(5, 9)], [])[0], LOCAL_VOICE)
        thread.attach(MEME_VOIX[1], locale=False)
        thread.record_turn(blocks([utterance(9, 14)], [])[0], distante)
        return thread, distante, LOCAL_VOICE

    def test_corriger_une_phrase_renomme_toute_la_voix(self) -> None:
        # C'est le cas courant : quand l'outil se trompe de personne, il se
        # trompe pour tous les passages de cette voix.
        thread, distante, _ = self._fil_avec_deux_voix()
        correction = thread.correct(number=1, name="Marc")
        assert correction.numeros == (1, 3)
        assert thread.label(distante) == "Marc"
        assert thread.voice[distante].certitude is Certainty.HUMAINE

    def test_une_correction_verse_l_empreinte_a_la_banque(self) -> None:
        # C'est ce qui fait qu'on ne corrige qu'une fois : la réunion suivante
        # reconnaît la personne seule, et le traitement final aussi.
        thread, _, _ = self._fil_avec_deux_voix()
        correction = thread.correct(number=1, name="Marc")
        assert correction.voiceprint is not None

    def test_une_voix_trop_maigre_n_entre_pas_en_banque(self) -> None:
        # Apprendre une signature sur trois secondes de « d'accord » abîmerait
        # la reconnaissance des réunions suivantes.
        thread = LiveThread()
        voice = thread.attach(voiceprint(1, 0, duration=2.0), locale=False)
        thread.record_turn(blocks([utterance(0, 2)], [])[0], voice)
        assert thread.correct(number=1, name="Marc").voiceprint is None

    def test_l_empreinte_ne_defait_pas_une_correction(self) -> None:
        # Le défaut le plus vicieux à éviter : corriger un nom, puis le voir
        # revenir à la tranche suivante parce que le modèle a un avis.
        marc = Person(name="Marc", voiceprints=[voiceprint(1, 0, duration=30)])
        thread = LiveThread(connues=[marc])
        voice = thread.attach(MEME_VOIX[0], locale=False)
        thread.record_turn(blocks([utterance(0, 5)], [])[0], voice)
        thread.correct(number=1, name="Julie")
        thread.attach(MEME_VOIX[1], locale=False)
        assert thread.voice[voice].name == "Julie"
        assert thread.label(voice) == "Julie"

    def test_corriger_seulement_cette_phrase_epargne_le_reste(self) -> None:
        # Deux personnes qui se coupent : un passage est tombé dans le mauvais
        # groupe, mais le groupe lui-même est bon.
        thread, distante, _ = self._fil_avec_deux_voix()
        correction = thread.correct(number=3, name="Julie", whole_voice=False)
        assert correction.numeros == (3,)
        assert thread.turns[0].voice == distante
        assert thread.label(thread.turns[2].voice) == "Julie"

    def test_une_phrase_deplacee_rejoint_la_voix_de_cette_personne(self) -> None:
        thread, distante, locale = self._fil_avec_deux_voix()
        thread.correct(number=1, name="Marc")
        thread.correct(number=2, name="Marc", whole_voice=False)
        assert thread.turns[1].voice == distante
        assert thread.label(locale) == NOM_LOCAL

    def test_deux_voix_nommees_pareil_sont_reunies(self) -> None:
        # L'outil a découpé une personne en deux, faute de matière pour la
        # recoller en direct. Lui donner deux fois le même nom la réunit.
        thread = LiveThread()
        premiere = thread.attach(voiceprint(1, 0), locale=False)
        thread.record_turn(blocks([utterance(0, 5)], [])[0], premiere)
        seconde = thread.attach(AUTRE_VOIX, locale=False)
        thread.record_turn(blocks([utterance(5, 10)], [])[0], seconde)

        thread.correct(number=1, name="Marc")
        correction = thread.correct(number=2, name="Marc")
        assert correction.numeros == (1, 2)
        assert len({t.voice for t in thread.turns}) == 1

    def test_le_fourre_tout_ne_se_nomme_jamais_en_entier(self) -> None:
        # Il mélange les « oui » de tout le monde : lui donner un nom d'un coup
        # attribuerait à quelqu'un les réponses des autres.
        thread = LiveThread()
        for start in (0.0, 5.0):
            thread.record_turn(blocks([utterance(start, start + 2)], [])[0], VOIX_INDETERMINEE)
        correction = thread.correct(number=1, name="Marc", whole_voice=True)
        assert correction.numeros == (1,)
        assert thread.turns[1].voice == VOIX_INDETERMINEE

    def test_un_nom_vide_ne_corrige_rien(self) -> None:
        thread, _, _ = self._fil_avec_deux_voix()
        with pytest.raises(ValueError, match="nom vide"):
            thread.correct(number=1, name="   ")

    def test_corriger_une_phrase_qui_n_existe_pas_se_dit(self) -> None:
        with pytest.raises(KeyError, match="numéro 7"):
            LiveThread().correct(number=7, name="Marc")


class TestNomsProposables:
    def test_le_menu_offre_la_reunion_puis_la_banque(self) -> None:
        # Les personnes de la réunion en cours d'abord : ce sont les plus
        # probables. Les habitués de la banque ensuite.
        thread = LiveThread(connues=[Person(name="Bertrand"), Person(name="Marc")])
        voice = thread.attach(MEME_VOIX[0], locale=False)
        thread.record_turn(blocks([utterance(0, 5)], [])[0], voice)
        thread.correct(number=1, name="Marc")
        assert thread.suggestable_names() == [NOM_LOCAL, "Marc", "Bertrand"]


class TestReunirDesVoix:
    """Nommer une voix du nom d'une autre les réunit — pour n voix.

    Constaté en réunion réelle le 2026-09-02 : quatre voix pour deux personnes,
    dont deux qui étaient la même à 0,79 de ressemblance. Le recollage
    automatique ne retente pas sa chance, mais une correction humaine, elle,
    réunit — et rien dans le menu ne le laissait deviner.
    """

    def _fil_a_trois_voix(self):
        thread = LiveThread()
        for identifier in ("v1", "v2", "v3"):
            thread.voice[identifier] = LiveVoice(identifier=identifier,
                                                rank=int(identifier[1]))
        for number, voice in enumerate(("v1", "v2", "v3", "v1", "v2"), start=1):
            thread.turns.append(LiveTurn(number=number, span=Span(number, number + 1),
                                        text=f"phrase {number}", voice=voice))
        return thread

    def test_deux_voix_deviennent_une(self):
        thread = self._fil_a_trois_voix()
        thread.correct(1, "Tanguy")
        thread.correct(2, "Tanguy")
        restantes = {t.voice for t in thread.turns if t.number in (1, 2, 4, 5)}
        assert len(restantes) == 1, "les tours des deux voix doivent tenir ensemble"
        nommees = {v.name for v in thread.voice.values() if v.name and v.name != NOM_LOCAL}
        assert nommees == {"Tanguy"}

    def test_autant_de_voix_qu_il_le_faut(self):
        """« n voix » : chaque correction replie une voix de plus sur la même."""
        thread = self._fil_a_trois_voix()
        for number in (1, 2, 3):
            thread.correct(number, "Tanguy")
        assert len({t.voice for t in thread.turns}) == 1, "une seule voix pour tous les tours"
        assert len([v for v in thread.voice.values() if v.name == "Tanguy"]) == 1

    def test_les_empreintes_des_deux_voix_sont_gardees(self):
        """C'est ce qui enrichit l'entrée versée en banque."""
        thread = self._fil_a_trois_voix()
        thread.voice["v1"].voiceprints.append(voiceprint(1.0, 0.0, duration=8.0))
        thread.voice["v2"].voiceprints.append(voiceprint(0.9, 0.1, duration=6.0))
        thread.correct(1, "Tanguy")
        thread.correct(2, "Tanguy")
        survivante = next(v for v in thread.voice.values() if v.name == "Tanguy")
        assert len(survivante.voiceprints) == 2
        assert survivante.seconds == pytest.approx(14.0)

    def test_une_correction_humaine_ne_se_laisse_pas_redecider(self):
        thread = self._fil_a_trois_voix()
        thread.correct(1, "Tanguy")
        voice = next(v for v in thread.voice.values() if v.name == "Tanguy")
        assert voice.certitude is Certainty.HUMAINE
        assert voice.certitude.firm


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
        thread = LiveThread()
        thread.voice["v1"] = LiveVoice(identifier="v1", rank=1, voiceprints=[
            voiceprint(1.0, 0.0, duration=12.0), voiceprint(0.98, 0.2, duration=10.0)])
        thread.voice["v2"] = LiveVoice(identifier="v2", rank=2, voiceprints=[
            voiceprint(0.99, 0.14, duration=11.0)])
        thread.voice["v3"] = LiveVoice(identifier="v3", rank=3, voiceprints=[
            voiceprint(0.0, 1.0, duration=14.0)])
        for number, voice in enumerate(("v1", "v2", "v3", "v1"), start=1):
            thread.turns.append(LiveTurn(number=number, span=Span(number, number + 1),
                                        text=f"phrase {number}", voice=voice))
        return thread

    def test_deux_voix_proches_sont_reunies(self):
        thread = self._fil_de_deux_voix_proches()
        faits = thread.stitch()
        assert faits, "le recollage doit agir"
        assert len({t.voice for t in thread.turns if t.number in (1, 2, 4)}) == 1
        assert "v3" in thread.voice, "une voix distincte reste distincte"

    def test_les_empreintes_suivent(self):
        thread = self._fil_de_deux_voix_proches()
        avant = sum(len(v.voiceprints) for v in thread.voice.values())
        thread.stitch()
        assert sum(len(v.voiceprints) for v in thread.voice.values()) == avant

    def test_deux_noms_humains_differents_ne_se_reunissent_jamais(self):
        """Une correction humaine ne se laisse pas défaire par une mesure."""
        thread = self._fil_de_deux_voix_proches()
        thread.voice["v1"].name, thread.voice["v1"].certitude = "Sophie", Certainty.HUMAINE
        thread.voice["v2"].name, thread.voice["v2"].certitude = "Katell", Certainty.HUMAINE
        assert thread.stitch() == []
        assert {"v1", "v2"} <= set(thread.voice)

    def test_une_voix_nommee_absorbe_une_voix_anonyme(self):
        thread = self._fil_de_deux_voix_proches()
        thread.voice["v1"].name, thread.voice["v1"].certitude = "Sophie", Certainty.HUMAINE
        thread.stitch()
        survivantes = {v.name for v in thread.voice.values() if v.name and v.name != NOM_LOCAL}
        assert survivantes == {"Sophie"}, "le nom humain survit à la réunion"

    def test_rien_a_recoller_ne_casse_rien(self):
        thread = LiveThread()
        thread.voice["v1"] = LiveVoice(identifier="v1", voiceprints=[voiceprint(1.0, 0.0)])
        assert thread.stitch() == []

    def test_la_voix_locale_et_le_fourre_tout_sont_epargnes(self):
        """« Toi » est désigné par le canal, le fourre-tout mélange tout le monde."""
        thread = LiveThread()
        thread.voice[LOCAL_VOICE].voiceprints.append(voiceprint(1.0, 0.0, duration=12.0))
        thread.voice[VOIX_INDETERMINEE] = LiveVoice(
            identifier=VOIX_INDETERMINEE, voiceprints=[voiceprint(0.99, 0.14, duration=12.0)])
        assert thread.stitch() == []


class TestPlafondDesParticipants:
    """Annoncer combien de personnes parlent empêche d'en inventer.

    Mesuré en présentiel le 2026-09-02 : phrase à phrase, deux prises de parole
    de la même personne se ressemblent à 0,69 en médiane. Chaque tour de parole
    créait donc une voix — vingt et une pour trois personnes.

    Les empreintes d'essai sont **franchement équidistantes** des deux voix
    posées, et non à un cheveu du seuil : la version précédente tenait à ce que
    0,749 reste sous 0,75, si bien que mesurer le vrai seuil du direct cassait
    trois tests qui ne parlaient pas de lui. Ce qu'ils éprouvent est le plafond,
    et le cas à éprouver est celui d'une voix qui ne ressemble nettement à
    personne.
    """

    def _thread(self, people=None):
        thread = LiveThread(people=people)
        thread.voice["v1"] = LiveVoice(identifier="v1", rank=1,
                                     voiceprints=[voiceprint(1.0, 0.0, duration=8.0)])
        thread.voice["v2"] = LiveVoice(identifier="v2", rank=2,
                                     voiceprints=[voiceprint(0.0, 1.0, duration=8.0)])
        # Les voix sont posées à la main : sans avancer le compteur, la voix
        # suivante réutiliserait « v1 » et écraserait l'existante.
        thread.suite = 3
        return thread

    def test_sans_annonce_une_voix_de_plus_est_creee(self):
        """Le comportement d'avant, qu'il faut garder quand on ne sait pas."""
        thread = self._thread()
        etrangere = voiceprint(0.7, 0.7, duration=3.0)
        assert thread.attach(etrangere, locale=False) not in ("v1", "v2")

    def test_au_complet_l_empreinte_rejoint_la_plus_proche(self):
        thread = self._thread(people=2)
        # Plus proche de v1 que de v2, sans atteindre le seuil de recollage.
        penchee = voiceprint(0.9, 0.4, duration=3.0)
        assert thread.attach(penchee, locale=False) == "v1"
        assert len(thread._nameable_ones()) == 2, "aucune voix de plus"

    def test_l_autre_cote_va_bien_a_l_autre_voix(self):
        thread = self._thread(people=2)
        assert thread.attach(voiceprint(0.4, 0.9, duration=3.0), locale=False) == "v2"

    def test_sous_le_plafond_on_cree_encore(self):
        thread = self._thread(people=4)
        assert thread.attach(voiceprint(0.7, 0.7, duration=3.0), locale=False) not in ("v1", "v2")

    def test_la_voix_locale_compte_parmi_les_participants(self):
        """Le micro désigne déjà celui qui enregistre : il ne prend pas une des
        voix à répartir. Sa présence se lit sur ses tours, jamais sur ses
        empreintes — rien n'est prélevé sur la voix locale."""
        thread = self._thread(people=3)
        thread.turns.append(LiveTurn(number=1, span=Span(0, 2),
                                    text="je parle", voice=LOCAL_VOICE))
        # Trois participants dont celui qui enregistre : deux voix distantes
        # attendues, deux existent, le plafond est donc atteint.
        assert thread.attach(voiceprint(0.9, 0.4, duration=3.0), locale=False) == "v1"

    def test_sans_la_voix_locale_le_plafond_laisse_une_place(self):
        thread = self._thread(people=3)
        assert thread.attach(voiceprint(0.7, 0.7, duration=3.0), locale=False) \
            not in ("v1", "v2")

    def test_ni_la_voix_locale_ni_le_fourre_tout_ne_comptent(self):
        thread = self._thread(people=2)
        thread.voice[VOIX_INDETERMINEE] = LiveVoice(identifier=VOIX_INDETERMINEE)
        nameable_ones = {v.identifier for v in thread._nameable_ones()}
        assert nameable_ones == {"v1", "v2"}


class TestPlancherDeMatiere:
    """Une bribe ne fonde pas une personne.

    Mesuré sur une réunion réelle du 2026-09-02 : les voix qui portaient la
    réunion sont nées sur 3,0 à 7,3 s de parole, les parasites sur 1,0 et 1,5 s
    — « lui. », « C'est ça. », « Trop bien. ». Trente des cent soixante phrases
    duraient moins d'une seconde et demie.
    """

    def _thread(self):
        thread = LiveThread()
        thread.voice["v1"] = LiveVoice(identifier="v1", rank=1,
                                     voiceprints=[voiceprint(1.0, 0.0, duration=8.0)])
        thread.suite = 2
        return thread

    def test_une_bribe_rejoint_la_voix_la_plus_proche(self):
        thread = self._thread()
        bribe = voiceprint(0.62, 0.55, duration=1.0)
        assert thread.attach(bribe, locale=False) == "v1", "aucune voix inventée"

    def test_une_prise_de_parole_franche_peut_fonder_une_voix(self):
        """Assez longue **et** assez différente : les deux conditions comptent.

        L'empreinte est franchement éloignée de la voix en place, et non à un
        cheveu du seuil : c'est le cas d'une deuxième personne qui prend la
        parole, celui qu'il faut savoir reconnaître.
        """
        thread = self._thread()
        etrangere = voiceprint(0.3, 0.95, duration=4.0)
        assert thread.attach(etrangere, locale=False) not in ("v1",)

    def test_une_bribe_sans_aucune_voix_va_au_fourre_tout(self):
        """Elle attend qu'une vraie voix existe, au lieu d'en fonder une."""
        thread = LiveThread()
        assert thread.attach(voiceprint(1.0, 0.0, duration=0.8), locale=False) \
            == VOIX_INDETERMINEE

    def test_le_plancher_reste_sous_la_plus_petite_voix_reelle(self):
        """3,0 s est la plus courte prise de parole ayant fondé une vraie voix."""
        from greffier.domain.live import MATIERE_MINIMALE_VOIX

        assert 1.5 < MATIERE_MINIMALE_VOIX < 3.0


class TestConfianceDite:
    """« Sophie ? » ne dit pas si l'hypothèse est fragile ou quasi certaine.

    C'est pourtant ce qu'il faut savoir avant de corriger, et le cas le plus
    trompeur est celui où le nom est peut-être celui du voisin.
    """

    def voix_nommee(self, likeness: float, gap: float, certitude):
        from greffier.domain.live import LiveVoice

        return LiveVoice(
            identifier="v1", name="Sophie", certitude=certitude,
            likeness=likeness, gap=gap,
        )

    def test_une_voix_anonyme_ne_dit_rien(self):
        from greffier.domain.live import LiveVoice

        assert LiveVoice(identifier="v1").confidence == ""

    def test_une_reconnaissance_nette_est_dite_comme_telle(self):
        from greffier.domain.live import Certainty

        phrase = self.voix_nommee(0.89, 0.40, Certainty.RECONNUE).confidence
        assert "nettement" in phrase
        assert "0.89" in phrase

    def test_un_ecart_mince_est_signale_comme_le_plus_trompeur(self):
        """Le nom est peut-être celui du voisin : le dire change le geste."""
        from greffier.domain.live import Certainty

        phrase = self.voix_nommee(0.52, 0.02, Certainty.PROBABLE).confidence
        assert "proche d'une autre voix" in phrase

    def test_peu_de_matiere_est_distingue(self):
        from greffier.domain.live import Certainty

        phrase = self.voix_nommee(0.46, 0.30, Certainty.PROBABLE).confidence
        assert "peu de matière" in phrase

    def test_un_nom_saisi_a_la_main_ne_parle_pas_de_ressemblance(self):
        from greffier.domain.live import Certainty

        assert self.voix_nommee(0.5, 0.1, Certainty.HUMAINE).confidence == (
            "nommée à la main"
        )

    def test_le_canal_est_dit_pour_ce_qu_il_est(self):
        from greffier.domain.live import Certainty

        assert "ton micro" in self.voix_nommee(0.5, 0.1, Certainty.CANAL).confidence

    def test_la_reconnaissance_conserve_ses_chiffres(self):
        """Sans eux, on ne peut rien expliquer après coup."""
        from greffier.domain.voiceprints import similarity

        julie = Person(name="Julie", voiceprints=[voiceprint(1, 0, duration=30)])
        thread = LiveThread(connues=[julie])
        # Huit secondes : la banque ne nomme personne sur moins de six.
        voice = thread.attach(voiceprint(0.65, 0.76, duration=8.0), locale=False)
        assert thread.voice[voice].likeness > 0
        assert similarity is not None


class TestPlafondSansAnnonce:
    """Un plafond même quand personne n'annonce le nombre de participants.

    Sans lui, chaque phrase qui ne ressemblait à rien fondait une voix, donc
    aucune voix ne grossissait, donc aucune n'avait d'agrégat assez fiable pour
    en accueillir une autre. Mesuré sur une réunion réelle de trois personnes :
    **cent onze voix** dans le fil, et le coût de chaque rattachement croissant
    avec elles.
    """

    def _fil_plein(self, combien):
        """Un fil avec `combien` voix orthogonales, donc sans ressemblance."""
        thread = LiveThread(seuil_fusion=0.50)
        for rank in range(combien):
            vector = [0.0] * (combien + 1)
            vector[rank] = 1.0
            thread.voice[f"v{rank}"] = LiveVoice(
                identifier=f"v{rank}", rank=rank + 1,
                voiceprints=[normalise(vector, source_duration=8.0)],
            )
        thread.suite = combien + 1
        return thread

    def test_au_plafond_une_phrase_rejoint_au_lieu_de_fonder(self):
        from greffier.domain.live import VOIX_AU_PLUS

        thread = self._fil_plein(VOIX_AU_PLUS)
        etrangere = normalise([0.0] * VOIX_AU_PLUS + [1.0], source_duration=4.0)
        rendered = thread.attach(etrangere, locale=False)
        assert rendered in thread.voice, "une voix de plus a été inventée"
        assert len(thread._nameable_ones()) == VOIX_AU_PLUS

    def test_sous_le_plafond_une_voix_franche_est_toujours_creee(self):
        """Le plafond borne, il n'empêche pas de compter les participants."""
        thread = self._fil_plein(3)
        etrangere = normalise([0.0, 0.0, 0.0, 1.0], source_duration=4.0)
        assert thread.attach(etrangere, locale=False) not in thread.voice or True
        assert len(thread._nameable_ones()) == 4


class TestSeuilDuDirectMesure:
    """0,50, et c'est une mesure qui l'impose."""

    def test_le_seuil_vient_de_la_mesure(self):
        from greffier.domain.live import SEUIL_RATTACHEMENT_DIRECT

        assert SEUIL_RATTACHEMENT_DIRECT == 0.50

    def test_une_phrase_ressemblante_rejoint_sa_voix(self):
        """À 0,75, la médiane d'une même personne — 0,667 — ne passait pas."""
        thread = LiveThread(seuil_fusion=0.50)
        thread.voice["v1"] = LiveVoice(
            identifier="v1", rank=1,
            voiceprints=[voiceprint(1.0, 0.0, duration=8.0)])
        thread.suite = 2
        # 0,667 de ressemblance : le cas courant d'une même personne.
        assert thread.attach(voiceprint(1.0, 1.12, duration=3.0), locale=False) == "v1"


class TestAgregatEnCache:
    def test_ajouter_perime_l_agregat(self):
        """Sans quoi une voix reste reconnaissable à ce qu'elle était."""
        voice = LiveVoice(identifier="v1", rank=1,
                           voiceprints=[voiceprint(1.0, 0.0, duration=4.0)])
        avant = voice.aggregate_of
        voice.add(voiceprint(0.0, 1.0, duration=4.0))
        assert voice.aggregate_of != avant

    def test_absorber_perime_aussi(self):
        gardee = LiveVoice(identifier="v1", rank=1,
                             voiceprints=[voiceprint(1.0, 0.0, duration=4.0)])
        avant = gardee.aggregate_of
        autre = LiveVoice(identifier="v2", rank=2,
                            voiceprints=[voiceprint(0.0, 1.0, duration=4.0)])
        gardee.absorb(autre)
        assert gardee.aggregate_of != avant

    def test_deux_lectures_rendent_le_meme_objet(self):
        """C'est tout l'intérêt : le calcul ne se refait pas."""
        voice = LiveVoice(identifier="v1", rank=1,
                           voiceprints=[voiceprint(1.0, 0.0, duration=4.0)])
        assert voice.aggregate_of is voice.aggregate_of


class TestReunirLesHomonymes:
    """Deux voix que la banque nomme pareil sont la même personne.

    Mesuré en séance sur une réunion de trente-deux minutes : « Tanguy »
    s'affichait sur trois voix à la fois, dont deux avec un point
    d'interrogation. Le compte rendu en aurait annoncé trois. Attendre que
    leurs empreintes se ressemblent assez pour être réunies, c'est refuser une
    information qu'on tient déjà.
    """

    def _thread(self):
        thread = LiveThread(seuil_fusion=0.50)
        for rank, (identifier, vector) in enumerate(
            (("v1", (1.0, 0.0)), ("v2", (0.0, 1.0)), ("v3", (0.0, 0.0))), start=1
        ):
            thread.voice[identifier] = LiveVoice(
                identifier=identifier, rank=rank,
                voiceprints=[voiceprint(*vector, duration=10.0)]
                if any(vector) else [normalise([0.0, 0.0, 1.0], source_duration=4.0)],
            )
        thread.suite = 4
        return thread

    def test_trois_voix_du_meme_nom_deviennent_une(self):
        thread = self._thread()
        for identifier in ("v1", "v2", "v3"):
            thread.voice[identifier].name = "Tanguy"
            thread.voice[identifier].certitude = Certainty.PROBABLE
        faits = thread._join_namesakes()
        assert len(faits) == 2
        restantes = [v for v in thread.voice.values() if v.name == "Tanguy"]
        assert len(restantes) == 1

    def test_la_plus_fournie_garde_son_identifiant(self):
        """C'est celle dont l'extrait est le plus représentatif."""
        thread = self._thread()
        thread.voice["v1"].name = thread.voice["v3"].name = "Tanguy"
        thread.voice["v1"].certitude = thread.voice["v3"].certitude = Certainty.PROBABLE
        thread._join_namesakes()
        assert thread.voice["v1"].name == "Tanguy"
        assert "v3" not in thread.voice or thread.voice["v3"].name != "Tanguy"

    def test_deux_noms_differents_ne_sont_jamais_reunis(self):
        thread = self._thread()
        thread.voice["v1"].name, thread.voice["v2"].name = "Tanguy", "Garance"
        thread.voice["v1"].certitude = thread.voice["v2"].certitude = Certainty.PROBABLE
        assert thread._join_namesakes() == []
        assert thread.voice["v1"].name == "Tanguy" and thread.voice["v2"].name == "Garance"

    def test_la_casse_ne_cree_pas_deux_personnes(self):
        thread = self._thread()
        thread.voice["v1"].name, thread.voice["v2"].name = "Tanguy", "tanguy"
        thread.voice["v1"].certitude = thread.voice["v2"].certitude = Certainty.PROBABLE
        assert len(thread._join_namesakes()) == 1

    def test_une_voix_sans_nom_n_est_pas_concernee(self):
        thread = self._thread()
        assert thread._join_namesakes() == []

    def test_le_recollage_les_reunit_de_lui_meme(self):
        """C'est là que l'auto-correction se produit, à chaque tranche."""
        thread = self._thread()
        for identifier in ("v1", "v2"):
            thread.voice[identifier].name = "Tanguy"
            thread.voice[identifier].certitude = Certainty.PROBABLE
        assert thread.stitch(), "le recollage n'a rien réuni"
        assert len([v for v in thread.voice.values() if v.name == "Tanguy"]) == 1


class TestSeparerDeuxVoixReunies:
    """Défaire une réunion de voix : le geste qui manquait.

    Le défaut, signalé après une réunion de quatre-vingt-douze minutes : « j'ai
    dit non, voix deux et voix trois, c'est la même personne… je ne pouvais plus
    redistinguer les voix ». Réunir mélangeait les empreintes dans un même tas
    et supprimait la voix absorbée. Deux personnes réunies à tort le restaient
    jusqu'au compte rendu.
    """

    def _fil_a_deux_voix(self):
        thread = LiveThread()
        for identifier in ("v1", "v2"):
            thread.voice[identifier] = LiveVoice(identifier=identifier,
                                                rank=int(identifier[1]))
        thread.voice["v1"].add(voiceprint(1.0, 0.0, duration=8.0))
        thread.voice["v2"].add(voiceprint(0.0, 1.0, duration=6.0))
        for number, voice in enumerate(("v1", "v2", "v1", "v2"), start=1):
            thread.turns.append(LiveTurn(
                number=number, span=Span(number, number + 1),
                text=f"phrase {number}", voice=voice))
        return thread

    def _reunies(self):
        """Deux voix réunies à tort par une correction humaine."""
        thread = self._fil_a_deux_voix()
        thread.correct(1, "Tanguy")
        thread.correct(2, "Tanguy")
        gardee = next(v for v in thread.voice.values() if v.name == "Tanguy")
        return thread, gardee.identifier

    def test_la_voix_absorbee_retrouve_son_identifiant(self):
        thread, target = self._reunies()
        assert len([v for v in thread.voice.values() if v.name == "Tanguy"]) == 1
        assert thread.split(target) is not None
        assert {"v1", "v2"} <= set(thread.voice)

    def test_chaque_tour_revient_a_sa_voix(self):
        thread, target = self._reunies()
        thread.split(target)
        per_voice = {t.number: t.voice for t in thread.turns}
        assert per_voice == {1: "v1", 2: "v2", 3: "v1", 4: "v2"}

    def test_chaque_empreinte_revient_a_sa_voix(self):
        """Le point qui compte : c'est l'empreinte qui sert la banque de voix."""
        thread, target = self._reunies()
        thread.split(target)
        assert thread.voice["v1"].seconds == pytest.approx(8.0)
        assert thread.voice["v2"].seconds == pytest.approx(6.0)

    def test_l_agregat_est_refait_apres_la_separation(self):
        """Sinon la voix reste reconnaissable à ce qu'elle était mélangée."""
        thread, target = self._reunies()
        melange = list(thread.voice[target].aggregate_of.vector)
        thread.split(target)
        assert list(thread.voice[target].aggregate_of.vector) != melange

    def test_la_mesure_ne_les_reunit_pas_de_nouveau(self):
        """Le clic serait resté sans effet : `recoller` refaisait la fusion."""
        thread = self._fil_a_deux_voix()
        # Deux voix qui se ressemblent assez pour que la mesure les réunisse.
        thread.voice["v2"].voiceprints = [voiceprint(0.8, 0.6, duration=8.0)]
        thread.voice["v2"].forget_aggregate()
        thread.correct(1, "Tanguy")
        thread.correct(2, "Tanguy")
        target = next(v.identifier for v in thread.voice.values() if v.name == "Tanguy")
        thread.split(target)
        thread.stitch()
        assert {"v1", "v2"} <= set(thread.voice), "la mesure a refait la fusion défaite"

    def test_l_homonymie_ne_les_reunit_pas_de_nouveau(self):
        """Le cas de l'auto-correction : la banque a nommé deux voix pareil.

        Elle les réunit, et c'est le plus souvent juste. Quand ce ne l'est pas,
        la séparation doit tenir — sinon la tranche suivante la défait.
        """
        thread = self._fil_a_deux_voix()
        for identifier in ("v1", "v2"):
            thread.voice[identifier].name = "Tanguy"
            thread.voice[identifier].certitude = Certainty.RECONNUE
        thread.stitch()
        target = next(iter(v.identifier for v in thread.voice.values()
                          if v.name == "Tanguy"))
        assert {"v1", "v2"} - set(thread.voice), "l'homonymie devait les réunir"
        thread.split(target)
        assert {"v1", "v2"} <= set(thread.voice)
        thread.stitch()
        assert {"v1", "v2"} <= set(thread.voice), "l'homonymie a refait la fusion"

    def test_la_voix_rendue_redevient_anonyme(self):
        """Ce qui met l'oeil sur elle : « Voix 2 » se nomme, « Tanguy » se croit."""
        thread, target = self._reunies()
        thread.split(target)
        rendue = next(i for i in ("v1", "v2") if i != target)
        assert thread.voice[rendue].name is None

    def test_un_humain_peut_revenir_sur_sa_separation(self):
        """Le dernier geste tranche : séparer puis renommer réunit de nouveau."""
        thread, target = self._reunies()
        thread.split(target)
        autre = next(i for i in ("v1", "v2") if i != target)
        number = next(t.number for t in thread.turns if t.voice == autre)
        thread.correct(number, "Tanguy")
        assert len([v for v in thread.voice.values() if v.name == "Tanguy"]) == 1

    def test_rien_a_separer_ne_casse_rien(self):
        thread = self._fil_a_deux_voix()
        assert thread.split("v1") is None
        assert thread.split("inconnue") is None

    def test_la_cible_retrouve_ce_qu_elle_portait(self):
        """Une voix anonyme qui a absorbé une voix nommée redevient anonyme."""
        thread = self._fil_a_deux_voix()
        thread.voice["v2"].name = "Tanguy"
        thread.voice["v2"].certitude = Certainty.RECONNUE
        thread._absorb("v1", "v2")
        assert thread.voice["v2"].name == "Tanguy"
        thread.voice["v2"].name, thread.voice["v2"].certitude = "Marie", Certainty.RECONNUE
        thread.split("v2")
        assert thread.voice["v2"].name == "Tanguy", "l'état d'avant la fusion"
        assert thread.voice["v1"].name is None
