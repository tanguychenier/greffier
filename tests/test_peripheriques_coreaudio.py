"""Lecture du matériel audio réel.

L'analyse est une fonction pure : elle s'éprouve sur des sorties capturées, y
compris celles qu'on ne peut pas reproduire à volonté sur un poste donné. Les
sorties ci-dessous viennent d'un vrai Mac, avant et après branchement du casque.
"""

from __future__ import annotations

from greffier.adaptateurs.peripheriques_coreaudio import analyser
from greffier.domaine.peripheriques import Materiel, Veille, micro_conseille

# Relevé réel, casque et station débranchés.
SEUL = """Périphériques audio :

  BlackHole 2ch  [entrée 2ch, sortie 2ch]
    uid: BlackHole2ch_UID
  Haut-parleurs MacBook Pro  [sortie 2ch]
    uid: BuiltInSpeakerDevice
  Micro MacBook Pro  [entrée 1ch]
    uid: BuiltInMicrophoneDevice
  Reunion Entree  [entrée 3ch, sortie 2ch]
    uid: com.reunions.entree
  Reunion Sortie  [sortie 2ch]
    uid: com.reunions.sortie
"""

# Le même poste, casque Jabra et station branchés.
BRANCHE = """Périphériques audio :

  BlackHole 2ch  [entrée 2ch, sortie 2ch]
    uid: BlackHole2ch_UID
  HP E273m  [sortie 2ch]
    uid: 220E6E34-0000-0000-0120-0103803C2278
  Haut-parleurs MacBook Pro  [sortie 2ch]
    uid: BuiltInSpeakerDevice
  Jabra EVOLVE 30 II  [entrée 1ch]
    uid: AppleUSBAudioEngine:GN Audio A/S:Jabra EVOLVE 30 II:0000718017FA09:1
  Jabra EVOLVE 30 II  [sortie 2ch]
    uid: AppleUSBAudioEngine:GN Audio A/S:Jabra EVOLVE 30 II:0000718017FA09:2
  Micro MacBook Pro  [entrée 1ch]
    uid: BuiltInMicrophoneDevice
  Realtek USB2.0 Audio  [entrée 2ch]
    uid: AppleUSBAudioEngine:Generic:USB Audio:200901010001:1
  Reunion Entree  [entrée 3ch, sortie 2ch]
    uid: com.reunions.entree
  Reunion Sortie  [sortie 2ch]
    uid: com.reunions.sortie
"""


class TestAnalyse:
    def test_chaque_peripherique_est_reconnu(self) -> None:
        assert len(analyser(SEUL).peripheriques) == 5
        assert len(analyser(BRANCHE).peripheriques) == 9

    def test_les_canaux_sont_lus_dans_les_deux_sens(self) -> None:
        agrege = analyser(SEUL).par_nom("Reunion Entree")
        assert agrege is not None
        assert agrege.entrees == 3
        assert agrege.sorties == 2

    def test_un_peripherique_de_sortie_seule_n_a_pas_d_entree(self) -> None:
        hp = analyser(SEUL).par_nom("Haut-parleurs MacBook Pro")
        assert hp is not None
        assert hp.entrees == 0
        assert not hp.capte

    def test_l_uid_est_conserve_entier(self) -> None:
        jabra = analyser(BRANCHE).par_nom("Jabra EVOLVE 30 II")
        assert jabra is not None
        assert jabra.uid.endswith(":1")

    def test_un_nom_porte_par_deux_appareils_ne_se_perd_pas(self) -> None:
        # Le Jabra expose micro et écouteurs sous le même nom, uid différents.
        jabras = [p for p in analyser(BRANCHE).peripheriques if p.nom.startswith("Jabra")]
        assert len(jabras) == 2
        assert {p.entrees for p in jabras} == {0, 1}

    def test_seuls_les_appareils_qui_captent_comptent_comme_micros(self) -> None:
        assert {p.nom for p in analyser(SEUL).micros} == {
            "BlackHole 2ch", "Micro MacBook Pro", "Reunion Entree",
        }

    def test_une_sortie_vide_ne_fait_pas_echouer_l_analyse(self) -> None:
        assert analyser("").peripheriques == ()
        assert analyser("Périphériques audio :\n\n").peripheriques == ()

    def test_une_sortie_tronquee_ignore_l_entree_incomplete(self) -> None:
        # Un appareil annoncé sans sa ligne « uid » est écarté plutôt que
        # d'entrer dans la comparaison sous une forme partielle.
        tronque = SEUL[: SEUL.index("  Reunion Entree")] + "  Casque coupé  [entrée 1ch]\n"
        noms = {p.nom for p in analyser(tronque).peripheriques}
        assert "Casque coupé" not in noms


class TestDecisionSurDuReel:
    """La décision, appliquée aux relevés réels plutôt qu'à des cas fabriqués."""

    def test_le_branchement_du_casque_est_vu(self) -> None:
        veille = Veille(micro_voulu="Jabra EVOLVE 30 II")
        decision = veille.examiner(analyser(SEUL), analyser(BRANCHE))
        assert decision.micro == "Jabra EVOLVE 30 II"
        assert decision.audio_suspect

    def test_le_debranchement_evite_l_entree_ligne_de_la_station(self) -> None:
        # En débranchant, la station Realtek disparaît aussi. Mais même si elle
        # restait, elle ne devrait pas être choisie : voir le test suivant.
        veille = Veille(micro_voulu="Jabra EVOLVE 30 II")
        assert veille.examiner(analyser(BRANCHE), analyser(SEUL)).micro == "Micro MacBook Pro"

    def test_la_station_seule_ne_bat_pas_le_micro_du_portable(self) -> None:
        # Station branchée, casque non : l'entrée ligne du Realtek est presque
        # toujours vide, le micro du portable capte au moins quelque chose.
        materiel = analyser(BRANCHE)
        sans_casque = Materiel(
            tuple(p for p in materiel.peripheriques if not p.nom.startswith("Jabra"))
        )
        assert sans_casque.par_nom("Realtek USB2.0 Audio") is not None
        assert micro_conseille(sans_casque, "Jabra EVOLVE 30 II") == "Micro MacBook Pro"

    def test_l_agrege_n_est_jamais_retenu_malgre_ses_trois_entrees(self) -> None:
        assert micro_conseille(analyser(SEUL), "Casque absent") == "Micro MacBook Pro"
