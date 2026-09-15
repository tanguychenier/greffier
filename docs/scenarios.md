# Les scénarios : ce qui est éprouvé, ce qui ne l'est pas

Un outil qui écoute des réunions rencontre un nombre fini de situations, et la
plupart n'ont jamais été jouées. Ce document les liste toutes, dit lesquelles
sont couvertes et par quoi, et sert de plan de travail. Une situation non
listée ici est une situation que personne n'a envisagée : l'ajouter vaut mieux
que de la découvrir en séance.

Trois états : **couvert** par un test qui échouerait si le comportement
changeait, **mesuré** sans être tenu par un test, et **ouvert**.

## La prise de son et la salle

| Situation | État | Où |
|---|---|---|
| Deux voix distinctes, visioconférence | couvert | `test_whole_chain` |
| Trois voix autour d'une table, un seul micro | couvert | `test_in_the_room` |
| Fuite du son système dans le micro | couvert | `test_in_the_room` |
| Micro au milieu de la pièce, quatre personnes, bruit de salle | mesuré | corpus AMI, 91,6 % de justesse |
| Quelqu'un **arrive en cours** de réunion | ouvert | |
| Quelqu'un **part** avant la fin | ouvert | |
| Quelqu'un **change de place** ou s'éloigne du micro | partiellement | la mise à niveau des extraits le neutralise |
| Casque branché ou débranché en séance | partiellement | l'évènement matériel est suivi, la continuité de la voix non |
| **Parole superposée** longue, deux personnes ensemble | ouvert | |
| Silence long, puis reprise | ouvert | |
| Bruit de fond continu : ventilation, rue, clavier | ouvert | |
| Quelqu'un au **haut-parleur du téléphone** posé sur la table | ouvert | |
| Réunion **hybride** : des gens dans la salle, d'autres en ligne | ouvert | |
| **Musique ou vidéo** jouée pendant la réunion | ouvert | |
| La même personne **présente et connectée** : sa voix arrive deux fois | ouvert | |
| Réunion plus longue que le garde-fou de quatre heures | ouvert | |
| Réunion de trente secondes | ouvert | |

## La langue

| Situation | État | Où |
|---|---|---|
| Réunion en français | couvert | toute la chaîne |
| Interface en anglais | couvert | `test_wording_files`, `test_chosen_language` |
| Réunion **mêlant deux langues** | ouvert | |
| Personne au **fort accent** | ouvert | |
| Termes rares et sigles | mesuré | 11 sur 15 sans amorce, 15 sur 15 avec |
| Chiffres, dates, montants dits à l'oral | ouvert | |

## Qui est qui

| Situation | État | Où |
|---|---|---|
| Deux prénoms dits, deux voix | couvert | `test_whole_chain` |
| Quelqu'un cité mais absent | couvert | `make_hard_cases`, cas « absent » |
| Prénom interpellé sans réponse | couvert | `make_hard_cases`, cas « sans-reponse » |
| Une personne de la banque absente de la réunion | couvert | les personnes attendues bornent la banque |
| La banque retrouve une voix d'une réunion à l'autre | couvert | `test_bank_across_meetings` |
| **Deux personnes du même prénom** dans la même réunion | ouvert | |
| Un nom **corrigé en cours** de réunion | partiellement | `test_live_with_assistant` |
| Une empreinte **fausse entre en banque**, et il faut s'en remettre | partiellement | `intruding_voiceprints` existe, le parcours non |
| Une banque de **centaines** de personnes | ouvert | |
| Deux voix fusionnées à la main, à **séparer de nouveau** | ouvert | sans retour arrière |

## Ce qui casse

| Situation | État | Où |
|---|---|---|
| Le rédacteur échoue, la transcription est gardée | couvert | `test_window`, reprise par « Rédiger » |
| Aucun modèle installé | couvert | la fenêtre le dit et propose |
| La carte graphique ne peut pas calculer | couvert | `test_transcription_device` |
| Deux moteurs ONNX dans un processus | couvert | `test_cuda` |
| **Disque plein** pendant l'enregistrement | ouvert | |
| Le **micro disparaît** en séance | partiellement | veille matérielle sur macOS |
| La machine **se met en veille** | ouvert | |
| Le **réseau tombe** pendant la rédaction | partiellement | le délai existe, le parcours non |
| L'application **s'arrête** en séance | partiellement | `greffier recuperer` |
| Les **modèles sont effacés** entre deux réunions | ouvert | |
| Fichier audio **abîmé** | ouvert | |
| **Changement d'heure** pendant la réunion | ouvert | |

## Ce que la loi demande

| Situation | État | Où |
|---|---|---|
| Dire dans le compte rendu ce qui a été annoncé aux participants | couvert | ligne de consentement |
| **Effacer une personne** de la banque et de toutes les réunions | couvert | `test_erase_person`, `greffier oublier-une-personne` |
| Effacer une réunion entière | partiellement | en ligne de commande, pas dans la fenêtre |

## Ce que l'outil devrait avoir

- **Dire qu'il doute, au moment où il doute.** Il sait se faire corriger, il ne
  demande jamais.
- **Un retour arrière** sur la séparation de deux voix.
- **Effacer une réunion** depuis la fenêtre.
- **Un premier lancement** qui prend par la main quand rien n'est configuré.

## Ce qui vient d'arriver

- **Une confiance par tour**, mesurée avant d'être montrée : la transcription
  lisible marque « (?) » les passages que le modèle n'a pas bien entendus, le
  tableur porte le chiffre, et la fenêtre dit combien de passages méritent une
  réécoute. Le seuil vient de `tools/measure_confidence.py`, voir
  `docs/calibrage.md`. Couvert par `test_doubt`.
- **Exporter la transcription** en SRT, WebVTT ou CSV, en ligne de commande et
  depuis la fenêtre. Les sous-titres sont découpés comme des sous-titres : deux
  lignes de quarante-deux caractères au plus, le nom du locuteur compté dans la
  largeur de sa ligne et écrit une fois par tour, la durée du tour partagée
  entre ses blocs. Couvert par `test_export`.

## Ce qui a été essayé et retiré

**Rattacher une bribe à ses voisines.** Une bribe trop courte pour porter une
empreinte, encadrée des deux côtés par la même voix et à moins de deux secondes
de chacune, lui appartient presque sûrement. La règle a été écrite, branchée et
mesurée sur une réunion réelle au micro de table :

| | Justesse | Faux | Sans avis |
|---|---|---|---|
| Sans la règle | 91,6 % | 0,3 % | 8,1 % |
| Avec la règle | 91,8 % | **0,5 %** | 7,7 % |

Deux dixièmes gagnés d'un côté, deux dixièmes perdus de l'autre : l'échange se
fait un pour un entre « je ne sais pas » et « je me trompe ». Le second coûte
plus cher que le premier, puisqu'il attribue les mots de quelqu'un à un autre
et que personne ne le voit. La règle a donc été retirée.
