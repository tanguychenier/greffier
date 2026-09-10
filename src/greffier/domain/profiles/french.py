"""French: the rules measured on real meetings."""

from __future__ import annotations

import re

from greffier.domain.language import Detection, LanguageProfile, Splitting, Wording
from greffier.domain.models import MentionKind

_NAME = r"(?P<nom>[A-ZÉÈÊÀÂÎÔÛÇ][\w'’-]{1,19})"

_MOTIFS: list[tuple[MentionKind, re.Pattern[str], bool]] = [
    (MentionKind.AUTO_PRESENTATION, re.compile(
        r"(?i:\bje m['’]appelle|\bmoi,? c['’]est)\s+" + _NAME
    ), False),
    (MentionKind.AUTO_PRESENTATION, re.compile(
        r"(?i:\bc['’]est)\s+" + _NAME + r"\s+(?i:qui\s+(?:vous\s+)?parle)"
    ), False),
    (MentionKind.AUTO_PRESENTATION, re.compile(
        r"(?i:\bje suis)\s+" + _NAME + r"\b"
    ), False),
    (MentionKind.AUTO_PRESENTATION, re.compile(
        _NAME + r"\s*,?\s*(?i:à l['’]appareil)"
    ), False),
    (MentionKind.INTERPELLATION, re.compile(
        _NAME + r"\s*,\s*(?:(?i:tu|vous)\s+(?!(?i:vois|voyez|sais|savez)\b)"
        r"|(?i:est-ce que\b|peux-tu\b|pouvez-vous\b|qu['’]en penses|qu['’]en pensez))"
    ), False),
    (MentionKind.INTERPELLATION, re.compile(
        r"(?i:\bvas-y|\ballez-y|\bà toi|\bje te laisse|\bje vous laisse"
        r"|\bje passe la parole à|\bla parole (?:est )?à)\s+" + _NAME + r"\b"
    ), False),
    (MentionKind.RENVOI, re.compile(
        r"(?i:\bmerci)\s+" + _NAME + r"\b"
    ), False),
    (MentionKind.RENVOI, re.compile(
        r"(?i:\bcomme (?:le |l['’])?(?:disait|dit|a dit)|\bd['’]accord avec"
        r"|\bje rejoins|\bje suis d['’]accord avec)\s+" + _NAME + r"\b"
    ), False),
    (MentionKind.RENVOI, re.compile(
        _NAME + r"\s+(?i:a raison|vient de (?:le )?dire|l['’]a dit)\b"
    ), False),
    (MentionKind.INTERPELLATION, re.compile(
        r"(?i:\btoi)\s*,\s*" + _NAME + r"\b"
    ), False),
    (MentionKind.INTERPELLATION, re.compile(
        r"(?:^|(?<=[.?!]\s))" + _NAME + r"\s*,\s*(?=[^.?!]{0,60}?\b(?i:tu|vous|on)\b)"
    ), False),
    (MentionKind.INTERPELLATION, re.compile(
        r"^" + _NAME + r"\s*[,.?!]?\s*$"
    ), True),
    (MentionKind.RENVOI, re.compile(
        r"(?i:\bqu[e\u2019']\s*(?:présentait|présente|disait|expliquait|proposait"
        r"|évoquait|montrait|a présenté|a dit))\s+" + _NAME + r"\b"
    ), False),
]

EXCLUS_PAR_DEFAUT: frozenset[str] = frozenset({
    "mais", "bon", "bref", "ensuite", "enfin", "ecoute", "ecoutez", "attends",
    "ok", "ah", "eh", "euh", "apres", "avant", "sinon", "sur", "dans", "les",
    "est", "peut", "parce", "pourquoi", "comment", "quand", "moi", "toi", "lui",
    "elle", "nous", "vous", "ils", "elles", "ca", "cela", "ceci", "celui",
    "effectivement", "exactement", "super", "parfait", "tres", "plus", "moins",
    "tiens", "tenez", "regarde", "regardez", "voyons", "allez", "vas",
    "dis", "dites", "figure", "imagine", "franchement", "honnetement",
    "petit", "grand", "aujourd'hui", "hier", "demain", "pareil", "pardon", "desole",
    "bonjour", "bonsoir", "merci", "oui", "non", "voila", "donc", "alors",
    "monsieur", "madame", "tout", "tous", "toute", "toutes", "beaucoup",
    "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche",
    "janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout",
    "septembre", "octobre", "novembre", "decembre",
    "teams", "zoom", "jira", "gitlab", "outlook", "claude", "mac", "windows",
    "france", "paris", "universite",
})

BOILERPLATE: frozenset[str] = frozenset({
    "sous titrage",
    "sous titrage realise par",
    "sous titrage realise par la communaute d amara org",
    "sous titrage realise par la communaute d amara",
    "sous titrage societe radio canada",
    "sous titres realises par la communaute d amara org",
    "sous titres realises par la communaute",
    "sous titres realises par",
    "sous titres par",
    "traduction et sous titrage",
    "amara org",
    "merci d avoir regarde cette video",
    "merci d avoir regarde",
    "merci de votre attention",
    "abonnez vous",
    "n oubliez pas de vous abonner",
})

_DECISIONS = [
    re.compile(r"(?i:\bon (?:décide|acte|valide|part sur|retient)\b)"),
    re.compile(r"(?i:\bil faut (?:qu[e']|absolument)\b)"),
    re.compile(r"(?i:\bje (?:m'en charge|prends|note)\b)"),
    re.compile(r"(?i:\b(?:action|à faire|suite à donner)\s*:)"),
    re.compile(r"(?i:\bd'ici (?:lundi|mardi|mercredi|jeudi|vendredi|la semaine|le)\b)"),
]

FRENCH = LanguageProfile(
    code="fr",
    name="Français",
    detection=Detection(
        active=True,
        motifs=tuple(_MOTIFS),
        exclus=EXCLUS_PAR_DEFAUT,
        longueur_minimale=3,
        suffixe_adverbial="ment",
        longueur_du_suffixe=8,
    ),
    decoupage=Splitting(mots_separes_par_des_espaces=True),
    redaction=Wording(boilerplate=BOILERPLATE, motifs_de_decision=tuple(_DECISIONS)),
)
