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

import platform
import sys
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


class CompteRendu(BaseModel):
    """Qui rédige, et où va le résultat.

    Claude Code par défaut : distinguer une décision d'une hypothèse et
    rattacher une position à une personne reste hors de portée des modèles qui
    tournent sur un portable. C'est le seul maillon de la chaîne qui sort du
    poste, et c'est un choix assumé — `ollama` le remplace pour qui veut du
    100 % local, au prix d'une synthèse plus grossière.
    """

    moteur: str = "claude"       # claude | ollama | aucun
    #: Le modèle du moteur choisi. Vide : celui que `modele_effectif` désigne,
    #: qui dépend du moteur — un nom de modèle Ollama n'a aucun sens pour Claude
    #: Code, et l'inverse non plus.
    modele: str = ""
    destinataire: str = ""

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
