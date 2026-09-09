"""Configuration de Greffier.

Trois sources, de la plus forte à la plus faible :

1. les variables d'environnement, préfixées `GREFFIER_` ;
2. un fichier `.env` — celui du dossier courant, sinon celui de la configuration ;
3. un fichier `config.toml`, pour qui préfère un format structuré.

Tout est facultatif. Un poste sans aucun de ces fichiers doit fonctionner avec
des valeurs par défaut raisonnables, sinon la première utilisation devient une
séance de réglages. Rien de tout cela ne vit dans le dépôt : l'adresse mail, le
vocabulaire métier et les noms de projets sont propres à chacun, et les avoir
eus en dur est précisément ce qui rendait la chaîne d'origine impubliable.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
import tempfile
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

# Les emplacements vivent dans un module sans dépendance : l'installeur les lit
# avant que pydantic ne soit installé, et doit dire la même chose que nous.
from greffier.emplacements import dossier_config, dossier_donnees

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - repli pour les postes en 3.9/3.10
    import tomli as tomllib


class Chemins(BaseModel):
    modeles: Path = Field(default_factory=lambda: dossier_donnees() / "modeles")
    donnees: Path = Field(default_factory=dossier_donnees)

    @property
    def enregistrements(self) -> Path:
        return self.donnees / "enregistrements"

    @property
    def transcriptions(self) -> Path:
        return self.donnees / "transcriptions"

    @property
    def comptes_rendus(self) -> Path:
        return self.donnees / "comptes-rendus"

    @property
    def banque_de_voix(self) -> Path:
        return self.donnees / "banque-de-voix"

    @property
    def direct(self) -> Path:
        """Le fil de ce qui se dit, réunion par réunion.

        Conservé après la réunion : c'est la trace de qui a corrigé quoi, et le
        seul endroit où l'on peut vérifier qu'une attribution vient d'un humain
        et non d'une empreinte.
        """
        return self.donnees / "direct"

    @property
    def propositions(self) -> Path:
        """Ce que la veille a proposé pendant la réunion, réunion par réunion.

        Défini ici et non à l'endroit qui l'ouvre : le chemin était écrit en
        dur à deux endroits de la ligne de commande, donc invisible pour qui
        veut ranger ou effacer une réunion.
        """
        return self.donnees / "propositions"

    @property
    def contexte(self) -> Path:
        """Le glossaire du milieu de travail : sigles, produits, personnes.

        Hors de `config.toml` : il grossit, se partage entre collègues et se
        relit à la main, ce qu'un fichier régénéré à chaque changement dans la
        fenêtre supporte mal.
        """
        return dossier_config() / "contexte.toml"

    @property
    def questions(self) -> Path:
        """Ce que l'outil a demandé pendant la réunion, et ce qu'on a répondu.

        Dans les données et non dans la configuration : c'est la trace d'une
        réunion, elle vit et meurt avec elle.
        """
        return self.donnees / "questions"


class Audio(BaseModel):
    # Sur macOS, deux périphériques à créer une fois. Ailleurs, le système
    # expose déjà de quoi réenregistrer sa propre sortie.
    entree: str = "Reunion Entree" if platform.system() == "Darwin" else "default"
    sortie: str = "Reunion Sortie" if platform.system() == "Darwin" else "default.monitor"
    # Micro que le périphérique agrégé doit porter. Vide : le meilleur micro
    # réellement branché au moment de démarrer. C'est ce réglage que la veille
    # cherche à retrouver quand le matériel change en cours de réunion.
    micro: str = ""
    # Garde-fou : sans second clic, l'enregistrement tournerait jusqu'à remplir
    # le disque (~115 Mo/h). Quatre heures couvrent largement une réunion.
    duree_maximale: int = 14_400


class Transcription(BaseModel):
    moteur: str = "whisper.cpp" if platform.system() == "Darwin" else "faster-whisper"
    # Taille du modèle pour faster-whisper ; ignoré par whisper.cpp, qui prend le
    # fichier téléchargé par l'installeur.
    modele: str = "large-v3"
    #: Code de langue à deux lettres. **Vide : le modèle la reconnaît lui-même**,
    #: ce qu'il faut pour une réunion qui bascule d'une langue à l'autre. Le
    #: défaut reste le français : l'annoncer vaut mieux que la faire deviner
    #: quand on la connaît.
    langue: str = "fr"
    # Passé au modèle en amorce : c'est ce qui améliore le plus la transcription
    # des noms propres et des acronymes rares.
    vocabulaire: list[str] = Field(default_factory=list)

    @property
    def amorce(self) -> str:
        if not self.vocabulaire:
            return ""
        return "Réunion de travail. Vocabulaire : " + ", ".join(self.vocabulaire) + "."


class Direct(BaseModel):
    """La transcription affichée pendant que la réunion a lieu.

    Elle a un coût : un second modèle de transcription tourne en parallèle de la
    capture, et une empreinte vocale est calculée à chaque tranche. C'est le prix
    de pouvoir corriger un locuteur **pendant** la réunion plutôt que de
    découvrir l'erreur dans le compte rendu.
    """

    actif: bool = True
    #: Toutes les combien de secondes une tranche est transcrite. Trente ne se
    #: vivent pas comme du direct : on parle, et rien n'apparaît pendant une
    #: demi-minute. Dix laissent le temps d'une phrase entière tout en gardant
    #: l'impression que l'outil suit.
    periode: float = 10.0
    #: Taille du modèle de transcription du direct. **Vide : celui que la
    #: machine fait tourner sans souffrir**, le même que la transcription
    #: définitive quand elle en a les moyens.
    #:
    #: « small » était le défaut, au motif qu'il faut être rapide plutôt que
    #: juste. Mesuré sur un Mac Apple Silicon, tranche réelle de dix secondes :
    #: 0,72 s avec `small` pour trois fragments faux, 1,44 s avec
    #: `large-v3-turbo` pour une phrase cohérente. Le budget d'une tranche est
    #: de dix secondes : le grand modèle tient avec sept fois la marge, et le
    #: petit rendait le fil du direct illisible pour rien.
    modele: str = ""


class Locuteurs(BaseModel):
    # Mots que la détection des prénoms ne doit jamais retenir : noms de
    # projets, d'outils, de produits.
    pas_des_prenoms: list[str] = Field(default_factory=list)
    # Laissé vide, le nombre de participants est déduit par recollage des voix.
    personnes: int | None = None


#: Les modèles que Claude Code accepte comme alias, du plus puissant au plus
#: léger. Le libellé dit à quoi sert chacun ici, pas ce que vaut le modèle en
#: général : c'est le choix « pour rédiger un compte rendu » qu'on présente.
#:
#: Ici et non dans l'assistant de première configuration : la fenêtre s'en sert
#: aussi, et allait le chercher dans un assistant en terminal dont elle n'a que
#: faire. Le défaut, lui, est juste à côté — CLAUDE_PAR_DEFAUT.
MODELES_CLAUDE: list[tuple[str, str]] = [
    ("opus", "Opus — recommandé : la synthèse est excellente et le quota tient"),
    ("fable", "Fable — le haut de la gamme, plus coûteux pour un compte rendu identique"),
    ("sonnet", "Sonnet — plus léger et plus rapide, synthèse un peu moins fine"),
    ("haiku", "Haiku — le plus économique, à réserver aux réunions courtes"),
]


class CompteRendu(BaseModel):
    """Qui rédige, et où va le résultat.

    Claude Code par défaut : distinguer une décision d'une hypothèse et
    rattacher une position à une personne reste hors de portée des modèles qui
    tournent sur un portable. C'est le seul maillon de la chaîne qui sort du
    poste, et c'est un choix assumé — `ollama` le remplace pour qui veut du
    100 % local, au prix d'une synthèse plus grossière.
    """

    moteur: str = "claude"       # claude | ollama | aucun
    #: La langue du DOCUMENT. Vide : celle de la réunion.
    #:
    #: Distincte de `transcription.langue`, dont le vide veut dire « reconnais-la
    #: toi-même » et ne dit rien de la langue dans laquelle écrire. On peut tenir
    #: une réunion en anglais et vouloir son compte rendu en français.
    langue: str = ""
    #: Le modèle du moteur choisi. Vide : celui que `modele_effectif` désigne,
    #: qui dépend du moteur — un nom de modèle Ollama n'a aucun sens pour Claude
    #: Code, et l'inverse non plus.
    modele: str = ""
    destinataire: str = ""
    #: Secondes accordées au rédacteur avant de renoncer. Réglable parce que la
    #: bonne valeur dépend de la longueur des réunions et de la charge du
    #: service : 900 s codées en dur ont fait échouer la rédaction d'une réunion
    #: de 32 minutes le 2026-09-09, sans recours pour qui la relançait. Dépasser
    #: ce délai ne perd plus rien — la transcription est gardée avant, et
    #: « greffier rediger » reprend.
    delai: int = 1800

    #: Ce que Claude Code utilise quand rien n'est demandé. **Pas le modèle le
    #: plus puissant, le second** : rédiger un compte rendu à partir d'une
    #: transcription déjà attribuée est un travail de synthèse, pas de
    #: raisonnement long. Le premier de la gamme coûte plus cher sans rendre un
    #: meilleur document, et une réunion par jour suffirait à entamer un quota.
    CLAUDE_PAR_DEFAUT: ClassVar[str] = "opus"
    OLLAMA_PAR_DEFAUT: ClassVar[str] = "qwen3:8b"

    @property
    def modele_effectif(self) -> str:
        """Le modèle à passer au moteur, réglage vide compris."""
        if self.modele:
            return self.modele
        if self.moteur == "claude":
            return self.CLAUDE_PAR_DEFAUT
        if self.moteur == "ollama":
            return self.OLLAMA_PAR_DEFAUT
        return ""


class Apparence(BaseModel):
    """Ce que la fenêtre montre, indépendamment de ce qu'elle fait.

    « systeme » suit le réglage clair/sombre du poste : c'est le défaut, parce
    qu'une application qui impose son goût jure avec tout le reste de l'écran.
    Les deux autres valeurs forcent, pour qui préfère.
    """

    theme: str = "systeme"       # systeme | clair | sombre


class Courriel(BaseModel):
    """Envoi par SMTP, pour les postes sans Outlook.

    Le mot de passe ne figure jamais ici : il vient de la variable
    `GREFFIER_SMTP_MOT_DE_PASSE`, qu'on peut fournir par un gestionnaire de
    secrets plutôt que par un fichier.
    """

    serveur: str = ""
    port: int = 587
    utilisateur: str = ""
    expediteur: str = ""


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GREFFIER_",
        env_nested_delimiter="__",
        env_file=(".env", str(dossier_config() / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    chemins: Chemins = Field(default_factory=Chemins)
    audio: Audio = Field(default_factory=Audio)
    transcription: Transcription = Field(default_factory=Transcription)
    direct: Direct = Field(default_factory=Direct)
    locuteurs: Locuteurs = Field(default_factory=Locuteurs)
    compte_rendu: CompteRendu = Field(default_factory=CompteRendu)
    courriel: Courriel = Field(default_factory=Courriel)
    apparence: Apparence = Field(default_factory=Apparence)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # L'environnement l'emporte sur le .env, qui l'emporte sur le TOML :
        # on doit pouvoir forcer un réglage le temps d'une commande sans
        # modifier de fichier.
        return (init_settings, env_settings, dotenv_settings, _SourceToml(settings_cls))

    @classmethod
    def charger(cls, fichier: Path | None = None) -> Config:
        """Lit la configuration, ou rend les valeurs par défaut si elle manque."""
        if fichier is not None:
            # « model_validate » et non un dépliage : la structure vient d'un
            # fichier, elle doit être validée, pas supposée conforme.
            return cls.model_validate(_lire_toml(fichier))
        return cls()


def _lire_toml(chemin: Path) -> dict[str, object]:
    """Contenu d'un fichier TOML, vide s'il n'existe pas.

    Un fichier absent n'est pas une erreur : c'est le cas d'un poste qui vient
    d'installer. Un fichier illisible en est une — mieux vaut le dire que
    d'appliquer silencieusement autre chose que ce qui y est écrit.
    """
    if not chemin.exists():
        return {}
    try:
        return tomllib.loads(chemin.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as erreur:
        raise ValueError(f"{chemin} est illisible : {erreur}") from erreur


class _SourceToml(PydanticBaseSettingsSource):
    """Lit `config.toml` s'il existe, en dernier recours."""

    def get_field_value(  # pragma: no cover - la source ne lit jamais champ par champ
        self, field: object, field_name: str
    ) -> tuple[object, str, bool]:
        return None, field_name, False

    def __call__(self) -> dict[str, object]:
        return _lire_toml(dossier_config() / "config.toml")


# --------------------------------------------------------------- écriture
#
# Venu de `reglages`, qui vivait à la racine du paquet. C'est la moitié écriture
# de ce module : même fichier cible, même dossier, même objet. Les tenir
# séparés est ce qui rendait possible qu'ils divergent — et le dictionnaire
# SECTIONS énumère à la main les champs à réécrire, si bien qu'un champ ajouté
# ici et oublié là était perdu au premier enregistrement depuis la fenêtre.
#
# Écrit `config.toml`, ce que rien ne savait faire jusqu'ici.
# 
# La configuration était lue de trois sources et modifiable seulement à la main,
# ou par l'assistant qui écrivait un `.env`. Régler le micro ou le rédacteur
# depuis la fenêtre demande de savoir **écrire**, et d'écrire au même endroit que
# celui d'où on lit — deux fichiers qui se contredisent valent moins que pas de
# fichier du tout.
# 
# Le fichier est **régénéré**, pas rustiné : les commentaires sont réécrits à
# partir de ce module, donc ils ne mentent jamais sur ce que vaut le réglage
# voisin. Ce que l'utilisateur avait écrit lui-même dans le fichier est conservé
# dans une sauvegarde `config.toml.precedent`, jamais silencieusement perdu.
# 
# Seuls les réglages que l'interface propose passent ici. Les chemins, le
# vocabulaire et les mots qui ne sont pas des prénoms restent au fichier : ce sont
# des listes qui se tiennent mieux dans un éditeur que dans un formulaire, et les
# écrire depuis la fenêtre reviendrait à les tronquer.


#: Ce qui est écrit, section par section, dans cet ordre. **Tout** ce que la
#: configuration porte de significatif y figure, pas seulement ce que la fenêtre
#: règle : le fichier est régénéré, donc un champ absent d'ici serait perdu — le
#: vocabulaire d'une équipe, par exemple, qui se compte en dizaines de mots et
#: dont la perte dégraderait chaque transcription suivante sans rien annoncer.
#:
#: `chemins` en est délibérément absent. L'y écrire figerait les dossiers dans
#: le fichier : c'est ce que faisait la version précédente, et un poste dont les
#: données ont déménagé continuait de lire l'ancien emplacement.
SECTIONS: dict[str, tuple[str, ...]] = {
    "audio": ("micro", "entree", "sortie", "duree_maximale"),
    "transcription": ("moteur", "modele", "langue", "vocabulaire"),
    "direct": ("actif", "periode", "modele"),
    "locuteurs": ("pas_des_prenoms", "personnes"),
    "compte_rendu": ("moteur", "modele", "langue", "destinataire", "delai"),
    "courriel": ("serveur", "port", "utilisateur", "expediteur"),
    "apparence": ("theme",),
}

_COMMENTAIRES = {
    "audio": "Périphériques de capture. « micro » vide : le mieux entendu au démarrage.",
    "transcription": ("Le modèle de la transcription définitive, faite après la réunion.\n"
                      "# « vocabulaire » est ce qui améliore le plus les noms propres rares."),
    "direct": "Ce qui s'affiche pendant la réunion. Un second modèle tourne : c'est son coût.",
    "locuteurs": "Mots à ne jamais prendre pour des prénoms : projets, outils, produits.",
    "compte_rendu": ("Qui rédige, avec quel modèle, et à qui le compte rendu part.\n"
                     "# « modele » vide : le second de la gamme, qui suffit pour une synthèse.\n"
                     "# « delai » : secondes accordées au rédacteur. Le dépasser ne perd rien,\n"
                     "# la transcription est gardée avant ; « greffier rediger » reprend."),
    "courriel": "Envoi SMTP, pour les postes sans Outlook. Le mot de passe n'est jamais ici.",
    "apparence": "systeme suit le réglage clair/sombre du poste.",
}

_ENTETE = """# Configuration de Greffier.
#
# Écrit par l'onglet Réglages de la fenêtre ; modifiable à la main sans risque.
# Tout est facultatif : ce qui manque reprend la valeur par défaut. Les
# variables « GREFFIER_* » et un fichier « .env » l'emportent sur ce fichier,
# dans cet ordre — on doit pouvoir forcer un réglage le temps d'une commande.
#
# La version précédente de ce fichier est conservée en « config.toml.precedent ».
"""


def fichier_config(dossier: Path | None = None) -> Path:
    return (dossier or dossier_config()) / "config.toml"


def rendre(config: Config) -> str:
    """Le contenu TOML de cette configuration. Fonction pure, éprouvable seule."""
    morceaux = [_ENTETE]
    for section, champs in SECTIONS.items():
        modele = getattr(config, section)
        lignes = []
        if section in _COMMENTAIRES:
            lignes.append(f"# {_COMMENTAIRES[section]}")
        lignes.append(f"[{section}]")
        for champ in champs:
            valeur = getattr(modele, champ)
            # TOML n'a pas de « null » : un champ non renseigné s'omet, et la
            # valeur par défaut reprend la main à la lecture.
            if valeur is None:
                continue
            lignes.append(f"{champ} = {_valeur(valeur)}")
        morceaux.append("\n".join(lignes))
    return "\n\n".join(morceaux) + "\n"


def _valeur(valeur: object) -> str:
    """Un scalaire ou une liste, en TOML.

    Pas de `json.dumps` : il rendrait bien `True` en `true` par chance, mais
    aussi les chemins en objets et les caractères accentués en séquences
    d'échappement, là où TOML attend de l'UTF-8 tel quel.
    """
    if isinstance(valeur, bool):
        return "true" if valeur else "false"
    if isinstance(valeur, (int, float)):
        return repr(valeur)
    if isinstance(valeur, (list, tuple)):
        if not valeur:
            return "[]"
        return "[" + ", ".join(_valeur(v) for v in valeur) + "]"
    texte = str(valeur).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{texte}"'


def sauver(config: Config, dossier: Path | None = None) -> Path:
    """Écrit la configuration, en gardant une copie de la précédente.

    Écriture atomique : un remplacement, jamais un fichier tronqué. La fenêtre
    enregistre pendant qu'une réunion peut tourner, et un processus auxiliaire
    qui relirait un fichier à moitié écrit s'arrêterait sur une erreur de
    syntaxe.
    """
    cible = fichier_config(dossier)
    cible.parent.mkdir(parents=True, exist_ok=True)
    if cible.exists():
        shutil.copy2(cible, cible.with_suffix(".toml.precedent"))
    # Le fichier temporaire naît dans le dossier de destination : un
    # remplacement n'est atomique que sur le même système de fichiers.
    descripteur, provisoire = tempfile.mkstemp(dir=cible.parent, prefix=".config-",
                                               suffix=".toml")
    try:
        with os.fdopen(descripteur, "w", encoding="utf-8") as flux:
            flux.write(rendre(config))
        os.replace(provisoire, cible)
    except BaseException:
        Path(provisoire).unlink(missing_ok=True)
        raise
    return cible
