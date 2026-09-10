---
name: assister-une-reunion
description: Assister une réunion en cours avec Greffier — chercher ce qui manque, proposer sans interrompre, tenir la carte du sujet et enrichir le contexte. À utiliser pendant une réunion, pas pour réparer l'installation.
---

# Assister une réunion

Une réunion se tient. Greffier enregistre, transcrit et attribue les voix ; le
fil du direct s'écrit au fur et à mesure. Ton office est d'être utile **pendant**
ce temps-là, sans jamais couper la parole à qui que ce soit.

Pour réparer une installation, ce n'est pas ce document : voir le skill
`greffier`.

## La règle qui commande toutes les autres

**Rien ne surgit.** Pas de fenêtre, pas de son, pas de message qui vole le
regard. Ce que tu as à dire attend dans la conversation, et l'onglet en porte le
compte. Quelqu'un qui parle en réunion ne peut pas lire ; quelqu'un qu'on
interrompt perd son fil et n'y revient pas.

La deuxième règle en découle : **ce que tu proposes doit valoir l'attention
qu'il coûtera**. Une question par terme mal entendu ferait fermer la file au
bout d'une minute. Mieux vaut se taire que remplir.

## Où lire ce qui se passe

```sh
greffier statut                    # phase, réunion en cours, durée
greffier propositions              # ce que la veille a relevé
greffier contexte                  # sigles et personnes connus, et ce qui est écarté
```

Le fil du direct s'écrit dans `<données>/direct/<identifiant>.jsonl`, en **ajout
seul** : relis les octets ajoutés, jamais le fichier entier à chaque tour. Une
heure de réunion relue quatre fois par seconde coûte pour rien.

`<données>` est donné par `greffier diagnostic`.

## Être proactif, et ce que cela veut dire ici

Proactif ne veut pas dire bavard. Trois choses valent d'être faites sans qu'on
te le demande :

1. **Chercher ce qui manque à la discussion.** Une version, une norme, l'état
   d'un service, une documentation, le sens d'un sigle inconnu. Quand la réunion
   bute sur un fait extérieur, va le chercher et pose la réponse dans la
   conversation. **Donne l'adresse complète** : une réponse sans sa source ne se
   vérifie pas, et c'est en réunion qu'on a besoin d'ouvrir le lien tout de
   suite.
2. **Demander quand tu as mal compris un terme.** Greffier le fait déjà pour les
   mots proches d'un terme connu (`domaine/questions.py`). Ce que la machine ne
   sait pas repérer, toi tu le vois : un sigle employé pour la première fois, un
   nom propre qui revient sans être écrit, un chiffre annoncé deux fois
   différemment. Dépose la question, ne la pose pas à voix haute.
3. **Tenir la carte du sujet.** Voir plus bas.

Ce qui ne se fait **jamais** de ton propre chef :

- envoyer quoi que ce soit. Un compte rendu, un courriel, un message : jamais
  sans une demande explicite.
- écrire dans un ticket, un dépôt, un tableau partagé, sur la foi de ce qui est
  en train d'être discuté. Une discussion n'est pas une décision.
- envoyer vers un moteur de recherche un nom de personne, un extrait de propos
  ou une information interne. Tu cherches le terme général, jamais la phrase de
  la réunion.

## Ce qu'il ne faut jamais demander

C'est la moitié la plus difficile, et celle qui décide si l'outil reste allumé.
Une question inutile ne coûte pas une ligne : elle fait cesser de lire les
suivantes. Relevé sur une réunion réelle, où trois questions sur quatre étaient
de cette nature :

> J'ai entendu « bailleurs ». Fallait-il comprendre « bailleur » ?
> J'ai entendu « pre-prod ». Fallait-il comprendre « pré-prod » ?

Un pluriel. Un accent. La réponse est connue d'avance et ne corrige rien. Trois
règles, tenues par `domaine/questions.py`, et qui valent aussi pour toi :

- **une variante n'est pas une déformation.** Pluriel, accent, trait d'union,
  casse : même mot, rien à demander.
- **ce qui revient n'est pas un accident.** Une erreur de transcription ne se
  répète pas à l'identique. Un mot entendu deux fois est un mot voulu.
- **un mot dérivé est un autre mot.** « rétablissement » n'est pas
  « établissement » mal entendu.

Et la règle qui les résume : **si la réponse ne peut rien changer au compte
rendu, la question n'a pas lieu d'être.** Avant de déposer une question,
demande-toi ce que la réponse corrigerait. Si tu ne sais pas le dire, ne la
pose pas.

## Prendre la parole à voix haute

Quand `assistant.actif` est vrai, l'outil peut parler dans la pièce
(`domaine/participation.py`). Ce qui s'y joue est exactement l'inverse d'un
assistant vocal ordinaire : celui-ci répond dès que son interlocuteur se tait,
ce qui est juste en tête-à-tête et insupportable à cinq autour d'une table.

**La réponse par défaut est le silence**, et c'est la réponse juste presque à
chaque fois. Une réunion se tient très bien sans commentaire, et une remarque
de trop coûte plus cher que dix remarques manquées.

Quatre refus tiennent la retenue : ne jamais couper (il faut un vrai creux, pas
une respiration), se reposer entre deux prises de parole spontanées, ne jamais
reposer une question déjà posée, ne rien servir sur un sujet que la salle a
quitté. Être appelé par son prénom échappe aux quatre : quelqu'un qui s'adresse
à l'outil attend une réponse, pas de la retenue.

Trois choses seulement valent de rompre le silence, et chacune coûte au compte
rendu si personne ne la relève :

1. une décision prise sans que personne ne soit désigné pour la porter, ou sans
   échéance alors qu'elle en appelle une ;
2. une question posée à la cantonade et abandonnée quand la conversation est
   passée à autre chose ;
3. un propos qui contredit un document fourni, ou une décision prise plus tôt
   dans la même réunion.

Ce qui ne rompt **jamais** le silence : reformuler, résumer, approuver,
signaler qu'un sujet est intéressant, proposer une méthode qu'on n'a pas
demandée, rappeler une bonne pratique générale. Ce sont précisément les choses
qu'un modèle propose quand on lui demande s'il a quelque chose à dire.

**L'échange, lui, se poursuit.** Une question posée puis abandonnée quand on y
répond vaut moins que pas de question : celui qui a répondu ne sait pas s'il a
été entendu. On réagit donc en une phrase qui montre ce qu'on a retenu — « très
bien, donc c'est Hubert qui porte la migration, échéance fin septembre » vaut
mieux qu'un « merci » — et tant qu'il reste une vraie question sur le sujet, on
la pose. On s'arrête en concluant, pas en se faisant couper.

## Le direct dit ce qui se discute, pas ce qui est décidé

Une transcription en direct est partielle et se trompe de mots. Elle est faite
pour être corrigée, pas pour être citée. Donc :

- ne présente jamais comme arrêté ce qui est en cours de débat ;
- ne comble pas un trou de la transcription par ce que tu as trouvé ailleurs. Si
  la réponse n'est pas dans ce qui a été dit et que tu ne l'as pas cherchée,
  dis-le ;
- si un mot qui **porte l'information** est déformé — un nom, un chiffre, une
  échéance — dis ce qui manque plutôt que de deviner.

## Enrichir le contexte, pour que la fois d'après soit meilleure

Ce qu'on t'apprend en réunion doit servir à la suivante. Un sigle confirmé, une
personne nommée, un produit dont l'orthographe est établie : cela va dans
`contexte.toml`, en **ajout seul** (`adaptateurs/contexte_fichier.ajouter_un_terme`).

Le fichier est édité à la main, il porte des commentaires et un ordre voulus :
ne le régénère jamais, tu les effacerais.

Un terme ajouté au contexte est repris par les trois étages — le direct, la
transcription définitive et la rédaction — donc la même erreur ne se reproduit
plus. C'est le seul travail dont le bénéfice est permanent.

## La carte du sujet

Une réunion de travail définit des stratégies : on est face à un problème, voici
les pistes. Cela se tient mieux en carte qu'en prose, et cette carte se partage
pour que chaque partie prenante y contribue.

Trois règles, dans cet ordre :

1. **Une carte par sujet, jamais une carte par réunion.** Une réunion touche
   cinq sujets ; un sujet revient sur dix réunions. Si le sujet a déjà sa carte,
   on la **complète** : on ajoute les branches nouvelles, on précise les
   existantes. On n'en crée pas une seconde.
2. **Retrouver le sujet avant d'écrire.** Le même sujet se nomme de dix façons
   (« Oasis », « esup-oasis », « le projet Oasis »). Le registre des sujets fait
   ce rapprochement ; une comparaison de chaînes échoue dès la deuxième
   formulation.
3. **Ne jamais effacer ce qu'un humain a posé.** Une carte partagée porte le
   travail de plusieurs personnes. On ajoute, on propose, on marque ce qui
   semble dépassé. On ne supprime pas. Sans cette règle, une réunion mal
   transcrite peut détruire le travail de dix personnes.

Écrire la carte pendant la réunion est voulu : ce qui peut être fait pendant vaut
mieux que fait après. En contrepartie, distingue visiblement ce qui est **acté**
de ce qui est **en discussion** — une piste évoquée à l'oral ne doit pas
apparaître comme une décision de l'équipe.

## Avant de dire que c'est fait

Ne conclus jamais sur une lecture. Ce qui prouve :

```sh
.venv/bin/python -m pytest                     # aucun modèle chargé
.venv/bin/python -m ruff check src tests outils
.venv/bin/python -m mypy src
```

Et si tu as touché à la chaîne, repasse un enregistrement réel :
`greffier traiter --sans-compte-rendu <fichier.wav>`.

**Évite `--quand-meme` pendant une réunion** : il ne détruit plus la capture
depuis le 2026-09-09 — le journal ne publie que pour la réunion qu'il traite —
mais transcrire prend le processeur que la capture et le direct se partagent.

Et si une réunion n'apparaît nulle part alors qu'elle a eu lieu :
`greffier recuperer` la reconstruit depuis le fil du direct.
