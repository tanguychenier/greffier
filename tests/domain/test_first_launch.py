"""What a fresh machine still has to do, in order."""

from greffier.domain.first_launch import is_a_first_launch, next_to_do, steps


class TestTheThreeSteps:
    def test_nothing_done_is_a_first_launch_with_the_models_first(self):
        the_steps = steps(models_present=False, claude_signed_in=False, microphone_chosen=False)
        assert is_a_first_launch(the_steps)
        assert next_to_do(the_steps).key == "modeles"

    def test_the_models_in_place_the_account_comes_next(self):
        the_steps = steps(models_present=True, claude_signed_in=False, microphone_chosen=True)
        assert [s.done for s in the_steps] == [True, False, True]
        assert next_to_do(the_steps).key == "compte"

    def test_everything_done_needs_no_hand(self):
        the_steps = steps(models_present=True, claude_signed_in=True, microphone_chosen=True)
        assert not is_a_first_launch(the_steps)
        assert next_to_do(the_steps) is None

    def test_the_steps_are_named_in_the_order_they_are_needed(self):
        """The window reads the keys to show each step; a misspelt one shows nothing."""
        the_steps = steps(models_present=False, claude_signed_in=False, microphone_chosen=False)
        assert [s.key for s in the_steps] == ["modeles", "compte", "micro"]

    def test_with_only_the_microphone_left_it_is_what_comes_next(self):
        the_steps = steps(models_present=True, claude_signed_in=True, microphone_chosen=False)
        assert is_a_first_launch(the_steps)
        assert next_to_do(the_steps).key == "micro"
