"""Formatting the minutes for sending by email.

Every style is inline: mail clients drop stylesheets.
"""

from __future__ import annotations

import html
import re
import unicodedata

from greffier.domain.texts import short_voiceprint

_INK = "#24242b"
_PALE_INK = "#5b5b66"
_FILET = "#e0e0e6"
_HEADER_GROUND = "#f6f6f8"
_FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
_FIXED_FONT = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"

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
    "th": f"background:{_HEADER_GROUND};border:1px solid {_FILET};padding:9px 11px;"
          f"text-align:left;font-weight:600;color:{_INK};white-space:nowrap",
    "td": f"border:1px solid {_FILET};padding:9px 11px;vertical-align:top;color:{_INK}",
    "td_premiere": f"border:1px solid {_FILET};padding:9px 11px;vertical-align:top;"
                   f"color:{_INK};min-width:96px",
    "td_absent": f"border:1px solid {_FILET};padding:9px 11px;vertical-align:top;"
                 f"color:#9a9aa4;font-style:italic",
    "blockquote": f"margin:14px 0;padding:9px 15px;border-left:3px solid {_FILET};"
                  f"color:{_PALE_INK};font-style:italic",
    "code": f"font:13px {_FIXED_FONT};background:{_HEADER_GROUND};"
            f"padding:1px 5px;border-radius:3px",
    "hr": f"border:0;border-top:1px solid {_FILET};margin:26px 0",
}

_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])")
_CODE = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$")

def _tag(style: str, content: str, extra: str = "", name: str = "") -> str:
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
    output = _CODE.sub(lambda m: _tag("code", m.group(1)), output)
    output = _BOLD.sub(r"<strong>\1</strong>", output)
    output = _ITALIC.sub(r"<em>\1</em>", output)
    return _LINK.sub(
        lambda m: f'<a href="{m.group(2)}" style="color:#2c5aa0">{m.group(1)}</a>', output
    )

def _anchor(title: str) -> str:
    """A stable identifier for a section, without accents."""
    without_accents = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    reduced = re.sub(r"[^a-z0-9]+", "-", without_accents.lower()).strip("-")
    return "s-" + (reduced or short_voiceprint(title))

def sections(minutes: str) -> list[str]:
    """The titles of the second-level sections, in order."""
    return [
        line.strip().lstrip("#").strip()
        for line in minutes.splitlines()
        if line.strip().startswith("## ")
    ]

def _summary(minutes: str) -> str:
    """A table of contents at the top of the email."""
    titles = sections(minutes)
    if len(titles) < 3:
        return ""
    entries = "".join(
        f'<span style="white-space:nowrap;margin:0 22px 0 0;'
        f'font:400 13px/2 {_FONT}">'
        f'<span style="color:{_PALE_INK}">{number}.</span> '
        f'<a href="#{_anchor(title)}" style="color:{_INK};text-decoration:none">'
        f"{html.escape(title)}</a></span>"
        for number, title in enumerate(titles, 1)
    )
    return (
        f'<div style="margin:0 0 30px;padding:13px 17px;background:{_HEADER_GROUND};'
        f'border-left:3px solid {_INK};border-radius:0 4px 4px 0">'
        f'<div style="font:600 10px/1 {_FONT};letter-spacing:.11em;'
        f'text-transform:uppercase;color:{_PALE_INK};padding-bottom:7px">Sommaire</div>'
        f"{entries}</div>"
    )

def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]

def as_html(markdown: str) -> str:
    """Converts the minutes into an HTML fragment, styles included."""
    lines = markdown.splitlines()
    output: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        bare = line.strip()

        if not bare:
            i += 1
            continue

        if bare.startswith("#"):
            level = len(bare) - len(bare.lstrip("#"))
            name = f"h{min(level, 3)}"
            text = bare.lstrip("#").strip()
            anchor = f' id="{_anchor(text)}"' if level == 2 else ""
            output.append(_tag(name, _as_line(text), anchor))
            i += 1
            continue

        if set(bare) <= {"-", "*", "_"} and len(bare) >= 3:
            output.append(f'<hr style="{_STYLES["hr"]}">')
            i += 1
            continue

        if "|" in bare and i + 1 < len(lines) and _TABLE_SEPARATOR.match(lines[i + 1]):
            headers = _cells(bare)
            i += 2
            corps: list[list[str]] = []
            while i < len(lines) and "|" in lines[i]:
                corps.append(_cells(lines[i]))
                i += 1
            head = "".join(_tag("th", _as_line(c)) for c in headers)
            ranks = "".join(
                "<tr>"
                + "".join(
                    _tag(_cell_style(c, rank), _as_line(c), name="td")
                    for rank, c in enumerate(r)
                )
                + "</tr>"
                for r in corps
            )
            output.append(_tag("table", f"<thead><tr>{head}</tr></thead><tbody>{ranks}</tbody>"))
            continue

        if bare.startswith((">", "&gt;")):
            block = []
            while i < len(lines) and lines[i].strip().startswith((">", "&gt;")):
                block.append(lines[i].strip().lstrip(">").strip())
                i += 1
            output.append(_tag("blockquote", _as_line(" ".join(block))))
            continue

        if re.match(r"^[-*+]\s+", bare) or re.match(r"^\d+[.)]\s+", bare):
            ordered_one = bool(re.match(r"^\d+[.)]\s+", bare))
            items = []
            while i < len(lines):
                current = lines[i].strip()
                if re.match(r"^[-*+]\s+", current) or re.match(r"^\d+[.)]\s+", current):
                    items.append(re.sub(r"^([-*+]|\d+[.)])\s+", "", current))
                    i += 1
                elif current and not current.startswith("#") and items:
                    items[-1] += " " + current
                    i += 1
                else:
                    break
            content = "".join(_tag("li", _as_line(t)) for t in items)
            output.append(_tag("ol" if ordered_one else "ul", content))
            continue

        block = []
        while (i < len(lines) and lines[i].strip()
               and not lines[i].strip().startswith(("#", ">", "|"))):
            block.append(lines[i].strip())
            i += 1
        if block:
            output.append(_tag("p", _as_line(" ".join(block))))
        else:
            i += 1

    return "\n".join(output)

def _header(minutes: str) -> tuple[str, str]:
    """Separates the title and the context line from the rest."""
    lines = minutes.splitlines()
    title = context = ""
    remaining = 0
    for index, line in enumerate(lines):
        bare = line.strip()
        if not bare:
            continue
        if not title and bare.startswith("# "):
            title = bare[2:].strip()
            remaining = index + 1
            continue
        if title and not context and not bare.startswith("#"):
            context = bare
            remaining = index + 1
        break
    if not title:
        return "", minutes
    block = (
        f'<h1 style="{_STYLES["h1"]}">{_as_line(title)}</h1>'
        + (
            f'<p style="margin:0 0 24px;font:400 13px/1.5 {_FONT};'
            f'color:{_PALE_INK}">{_as_line(context)}</p>'
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
        f'font:400 12px/1.5 {_FONT};color:{_PALE_INK}">{html.escape(pied)}</p>'
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

