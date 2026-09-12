"""Configuration.

One file per machine, in TOML, written back with its comments. Every field
carries the key the file already uses as a validation alias: the Python name can
be in English without a single machine's settings breaking.
"""

from __future__ import annotations

import os
import platform
import shutil
import tempfile
import tomllib
from pathlib import Path
from typing import ClassVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from greffier.domain.arithmetic import AUTO
from greffier.locations import config_folder, data_folder


class Paths(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    models: Path = Field(
        default_factory=lambda: data_folder() / "modeles",
        validation_alias=AliasChoices("models", "modeles"),
    )
    data: Path = Field(
        default_factory=data_folder,
        validation_alias=AliasChoices("data", "donnees"),
    )

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
        """Where the voice says which process is playing sound, so it can be cut."""
        return self.data / "parole.pid"

    @property
    def synthetic_voice(self) -> Path:
        """The model that gives the assistant a voice."""
        return self.models / "voix"

    @property
    def voice_bank(self) -> Path:
        return self.data / "banque-de-voix"

    @property
    def live(self) -> Path:
        """The thread of what is being said, meeting by meeting."""
        return self.data / "direct"

    @property
    def propositions(self) -> Path:
        """What the watch suggested during the meeting, meeting by meeting."""
        return self.data / "propositions"

    @property
    def context(self) -> Path:
        """The glossary of the working setting: acronyms, products, people."""
        return config_folder() / "contexte.toml"

    @property
    def subjects(self) -> Path:
        """The tracked subjects, their aliases and where their boards live."""
        return config_folder() / "sujets.toml"

    @property
    def sources(self) -> Path:
        """The outside sources the tool may consult."""
        return config_folder() / "sources.toml"

    @property
    def pieces(self) -> Path:
        """The text of the documents supplied for a meeting."""
        return self.data / "pieces"

    @property
    def questions(self) -> Path:
        """What the tool asked during the meeting, and what was answered."""
        return self.data / "questions"

    @property
    def graph(self) -> Path:
        """The index of what the tool knows, rebuilt from everything else."""
        return self.data / "graphe.sqlite3"

    @property
    def preparations(self) -> Path:
        """Meetings prepared before they are held."""
        return self.data / "preparations"

    @property
    def memory(self) -> Path:
        """What earlier meetings left: decisions, open points, documents."""
        return self.data / "memoire.jsonl"

    @property
    def conversations(self) -> Path:
        """What was said with the assistant, meeting by meeting."""
        return self.data / "conversations"

    @property
    def troubles(self) -> Path:
        """What went wrong, one line each, to attach to a report."""
        return self.data / "incidents.log"

    @property
    def backups(self) -> Path:
        """Where the archives land when no folder is set."""
        return self.data / "sauvegardes"

class Audio(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    input: str = Field(
        default="Reunion Entree" if platform.system() == "Darwin" else "default",
        validation_alias=AliasChoices("input", "entree"),
    )
    output: str = Field(
        default="Reunion Sortie" if platform.system() == "Darwin" else "default.monitor",
        validation_alias=AliasChoices("output", "sortie"),
    )
    mic: str = Field(default="", validation_alias=AliasChoices("mic", "micro"))
    maximum_length: int = Field(
        default=14_400,
        validation_alias=AliasChoices("maximum_length", "duree_maximale"),
    )

class Transcription(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    engine: str = Field(
        default="whisper.cpp" if platform.system() == "Darwin" else "faster-whisper",
        validation_alias=AliasChoices("engine", "moteur"),
    )
    model: str = Field(default="large-v3", validation_alias=AliasChoices("model", "modele"))
    language: str = Field(default="fr", validation_alias=AliasChoices("language", "langue"))
    vocabulary: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("vocabulary", "vocabulaire"),
    )

    @property
    def prompt_seed(self) -> str:
        if not self.vocabulary:
            return ""
        return "Réunion de travail. Vocabulaire : " + ", ".join(self.vocabulary) + "."

class Live(BaseModel):
    """The transcript shown while the meeting is happening.

    It has a cost: a second transcription model runs alongside capture. That is the
    price of being able to correct a speaker **during** the meeting rather than
    finding the mistake in the minutes.
    """

    model_config = ConfigDict(populate_by_name=True)

    active: bool = Field(default=True, validation_alias=AliasChoices("active", "actif"))
    period: float = Field(default=10.0, validation_alias=AliasChoices("period", "periode"))
    model: str = Field(default="", validation_alias=AliasChoices("model", "modele"))

class Hardware(BaseModel):
    """What the models run on.

    « auto » takes the graphics card when the driver answers. Cutting a meeting
    into speaker turns runs the voiceprint model on every excerpt, which on a
    processor costs more than the transcription and the minutes together.
    """

    model_config = ConfigDict(populate_by_name=True)

    device: str = Field(
        default=AUTO,
        validation_alias=AliasChoices("device", "peripherique"),
    )

class Speakers(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    not_first_names: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("not_first_names", "pas_des_prenoms"),
    )
    people: int | None = Field(default=None, validation_alias=AliasChoices("people", "personnes"))

MODELES_CLAUDE: list[tuple[str, str]] = [
    ("opus", "Opus, recommandé : la synthèse est excellente et le quota tient"),
    ("fable", "Fable : le haut de la gamme, plus coûteux pour un compte rendu identique"),
    ("sonnet", "Sonnet : plus léger et plus rapide, synthèse un peu moins fine"),
    ("haiku", "Haiku : le plus économique, à réserver aux réunions courtes"),
]

class Minutes(BaseModel):
    """Who writes, and where the result goes."""

    model_config = ConfigDict(populate_by_name=True)

    # claude | ollama | aucun
    engine: str = Field(
        default="claude",
        validation_alias=AliasChoices("engine", "moteur"),
    )
    language: str = Field(default="", validation_alias=AliasChoices("language", "langue"))
    model: str = Field(default="", validation_alias=AliasChoices("model", "modele"))
    recipient: str = Field(default="", validation_alias=AliasChoices("recipient", "destinataire"))
    timeout: int = Field(default=1800, validation_alias=AliasChoices("timeout", "delai"))

    CLAUDE_PAR_DEFAUT: ClassVar[str] = "opus"
    OLLAMA_PAR_DEFAUT: ClassVar[str] = "qwen3:8b"

    @property
    def effective_model(self) -> str:
        """The model to hand the engine, empty setting included."""
        if self.model:
            return self.model
        if self.engine == "claude":
            return self.CLAUDE_PAR_DEFAUT
        if self.engine == "ollama":
            return self.OLLAMA_PAR_DEFAUT
        return ""

class Backup(BaseModel):
    """Where the data is copied, and how many copies are kept."""

    model_config = ConfigDict(populate_by_name=True)

    folder: str = Field(default="", validation_alias=AliasChoices("folder", "dossier"))
    apres_chaque_reunion: bool = Field(
        default=True,
        validation_alias=AliasChoices("apres_chaque_reunion", "apres_chaque_reunion"),
    )
    kept: int = Field(default=7, validation_alias=AliasChoices("kept", "gardees"))

class Retention(BaseModel):
    """How long recordings stay, and when they are compressed."""

    model_config = ConfigDict(populate_by_name=True)

    compresser_apres_jours: int = Field(
        default=7,
        validation_alias=AliasChoices("compresser_apres_jours", "compresser_apres_jours"),
    )
    effacer_apres_jours: int = Field(
        default=0,
        validation_alias=AliasChoices("effacer_apres_jours", "effacer_apres_jours"),
    )

class Conversation(BaseModel):
    """What the assistant may do when it is asked something."""

    model_config = ConfigDict(populate_by_name=True)

    recherche_web: bool = Field(
        default=True,
        validation_alias=AliasChoices("recherche_web", "recherche_web"),
    )
    disclosure: str = Field(
        default="rien",
        validation_alias=AliasChoices("disclosure", "information"),
    )

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
    """The assistant as a participant: its name, its voice, its restraint."""

    model_config = ConfigDict(populate_by_name=True)

    active: bool = Field(default=True, validation_alias=AliasChoices("active", "actif"))
    name: str = Field(default="Lucie", validation_alias=AliasChoices("name", "nom"))
    voice: str = Field(default="kokoro", validation_alias=AliasChoices("voice", "voix"))
    rate: float = Field(default=0.95, validation_alias=AliasChoices("rate", "vitesse"))
    speaker_index: int = Field(
        default=0,
        validation_alias=AliasChoices("speaker_index", "locuteur"),
    )

    @property
    def effective_speaker(self) -> int:
        """The voice that goes with this first name, when it is on the list."""
        return FIRST_NAMES.get(self.name, self.speaker_index)
    rest: float = Field(default=180.0, validation_alias=AliasChoices("rest", "repos"))
    creux_minimal: float = Field(
        default=2.0,
        validation_alias=AliasChoices("creux_minimal", "creux_minimal"),
    )
    demander_les_voix: bool = Field(
        default=False,
        validation_alias=AliasChoices("demander_les_voix", "demander_les_voix"),
    )
    initiative: bool = Field(
        default=False,
        validation_alias=AliasChoices("initiative", "initiative"),
    )

class Interface(BaseModel):
    """What the tool says, and in which language it says it."""

    model_config = ConfigDict(populate_by_name=True)

    #: Empty means « ask the machine ». Somebody who has told their system what
    #: language they read should not have to tell this tool as well; the setting
    #: is for the case where the two differ, which is a preference and not a
    #: mistake.
    language: str = Field(default="", validation_alias=AliasChoices("language", "langue"))


class Appearance(BaseModel):
    """What the window shows, independently of what it does."""

    model_config = ConfigDict(populate_by_name=True)

    # systeme | clair | sombre
    theme: str = Field(
        default="systeme",
        validation_alias=AliasChoices("theme", "theme"),
    )

class Email(BaseModel):
    """Sending over SMTP, for machines without Outlook.

    The password comes from the environment, never from a file in the repository.
    """

    model_config = ConfigDict(populate_by_name=True)

    server: str = Field(default="", validation_alias=AliasChoices("server", "serveur"))
    port: int = Field(default=587, validation_alias=AliasChoices("port", "port"))
    user: str = Field(default="", validation_alias=AliasChoices("user", "utilisateur"))
    sender: str = Field(default="", validation_alias=AliasChoices("sender", "expediteur"))

class Api(BaseModel):
    """The HTTP door, for a site that wants to drive the tool.

    Shut by default and bound to the loopback when opened: everything this tool
    holds -- recordings, transcripts, voice prints -- is on the machine, and a
    door listening on every interface is a decision, never an accident.
    """

    model_config = ConfigDict(populate_by_name=True)

    host: str = Field(default="127.0.0.1", validation_alias=AliasChoices("host", "hote"))
    port: int = Field(default=8765, validation_alias=AliasChoices("port", "port"))
    #: Written on first start when it is empty, so that a site can be configured
    #: once. No token, no answer -- even on the loopback, where any process of
    #: the machine could otherwise read every meeting.
    token: str = Field(default="", validation_alias=AliasChoices("token", "jeton"))


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
        default_factory=Paths, validation_alias=AliasChoices("paths", "chemins")
    )
    audio: Audio = Field(default_factory=Audio)
    transcription: Transcription = Field(default_factory=Transcription)
    live: Live = Field(
        default_factory=Live, validation_alias=AliasChoices("live", "direct")
    )
    speakers: Speakers = Field(
        default_factory=Speakers, validation_alias=AliasChoices("speakers", "locuteurs")
    )
    minutes: Minutes = Field(
        default_factory=Minutes, validation_alias=AliasChoices("minutes", "compte_rendu")
    )
    email: Email = Field(
        default_factory=Email, validation_alias=AliasChoices("email", "courriel")
    )
    backup: Backup = Field(
        default_factory=Backup, validation_alias=AliasChoices("backup", "sauvegarde")
    )
    retention: Retention = Field(default_factory=Retention)
    hardware: Hardware = Field(
        default_factory=Hardware, validation_alias=AliasChoices("hardware", "materiel")
    )
    conversation: Conversation = Field(default_factory=Conversation)
    api: Api = Field(default_factory=Api)
    interface: Interface = Field(default_factory=Interface)
    assistant: AssistantSettings = Field(default_factory=AssistantSettings)
    appearance: Appearance = Field(
        default_factory=Appearance, validation_alias=AliasChoices("appearance", "apparence")
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
        # Chaque source passe par la même traduction : une source qui parlerait
        # français et une autre anglais poseraient deux clés pour un seul
        # réglage, et la priorité se jouerait alors sur l'orthographe.
        return tuple(
            _Canonical(settings_cls, source)
            for source in (init_settings, env_settings, dotenv_settings,
                           _TomlSource(settings_cls))
        )

    @classmethod
    def load(cls, file: Path | None = None) -> Config:
        """Reads the configuration, or returns the defaults when it is missing."""
        if file is not None:
            return cls.model_validate(_read_toml(file))
        return cls()

def _read_toml(path: Path) -> dict[str, object]:
    """Contents of a TOML file, empty when it does not exist."""
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as erreur:
        raise ValueError(f"{path} est illisible : {erreur}") from erreur

def _accepted_names(field: object) -> tuple[str, ...]:
    """Every spelling a field answers to, the French one included."""
    alias = getattr(field, "validation_alias", None)
    if alias is None:
        return ()
    if isinstance(alias, str):
        return (alias,)
    return tuple(c for c in getattr(alias, "choices", ()) if isinstance(c, str))


def _canonical(data: dict[str, object], model: type[BaseModel]) -> dict[str, object]:
    """The same settings, keyed by field name rather than by French alias.

    The file says `compte_rendu.moteur`, an environment variable says
    `minutes.engine`: two spellings of one setting. Merged as they come, they
    stay two entries, the file's own spelling wins, and
    `GREFFIER_MINUTES__ENGINE` changes nothing -- while the header written into
    every config.toml promises the opposite. Translated here, both land on the
    same key, and the variable, coming from a source of higher priority, takes
    precedence. What the file holds and the variable does not is kept: the
    merge happens setting by setting, not section by section.

    A key that matches no field is passed through untouched, to be reported by
    the validation rather than swallowed here.
    """
    translated: dict[str, object] = {}
    for key, value in data.items():
        name, nested = key, None
        for candidate, field in model.model_fields.items():
            if key == candidate or key in _accepted_names(field):
                name = candidate
                annotation = field.annotation
                if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                    nested = annotation
                break
        if nested is not None and isinstance(value, dict):
            translated[name] = _canonical(value, nested)
        else:
            translated[name] = value
    return translated


class _Canonical(PydanticBaseSettingsSource):
    """Any source, its keys translated to field names before the merge.

    The sources are merged by key, then the whole is validated. Two sources
    spelling one setting differently -- `compte_rendu.moteur` in the file,
    `minutes.engine` from the environment -- produce two keys that never meet,
    and the winner is whichever spelling the validation prefers rather than
    whichever source ranks higher. Translated first, the settings meet, and the
    order declared above is the order that applies.
    """

    def __init__(self, settings_cls: type[BaseSettings], source: PydanticBaseSettingsSource):
        super().__init__(settings_cls)
        self._source = source

    def get_field_value(  # pragma: no cover - la source ne lit jamais champ par champ
        self, field: object, field_name: str
    ) -> tuple[object, str, bool]:
        return None, field_name, False

    def __call__(self) -> dict[str, object]:
        return _canonical(self._source(), self.settings_cls)


class _TomlSource(PydanticBaseSettingsSource):
    """Reads config.toml when it exists, as a last resort."""

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
    "api": ("hote", "port", "jeton"),
    "interface": ("langue",),
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
                  "# s'il se fait entendre. Il participe toujours, il écoute,\n"
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
# dans cet ordre, on doit pouvoir forcer un réglage le temps d'une commande.
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
    """The name of the field that carries this file key.

    The file keys stay the ones machines have already written, the fields are in
    English: the validation alias is the link, and reading it here avoids keeping a
    second table up to date by hand.
    """
    for name, champ in type(model).model_fields.items():
        if key == name or key in _accepted_names(champ):
            return name
    return key

def render(config: Config) -> str:
    """The TOML contents of this configuration. Pure function, testable alone."""
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
    """A scalar or a list, in TOML."""
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
    """Writes the configuration, keeping a copy of the previous one.

    Atomic: one replacement, never a truncated file. The window saves while a
    meeting may be running, and a helper process reading a half-written file would
    stop on a syntax error.
    """
    target = config_path(folder)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.copy2(target, target.with_suffix(".toml.precedent"))
    descripteur, temporary = tempfile.mkstemp(dir=target.parent, prefix=".config-",
                                               suffix=".toml")
    try:
        with os.fdopen(descripteur, "w", encoding="utf-8") as stream:
            stream.write(render(config))
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return target
