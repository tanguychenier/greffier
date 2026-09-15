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
