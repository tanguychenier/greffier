# Preuve que la fenêtre s'ouvre sous Linux.
#
# Distincte de `preuve-linux.Dockerfile`, qui prouve l'installation et la
# chaîne : celle-ci ne télécharge aucun modèle, puisqu'ouvrir la fenêtre n'en
# demande aucun. Elle se construit donc en quelques minutes.
#
# Debian plutôt que l'image `python:3.13-slim` : cette dernière compile son
# interpréteur sans Tk, et le paquet `python3-tk` de Debian s'adresse au python
# de Debian, pas à celui-là. Trixie livre Python 3.13, ce que le projet exige.
#
#     docker build -f outils/preuve-fenetre-linux.Dockerfile -t greffier-fenetre .
FROM debian:trixie-slim

# `python3-tk` est la seule dépendance système de l'interface, et c'est
# exactement la ligne que le README demande d'exécuter. `xvfb` (avec `xauth`, qu'il réclame) fournit l'écran
# que n'importe quelle machine de bureau aurait : sans lui, Tk n'a pas de
# serveur X et refuse de s'ouvrir — ce qui prouverait seulement l'absence
# d'écran, pas un défaut du code.
RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends \
       python3 python3-venv python3-tk xvfb xauth libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /travail/greffier
COPY greffier /travail/greffier

# `--system-site-packages` pour que le `tkinter` du système reste visible : il
# est livré par apt, pas par pip, et un environnement fermé le cacherait.
RUN python3 -m venv --system-site-packages .venv \
    && .venv/bin/pip install -q --no-cache-dir \
       pydantic pydantic-settings typer numpy soundfile sherpa-onnx

ENV GREFFIER_CONFIG=/travail/config \
    GREFFIER_DONNEES=/travail/donnees \
    NO_COLOR=1

# La fenêtre est réellement construite, puis chaque onglet est affiché — la
# méthode déjà retenue sur macOS, qui pilote la vraie fenêtre plutôt que de
# simuler des clics sur des coordonnées. Ce qui est prouvé : Tk s'ouvre, la
# palette se calcule, les cinq onglets se peignent sans exception.
RUN xvfb-run -a .venv/bin/python outils/preuve_fenetre.py
