"""The graph, in one SQLite file next to the meetings.

An index and never the truth: everything here is rebuilt from the meetings, the
voice bank, the memory and the preparations, which stay the source. A graph that
cannot be thrown away is a graph nobody dares feed.

SQLite because it is in the standard library, holds in one file, survives being
copied with the rest of the folder, and answers a question in one statement
instead of reading every meeting ever held.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path

from greffier.domain.graph import Edge, Kind, Known, Link, Node

SCHEMA = """
CREATE TABLE IF NOT EXISTS noeud (
    genre TEXT NOT NULL,
    cle   TEXT NOT NULL,
    nom   TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (genre, cle)
);
CREATE TABLE IF NOT EXISTS arete (
    lien        TEXT NOT NULL,
    genre_debut TEXT NOT NULL,
    cle_debut   TEXT NOT NULL,
    genre_fin   TEXT NOT NULL,
    cle_fin     TEXT NOT NULL,
    quand       TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (lien, genre_debut, cle_debut, genre_fin, cle_fin)
);
CREATE INDEX IF NOT EXISTS arete_par_fin ON arete (genre_fin, cle_fin);
"""


def open_it(file: Path) -> sqlite3.Connection:
    file.parent.mkdir(parents=True, exist_ok=True)
    lien = sqlite3.connect(file)
    lien.executescript(SCHEMA)
    return lien


def forget_everything(file: Path) -> None:
    """Empties the index. The sources stay, so it can be built again."""
    with closing(open_it(file)) as lien:
        lien.execute("DELETE FROM arete")
        lien.execute("DELETE FROM noeud")
        lien.commit()


def write(file: Path, nodes: Iterable[Node], edges: Iterable[Edge]) -> None:
    with closing(open_it(file)) as lien:
        lien.executemany(
            "INSERT OR REPLACE INTO noeud (genre, cle, nom) VALUES (?, ?, ?)",
            [(node.kind.value, node.key, node.name) for node in nodes],
        )
        lien.executemany(
            "INSERT OR REPLACE INTO arete "
            "(lien, genre_debut, cle_debut, genre_fin, cle_fin, quand) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(edge.link.value, edge.start[0].value, edge.start[1],
              edge.end[0].value, edge.end[1], edge.on) for edge in edges],
        )
        lien.commit()


def forget_person(file: Path, name: str) -> int:
    """Removes somebody and everything said of them. Article 9 is not a setting."""
    with closing(open_it(file)) as lien:
        efface = lien.execute(
            "DELETE FROM arete WHERE (genre_debut = ? AND cle_debut = ?) "
            "OR (genre_fin = ? AND cle_fin = ?)",
            (Kind.PERSON.value, name, Kind.PERSON.value, name),
        ).rowcount
        efface += lien.execute(
            "DELETE FROM noeud WHERE genre = ? AND cle = ?",
            (Kind.PERSON.value, name),
        ).rowcount
        lien.commit()
        return efface


def known_about(file: Path, subject: str, meetings_at_most: int = 5) -> Known:
    """What is known around a subject, most recent first."""
    if not file.exists() or not subject.strip():
        return Known(subject=subject)
    with closing(open_it(file)) as lien:
        reunions = [
            ligne[0] for ligne in lien.execute(
                "SELECT cle_debut FROM arete WHERE lien = ? AND genre_fin = ? "
                "AND cle_fin = ? ORDER BY cle_debut DESC LIMIT ?",
                (Link.ABOUT.value, Kind.SUBJECT.value, subject, meetings_at_most),
            )
        ]
        if not reunions:
            return Known(subject=subject)
        trous = ",".join("?" * len(reunions))
        personnes = [
            ligne[0] for ligne in lien.execute(
                f"SELECT DISTINCT cle_debut FROM arete WHERE lien = ? "  # noqa: S608
                f"AND cle_fin IN ({trous}) ORDER BY cle_debut",
                (Link.ATTENDED.value, *reunions),
            )
        ]
        ouverts = [
            ligne[0] for ligne in lien.execute(
                f"SELECT cle_fin FROM arete WHERE lien = ? "  # noqa: S608
                f"AND cle_debut IN ({trous})",
                (Link.LEFT_OPEN.value, *reunions),
            )
        ]
        documents = [
            ligne[0] for ligne in lien.execute(
                f"SELECT DISTINCT cle_debut FROM arete WHERE lien = ? "  # noqa: S608
                f"AND cle_fin IN ({trous})",
                (Link.SUPPLIED.value, *reunions),
            )
        ]
        sources = [
            ligne[0] for ligne in lien.execute(
                "SELECT cle_debut FROM arete WHERE lien = ? AND cle_fin = ?",
                (Link.TRACKED_IN.value, subject),
            )
        ]
    return Known(
        subject=subject,
        people=tuple(personnes),
        meetings=tuple(reunions),
        open_points=tuple(ouverts),
        documents=tuple(documents),
        sources=tuple(sources),
    )
