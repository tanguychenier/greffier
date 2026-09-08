---
name: greffier
description: Réparer une installation de Greffier — où sont les fichiers, ce que le diagnostic dit, et les pièges qui ne se devinent pas.
---

# Réparer Greffier

Greffier enregistre une réunion, la transcrit, sépare les voix, leur donne un nom
et fait rédiger le compte rendu. Quand quelque chose casse, c'est vers toi qu'on
se tourne. Ce document dit où regarder, et surtout ce qui ne se devine pas.

## Commencer par là, toujours

```sh
greffier diagnostic      # constate sans rien modifier
greffier verifier        # dit si la chaîne s'assemble
python3 outils/installer.py --verifier   # constate sans rien installer
```

`greffier diagnostic` répond sur ffmpeg, le micro, la capture du son des autres,
la présence et la session du rédacteur, la mémoire vive et l'espace disque. Un
`✗` y nomme son remède. N'entreprends rien avant de l'avoir lu : la moitié des
pannes rapportées sont un de ces sept constats.

## Où vivent les fichiers

| Système | Configuration et données |
|---|---|
| macOS | `~/Library/Application Support/Greffier` |
| Linux | `~/.config/greffier` et `~/.local/share/greffier` |
| Windows | `%APPDATA%\greffier` et `%LOCALAPPDATA%\greffier` |

`XDG_CONFIG_HOME` et `XDG_DATA_HOME`, s'ils sont posés, l'emportent partout —
c'est ce qui isole les tests.

**Sur macOS, ce n'est pas la convention XDG, et c'est délibéré.** Les dossiers
cachés du compte (`~/.config`, `~/.local`) sont surveillés par la garde du poste,
WithSecure XFENCE, dont l'agent tourne sous `local.xfence.rc`. Elle redemandait
une autorisation pour chaque accès de chaque programme de la chaîne, à chaque
réunion ; une écriture y a même été refusée en pleine réunion, et le direct s'est
arrêté net. `Application Support` est l'endroit où toutes les applications
écrivent, et personne ne le conteste. **Ne propose jamais de revenir aux dossiers
cachés sur macOS** : c'est une régression déjà payée une fois.

Si une écriture est refusée sans explication sur macOS, regarde de ce côté avant
de soupçonner le code.

## Le journal, quand la fenêtre est lancée depuis l'application

Le paquet `/Applications/Greffier.app` n'a pas de terminal où écrire. Sa sortie
part dans :

```
~/Library/Logs/Greffier.log
```

C'est le seul endroit où une exception survenue au démarrage de la fenêtre
laisse une trace. Depuis le dépôt, `greffier fenetre` écrit dans le terminal
comme n'importe quelle commande — les deux chemins ne racontent pas la même
chose, et une panne qui n'apparaît que par l'application se lit là.

## Ce qui ne se devine pas

**La signature du paquet est stable, à dessein.** Une signature ad hoc n'est que
le hachage du binaire : chaque reconstruction change l'identité, et macOS
redemande toutes les autorisations — micro, Outlook, XFENCE. Le paquet est donc
signé avec un certificat, Apple s'il y en a un dans le trousseau, sinon un
certificat local créé une fois pour toutes. **Ne signe jamais ad hoc pour
« aller plus vite »** : les autorisations de l'utilisateur seraient à redonner.

**Le rédacteur par défaut est le second de la gamme, pas le premier.** C'est
`opus` pour Claude Code (`config.py`, `CLAUDE_PAR_DEFAUT`). Rédiger un compte
rendu à partir d'une transcription déjà découpée et attribuée est un travail de
synthèse, pas de raisonnement long : le haut de la gamme rend le même document
en entamant un quota bien plus vite. **Ne « corrige » pas ce défaut vers le
modèle le plus puissant** — c'est un choix, pas un oubli.

**Une modification du code ne se voit pas dans l'application.** Le paquet
embarque ses propres copies de l'interpréteur, des bibliothèques et du code.
Après une modification, relance `python3 outils/installer.py` pour le
reconstruire. La ligne de commande du dépôt, elle, suit le code immédiatement.

**Le compte rendu est le seul maillon qui sort du poste.** Si la demande est que
rien ne sorte, la réponse est `compte_rendu.moteur = "ollama"`, pas de couper le
réseau.

## Pannes fréquentes, et ce qu'elles sont vraiment

| Symptôme | Cause habituelle |
|---|---|
| Enregistrement muet sur macOS | le périphérique agrégé référence un matériel précis : casque débranché, micro absent de l'agrégé. Le reconstruire (`greffier peripheriques`) |
| Le son des autres n'est pas capté | macOS : BlackHole absent. Linux : aucun serveur de son joignable |
| Tout marche sauf le compte rendu | la session du rédacteur n'est pas ouverte. `greffier diagnostic` le dit |
| La fenêtre ne s'ouvre pas depuis le dépôt | Tcl introuvable : `situer_tcl()` pose `TCL_LIBRARY`/`TK_LIBRARY` — vérifier qu'il s'exécute |
| La transcription échoue après plusieurs minutes | Linux : carte graphique sans cuBLAS. Le repli sur le processeur existe, il est lent |
| Un réglage a disparu | la version précédente est en `config.toml.precedent`, à côté |

## Avant de conclure

Ne réponds pas « c'est corrigé » sur la foi d'une lecture. Rejoue ce qui prouve :

```sh
.venv/bin/python -m pytest        # rapide, aucun modèle chargé
.venv/bin/ruff check src tests outils
.venv/bin/mypy
```

Et si la panne touchait la chaîne elle-même, repasse un enregistrement réel :
`greffier traiter --sans-compte-rendu <fichier.wav>`.
