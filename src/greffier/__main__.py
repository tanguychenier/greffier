"""Allows `python -m greffier`, which the watch needs to relaunch itself."""

from greffier.cli import application

if __name__ == "__main__":
    application()
