"""Le français : les règles éprouvées sur de vraies réunions.

Chaque motif, chaque exclusion et chaque seuil de ce fichier vient d'un incident
mesuré sur un enregistrement réel, et son commentaire l'explique. C'est ce qui
distingue ce profil d'une simple table de traduction, et ce qui rend malhonnête
d'en recopier la forme dans une autre langue sans l'avoir éprouvée : les règles
ne décrivent pas une grammaire, elles décrivent ce que des gens ont dit.

Déplacé depuis `noms`, `generiques` et `instructions` sans qu'une règle change :
les tests qui les gardaient sont les mêmes, et ce sont eux qui prouvent que le
déplacement n'a rien coûté.
"""

from __future__ import annotations

import re

from greffier.domaine.langue import Decoupage, Detection, ProfilLinguistique, Redaction
from greffier.domaine.modeles import TypeMention

# Un nom propre commence par une majuscule — whisper les restitue ainsi. Les
# mots déclencheurs, eux, sont insensibles à la casse : « Merci » en début de
# phrase et « merci » au fil de l'eau désignent la même chose. D'où les
# drapeaux locaux « (?i:…) », qui laissent la contrainte de majuscule intacte
# sur le nom lui-même.
_NOM = r"(?P<nom>[A-ZÉÈÊÀÂÎÔÛÇ][\w'’-]{1,19})"

# Troisième membre : « confirmation seule ». Un tel motif est trop large pour
# désigner un prénom à lui seul — il ne compte que si le nom a déjà été repéré
# par un motif franc ailleurs dans la réunion.
_MOTIFS: list[tuple[TypeMention, re.Pattern[str], bool]] = [
    # --- le locuteur se nomme lui-même ---
    (TypeMention.AUTO_PRESENTATION, re.compile(
        r"(?i:\bje m['’]appelle|\bmoi,? c['’]est)\s+" + _NOM
    ), False),
    # « c'est Marc » tout court désignerait n'importe qui : on exige la formule
    # complète, sans quoi une phrase à propos d'un absent le ferait participant.
    (TypeMention.AUTO_PRESENTATION, re.compile(
        r"(?i:\bc['’]est)\s+" + _NOM + r"\s+(?i:qui\s+(?:vous\s+)?parle)"
    ), False),
    (TypeMention.AUTO_PRESENTATION, re.compile(
        r"(?i:\bje suis)\s+" + _NOM + r"\b"
    ), False),
    (TypeMention.AUTO_PRESENTATION, re.compile(
        _NOM + r"\s*,?\s*(?i:à l['’]appareil)"
    ), False),
    # --- le locuteur passe la parole à quelqu'un ---
    # « tu vois », « tu sais », « vous voyez » sont des tics de langage, pas des
    # adresses : sans cette exception, « un macro Kanban, tu vois » ferait de
    # Kanban un participant. Constaté sur une vraie réunion.
    (TypeMention.INTERPELLATION, re.compile(
        _NOM + r"\s*,\s*(?:(?i:tu|vous)\s+(?!(?i:vois|voyez|sais|savez)\b)"
        r"|(?i:est-ce que\b|peux-tu\b|pouvez-vous\b|qu['’]en penses|qu['’]en pensez))"
    ), False),
    (TypeMention.INTERPELLATION, re.compile(
        r"(?i:\bvas-y|\ballez-y|\bà toi|\bje te laisse|\bje vous laisse"
        r"|\bje passe la parole à|\bla parole (?:est )?à)\s+" + _NOM + r"\b"
    ), False),
    # --- le locuteur renvoie à celui qui vient de parler ---
    (TypeMention.RENVOI, re.compile(
        r"(?i:\bmerci)\s+" + _NOM + r"\b"
    ), False),
    (TypeMention.RENVOI, re.compile(
        r"(?i:\bcomme (?:le |l['’])?(?:disait|dit|a dit)|\bd['’]accord avec"
        r"|\bje rejoins|\bje suis d['’]accord avec)\s+" + _NOM + r"\b"
    ), False),
    (TypeMention.RENVOI, re.compile(
        _NOM + r"\s+(?i:a raison|vient de (?:le )?dire|l['’]a dit)\b"
    ), False),
    # --- formulations relevées sur de vraies réunions ---
    # « Mais pour ça, toi, Josiane, c'est pas besoin ? »
    (TypeMention.INTERPELLATION, re.compile(
        r"(?i:\btoi)\s*,\s*" + _NOM + r"\b"
    ), False),
    # « Josiane, on a lu ensemble et tu nous diras » : un nom en tête de phrase
    # n'est un appel que si une adresse suit. L'anticipation évite de prendre
    # pour un prénom le premier mot capitalisé venu.
    (TypeMention.INTERPELLATION, re.compile(
        r"(?:^|(?<=[.?!]\s))" + _NOM + r"\s*,\s*(?=[^.?!]{0,60}?\b(?i:tu|vous|on)\b)"
    ), False),
    # Un segment réduit au seul mot : « Josiane. » appelle quelqu'un, mais
    # « Ouais. » et « Exact. » aussi passeraient. D'où la confirmation seule —
    # relevé sur la réunion du 2026-08-20, où ce motif ramassait tous les
    # acquiescements.
    (TypeMention.INTERPELLATION, re.compile(
        r"^" + _NOM + r"\s*[,.?!]?\s*$"
    ), True),
    # « pour ce que présentait Josiane »
    (TypeMention.RENVOI, re.compile(
        r"(?i:\bqu[e\u2019']\s*(?:présentait|présente|disait|expliquait|proposait"
        r"|évoquait|montrait|a présenté|a dit))\s+" + _NOM + r"\b"
    ), False),
]

# Mots qui passent les motifs sans être des noms de personne. Le vocabulaire
# métier du projet s'y ajoute par configuration : sans quoi « merci Copernic »
# créerait un participant.
EXCLUS_PAR_DEFAUT: frozenset[str] = frozenset({
    # Ouvertures de phrase : un mot capitalisé en tête n'est pas un prénom.
    "mais", "bon", "bref", "ensuite", "enfin", "ecoute", "ecoutez", "attends",
    "ok", "ah", "eh", "euh", "apres", "avant", "sinon", "sur", "dans", "les",
    "est", "peut", "parce", "pourquoi", "comment", "quand", "moi", "toi", "lui",
    "elle", "nous", "vous", "ils", "elles", "ca", "cela", "ceci", "celui",
    "effectivement", "exactement", "super", "parfait", "tres", "plus", "moins",
    # Interjections et impératifs d'attention : « Tiens, tu as vu ? » a été pris
    # pour un prénom sur une vraie réunion.
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

GENERIQUES: frozenset[str] = frozenset({
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

# Formulations qui annoncent une décision ou une suite à donner. Elles servent à
# faire remonter les points à retenir pendant la réunion, pas à décider.
_DECISIONS = [
    re.compile(r"(?i:\bon (?:décide|acte|valide|part sur|retient)\b)"),
    re.compile(r"(?i:\bil faut (?:qu[e']|absolument)\b)"),
    re.compile(r"(?i:\bje (?:m'en charge|prends|note)\b)"),
    re.compile(r"(?i:\b(?:action|à faire|suite à donner)\s*:)"),
    re.compile(r"(?i:\bd'ici (?:lundi|mardi|mercredi|jeudi|vendredi|la semaine|le)\b)"),
]

FRANCAIS = ProfilLinguistique(
    code="fr",
    nom="Français",
    detection=Detection(
        active=True,
        motifs=tuple(_MOTIFS),
        exclus=EXCLUS_PAR_DEFAUT,
        longueur_minimale=3,
        # Les adverbes en « -ment » ouvrent d'innombrables phrases —
        # « Effectivement, tu as raison », « Normalement, on livre jeudi » — et
        # aucun n'a moins de huit lettres. Le seuil épargne « Clément », à peu
        # près le seul prénom français de cette forme.
        suffixe_adverbial="ment",
        longueur_du_suffixe=8,
    ),
    decoupage=Decoupage(mots_separes_par_des_espaces=True),
    redaction=Redaction(generiques=GENERIQUES, motifs_de_decision=tuple(_DECISIONS)),
)
