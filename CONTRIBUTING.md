# Contributing

Patches are welcome. What follows is not a wish list: it is what the guard hooks
and the CI already refuse, plus the few habits that make this codebase readable
from one end to the other.

## The licence first

Greffier is under [PolyForm Noncommercial 1.0.0](LICENCE): free for
universities, research laboratories, public institutions and personal use,
closed to commercial exploitation without a separate agreement. By sending a
patch you agree that it ships under those same terms.

## Commits

- **Atomic.** One commit, one subject. A fix and the refactoring that made room
  for it are two commits, even when written in the same hour.
- **Angular convention** for the subject: `type(scope): what changed`, in the
  imperative or as a plain statement of the defect,
  `fix(window): ending a meeting froze the window instead of showing the end`.
  Types in use: `feat`, `fix`, `refactor`, `perf`, `docs`, `test`, `chore`.
- **In English**, subject and body alike. The body says **why**, what was
  measured, and what was ruled out: a diff shows what changed and never why.
  Numbers beat adjectives, `0.19 × real time` says more than `fast`.
- No attribution trailers, no generated footers. The history is signed by the
  person who sends the patch.
- Branch names read like their subject: `fix/the-command-was-not-in-the-path`.

## The language of the code

**Code in English, software in French.** Identifiers, docstrings, comments,
commit messages, pull requests: English. Everything the software says to the
person using it: window labels, installer messages, the minutes themselves:
French. A few older files are still French throughout; translating one is a
commit of its own, never a passenger on a fix.

## Architecture

Hexagonal, and enforced rather than hoped for:

- `domain/`: pure. No I/O, no network, no `subprocess`, no framework. The
  rules about voices, names and minutes live here and are testable in
  milliseconds.
- `application/`: the use cases, orchestrating the domain through **ports**.
- `ports/`: the interfaces the outside must satisfy.
- `adapters/`: everything that touches the world: ffmpeg, whisper, sherpa-onnx,
  SMTP, the file system, the command-line assistant.
- `interface/`: the Tk window, a primary adapter like any other.

`tests/architecture/test_layers.py` reads the imports with `ast`, late imports
inside functions included, and fails on any dependency running the wrong way.
It caught four inverted dependencies on its first run; it is not decorative.

Beyond the layers: SOLID, and the plain kind of clean code, small functions
that do one thing, names that say what they hold, no comment restating the line
below it. A comment earns its place by saying what the code cannot: the
measurement, the alternative that was tried, the reason for the odd-looking
choice.

## The environment

```sh
uv sync --group dev --extra api   # .venv from uv.lock: the package, the HTTP door, the tools
uv run ruff check src tests tools
uv run mypy
uv run pytest                     # GREFFIER_ECRAN_D_ESSAI=1 xvfb-run -a uv run pytest without a screen
```

`uv.lock` pins what everyone gets, the CI included, which runs the same three
commands on it with `--locked`. Moving a version is `uv lock --upgrade-package
<name>`, on purpose and in a commit of its own; Dependabot opens one a week.

## Tests

Four kinds, all in `tests/`:

- **Unit**, by default. `uv run pytest`. Fast, no model, no network.
- **Architecture**, the layer rules above.
- **Integration**, `pytest -m integration`: the real chain on a synthesised
  meeting: transcription, voice separation, first names, minutes. It needs the
  models and a speech synthesiser; where one is missing the tests say which,
  and skip rather than lie.
- **Slow**, `pytest -m lent`: calls the real writer, so the network and an
  account's quota. Run by hand before a demonstration.

The window has its own proof, `tools/window_proof.py`, which builds the real
window, paints every tab and photographs it, because a test that says a tab
paints without exception will never notice a button sitting outside the frame.

**Coverage. The standard is 100 %**, and the figure is given as it is rather
than as it should be. Measured on 2026-10-03 with `uv run pytest
--cov=greffier`, unit tests alone, 2 752 tests:

| Layer | Covered | Statements |
|---|---|---|
| `ports/` | **100 %** | 48 |
| `domain/` | 97 % | 3 280 |
| `application/` | 91 % | 2 554 |
| `adapters/` | 86 % | 3 785 |
| `interface/` | 65 % | 3 258 |
| `cli.py`, `wiring.py` | 57 % | 1 802 |
| `locations.py`, `__main__.py` | 96 % | 76 |
| **total** | **81 %** | 14 803 |

The gap is not in the rules: it is in the window and in the command line, the
two places a test has to drive something that draws or that reads a terminal.
`cli.py` alone is 1 508 statements at 51 %, `window.py` 2 291 at 57 %. Closing
it is the standing job, and a patch is expected to leave its own layer no lower
than it found it. The CI holds a floor of 80 % on the total, one point under
the measure so that a patch cannot lower it unnoticed; it follows the measure
upwards and is not a target.

Coverage is a floor and never a goal: a test that asserts nothing covers lines
and proves nothing. Which is what mutation testing is for.

**Mutation testing** for the domain, when a rule is subtle. It is configured in
`pyproject.toml` and takes no argument:

```sh
uv run mutmut run          # the whole domain, against tests/domain: six to seven minutes
uv run mutmut results      # what survived
uv run mutmut show <id>    # the line it changed, and to what
```

A surviving mutant means the test suite accepts a code that is wrong. Either the
test is missing, or the line was.

Run for the first time on 2026-09-12, on `emptiness.py` and `arithmetic.py`:
33 mutants, 29 killed, **4 survivors**, all in `compute_threads`. Three came
from a fallback nobody exercised (`os.cpu_count()` returning `None`, which it
does in some containers) and one from a real division read as an integer one.
Three tests killed them. The last survivor replaces `or 2` with `or 3`, which
this function cannot tell apart since both halve to one thread: an equivalent
mutant, and the honest ceiling here is 32 out of 33.

Run on the whole domain on 2026-10-03 (mutmut 3.8, 2 min 59 s on 4 cores):
5 090 mutants, 3 629 killed, 1 100 survived, 348 in functions no domain test
reaches, 13 timeouts: a score of 71 %, concentrated in `live.py` (184
survivors), `graph.py` (118), `names.py` (103) and `voiceprints.py` (78), with
`meeting.py` alone holding 125 mutants no test touched.

Run again on 2026-10-04, after one commit per module (mutmut 3.8, 6 min 25 s
on 4 cores, judged by `tests/domain` alone): **5 031 mutants, 4 919 killed,
97 survived**, 0 in functions no domain test reaches, 15 timeouts. mutmut
counts a timeout as a kill, which gives a score of **98 %**. The figure is
given as it is, and what the 97 survivors are is said in the commits rather
than hidden in the score. Seventy-five sit in eight modules, `live.py` (17),
`voiceprints.py` (16), `participation.py` (10), `export.py` (10),
`transcription.py` (9), `questions.py` (5), `names.py` (5) and `subjects.py`
(3), whose commits name most of them equivalent; the claim is re-read module
by module before it is believed, and a few of them are distinguishable only
by inputs outside the module's contract. The 22 others, one to three per
module across fifteen modules, `intents.py` (3), `first_names.py` (3),
`board.py` (2), `channels.py` (2), `her_voice.py` (2) and one each in
`arithmetic.py`, `backup.py`, `devices.py`, `instructions.py`, `meeting.py`,
`memory.py`, `profiles/__init__.py`, `store.py`, `texts.py` and `tongue.py`,
are the honest ceiling: mutants no test can tell apart from the code, each
named with its reason in the commit that examined its module, `or 2` to
`or 3` where both halve to one thread, a strip set gaining an upper-case X
after a `lower()`, `flags=re.UNICODE` dropped where it is the default for a
`str` pattern, a sentinel assigned and never read. The claim is held
strictly, since most « equivalent » survivors turn out to be untested
behaviour: on this branch, reading the survivors one by one gave ten
`fix(domain)` commits, defects and dead guards both, each with the test that
proves it, and re-reading a claim of equivalence gave one more test,
`collapse_loops` at a threshold of one. The timeouts are loops a mutation
made endless, a position set back instead of advanced; they stay. A few
of them loop for ever on one test's input and raise on another's, and
mutmut hands pytest, with `-x`, the tests that reach a mutant in the
order of a set of their names, which changes from one process to the
next: `without_loop` mutants 54 and 69 and `collapse_loops` mutants 8
and 21 have each been reported killed on one run and timed out on
another, so the count reads as 14 to 18 rather than as one number, 15
on this run and 17 on an earlier run of the same day, which the
count tolerates since neither is a survivor. Raising the score is the standing
job, one module at a time; `mutmut results` filtered on the module's name is
where it starts.

The CI holds the measure as a budget: the `mutants` job runs the whole domain
and fails when more than 97 lines of `mutmut results` end in `: survived`,
the number counted on 2026-10-04. Like the coverage floor it is a ratchet, it
follows the measure downwards each time a commit kills survivors and says so,
and it is never a target.

## Before sending

```sh
./tools/hooks/install.sh     # once
```

The hook then refuses a commit that does not pass `ruff`, `mypy` and the tests.
The same three run in the CI and block the pull request. Running them "on the
side" is not enough: three quality remarks reached commits before that guard
existed. Without a `.venv` the hook refuses the commit too, and prints the one
command that creates it: nothing checked is not the same as nothing wrong.

A pull request says what it fixes, how it was measured, and what remains open.
The ones already merged are the model.
