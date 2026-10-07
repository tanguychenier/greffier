"""Hypothesis, settled once for the domain's property tests.

No deadline: the default 200 ms turns a slow runner into a failing test, and
the gate runs under xvfb beside the window's tests. Derandomised: the same
examples on every machine, so a failure found here fails in the CI as well,
and the other way round; a fresh search is one `--hypothesis-seed` away.
"""

from hypothesis import HealthCheck, settings

settings.register_profile(
    "greffier",
    deadline=None,
    derandomize=True,
    max_examples=200,
    # differing_executors: mutmut runs the suite in its own process, for stats
    # then clean, and forks that process for every mutant, so a @given method
    # runs on a second instance of its class and Hypothesis fails it before any
    # example: a kill the mutant did not earn. Plain pytest never does this.
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.differing_executors],
)
settings.load_profile("greffier")
