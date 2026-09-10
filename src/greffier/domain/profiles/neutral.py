"""The profile for languages no measured rule serves yet.

It says so rather than pretending: first-name recognition is off, and the
interface reports it.
"""

from __future__ import annotations

from greffier.domain.language import Detection, LanguageProfile, Splitting

NEUTRAL = LanguageProfile(
    code="",
    name="",
    detection=Detection(active=False),
    decoupage=Splitting(mots_separes_par_des_espaces=False),
)
