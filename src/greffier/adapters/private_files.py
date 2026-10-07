"""Files that hold a secret, written private from the first byte.

The tokens file and the model's servers file were written with
`Path.write_text` under the process umask, then chmod'ed to 0600. Under the
usual desktop umask of 022 that leaves a 0644 file holding the Jira, GitLab
and Miro tokens for the whole duration of the write: every local user could
read it, and one that opened it in that window keeps its descriptor after the
chmod. `configuration.save_settings` already did it right: a temporary opened
by `mkstemp`, which creates 0600, written in the target's folder and renamed
onto it. One writer here, so the three files cannot drift apart again.

On Windows there is no umask and `chmod` only toggles the read-only flag:
the file inherits the ACL of its folder, the person's profile, which is the
owner's alone. Nothing more can be done there, and it is said here rather
than hidden behind a `chmod` that would mean nothing.
"""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

OWNER_ONLY_FILE = stat.S_IRUSR | stat.S_IWUSR
OWNER_ONLY_FOLDER = stat.S_IRWXU


def write_private_text(target: Path, text: str) -> None:
    """Replaces `target` with `text`, readable by its owner alone at every instant.

    Atomic as well: the previous content stays whole until the new one is in
    place, and a write that fails leaves no temporary behind.
    """
    _make_private_folder(target.parent)
    descriptor, temporary = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.stem}-", suffix=target.suffix,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            if os.name == "posix":
                # mkstemp opens 0600 today; set it ourselves so the guarantee
                # does not rest on an implementation detail of the standard
                # library. Inside the `with`, once the stream owns the
                # descriptor: a refused fchmod then closes it on the way out
                # instead of leaking it.
                os.fchmod(stream.fileno(), OWNER_ONLY_FILE)
            stream.write(text)
        Path(temporary).replace(target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _make_private_folder(folder: Path) -> None:
    """Creates the folder for its owner alone; one that exists keeps its mode."""
    if folder.exists():
        return
    folder.mkdir(mode=OWNER_ONLY_FOLDER, parents=True, exist_ok=True)
