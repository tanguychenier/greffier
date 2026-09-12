# Ce que la carte graphique change, mesuré

Machine de mesure : Ryzen 7 3750H (4 cœurs, 8 fils), GTX 1660 Ti Max-Q 6 Go,
pilote 595.84, Ubuntu 24.04. Réunion de référence : 40,7 s synthétisées, deux
voix. Le poste était **chargé** pendant les mesures (charge moyenne entre 9 et
29 : navigateur, OBS, conteneurs) ; les chiffres du processeur varient donc du
simple au triple d'un tour à l'autre, ceux de la carte presque pas. Chaque
comparaison a été faite deux fois de suite, dans les mêmes conditions.

## 1. Où partait le temps

| Poste | Mesure |
|---|---|
| Segmentation pyannote seule, 5 fenêtres | **0,35 s** |
| Une empreinte TitaNet de 3 s sur le processeur | **0,47 à 1,10 s** |
| `process()` complet du découpage | **43 à 95 s** |

Le découpage en tours de parole ne coûte pas cher à cause de la segmentation :
il coûte cher parce qu'il fait tourner TitaNet, 101 Mo, 25 millions de
paramètres, sur **chaque** extrait. Sur le processeur, ce seul modèle tient
entre 1,9 et 2,8 fois le temps réel.

## 2. Le même modèle sur la carte

Banc direct sur TitaNet, entrée de taille fixe, dix passes après trois passes de
chauffe :

| Durée d'extrait | Processeur (4 fils) | Carte |
|---|---|---|
| 1,5 s | 537 ms | **6,9 ms** |
| 3,0 s | 1 097 ms | **38,8 ms** |
| 6,0 s | 3 131 ms | **11,0 ms** |

## 3. Bout en bout, à tours de parole identiques

`auto` = la carte quand le pilote répond.

| Poste | Avant (découpage sur le processeur) | Après (tout sur la carte) |
|---|---|---|
| Ouverture du modèle de transcription | 12 à 19 s | 12 à 19 s |
| Transcription | 7,2 à 7,3 s | 7,2 à 9,0 s |
| **Tours de parole** | **30,2 à 38,9 s** | **6,2 à 8,9 s** |
| **Empreintes** | **4,7 à 6,2 s** | **0,9 à 1,5 s** |
| **Total** | **58,7 à 62,7 s** | **32,5 à 33,8 s** |

Les tours rendus sont **les mêmes**, bornes comprises : la carte ne change que
le temps.

La voix de l'assistante suit : 2,43 s pour prononcer une remarque de cinq
secondes sur le processeur, **0,28 s** sur la carte.

Mémoire prise sur la carte : 383 Mo pour le découpage, 1 905 Mo pour le modèle
de transcription. Les deux tiennent ensemble dans 6 Go.

## 4. Ce qui n'a pas marché

**Plus de fils.** `compute_threads()` rend déjà 4 sur cette machine, soit les 4
cœurs physiques. Mesuré de 1 à 8 fils sur TitaNet : le bruit de la charge
dépasse l'écart. Rien à gagner.

**Transcrire et découper en même temps.** Une fois les deux sur la carte, les
faire tourner dans deux fils donne **0,92×** : 13,14 s au lieu de 12,12 s. Ils
se disputent la carte et l'extraction des traits sur le processeur. Abandonné.

**Aligner les versions d'ONNX Runtime.** Voir ci-dessous : pire que le mal.

## 5. Le piège : deux ONNX Runtime dans un processus

faster-whisper charge son propre ONNX Runtime avec son détecteur de voix
(`vad_filter=True`), et la roue CUDA de sherpa-onnx embarque le sien. Les deux
ne tiennent pas ensemble :

| Ordre | Résultat |
|---|---|
| sherpa d'abord, puis faster-whisper | fonctionne |
| faster-whisper d'abord, puis sherpa sur le **processeur** | fonctionne |
| faster-whisper d'abord, puis sherpa sur la **carte** | `node_index < nodes_.size() was false` |
| versions rapprochées (onnxruntime 1.27.0 contre 1.27.1 embarquée) | **erreur de segmentation** |

Celui qui ouvre en second se lie aux symboles de l'autre. Rapprocher les
versions ne répare rien : ça remplace un graphe corrompu par un interpréteur
tué.

D'où les deux règles du code :

1. La racine de composition ouvre la session de la carte **avant** de construire
   un transcripteur : 1,09 s, et il ne reste que le contexte du pilote sur la
   carte (85 Mo).
2. Si malgré tout le rival est déjà là, le découpage se replie sur le
   processeur. Lent vaut mieux que perdu.

## 6. L'attente après « Terminer »

Ouvrir large-v3 prend plus longtemps que de transcrire la réunion. Fermer
proprement l'encodeur prend jusqu'à quinze secondes, et se produit avant. Les
deux se font maintenant en même temps :

| | Mesure |
|---|---|
| Sans préchauffage | 12 s d'encodeur + 21,98 s = **33,98 s** |
| Avec préchauffage | 12 s d'encodeur + 12,06 s = **24,06 s** |

## 7. Les modèles rouverts à chaque fois

La carte a rendu visible ce que la lenteur du processeur cachait : plusieurs
modèles étaient **rouverts à chaque usage**.

| Ce qui rouvrait | Quand | Coût |
|---|---|---|
| Voix de l'assistante | à chaque question posée en préparation | 4,59 s |
| Empreintes TitaNet (101 Mo) | à chaque clic sur « nommer », « séparer », « oublier » | 0,3 à 1,2 s |
| Transcription large-v3 | à chaque traitement | 12 à 19 s |

Trois questions posées de suite à l'assistante, avant et après :

    question 1 : 4,59 s     question 1 : 4,59 s
    question 2 : 4,6 s      question 2 : 0,29 s
    question 3 : 4,6 s      question 3 : 0,31 s

Les trois modèles sont maintenant gardés pour le processus, par fichier et par
périphérique. La voix s'ouvre en plus pendant que la personne parle au micro ou
que le rédacteur réfléchit, pour que même la première réponse arrive parlée.

## 8. Rejouer ces mesures

Les scripts de mesure ne sont pas versionnés : ils tiennent en une vingtaine de
lignes chacun et dépendent d'un enregistrement qui, lui, ne peut pas l'être. Ce
qu'ils font :

- ouvrir TitaNet par `onnxruntime` seul, en forçant `CPUExecutionProvider` puis
  `CUDAExecutionProvider`, et chronométrer dix passes sur une entrée
  `(1, 80, N)` ;
- construire un `OfflineSpeakerDiarization` avec `provider="cpu"` puis
  `"cuda"` sur les mêmes modèles et comparer les tours rendus ;
- appeler `wiring._transcriber`, puis `SherpaDiariser.segment`, puis
  `TitaNetExtractor.extract_spans` sur un même fichier, en chronométrant chaque
  poste.
