# Un corpus réel en français

Sur une réunion synthétisée, les seize combinaisons de décodage donnent le
même 1,75 % d'erreur de mots (`reste-a-faire.md`, 2026-09-12) : le synthétique
ne porte ni recouvrement, ni accent, ni éloignement du micro, les trois causes
de la plainte « les mots affichés n'étaient pas ceux dits en séance ». Il faut
donc du vrai, avec une référence écrite par des humains, pour départager.

## Les candidats, vérifiés le 2026-09-15

Quatre critères : français, plusieurs locuteurs dans une même pièce, texte de
référence avec les tours de parole, licence qui permet l'usage. L'audio ne va
jamais dans le dépôt : un script le télécharge chez son producteur.

| Corpus | Ce que c'est | Référence | Licence | Verdict |
|---|---|---|---|---|
| **SUMM-RE** (LINAGORA / LPL Aix-Marseille, Hugging Face `linagora/SUMM-RE`) | 283 conversations de réunion de 20 min, 3 à 4 personnes, spontanées, scénarisées (compte rendu, décision, planification) ; un micro par personne, une piste par personne ; 25 réunions du split `dev` enregistrées **en présentiel** au studio H2C2 et 3 au LPL | Transcription manuelle des splits `dev` et `test`, alignée au mot, par locuteur ; la fiche dit elle-même que la séparation des voix s'évalue en mélangeant les pistes | CC BY-SA 4.0 | **Retenu.** Couvre le recouvrement et l'accent, pas l'éloignement du micro : les pistes sont de proximité, le mélange n'a pas l'acoustique d'une salle |
| **Auditions de commission de l'Assemblée nationale** (`videos.assemblee-nationale.fr`) | Une salle, des micros de table, un président, des députés à distance variable, un ou plusieurs auditionnés ; interruptions et chevauchements réels | Le compte rendu nominatif, publié sous quelques jours ; **intégral mais relu** : hésitations retirées, syntaxe redressée | Téléchargement des vidéos ouvert par le portail, licence des vidéos non écrite ; comptes rendus des séances en Licence Ouverte sur `data.assemblee-nationale.fr`. Usage ici : mesure locale, aucune redistribution | **Retenu**, avec une mesure adaptée : le texte relu interdit un taux d'erreur brut ; on mesure les termes retrouvés et l'attribution des locuteurs, et l'erreur de mots sur un passage de cinq minutes vérifié à la main |
| **CEFC / ORFEO** (ORTOLANG) | 450 h agrégées de quatorze corpus : entretiens, conversations à deux, récits, interactions de service ; peu de réunions à plus de deux | Alignée | CC BY-NC-SA 3.0 FR | Refusé : presque pas de réunions, et la licence non commerciale n'apporte rien que SUMM-RE ne donne déjà |
| **ESLO 1 et 2** (ORTOLANG) | Entretiens sociolinguistiques à Orléans, à deux, souvent dans la rue | Alignée | CC BY 4.0 | Refusé : des entretiens, pas des réunions |
| **TCOF** (ORTOLANG) | Interactions adulte-adulte dont des « réunions de travail », enregistreur unique | Alignée | CC BY-NC-SA 2.0 | En réserve : si l'Assemblée ne suffit pas pour l'acoustique de salle |
| **Conférences Pierre Mendès France** (data.gouv.fr, Bercy) | 300 h de conférences avec questions de la salle, MP3 et XML | Format et fidélité non décrits sur la fiche | Licence Ouverte 2.0 | En réserve : un orateur principal, pas une réunion |
| **VoxPopuli, Europarl-ST** | Discours au Parlement européen, un orateur à la fois | Oui | CC0 / CC BY-NC | Refusé : des discours, pas des échanges |
| **ESTER, ETAPE, MEDIA** (ELRA) | Radio, télévision, dialogues téléphoniques | Oui | Payante | Refusé : payant, et pas des réunions |
| **AMI** | Réunions en anglais, déjà employé (91,6 % d'attribution) | Oui | CC BY 4.0 | Gardé pour la séparation des voix, inutile pour le français |

## Ce qui est retenu, et pourquoi ces deux-là

SUMM-RE apporte ce qu'aucun autre ne donne : une référence **mot à mot**, par
locuteur, sur des Français qui se coupent la parole pour de vrai. L'Assemblée
apporte ce que SUMM-RE n'a pas : **une salle**, des gens loin du micro, et un
nombre de locuteurs qui dépasse ce qu'une réunion d'entreprise connaît. À eux
deux, ils couvrent les trois causes de la plainte.

## Les enregistrements

`python3 tools/fetch_corpus.py` les dépose dans `corpus/` du dossier de données
(`~/.local/share/greffier/corpus` sous Linux), chacun avec sa référence
`*.reference.json` : la source, la licence, les locuteurs et les tours.

| Fichier | Quoi | Durée | Locuteurs | Ce qu'il apporte |
|---|---|---|---|---|
| `summre-032a_EARH.wav` | SUMM-RE, réunion de compte rendu, studio H2C2, quatre pistes mélangées en mono 16 kHz | 19,7 min, 17,5 min de parole, 391 tours | 4 | Référence mot à mot ; 1,4 min de parole superposée |
| `summre-036c_EAPH.wav` | SUMM-RE, réunion de planification, même studio | 26,8 min, 25,8 min de parole, 812 tours | 4 | Référence mot à mot ; **5,1 min de parole superposée**, un cinquième du temps |
| `assemblee-2026-07-22.wav` | Audition de « Les Oubliés de la République », commission d'enquête sur l'augmentation de la pauvreté ; la vidéo commence un quart d'heure avant l'ouverture, l'outil coupe ce silence et garde les 40 premières minutes de séance | 40 min sur 2 h 24 | 8 nommés dans le compte rendu (président, rapporteur, une députée, cinq auditionnés) | Une salle, des micros de table, des gens à distance variable ; 57 tours relus, 15 600 mots |

Vérifié à l'oreille du modèle, pas seulement au chiffre : les 25 premières
secondes du fichier de l'Assemblée donnent « Mes chers collègues, [je] vous
souhaite la bienvenue pour cette dernière audition avant la pause estivale »,
soit le premier tour du compte rendu ; à 20 minutes, un auditionné se présente.
Le compte rendu a d'ailleurs retiré « pour cette dernière audition avant la
pause estivale » : c'est ce genre de coupe qui interdit un taux d'erreur brut
sur ce texte.

Ce que le script ne fait pas : il ne garde ni la vidéo (1,2 Go, effacée après
extraction) ni les fichiers parquet de Hugging Face (un gigaoctet, dans le
cache de `huggingface_hub`, à effacer soi-même). Aucun de ces fichiers n'entre
dans le dépôt.

## La mesure, réglages par défaut (2026-09-15)

`python3 tools/measure_corpus.py`, chaîne installée telle quelle : `large-v3` sur
la carte, aucune amorce de vocabulaire, aucun nombre de participants déclaré.
Trois chiffres par enregistrement, définis dans l'outil et tenus par
`tests/test_measure_corpus.py` :

- **l'erreur de mots**, les deux textes lus de la même façon (minuscules, sans
  ponctuation, sans « euh »), distance d'édition sur les mots ;
- **les termes rares retrouvés** : les mots que la référence n'emploie qu'une
  fois et qui font au moins sept lettres, ceux qu'un modèle remplace par un
  mot plus courant ;
- **l'attribution** : chaque voix rendue est réputée être la personne qu'elle
  porte le plus souvent, puis chaque phrase est *juste*, *fausse*, ou *sans
  avis* quand elle n'a reçu aucune voix. Les deux derniers ne sont pas la
  même faute : un mauvais nom dans un compte rendu est pire qu'un blanc.

| | Erreur de mots | Termes rares | Juste | Faux | Sans avis | Voix rendues / personnes |
|---|---|---|---|---|---|---|
| Assemblée, 40 min | 47,1 % *(texte relu)* | 433 / 578 (75 %) | **96,7 %** | 2,9 % | 0,4 % | 5 / 7, une miette |
| SUMM-RE 032a, 19,7 min | **21,6 %** | 224 / 254 (88 %) | **89,0 %** | 2,8 % | 8,2 % | 4 / 4 |
| SUMM-RE 036c, 26,8 min | 33,0 % | 169 / 227 (74 %) | **64,1 %** | **23,9 %** | 12,1 % | **2 / 4**, dix miettes |

### Ce que les chiffres disent

**Les mots se perdent dans le recouvrement, pas dans le vocabulaire.** Sur
032a, les 21,6 % se décomposent en 12,1 % d'omissions, 4,4 % de substitutions
et 5,2 % d'ajouts. Les omissions sont les petits mots lancés pendant que
quelqu'un d'autre parle : « ouais » (17 fois), « ok » (14), « ben » (11),
« non » (9). Une part des substitutions n'en sont pas : « vingt » écrit « 20 »,
« etcetera » écrit « etc », « y'a » écrit « il y a ». Les ajouts sont menés par
le « ne » de négation (15 fois), que les gens ne prononcent pas et que le
modèle réécrit. Sur 036c, où un cinquième du temps est parlé à deux, les
omissions montent à 19,3 %.

**L'Assemblée ne se mesure pas en erreur de mots.** Contre les 4 700 mots du
compte rendu couverts par les 40 minutes, 24 % des mots entendus n'y figurent
pas (« et », « donc », « je », « que » : le texte publié resserre) et le
compte rendu écrit « nous » là où l'auditionné a dit « on ». Le chiffre mesure
la relecture. Ce que l'audition apporte, c'est la salle : 96,7 % d'attribution
juste avec des micros de table, deux voix pour le président (2 et 19), et
Mme Maurer fondue dans la voix de M. Abdelatif (11 phrases sur 92, ce sont les
2,9 % de faux). Les deux « personnes » restantes des 7 ont une phrase chacune.

**Le défaut, c'est 036c : quatre personnes rendues en deux voix.** La voix 0
porte 093 et 099 (437 et 103 phrases), la voix 26 porte 092 et 091 (84 et 72).
Ce ne sont pas des voix éclatées, ce sont des personnes **fondues deux à
deux**, et dix miettes d'une phrase autour. Le compte rendu annoncerait deux
participants là où il y en a quatre, et un quart des phrases porterait le
mauvais nom. La même chaîne sur 032a, même studio, même dispositif, rend 4
voix pour 4 personnes à 89 %. La différence entre les deux réunions : 1,4 min
de parole superposée d'un côté, 5,1 de l'autre, et des paires de voix plus
proches. C'est le cas que le synthétique ne produisait pas, et c'est celui
qu'il faut faire tomber en premier.

### Ce que ça change dans le plan

- La case suivante (rejouer les seize combinaisons et l'amorce) se joue sur
  036c et 032a, où la référence est mot à mot ; l'Assemblée ne sert qu'à
  l'attribution.
- Les omissions dans le recouvrement ne se règlent pas par un réglage de
  décodage : c'est un problème de séparation, pas de transcription.
- Les 12 voix de 036c mettent la phase 5 (adopter les petits agrégats au seuil
  du direct) devant une vraie réunion, avec un chiffre à battre : 64,1 %.

## Les seize combinaisons de décodage, sur le réel (2026-09-15)

`python3 tools/measure_decoding.py` : même préparation audio que la chaîne,
`large-v3` sur la carte, les seize combinaisons de `beam_size` (5 ou 1),
`vad_filter`, `condition_on_previous_text` et `temperature` (l'échelle de
repli de faster-whisper, ou 0). Sur le synthétique elles donnaient toutes
1,75 % ; sur le réel elles vont **de 21,5 % à 409 %**.

| Combinaison | 032a (19,7 min) | 036c (26,8 min) | Temps 032a |
|---|---|---|---|
| **beam 5, vad, cond, échelle** *(le produit)* | 22,1 % | **29,8 %** | 373 s |
| beam 5, sans vad, cond, échelle | **21,5 %** | 30,1 % | 292 s |
| beam 1, sans vad, cond, échelle | 24,2 % | 31,4 % | 198 s |
| beam 1, vad, cond, échelle | 24,4 % | 31,7 % | 239 s |
| beam 1, sans vad, sans cond (échelle ou 0) | 22,9 % | 33,3 % | 162 s |
| beam 5, vad, sans cond (échelle ou 0) | 24,0 % | 34,0 % | 225 s |
| beam 5, sans vad, sans cond (échelle ou 0) | 24,4 % | 34,3 % | 225 s |
| beam 1, vad, sans cond (échelle ou 0) | 24,5 % | 34,5 % | 158 s |
| beam 5, vad, cond, **température 0** | 22,1 % | **43,6 %** | 322 s |
| beam 5, sans vad, cond, **température 0** | 21,5 % | **85,3 %** | 329 s |
| beam 1, vad, cond, **température 0** | 31,3 % | **80,4 %** | 173 s |
| beam 1, sans vad, cond, **température 0** | **409 %** (17 642 mots pour 4 103) | **88,9 %** | 784 s |

### Ce qui bouge un chiffre, et ce qui ne bouge pas

- **Le réglage du produit est le bon.** Meilleur sur 036c, à 0,6 point du
  meilleur sur 032a. Rien à changer.
- **La zone dangereuse est nette** : `condition_on_previous_text` **sans**
  l'échelle de température. Le modèle se met à boucler : 17 642 mots
  transcrits pour 4 103 prononcés sur 032a, et quatre fois sur quatre au-delà
  de 43 % sur 036c. L'échelle de repli est ce qui sauve le conditionnement ;
  la couper est la seule façon de casser la transcription par un réglage.
- **Sans conditionnement, rien ne boucle jamais**, mais on paie 2 à 4 points.
  C'est le repli sûr si un jour une boucle est observée en séance.
- **Le faisceau** vaut 1 à 2 points et coûte 1,5 à 2 fois le temps.
- **Le filtre de voix** joue un demi-point, dans un sens ou dans l'autre.
- **Ce qu'aucun réglage ne rattrape** : sur 036c le meilleur reste à 29,8 %,
  et les omissions (19,3 % au réglage produit) sont les mots dits pendant
  qu'un autre parle. Ce n'est pas un problème de décodage.

### L'amorce, sans vocabulaire à lui donner

Le produit n'envoie une amorce que si un vocabulaire est configuré :
« Réunion de travail. Vocabulaire : … ». Mesurée seule, la phrase de tête
sans aucun terme derrière **coûte** : 24,9 % au lieu de 22,1 % sur 032a,
30,5 % au lieu de 29,8 % sur 036c, et deux à cinq termes rares de moins. Le
gain mesuré le 12/09 (11 puis 15 termes sur 15) vient donc des termes, pas de
la phrase qui les précède. Rien à changer tant que l'amorce n'existe qu'avec
des termes ; si un jour elle est envoyée à vide, ce chiffre dit de ne pas.
