# Le plan, en cases à cocher

Ce qui reste à faire sur Greffier après la 0.3.23, dans l'ordre où chaque
phase débloque la suivante. Une case se coche dans la PR qui termine le point,
avec la preuve en face : un chiffre mesuré, une image regardée, un test qui
échouerait si le comportement changeait. Le détail de chaque point est dans
`reste-a-faire.md` et `scenarios.md` ; ici, seulement l'état.

## Phase 1. Un corpus réel en français

Le synthétique donne 1,75 % d'erreur quelle que soit la combinaison de
décodage : il ne départage rien. Tout réglage attend cette phase.

- [x] Vérifier les corpus candidats sur quatre critères : français, plusieurs
      locuteurs dans une pièce, texte de référence avec les tours de parole,
      licence qui permet l'usage. Pistes : SUMM-RE, ORFEO, CID, ESLO, auditions
      de commissions de l'Assemblée nationale (vidéo publique et compte rendu
      nominatif sous Licence Ouverte).
      *Preuve : un tableau dans `corpus.md`, un candidat retenu ou refusé par ligne, avec la raison.*
- [x] Retenir deux ou trois enregistrements de 20 à 40 minutes qui couvrent
      les trois causes de la plainte : recouvrement, accent, distance au micro.
      *Preuve : un script de téléchargement dans `tools/`, jamais d'audio dans le dépôt.*
- [ ] Écrire `tools/measure_corpus.py` : taux d'erreur de mots, termes rares
      retrouvés, justesse de l'attribution des locuteurs (la mesure des 91,6 %
      de l'AMI, par la même machinerie que `replay_stitching.py`).
      *Preuve : le tableau des trois chiffres par enregistrement dans `corpus.md`.*
- [ ] Rejouer les seize combinaisons de décodage et l'amorce de vocabulaire
      sur le réel ; ne garder que ce qui bouge un chiffre.
      *Preuve : le tableau avant/après, et les réglages par défaut justifiés par lui.*

## Phase 2. Windows, vu pour de vrai

Seize tests couvrent les chemins propres au système ; personne n'a jamais
double-cliqué.

- [ ] Sur le runner Windows, lancer `Greffier.exe` sans argument, attendre,
      photographier l'écran et remonter les images en artefact (déclenchement
      à la main, pas par un tag).
      *Preuve : les images regardées : polices, boîtes du premier lancement, dossier de données sous `%LOCALAPPDATA%`.*
- [ ] Corriger ce que les images montrent.
      *Preuve : les images d'après, et un test par défaut trouvé.*
- [ ] Le vrai double-clic : machine virtuelle Windows 11 d'évaluation pilotée
      en VNC, ou son disque Windows à lui. À trancher par lui.
      *Preuve : une ligne « lancé sur Windows le … » dans le README, avec ce qui a été vu.*

## Phase 3. `initiative` sur une vraie réunion

Livrée désactivée ; la moitié proactive de l'assistante n'a jamais traversé
une séance.

- [ ] Récupérer la réunion du 2026-09-10 (six personnes, 3 878 s) depuis le
      Mac : audio, json et jsonl. Elle n'est pas sur ce PC.
- [ ] Étendre `tools/replay_live.py` pour alimenter `watch.py` avec le fil des
      phrases, `initiative` activée, et journaliser chaque prise de parole
      qu'elle aurait faite et ce qu'elle aurait dit.
      *Preuve : le journal des interventions sur la réunion réelle.*
- [ ] Juger chaque intervention : bon moment, utile, intrusive. Décider la
      valeur par défaut sur ces chiffres.
      *Preuve : le tableau dans `reste-a-faire.md`, et le réglage par défaut qui en découle.*

## Phase 4. Deux courtes tâches produit

- [ ] Présentiel : quand la prise de son n'a qu'un canal, la fenêtre et le
      compte rendu disent que l'attribution repose sur les voix.
      *Preuve : un test dans `test_window`, et la ligne dans un compte rendu réel.*
- [ ] Nombre de participants : quand les voix détectées dépassent le nombre
      déclaré, la fenêtre le suggère.
      *Preuve : un test sur les réunions synthétiques, et la suggestion vue à l'écran.*

## Phase 5. La chaîne d'après réunion au seuil du direct

Le direct a réuni Lise en une voix, l'après-réunion l'a éclatée en neuf.

- [ ] Mesurer avec `replay_stitching.py`, sur l'AMI et le corpus de la
      phase 1, l'adoption des petits agrégats à 0,50 au lieu de 0,75.
      *Preuve : le tableau justesse / faux / sans avis, comme pour la « bribe rattachée ». Gardé seulement si les deux côtés s'améliorent.*

## Phase 6. Le reste, après

- [ ] Dire qu'il doute au moment où il doute.
- [ ] Un premier lancement qui prend par la main quand rien n'est configuré.
- [ ] Regrouper les voix parasites sous « Les autres ».
- [ ] Les sources GitLab, Jira, Trello pour une question orale (attend une
      configuration réelle).
- [ ] Un AppImage pour Linux.
- [ ] Les 22 sauts de la suite d'intégration : la réunion de table à trois
      timbres, et « Lucie » entendue « UCI ».
- [ ] Une recherche à jour sur la séparation des voix ; tout candidat doit
      battre +0,099 de marge à 14,6 ms.

## Décisions qui sont à lui, pas des tâches

- Notarisation macOS : compte Apple payant, sinon Gatekeeper refuse le paquet
  sur un autre Mac.
- La prise de son : deux micros écartés contre la pieuvre. À mesurer sur une
  réunion étiquetée avant d'acheter quoi que ce soit.

## Règles sur toute la durée

Une PR par point sur `main` protégée ; CI verte en `LANG=C` sous xvfb avant
chaque push ; changelog régénéré par `tools/changelog.py` ; une release par
phase terminée ; chaque chiffre annoncé est mesuré et écrit dans `docs/`.
