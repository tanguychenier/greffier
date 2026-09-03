#!/usr/bin/env bash
# Raccourci vers l'installeur, qui est en Python pour tourner aussi sur Linux
# et Windows. Sous Windows : python outils\installer.py
exec "$(command -v python3 || command -v python)" "$(dirname "$0")/installer.py" "$@"
