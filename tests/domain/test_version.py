"""Savoir si une version est postérieure à une autre."""

from greffier.domain.version import is_newer, read


class TestReadingAVersion:
    def test_three_numbers(self):
        assert read("1.2.3") == (1, 2, 3)

    def test_the_v_of_a_tag_is_accepted(self):
        assert read("v0.2.0") == (0, 2, 0)

    def test_two_numbers_are_enough(self):
        assert read("0.2") == (0, 2, 0)

    def test_a_suffix_is_ignored(self):
        assert read("1.2.3-essai") == (1, 2, 3)

    def test_what_is_not_a_version_is_refused(self):
        assert read("dernière") is None
        assert read("") is None


class TestComparingVersions:
    def test_a_higher_version_is_noticed(self):
        assert is_newer("0.3.0", "0.2.0") is True

    def test_the_same_version_offers_nothing(self):
        assert is_newer("0.2.0", "0.2.0") is False

    def test_an_earlier_version_offers_nothing(self):
        assert is_newer("0.1.0", "0.2.0") is False

    def test_ten_comes_after_nine(self):
        """Une comparaison de chaînes affirme exactement l'inverse.

        L'erreur ne se voit qu'au dixième incrément, soit des mois après la
        mise en service.
        """
        assert is_newer("0.10.0", "0.9.0") is True
        assert is_newer("0.9.0", "0.10.0") is False

    def test_the_patch_number_counts(self):
        assert is_newer("0.2.1", "0.2.0") is True

    def test_an_unreadable_version_offers_nothing(self):
        assert is_newer("dernière", "0.2.0") is False
        assert is_newer("0.3.0", "inconnue") is False
