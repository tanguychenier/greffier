"""The README is the door of this repository: its links must lead somewhere.

A table of contents is worth exactly what its anchors are worth. GitHub builds
them from the headings, silently, and a heading reworded a month later leaves a
link that scrolls nowhere -- which is worse than no table of contents at all,
because the reader blames themselves.
"""

from __future__ import annotations

import re
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
README = (RACINE / "README.md").read_text(encoding="utf-8")


def anchor_of(titre: str) -> str:
    """The anchor GitHub gives a heading: lowercase, no punctuation, dashes."""
    sans_ponctuation = re.sub(r"[^\w\s-]", "", titre.strip().lower())
    return re.sub(r"\s+", "-", sans_ponctuation)


ANCRES = {anchor_of(t) for t in re.findall(r"^#{1,6}\s+(.+)$", README, re.M)}


class TestEveryLinkLeadsSomewhere:
    def test_the_table_of_contents_points_at_real_headings(self):
        vers_le_vide = sorted(
            cible for cible in re.findall(r"\]\(#([^)]+)\)", README)
            if cible not in ANCRES
        )
        assert not vers_le_vide, f"ancres inexistantes : {vers_le_vide}"

    def test_the_files_it_names_exist(self):
        """A link to a file that was moved sends the reader to a 404."""
        cibles = re.findall(r"\]\((?!https?://|#)([^)#]+)", README)
        absents = sorted({c for c in cibles if not (RACINE / c).exists()})
        assert not absents, f"fichiers introuvables : {absents}"

    def test_the_sections_the_table_of_contents_announces_are_all_there(self):
        """Six sections at least, or it is not a document one navigates."""
        assert len({a for a in ANCRES}) >= 6
