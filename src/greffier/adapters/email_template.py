"""Formatting the minutes for sending by email.

Every style is inline: mail clients drop stylesheets.
"""

from __future__ import annotations

import html
import re
import unicodedata

from greffier.domain.texts import short_voiceprint

_INK = "#24242b"
_ENCRE_PALE = "#5b5b66"
_FILET = "#e0e0e6"
_FOND_ENTETE = "#f6f6f8"
_FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
_POLICE_FIXE = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"

_STYLES = {
    "h1": f"margin:0 0 7px;font:600 25px/1.25 {_FONT};color:{_INK};"
          f"letter-spacing:-.01em",
    "h2": f"margin:38px 0 15px;padding-bottom:8px;border-bottom:2px solid {_INK};"
          f"font:600 12px/1.3 {_FONT};color:{_INK};letter-spacing:.1em;"
          f"text-transform:uppercase",
    "h3": f"margin:26px 0 7px;font:600 16px/1.35 {_FONT};color:{_INK}",
    "p": f"margin:0 0 13px;font:400 14px/1.65 {_FONT};color:{_INK}",
    "li": f"margin:0 0 7px;font:400 14px/1.6 {_FONT};color:{_INK}",
    "ul": "margin:0 0 14px;padding-left:22px",
    "ol": "margin:0 0 14px;padding-left:22px",
    "table": f"border-collapse:collapse;width:100%;margin:6px 0 18px;font:400 13px/1.55 {_FONT}",
    "th": f"background:{_FOND_ENTETE};border:1px solid {_FILET};padding:9px 11px;"
          f"text-align:left;font-weight:600;color:{_INK};white-space:nowrap",
    "td": f"border:1px solid {_FILET};padding:9px 11px;vertical-align:top;color:{_INK}",
    "td_premiere": f"border:1px solid {_FILET};padding:9px 11px;vertical-align:top;"
                   f"color:{_INK};min-width:96px",
    "td_absent": f"border:1px solid {_FILET};padding:9px 11px;vertical-align:top;"
                 f"color:#9a9aa4;font-style:italic",
    "blockquote": f"margin:14px 0;padding:9px 15px;border-left:3px solid {_FILET};"
                  f"color:{_ENCRE_PALE};font-style:italic",
    "code": f"font:13px {_POLICE_FIXE};background:{_FOND_ENTETE};padding:1px 5px;border-radius:3px",
    "hr": f"border:0;border-top:1px solid {_FILET};margin:26px 0",
}

_GRAS = re.compile(r"\*\*(.+?)\*\*")
_ITALIQUE = re.compile(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])")
_CODE = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$")

def _balise(style: str, content: str, extra: str = "", name: str = "") -> str:
    """A styled HTML tag."""
    return f'<{name or style} style="{_STYLES[style]}"{extra}>{content}</{name or style}>'

_ABSENCES = frozenset({"non dit", "à attribuer", "a attribuer", "non précisé", "sans objet"})

def _cell_style(content: str, rank: int) -> str:
    if content.strip().lower() in _ABSENCES:
        return "td_absent"
    return "td_premiere" if rank == 0 else "td"

def _as_line(text: str) -> str:
    """Escapes the text, then renders bold, italic and code."""
    output = html.escape(text, quote=False)
    output = _CODE.sub(lambda m: _balise("code", m.group(1)), output)
    output = _GRAS.sub(r"<strong>\1</strong>", output)
    output = _ITALIQUE.sub(r"<em>\1</em>", output)
    return _LINK.sub(
        lambda m: f'<a href="{m.group(2)}" style="color:#2c5aa0">{m.group(1)}</a>', output
    )

def _ancre(title: str) -> str:
    """A stable identifier for a section, without accents."""
    without_accents = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    reduit = re.sub(r"[^a-z0-9]+", "-", without_accents.lower()).strip("-")
    return "s-" + (reduit or short_voiceprint(title))

def sections(minutes: str) -> list[str]:
    """The titles of the second-level sections, in order."""
    return [
        line.strip().lstrip("#").strip()
        for line in minutes.splitlines()
        if line.strip().startswith("## ")
    ]

def _summary(minutes: str) -> str:
    """A table of contents at the top of the email."""
    titres = sections(minutes)
    if len(titres) < 3:
        return ""
    entrees = "".join(
        f'<span style="white-space:nowrap;margin:0 22px 0 0;'
        f'font:400 13px/2 {_FONT}">'
        f'<span style="color:{_ENCRE_PALE}">{number}.</span> '
        f'<a href="#{_ancre(title)}" style="color:{_INK};text-decoration:none">'
        f"{html.escape(title)}</a></span>"
        for number, title in enumerate(titres, 1)
    )
    return (
        f'<div style="margin:0 0 30px;padding:13px 17px;background:{_FOND_ENTETE};'
        f'border-left:3px solid {_INK};border-radius:0 4px 4px 0">'
        f'<div style="font:600 10px/1 {_FONT};letter-spacing:.11em;'
        f'text-transform:uppercase;color:{_ENCRE_PALE};padding-bottom:7px">Sommaire</div>'
        f"{entrees}</div>"
    )

def _cellules(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]

def as_html(markdown: str) -> str:
    """Converts the minutes into an HTML fragment, styles included."""
    lines = markdown.splitlines()
    output: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        nue = line.strip()

        if not nue:
            i += 1
            continue

        if nue.startswith("#"):
            level = len(nue) - len(nue.lstrip("#"))
            name = f"h{min(level, 3)}"
            text = nue.lstrip("#").strip()
            ancre = f' id="{_ancre(text)}"' if level == 2 else ""
            output.append(_balise(name, _as_line(text), ancre))
            i += 1
            continue

        if set(nue) <= {"-", "*", "_"} and len(nue) >= 3:
            output.append(f'<hr style="{_STYLES["hr"]}">')
            i += 1
            continue

        if "|" in nue and i + 1 < len(lines) and _TABLE_SEPARATOR.match(lines[i + 1]):
            entetes = _cellules(nue)
            i += 2
            corps: list[list[str]] = []
            while i < len(lines) and "|" in lines[i]:
                corps.append(_cellules(lines[i]))
                i += 1
            tete = "".join(_balise("th", _as_line(c)) for c in entetes)
            rangs = "".join(
                "<tr>"
                + "".join(
                    _balise(_cell_style(c, rank), _as_line(c), name="td")
                    for rank, c in enumerate(r)
                )
                + "</tr>"
                for r in corps
            )
            output.append(_balise("table", f"<thead><tr>{tete}</tr></thead><tbody>{rangs}</tbody>"))
            continue

        if nue.startswith((">", "&gt;")):
            block = []
            while i < len(lines) and lines[i].strip().startswith((">", "&gt;")):
                block.append(lines[i].strip().lstrip(">").strip())
                i += 1
            output.append(_balise("blockquote", _as_line(" ".join(block))))
            continue

        if re.match(r"^[-*+]\s+", nue) or re.match(r"^\d+[.)]\s+", nue):
            ordonnee = bool(re.match(r"^\d+[.)]\s+", nue))
            items = []
            while i < len(lines):
                courante = lines[i].strip()
                if re.match(r"^[-*+]\s+", courante) or re.match(r"^\d+[.)]\s+", courante):
                    items.append(re.sub(r"^([-*+]|\d+[.)])\s+", "", courante))
                    i += 1
                elif courante and not courante.startswith("#") and items:
                    items[-1] += " " + courante
                    i += 1
                else:
                    break
            content = "".join(_balise("li", _as_line(t)) for t in items)
            output.append(_balise("ol" if ordonnee else "ul", content))
            continue

        block = []
        while (i < len(lines) and lines[i].strip()
               and not lines[i].strip().startswith(("#", ">", "|"))):
            block.append(lines[i].strip())
            i += 1
        if block:
            output.append(_balise("p", _as_line(" ".join(block))))
        else:
            i += 1

    return "\n".join(output)

def _header(minutes: str) -> tuple[str, str]:
    """Separates the title and the context line from the rest."""
    lines = minutes.splitlines()
    title = context = ""
    remaining = 0
    for indice, line in enumerate(lines):
        nue = line.strip()
        if not nue:
            continue
        if not title and nue.startswith("# "):
            title = nue[2:].strip()
            remaining = indice + 1
            continue
        if title and not context and not nue.startswith("#"):
            context = nue
            remaining = indice + 1
        break
    if not title:
        return "", minutes
    block = (
        f'<h1 style="{_STYLES["h1"]}">{_as_line(title)}</h1>'
        + (
            f'<p style="margin:0 0 24px;font:400 13px/1.5 {_FONT};'
            f'color:{_ENCRE_PALE}">{_as_line(context)}</p>'
            if context
            else ""
        )
    )
    return block, "\n".join(lines[remaining:])

def email(minutes: str, pied: str = "") -> str:
    """Wraps the minutes in a complete document."""
    header, suite = _header(minutes)
    corps = header + _summary(minutes) + as_html(suite)
    signature = (
        f'<p style="margin:28px 0 0;padding-top:14px;border-top:1px solid {_FILET};'
        f'font:400 12px/1.5 {_FONT};color:{_ENCRE_PALE}">{html.escape(pied)}</p>'
        if pied
        else ""
    )
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"></head>'
        '<body style="margin:0;padding:0;background:#ffffff">'
        '<div style="max-width:740px;margin:0 auto;padding:26px 22px">'
        f"{corps}{signature}"
        "</div></body></html>"
    )

