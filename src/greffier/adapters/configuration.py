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
import tempfile
import tomllib
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from greffier.locations import config_folder, data_folder


class Paths(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    models: Path = Field(
        default_factory=lambda: data_folder() / "modeles",
        validation_alias="modeles",
    )
    data: Path = Field(default_factory=data_folder, validation_alias="donnees")

    @property
    def recordings(self) -> Path:
        return self.data / "enregistrements"

    @property
    def transcripts(self) -> Path:
        return self.data / "transcriptions"

    @property
    def minutes_folder(self) -> Path:
        return self.data / "comptes-rendus"

    @property
    def gag(self) -> Path:
        """Où la voix dit quel processus joue le son, pour qu'on puisse le couper.

        À la racine des données et non dans un sous-dossier : deux processus
        doivent le trouver sans se concerter, et il ne survit pas à la phrase
        qu'il désigne.
        """
        return self.data / "parole.pid"

    @property
    def synthetic_voice(self) -> Path:
        """Le modèle qui donne une voix à l'assistant.

        Sous « modeles » comme les autres : c'est un modèle, il pèse trois cent
        vingt mégaoctets, et l'installeur le pose là comme il pose whisper.
        """
        return self.models / "voix"

    @property
    def voice_bank(self) -> Path:
        return self.data / "banque-de-voix"

    @property
    def live(self) -> Path:
        """Le fil de ce qui se dit, réunion par réunion.

        Conservé après la réunion : c'est la trace de qui a corrigé quoi, et le
        seul endroit où l'on peut vérifier qu'une attribution vient d'un humain
        et non d'une empreinte.
        """
        return self.data / "direct"

    @property
    def propositions(self) -> Path:
        """Ce que la veille a proposé pendant la réunion, réunion par réunion.

        Défini ici et non à l'endroit qui l'ouvre : le chemin était écrit en
        dur à deux endroits de la ligne de commande, donc invisible pour qui
        veut ranger ou effacer une réunion.
        """
        return self.data / "propositions"

    @property
    def context(self) -> Path:
        """Le glossaire du milieu de travail : sigles, produits, personnes.

        Hors de `config.toml` : il grossit, se partage entre collègues et se
        relit à la main, ce qu'un fichier régénéré à chaque changement dans la
        fenêtre supporte mal.
        """
        return config_folder() / "contexte.toml"

    @property
    def subjects(self) -> Path:
        """Les sujets suivis, leurs appellations et où vit la carte de chacun.

        À côté du contexte : deux registres tenus par un humain, qui
        grossissent et se relisent.
        """
        return config_folder() / "sujets.toml"

    @property
    def sources(self) -> Path:
        """Les sources extérieures que l'outil a le droit de consulter.

        Ce qui n'y figure pas est inatteignable : le registre est la borne, et
        c'est un humain qui l'écrit. Aucun jeton n'y vit — seulement le nom de
        la variable ou de l'entrée de trousseau qui le porte.
        """
        return config_folder() / "sources.toml"

    @property
    def pieces(self) -> Path:
        """Le texte des documents fournis pour une réunion.

        Sous les données et non dans le dossier de configuration : ce sont des
        pièces de réunion, elles suivent la rétention et la sauvegarde du
        reste.
        """
        return self.data / "pieces"

    @property
    def questions(self) -> Path:
        """Ce que l'outil a demandé pendant la réunion, et ce qu'on a répondu.

        Dans les données et non dans la configuration : c'est la trace d'une
        réunion, elle vit et meurt avec elle.
        """
        return self.data / "questions"

    @property
    def conversations(self) -> Path:
        """Ce qu'on s'est dit avec l'assistant, réunion par réunion.

        Gardé comme le reste : une conversation qui disparaît au redémarrage
        n'est pas une conversation, c'est un brouillon.
        """
        return self.data / "conversations"

    @property
    def backups(self) -> Path:
        """Où atterrissent les archives quand aucun dossier n'est réglé.

        Sous les données, donc sur le même disque : c'est un défaut de repli, et
        l'outil le dit à chaque sauvegarde plutôt que de laisser croire que le
        travail est à l'abri.
        """
        return self.data / "sauvegardes"

class Audio(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    input: str = Field(
        default="Reunion Entree" if platform.system() == "Darwin" else "default",
        validation_alias="entree",
    )
    output: str = Field(
        default="Reunion Sortie" if platform.system() == "Darwin" else "default.monitor",
        validation_alias="sortie",
    )
    mic: str = Field(default="", validation_alias="micro")
    duree_maximale: int = Field(default=14_400, validation_alias="duree_maximale")

class Transcription(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    engine: str = Field(
        default="whisper.cpp" if platform.system() == "Darwin" else "faster-whisper",
        validation_alias="moteur",
    )
    model: str = Field(default="large-v3", validation_alias="modele")
    language: str = Field(default="fr", validation_alias="langue")
    vocabulary: list[str] = Field(default_factory=list, validation_alias="vocabulaire")

    @property
    def prompt_seed(self) -> str:
        if not self.vocabulary:
            return ""
        return "Réunion de travail. Vocabulaire : " + ", ".join(self.vocabulary) + "."

class Live(BaseModel):
    """La transcription affichée pendant que la réunion a lieu.

    Elle a un coût : un second modèle de transcription tourne en parallèle de la
    capture, et une empreinte vocale est calculée à chaque tranche. C'est le prix
    de pouvoir corriger un locuteur **pendant** la réunion plutôt que de
    découvrir l'erreur dans le compte rendu.
    """

    model_config = ConfigDict(populate_by_name=True)

    active: bool = Field(default=True, validation_alias="actif")
    period: float = Field(default=10.0, validation_alias="periode")
    model: str = Field(default="", validation_alias="modele")

class Speakers(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    not_first_names: list[str] = Field(default_factory=list, validation_alias="pas_des_prenoms")
    people: int | None = Field(default=None, validation_alias="personnes")

MODELES_CLAUDE: list[tuple[str, str]] = [
    ("opus", "Opus — recommandé : la synthèse est excellente et le quota tient"),
    ("fable", "Fable — le haut de la gamme, plus coûteux pour un compte rendu identique"),
    ("sonnet", "Sonnet — plus léger et plus rapide, synthèse un peu moins fine"),
    ("haiku", "Haiku — le plus économique, à réserver aux réunions courtes"),
]

class Minutes(BaseModel):
    """Qui rédige, et où va le résultat.

    Claude Code par défaut : distinguer une décision d'une hypothèse et
    rattacher une position à une personne reste hors de portée des modèles qui
    tournent sur un portable. C'est le seul maillon de la chaîne qui sort du
    poste, et c'est un choix assumé — `ollama` le remplace pour qui veut du
    100 % local, au prix d'une synthèse plus grossière.
    """

    model_config = ConfigDict(populate_by_name=True)

    engine: str = Field(default="claude", validation_alias="moteur")       # claude | ollama | aucun
    language: str = Field(default="", validation_alias="langue")
    model: str = Field(default="", validation_alias="modele")
    recipient: str = Field(default="", validation_alias="destinataire")
    timeout: int = Field(default=1800, validation_alias="delai")

    CLAUDE_PAR_DEFAUT: ClassVar[str] = "opus"
    OLLAMA_PAR_DEFAUT: ClassVar[str] = "qwen3:8b"

    @property
    def effective_model(self) -> str:
        """Le modèle à passer au moteur, réglage vide compris."""
        if self.model:
            return self.model
        if self.engine == "claude":
            return self.CLAUDE_PAR_DEFAUT
        if self.engine == "ollama":
            return self.OLLAMA_PAR_DEFAUT
        return ""

class Backup(BaseModel):
    """Où sont copiées les données, et combien de copies on garde.

    L'audio n'y est jamais : 1,1 Go contre 3 Mo pour tout le reste, et une
    réunion transcrite reste utilisable sans son enregistrement.
    """

    model_config = ConfigDict(populate_by_name=True)

    folder: str = Field(default="", validation_alias="dossier")
    apres_chaque_reunion: bool = Field(default=True, validation_alias="apres_chaque_reunion")
    kept: int = Field(default=7, validation_alias="gardees")

class Retention(BaseModel):
    """Combien de temps les enregistrements restent, et sous quelle forme.

    Ne concerne que l'audio : mesuré sur un poste après deux semaines, 1,1 Go
    d'enregistrements contre 3 Mo pour les transcriptions, les comptes rendus et
    la banque de voix réunis.
    """

    model_config = ConfigDict(populate_by_name=True)

    compresser_apres_jours: int = Field(default=7, validation_alias="compresser_apres_jours")
    effacer_apres_jours: int = Field(default=0, validation_alias="effacer_apres_jours")

class Conversation(BaseModel):
    """Ce que l'assistant a le droit de faire quand on lui parle.

    Distinct du compte rendu : celui-ci n'a jamais d'outil, quoi qu'on règle
    ici. Chercher pour répondre à une question et chercher pour rédiger un
    document ne sont pas la même chose.
    """

    model_config = ConfigDict(populate_by_name=True)

    recherche_web: bool = Field(default=True, validation_alias="recherche_web")
    disclosure: str = Field(default="rien", validation_alias="information")

FIRST_NAMES: dict[str, int] = {
    "Lucie": 0,
    "Camille": 0,
    "Alice": 0,
    "Manon": 0,
    "Louise": 0,
    "Martin": 1,
    "Julien": 1,
    "Antoine": 1,
    "Nicolas": 1,
    "Marius": 1,
    "Léon": 1,
}

KINDS = {0: "voix féminine", 1: "voix masculine"}

class AssistantSettings(BaseModel):
    """L'assistant en tant que participant : son nom, sa voix, sa retenue.

    Distinct de `conversation`, qui règle ce qu'il a le droit de faire quand on
    lui écrit. Ici il s'agit de ce qu'il fait **de lui-même** pendant la
    réunion, et de la façon dont il se fait entendre.
    """

    model_config = ConfigDict(populate_by_name=True)

    active: bool = Field(default=True, validation_alias="actif")
    name: str = Field(default="Lucie", validation_alias="nom")
    voice: str = Field(default="kokoro", validation_alias="voix")
    rate: float = Field(default=0.95, validation_alias="vitesse")
    speaker_index: int = Field(default=0, validation_alias="locuteur")

    @property
    def effective_speaker(self) -> int:
        """La voix qui va avec ce prénom, quand il est de la liste."""
        return FIRST_NAMES.get(self.name, self.speaker_index)
    rest: float = Field(default=180.0, validation_alias="repos")
    creux_minimal: float = Field(default=2.0, validation_alias="creux_minimal")
    demander_les_voix: bool = Field(default=False, validation_alias="demander_les_voix")
    initiative: bool = Field(default=False, validation_alias="initiative")

class Appearance(BaseModel):
    """Ce que la fenêtre montre, indépendamment de ce qu'elle fait.

    « systeme » suit le réglage clair/sombre du poste : c'est le défaut, parce
    qu'une application qui impose son goût jure avec tout le reste de l'écran.
    Les deux autres valeurs forcent, pour qui préfère.
    """

    model_config = ConfigDict(populate_by_name=True)

    theme: str = Field(default="systeme", validation_alias="theme")       # systeme | clair | sombre

class Email(BaseModel):
    """Envoi par SMTP, pour les postes sans Outlook.

    Le mot de passe ne figure jamais ici : il vient de la variable
    `GREFFIER_SMTP_MOT_DE_PASSE`, qu'on peut fournir par un gestionnaire de
    secrets plutôt que par un fichier.
    """

    model_config = ConfigDict(populate_by_name=True)

    server: str = Field(default="", validation_alias="serveur")
    port: int = Field(default=587, validation_alias="port")
    user: str = Field(default="", validation_alias="utilisateur")
    sender: str = Field(default="", validation_alias="expediteur")

class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GREFFIER_",
        env_nested_delimiter="__",
        env_file=(".env", str(config_folder() / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    paths: Paths = Field(
        default_factory=Paths, validation_alias="chemins"
    )
    audio: Audio = Field(default_factory=Audio)
    transcription: Transcription = Field(default_factory=Transcription)
    live: Live = Field(
        default_factory=Live, validation_alias="direct"
    )
    speakers: Speakers = Field(
        default_factory=Speakers, validation_alias="locuteurs"
    )
    minutes: Minutes = Field(
        default_factory=Minutes, validation_alias="compte_rendu"
    )
    email: Email = Field(
        default_factory=Email, validation_alias="courriel"
    )
    backup: Backup = Field(
        default_factory=Backup, validation_alias="sauvegarde"
    )
    retention: Retention = Field(default_factory=Retention)
    conversation: Conversation = Field(default_factory=Conversation)
    assistant: AssistantSettings = Field(default_factory=AssistantSettings)
    appearance: Appearance = Field(
        default_factory=Appearance, validation_alias="apparence"
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings, env_settings, dotenv_settings, _TomlSource(settings_cls))

    @classmethod
    def load(cls, file: Path | None = None) -> Config:
        """Lit la configuration, ou rend les valeurs par défaut si elle manque."""
        if file is not None:
            return cls.model_validate(_read_toml(file))
        return cls()

def _read_toml(path: Path) -> dict[str, object]:
    """Contenu d'un fichier TOML, vide s'il n'existe pas.

    Un fichier absent n'est pas une erreur : c'est le cas d'un poste qui vient
    d'installer. Un fichier illisible en est une — mieux vaut le dire que
    d'appliquer silencieusement autre chose que ce qui y est écrit.
    """
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as erreur:
        raise ValueError(f"{path} est illisible : {erreur}") from erreur

class _TomlSource(PydanticBaseSettingsSource):
    """Lit `config.toml` s'il existe, en dernier recours."""

    def get_field_value(  # pragma: no cover - la source ne lit jamais champ par champ
        self, field: object, field_name: str
    ) -> tuple[object, str, bool]:
        return None, field_name, False

    def __call__(self) -> dict[str, object]:
        return _read_toml(config_folder() / "config.toml")

SECTIONS: dict[str, tuple[str, ...]] = {
    "audio": ("micro", "entree", "sortie", "duree_maximale"),
    "transcription": ("moteur", "modele", "langue", "vocabulaire"),
    "direct": ("actif", "periode", "modele"),
    "locuteurs": ("pas_des_prenoms", "personnes"),
    "compte_rendu": ("moteur", "modele", "langue", "destinataire", "delai"),
    "courriel": ("serveur", "port", "utilisateur", "expediteur"),
    "sauvegarde": ("dossier", "apres_chaque_reunion", "gardees"),
    "retention": ("compresser_apres_jours", "effacer_apres_jours"),
    "conversation": ("recherche_web", "information"),
    "assistant": ("actif", "nom", "voix", "vitesse", "locuteur", "repos",
                  "creux_minimal", "initiative", "demander_les_voix"),
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
    "sauvegarde": ("Où sont copiées les données, sans l'audio (3 Mo contre 1,1 Go).\n"
                   "# « dossier » vide : à côté des données, ce qui ne protège pas de la\n"
                   "# perte du disque. Un disque externe, oui. Un espace synchronisé\n"
                   "# aussi, mais il envoie les transcriptions et la banque de voix chez\n"
                   "# son hébergeur : à décider soi-même, pas à subir."),
    "retention": ("Combien de temps les enregistrements restent. Compresser ne perd\n"
                  "# rien d'utile ; effacer perd la seule pièce qu'on ne peut pas refaire,\n"
                  "# donc « effacer_apres_jours = 0 » désactive. « greffier ranger »."),
    "conversation": ("Ce que l'assistant peut faire quand on lui parle pendant la\n"
                     "# réunion. « recherche_web » ne concerne jamais le compte rendu,\n"
                     "# qui n'a aucun outil. Ce qui sort du poste est le terme cherché.\n"
                     "# « information » : ce qui a été fait vis-à-vis des participants,\n"
                     "# « rien », « annoncé » ou « accord ». Une voix est une donnée\n"
                     "# biométrique ; le compte rendu porte la mention correspondante."),
    "assistant": ("L'assistant comme participant : le nom auquel il répond, et\n"
                  "# s'il se fait entendre. Il participe toujours — il écoute,\n"
                  "# prend des notes, pose ses questions par écrit ; le seul\n"
                  "# réglage est « voix », qui se relit pendant la réunion : on\n"
                  "# peut le faire taire sans rien arrêter. kokoro (neuronale, un\n"
                  "# modèle à télécharger), systeme (livrée par l'ordinateur), ou\n"
                  "# aucun. « repos » : secondes entre deux prises de parole\n"
                  "# spontanées. Être appelé par son nom ne compte pas : on\n"
                  "# répond tout de suite."),
    "apparence": "systeme suit le réglage clair/sombre du poste.",
}

_HEADER = """# Configuration de Greffier.
#
# Écrit par l'onglet Réglages de la fenêtre ; modifiable à la main sans risque.
# Tout est facultatif : ce qui manque reprend la valeur par défaut. Les
# variables « GREFFIER_* » et un fichier « .env » l'emportent sur ce fichier,
# dans cet ordre — on doit pouvoir forcer un réglage le temps d'une commande.
#
# La version précédente de ce fichier est conservée en « config.toml.precedent ».
"""

def config_path(folder: Path | None = None) -> Path:
    return (folder or config_folder()) / "config.toml"

SOUS_MODELE: dict[str, str] = {
    "chemins": "paths",
    "direct": "live",
    "locuteurs": "speakers",
    "compte_rendu": "minutes",
    "courriel": "email",
    "sauvegarde": "backup",
    "apparence": "appearance",
}

def _attribut(model: BaseModel, key: str) -> str:
    """Le nom du champ qui porte cette clef de fichier.

    Les clefs du fichier restent celles que les postes ont déjà écrites, les
    champs sont en anglais : c'est l'alias de validation qui fait le lien, et le
    lire ici évite de tenir une seconde table à jour à la main.
    """
    for name, champ in type(model).model_fields.items():
        if champ.validation_alias == key or name == key:
            return name
    return key

def render(config: Config) -> str:
    """Le contenu TOML de cette configuration. Fonction pure, éprouvable seule."""
    chunks = [_HEADER]
    for section, champs in SECTIONS.items():
        model = getattr(config, SOUS_MODELE.get(section, section))
        lines = []
        if section in _COMMENTAIRES:
            lines.append(f"# {_COMMENTAIRES[section]}")
        lines.append(f"[{section}]")
        for champ in champs:
            value = getattr(model, _attribut(model, champ))
            if value is None:
                continue
            lines.append(f"{champ} = {_value(value)}")
        chunks.append("\n".join(lines))
    return "\n\n".join(chunks) + "\n"

def _value(value: object) -> str:
    """Un scalaire ou une liste, en TOML.

    Pas de `json.dumps` : il rendrait bien `True` en `true` par chance, mais
    aussi les chemins en objets et les caractères accentués en séquences
    d'échappement, là où TOML attend de l'UTF-8 tel quel.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        if not value:
            return "[]"
        return "[" + ", ".join(_value(v) for v in value) + "]"
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'

def save_settings(config: Config, folder: Path | None = None) -> Path:
    """Écrit la configuration, en gardant une copie de la précédente.

    Écriture atomique : un remplacement, jamais un fichier tronqué. La fenêtre
    enregistre pendant qu'une réunion peut tourner, et un processus auxiliaire
    qui relirait un fichier à moitié écrit s'arrêterait sur une erreur de
    syntaxe.
    """
    target = config_path(folder)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.copy2(target, target.with_suffix(".toml.precedent"))
    descripteur, temporary = tempfile.mkstemp(dir=target.parent, prefix=".config-",
                                               suffix=".toml")
    try:
        with os.fdopen(descripteur, "w", encoding="utf-8") as flux:
            flux.write(render(config))
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return target
