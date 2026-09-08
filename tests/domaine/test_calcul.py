"""Combien de fils les modèles reçoivent, et pourquoi pas tous.

Les modèles ONNX n'en prennent qu'un par défaut, et la segmentation puis les
empreintes sont la partie la plus longue du traitement : sept cœurs sur huit
attendaient. Mesuré sur un entretien de cent cinq secondes : 287 s sur un fil,
206 s sur deux, 167 s sur quatre, 193 s sur huit. Tout prendre est moins bon
que la moitié, et ce test fige ce constat.
"""

from greffier.domaine.calcul import fils_de_calcul


class TestFilsDeCalcul:
    def test_la_moitie_des_coeurs(self):
        assert fils_de_calcul(8) == 4

    def test_jamais_moins_d_un_fil(self):
        """Un cœur unique donnerait zéro fil, et le modèle refuserait."""
        assert fils_de_calcul(1) == 1
        assert fils_de_calcul(0) == 1

    def test_un_gros_poste_en_prend_davantage(self):
        assert fils_de_calcul(16) == 8

    def test_la_moitie_laisse_de_quoi_travailler(self):
        """La veille tourne pendant la réunion : tout prendre la gênerait."""
        assert fils_de_calcul(8) < 8
