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

## Tests

Four kinds, all in `tests/`:

- **Unit**, by default. `pytest`. Fast, no model, no network.
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
than as it should be. Measured with `pytest --cov=greffier`, unit tests alone:

| Layer | Covered | Statements |
|---|---|---|
| `ports/` | **100 %** | 41 |
| `domain/` | 96 % | 2 485 |
| `application/` | 84 % | 2 072 |
| `adapters/` | 79 % | 2 910 |
| `interface/` | 19 % | 2 234 |
| `cli.py`, `wiring.py` | 19 % | 1 594 |
| **total** | **63 %** | 11 336 |

The gap is not in the rules: it is in the window and in the command line, the
two places a test has to drive something that draws or that reads a terminal.
Closing it is the standing job, and a patch is expected to leave its own layer
no lower than it found it.

Coverage is a floor and never a goal: a test that asserts nothing covers lines
and proves nothing. Which is what mutation testing is for.

**Mutation testing** for the domain, when a rule is subtle. It is configured in
`pyproject.toml` and takes no argument:

```sh
mutmut run          # the domain, against tests/domain and tests/domaine
mutmut results      # what survived
mutmut show <id>    # the line it changed, and to what
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

## Before sending

```sh
./tools/hooks/install.sh     # once
```

The hook then refuses a commit that does not pass `ruff`, `mypy` and the tests.
The same three run in the CI and block the pull request. Running them "on the
side" is not enough: three quality remarks reached commits before that guard
existed.

A pull request says what it fixes, how it was measured, and what remains open.
The ones already merged are the model.
