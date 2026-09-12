---
name: greffier
description: Réparer une installation de Greffier, où sont les fichiers, ce que le diagnostic dit, et les pièges qui ne se devinent pas.
---

# Réparer Greffier

Greffier enregistre une réunion, la transcrit, sépare les voix, leur donne un nom
et fait rédiger le compte rendu. Quand quelque chose casse, c'est vers toi qu'on
se tourne. Ce document dit où regarder, et surtout ce qui ne se devine pas.

## Commencer par là, toujours

```sh
greffier diagnostic      # constate sans rien modifier
greffier verifier        # dit si la chaîne s'assemble
greffier contexte        # ce que l'outil sait des sigles et des personnes
greffier niveau          # dit si le micro suffit à transcrire, parle pendant
python3 tools/install.py --verifier   # constate sans rien installer
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

`XDG_CONFIG_HOME` et `XDG_DATA_HOME`, s'ils sont posés, l'emportent partout,
c'est ce qui isole les tests.

**Sur macOS, ce n'est pas la convention XDG, et c'est délibéré.** Les dossiers
cachés du compte (`~/.config`, `~/.local`) sont surveillés par la garde du poste,
un logiciel de sécurité du poste. Il redemandait
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
comme n'importe quelle commande, les deux chemins ne racontent pas la même
chose, et une panne qui n'apparaît que par l'application se lit là.

Chaque session s'ouvre sur `=== démarré le AAAA-MM-JJ HH:MM:SS ===`. **Une
session sans ligne d'arrêt s'est terminée brutalement**, ce qui est en soi une
information. Si le journal ne contient rien alors que l'application tourne,
vérifie que le flux est ouvert en `buffering=1` dans le lanceur : `os._exit` ne
vide aucun tampon, et le journal est resté vide huit jours pour cette raison
(mesuré : 0 octet par session).

## Ce qui ne se devine pas

**La signature du paquet est stable, à dessein.** Une signature ad hoc n'est que
le hachage du binaire : chaque reconstruction change l'identité, et macOS
redemande toutes les autorisations : micro, Outlook, garde du poste. Le paquet est donc
signé avec un certificat, Apple s'il y en a un dans le trousseau, sinon un
certificat local créé une fois pour toutes. **Ne signe jamais ad hoc pour
« aller plus vite »** : les autorisations de l'utilisateur seraient à redonner.

**Le rédacteur par défaut est le second de la gamme, pas le premier.** C'est
`opus` pour Claude Code (`config.py`, `CLAUDE_PAR_DEFAUT`). Rédiger un compte
rendu à partir d'une transcription déjà découpée et attribuée est un travail de
synthèse, pas de raisonnement long : le haut de la gamme rend le même document
en entamant un quota bien plus vite. **Ne « corrige » pas ce défaut vers le
modèle le plus puissant** : c'est un choix, pas un oubli.

**Une modification du code ne se voit pas dans l'application.** Le paquet
embarque ses propres copies de l'interpréteur, des bibliothèques et du code.
Après une modification, relance `python3 tools/install.py` pour le
reconstruire. La ligne de commande du dépôt, elle, suit le code immédiatement.

**Le compte rendu est le seul maillon qui sort du poste**, avec la recherche de
l'assistant de conversation. Si la demande est que rien ne sorte, la réponse est
`compte_rendu.moteur = "ollama"` et `conversation.recherche_web = false`, pas de
couper le réseau.

**Le rédacteur du compte rendu n'a aucun outil, et ce n'est pas un oubli.** Un
document composé de ce qui a été dit ne doit pas pouvoir compléter une décision
par ce qu'un moteur de recherche a rendu. C'est l'assistant de la conversation
qui cherche, et seulement lui (`composition.assistant`). Ne « répare » pas cette
asymétrie.

**`greffier traiter --quand-meme` ne détruit plus la réunion en cours**, mais il
l'a fait deux fois avant le 2026-09-09. Le fichier d'état est unique : un
traitement lancé à côté y publiait ses phases jusqu'à « terminé », la fenêtre en
concluait que la réunion était finie, et la capture s'arrêtait, une réunion
entière perdue sans laisser un octet. Le journal de la chaîne ne publie
désormais que si l'état porte la réunion qu'il traite
(`Enregistrement.pour`). **Ne défais pas cette précaution** : c'est elle qui
rend le drapeau inoffensif. Il reste déconseillé pendant une réunion, pour une
autre raison : transcrire prend le processeur que la capture et le direct se
partagent.

**Une réunion qui n'apparaît nulle part alors qu'elle a eu lieu** se
reconstruit : `greffier recuperer <identifiant>` repart du fil du direct. La
transcription est moins bonne : modèle rapide, voix non recollées, et la
réunion porte un avertissement qui le dit. Si l'enregistrement existe encore,
`greffier traiter` vaut mieux.

**La réunion est gardée avant la rédaction.** L'ordre est : transcription,
voix, **écriture du fichier maître**, puis rédaction, puis envoi. Ne remonte
jamais la rédaction avant l'écriture pour « économiser une écriture » : c'est ce
qui faisait perdre une réunion entière quand le rédacteur échouait.

## Pannes fréquentes, et ce qu'elles sont vraiment

| Symptôme | Cause habituelle |
|---|---|
| Enregistrement muet sur macOS | le périphérique agrégé référence un matériel précis : casque débranché, micro absent de l'agrégé. Le reconstruire (`greffier peripheriques`) |
| Le son des autres n'est pas capté | macOS : BlackHole absent. Linux : aucun serveur de son joignable |
| Tout marche sauf le compte rendu | la session du rédacteur n'est pas ouverte. `greffier diagnostic` le dit |
| La fenêtre ne s'ouvre pas depuis le dépôt | Tcl introuvable : `situer_tcl()` pose `TCL_LIBRARY`/`TK_LIBRARY`, vérifier qu'il s'exécute |
| La transcription échoue après plusieurs minutes | Linux : carte graphique sans cuBLAS. Le repli sur le processeur existe, il est lent |
| Un réglage a disparu | la version précédente est en `config.toml.precedent`, à côté |
| Aucun compte rendu, mais la réunion est transcrite | la rédaction a échoué. `greffier rediger` la rejoue sans retranscrire, ou le bouton « Rédiger » |
| La rédaction expire | `compte_rendu.delai`, 1800 s par défaut. Rien n'est perdu : la réunion est gardée **avant** la rédaction |
| Des sigles ou des prénoms mal transcrits | ils manquent au contexte. `greffier contexte` dit ce qui est transmis et ce que l'amorce a écarté |
| Des mots courants déformés (« exploitement » pour « déploiement ») | ce n'est **pas** le vocabulaire : c'est le niveau. `greffier niveau` le mesure. Sous -43 dB le modèle invente au lieu d'écrire moins bien |
| Le casque est ignoré au profit du micro intégré | depuis le 2026-09-09, un casque qui capte l'emporte même plus faible. S'il est écarté, il rend moins que -68 dB : bouton de sourdine, ou débranché |
| La réunion n'a rien enregistré | la veille le signale désormais pendant la réunion. Si rien n'a été dit, chercher un traitement lancé en parallèle (voir ci-dessous) |
| « La dernière réunion » n'est pas la bonne | l'ordre suit l'horodatage de l'identifiant. Un identifiant sans date passe en fin de liste, à dessein |
| Le compte rendu annonce dix ou vingt participants | la segmentation sur-découpe et le recollage n'a pas été rejoué. `greffier revoir <réunion>` le rejoue sans retranscrire |
| Une personne connue n'est plus reconnue du tout | la banque a une **paire en conflit** : deux entrées trop ressemblantes font taire les deux noms. `greffier connus` la nomme, et dit quelle empreinte est fautive. `greffier connus --nettoyer <nom>` la retire sans effacer la personne |
| Une réunion a versé de fausses empreintes | `greffier connus --oublier-reunion <réunion>` défait ce qu'elle a déposé, sous tous les noms d'un coup |
| L'assistant ne répond pas à son prénom | il ne participe pas : bouton dans l'onglet **En direct**. Vérifier ensuite `assistant.nom` : un prénom court et distinct vaut mieux que « Greffier », que « le greffe » suffit à réveiller |
| L'assistant parle avec une voix de robot | le modèle de voix manque, il s'est replié sur celle du système. `python3 tools/install.py` le télécharge (80 Mo, dans `modeles/voix`) |
| L'assistant parle mais personne ne l'entend | la sortie système est sur « Reunion Sortie », le périphérique de capture. La réunion la repose en quittant ; en cours de réunion, la remettre à la main |
| L'assistant coupe la parole, ou ne dit jamais rien | `assistant.repos` et `assistant.creux_minimal`. Être appelé par son nom passe outre les deux, à dessein |
| L'assistant se répond à lui-même | il ne devrait pas : ses propres prises de parole sont exclues de ce qu'il réécoute. Si cela arrive, le haut-parleur est très en avance sur l'horloge de la réunion, le signaler avec le journal |
| Sous Linux, l'installation s'arrête sans rien dire | corrigé le 2026-09-10 : un `.venv` venu d'une autre machine était pris pour valide. Si cela se reproduit, effacer `.venv` et relancer |

## Avant de conclure

Ne réponds pas « c'est corrigé » sur la foi d'une lecture. Rejoue ce qui prouve :

```sh
.venv/bin/python -m pytest        # rapide, aucun modèle chargé
.venv/bin/ruff check src tests tools
.venv/bin/mypy
```

Et si la panne touchait la chaîne elle-même, repasse un enregistrement réel :
`greffier traiter --sans-compte-rendu <fichier.wav>`.
