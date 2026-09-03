"""Mise en forme du compte rendu pour l'envoi par courriel.

Un compte rendu part en Markdown : titres, tableaux, puces. Envoyé tel quel, il
arrive comme un mur de dièses et de barres verticales — c'est ce qui rendait le
courriel illisible. On le convertit donc en HTML avant l'envoi.

Pas de bibliothèque Markdown : la structure produite par le rédacteur est connue
et fermée (six niveaux de titres, tableaux, puces, gras, citations, code en
ligne). Une soixantaine de lignes suffisent, sans ajouter une dépendance pour de
la mise en forme — et le résultat se teste, ce qu'un moteur externe ne donne pas.

Les styles sont **en ligne, sur chaque balise** : les clients de messagerie
suppriment volontiers une feuille de style, y compris dans l'en-tête du document.
"""

from __future__ import annotations

import html
import re
import unicodedata

# Palette sobre : un compte rendu se lit, il ne se contemple pas.
_ENCRE = "#24242b"
_ENCRE_PALE = "#5b5b66"
_FILET = "#e0e0e6"
_FOND_ENTETE = "#f6f6f8"
_POLICE = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
_POLICE_FIXE = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"

_STYLES = {
    "h1": f"margin:0 0 7px;font:600 25px/1.25 {_POLICE};color:{_ENCRE};"
          f"letter-spacing:-.01em",
    # Un intertitre qui a la taille du corps ne se voit pas : la hiérarchie se
    # lit à la taille et au filet, pas au gras seul.
    "h2": f"margin:38px 0 15px;padding-bottom:8px;border-bottom:2px solid {_ENCRE};"
          f"font:600 12px/1.3 {_POLICE};color:{_ENCRE};letter-spacing:.1em;"
          f"text-transform:uppercase",
    "h3": f"margin:26px 0 7px;font:600 16px/1.35 {_POLICE};color:{_ENCRE}",
    "p": f"margin:0 0 13px;font:400 14px/1.65 {_POLICE};color:{_ENCRE}",
    "li": f"margin:0 0 7px;font:400 14px/1.6 {_POLICE};color:{_ENCRE}",
    "ul": "margin:0 0 14px;padding-left:22px",
    "ol": "margin:0 0 14px;padding-left:22px",
    "table": f"border-collapse:collapse;width:100%;margin:6px 0 18px;font:400 13px/1.55 {_POLICE}",
    "th": f"background:{_FOND_ENTETE};border:1px solid {_FILET};padding:9px 11px;"
          f"text-align:left;font-weight:600;color:{_ENCRE};white-space:nowrap",
    "td": f"border:1px solid {_FILET};padding:9px 11px;vertical-align:top;color:{_ENCRE}",
    # Première colonne : « Kerann, Camilo, Tanguy » se cassait sur trois lignes
    # alors que la place existait.
    "td_premiere": f"border:1px solid {_FILET};padding:9px 11px;vertical-align:top;"
                   f"color:{_ENCRE};min-width:96px",
    # Une échéance non dite ne doit pas peser autant qu'une vraie date : répétée
    # dix fois dans une colonne, elle attirait l'œil plus que les deux qui
    # portaient un jour.
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
_LIEN = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_SEPARATEUR_TABLEAU = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$")


def _balise(style: str, contenu: str, extra: str = "", nom: str = "") -> str:
    """Balise HTML stylée. `nom` diffère de `style` quand plusieurs styles
    s'appliquent à la même balise, comme les variantes de cellule."""
    return f'<{nom or style} style="{_STYLES[style]}"{extra}>{contenu}</{nom or style}>'


#: Valeurs qui disent l'absence d'une donnée plutôt qu'une donnée.
_ABSENCES = frozenset({"non dit", "à attribuer", "a attribuer", "non précisé", "sans objet"})


def _style_cellule(contenu: str, rang: int) -> str:
    if contenu.strip().lower() in _ABSENCES:
        return "td_absent"
    return "td_premiere" if rang == 0 else "td"


def _en_ligne(texte: str) -> str:
    """Échappe le texte, puis rend gras, italique, code et liens."""
    sortie = html.escape(texte, quote=False)
    sortie = _CODE.sub(lambda m: _balise("code", m.group(1)), sortie)
    sortie = _GRAS.sub(r"<strong>\1</strong>", sortie)
    sortie = _ITALIQUE.sub(r"<em>\1</em>", sortie)
    return _LIEN.sub(
        lambda m: f'<a href="{m.group(2)}" style="color:#2c5aa0">{m.group(1)}</a>', sortie
    )


def _ancre(titre: str) -> str:
    """Identifiant stable pour une section, sans accent ni espace."""
    sans_accent = unicodedata.normalize("NFKD", titre).encode("ascii", "ignore").decode()
    return "s-" + re.sub(r"[^a-z0-9]+", "-", sans_accent.lower()).strip("-")


def sections(compte_rendu: str) -> list[str]:
    """Intitulés des sections de deuxième niveau, dans l'ordre du document."""
    return [
        ligne.strip().lstrip("#").strip()
        for ligne in compte_rendu.splitlines()
        if ligne.strip().startswith("## ")
    ]


def _sommaire(compte_rendu: str) -> str:
    """Sommaire en tête du courriel, sur toute la largeur.

    Les entrées se suivent en ligne plutôt qu'en colonne : une liste verticale
    de cinq intitulés courts occupait un quart de la largeur et laissait le
    reste vide, ce qui donnait au document l'air d'être mal cadré.

    Les liens internes ne fonctionnent pas dans tous les logiciels de
    messagerie. Le sommaire garde sa valeur même inerte : il dit d'un coup
    d'œil ce que le document contient et dans quel ordre.
    """
    titres = sections(compte_rendu)
    if len(titres) < 3:
        return ""
    entrees = "".join(
        f'<span style="white-space:nowrap;margin:0 22px 0 0;'
        f'font:400 13px/2 {_POLICE}">'
        f'<span style="color:{_ENCRE_PALE}">{numero}.</span> '
        f'<a href="#{_ancre(titre)}" style="color:{_ENCRE};text-decoration:none">'
        f"{html.escape(titre)}</a></span>"
        for numero, titre in enumerate(titres, 1)
    )
    return (
        f'<div style="margin:0 0 30px;padding:13px 17px;background:{_FOND_ENTETE};'
        f'border-left:3px solid {_ENCRE};border-radius:0 4px 4px 0">'
        f'<div style="font:600 10px/1 {_POLICE};letter-spacing:.11em;'
        f'text-transform:uppercase;color:{_ENCRE_PALE};padding-bottom:7px">Sommaire</div>'
        f"{entrees}</div>"
    )


def _cellules(ligne: str) -> list[str]:
    return [c.strip() for c in ligne.strip().strip("|").split("|")]


def en_html(markdown: str) -> str:
    """Convertit le compte rendu en fragment HTML, styles en ligne compris."""
    lignes = markdown.splitlines()
    sortie: list[str] = []
    i = 0
    while i < len(lignes):
        ligne = lignes[i]
        nue = ligne.strip()

        if not nue:
            i += 1
            continue

        if nue.startswith("#"):
            niveau = len(nue) - len(nue.lstrip("#"))
            nom = f"h{min(niveau, 3)}"
            texte = nue.lstrip("#").strip()
            # Ancre sur les sections seulement : c'est là que le sommaire mène.
            ancre = f' id="{_ancre(texte)}"' if niveau == 2 else ""
            sortie.append(_balise(nom, _en_ligne(texte), ancre))
            i += 1
            continue

        if set(nue) <= {"-", "*", "_"} and len(nue) >= 3:
            sortie.append(f'<hr style="{_STYLES["hr"]}">')
            i += 1
            continue

        # Tableau : une ligne de cellules suivie d'une ligne de séparateurs.
        if "|" in nue and i + 1 < len(lignes) and _SEPARATEUR_TABLEAU.match(lignes[i + 1]):
            entetes = _cellules(nue)
            i += 2
            corps: list[list[str]] = []
            while i < len(lignes) and "|" in lignes[i]:
                corps.append(_cellules(lignes[i]))
                i += 1
            tete = "".join(_balise("th", _en_ligne(c)) for c in entetes)
            rangs = "".join(
                "<tr>"
                + "".join(
                    _balise(_style_cellule(c, rang), _en_ligne(c), nom="td")
                    for rang, c in enumerate(r)
                )
                + "</tr>"
                for r in corps
            )
            sortie.append(_balise("table", f"<thead><tr>{tete}</tr></thead><tbody>{rangs}</tbody>"))
            continue

        if nue.startswith((">", "&gt;")):
            bloc = []
            while i < len(lignes) and lignes[i].strip().startswith((">", "&gt;")):
                bloc.append(lignes[i].strip().lstrip(">").strip())
                i += 1
            sortie.append(_balise("blockquote", _en_ligne(" ".join(bloc))))
            continue

        if re.match(r"^[-*+]\s+", nue) or re.match(r"^\d+[.)]\s+", nue):
            ordonnee = bool(re.match(r"^\d+[.)]\s+", nue))
            items = []
            while i < len(lignes):
                courante = lignes[i].strip()
                if re.match(r"^[-*+]\s+", courante) or re.match(r"^\d+[.)]\s+", courante):
                    items.append(re.sub(r"^([-*+]|\d+[.)])\s+", "", courante))
                    i += 1
                elif courante and not courante.startswith("#") and items:
                    # Continuation d'un item sur la ligne suivante.
                    items[-1] += " " + courante
                    i += 1
                else:
                    break
            contenu = "".join(_balise("li", _en_ligne(t)) for t in items)
            sortie.append(_balise("ol" if ordonnee else "ul", contenu))
            continue

        # Paragraphe : tout ce qui suit jusqu'à une ligne vide.
        bloc = []
        while (i < len(lignes) and lignes[i].strip()
               and not lignes[i].strip().startswith(("#", ">", "|"))):
            bloc.append(lignes[i].strip())
            i += 1
        if bloc:
            sortie.append(_balise("p", _en_ligne(" ".join(bloc))))
        else:
            i += 1

    return "\n".join(sortie)


def _entete(compte_rendu: str) -> tuple[str, str]:
    """Sépare le titre et la ligne de contexte du reste du document.

    Les deux forment l'en-tête du courriel : un titre lisible et, dessous, la
    date et les participants. Le reste suit le sommaire.
    """
    lignes = compte_rendu.splitlines()
    titre = contexte = ""
    reste = 0
    for indice, ligne in enumerate(lignes):
        nue = ligne.strip()
        if not nue:
            continue
        if not titre and nue.startswith("# "):
            titre = nue[2:].strip()
            reste = indice + 1
            continue
        if titre and not contexte and not nue.startswith("#"):
            contexte = nue
            reste = indice + 1
        break
    if not titre:
        return "", compte_rendu
    bloc = (
        f'<h1 style="{_STYLES["h1"]}">{_en_ligne(titre)}</h1>'
        + (
            f'<p style="margin:0 0 24px;font:400 13px/1.5 {_POLICE};'
            f'color:{_ENCRE_PALE}">{_en_ligne(contexte)}</p>'
            if contexte
            else ""
        )
    )
    return bloc, "\n".join(lignes[reste:])


def courriel(compte_rendu: str, pied: str = "") -> str:
    """Enveloppe le compte rendu dans un document complet, prêt à envoyer."""
    entete, suite = _entete(compte_rendu)
    corps = entete + _sommaire(compte_rendu) + en_html(suite)
    signature = (
        f'<p style="margin:28px 0 0;padding-top:14px;border-top:1px solid {_FILET};'
        f'font:400 12px/1.5 {_POLICE};color:{_ENCRE_PALE}">{html.escape(pied)}</p>'
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


def sujet(compte_rendu: str, defaut: str) -> str:
    """Sujet du courriel : le titre du compte rendu, pas le nom du fichier.

    « Compte rendu de réunion — 2026-08-25_14h33_reunion-essai-reel » n'aide
    personne à retrouver un message six mois plus tard.
    """
    for ligne in compte_rendu.splitlines():
        nue = ligne.strip()
        if nue.startswith("# "):
            titre = _GRAS.sub(r"\1", nue[2:].strip())
            return titre or defaut
        if nue:
            break
    return defaut
