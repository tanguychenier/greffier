# Preuve d'installation sur Linux, depuis une image nue.
#
# Rien n'est préinstallé au-delà de Python et de git : c'est l'installeur qui
# doit détecter et poser ffmpeg, les modèles et l'environnement. Si cette image
# se construit, c'est qu'un collègue sous Linux peut installer Greffier.
FROM python:3.13-slim

# git uniquement pour cloner le dépôt, comme le ferait un collègue.
RUN apt-get update -qq && apt-get install -y -qq git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /travail
COPY greffier /travail/greffier
WORKDIR /travail/greffier

# Modèle de transcription réduit : le « large-v3 » pèse 1,5 Go et n'ajoute rien
# à la démonstration d'installation.
ENV GREFFIER_MODELE_WHISPER=small \
    GREFFIER_MODELES_EXISTANTS= \
    GREFFIER_MODELES=/travail/modeles \
    GREFFIER_CONFIG=/travail/config \
    NO_COLOR=1

RUN python3 outils/installer.py --oui

# Au-delà de l'installation : la chaîne tourne-t-elle vraiment sous Linux ?
RUN .venv/bin/python -m pytest tests/ \
    && .venv/bin/python -c "\
import pathlib, sys; sys.path.insert(0, 'src');\
from greffier.adaptateurs.empreintes_titanet import ExtracteurTitaNet;\
e = ExtracteurTitaNet(pathlib.Path('/travail/modeles/diarisation/nemo_en_titanet_large.onnx'));\
import numpy as np;\
emp = e.extraire(np.random.default_rng(0).normal(0, 0.1, 32000).astype('float32'), 16000);\
print('empreinte extraite sous Linux :', len(emp.vecteur), 'dimensions')"
