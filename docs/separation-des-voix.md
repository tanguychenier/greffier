# Séparer les voix : ce qu'on fait, ce qui existe, ce qu'on n'a pas mesuré

Document de travail, à discuter. Il sépare trois choses que la conversation
mélange volontiers : ce que l'outil fait aujourd'hui et à quel prix, ce que
l'état de l'art propose, et ce qu'il faudrait mesurer avant de changer quoi que
ce soit.

**Avertissement sur la seconde partie.** Ce que je sais de l'état de l'art
s'arrête à mai 2026 et n'a pas été vérifié depuis. Les noms et les principes
sont sûrs ; les classements et les « meilleurs » ne le sont pas, et une
recherche à jour est le premier point à faire ensemble.

**Depuis :** le banc des extracteurs a été lancé sur une réunion réelle de
1 h 42, et il tranche la question du modèle d'empreintes. CAM++ et ResNet293,
tous deux en tête des classements de vérification du locuteur, ont une marge
**négative** sur des extraits de 2,5 s, aucun seuil ne les sépare. TitaNet
reste. Voir [le REX du 10 septembre](rex-2026-09-10.md), section 4 : tout
candidat doit désormais battre **+0,099 de marge à 14,6 ms par extrait**.

## 1. Ce que l'outil fait

Trois étages, chacun mesuré sur une réunion réelle de 92 minutes à trois
personnes autour d'une table.

| Étage | Ce qui décide | Mesure |
|---|---|---|
| Segmentation | pyannote-segmentation-3.0, seuil de regroupement 0,45 | 298 groupes rendus |
| Empreintes | NeMo TitaNet large, 192 dimensions | phrase / agrégat : 0,667 contre 0,337 |
| Recollage | paires (0,75), adoption (0,45), consolidation (0,70) | 298 → 21, dont 3 réelles |
| En direct | rattachement (0,50), plafond 12 voix | 111 → 12, justesse 92,9 % |

Le principe qui tient tout : **sur-découper puis recoller est réversible ;
sous-découper ne l'est pas.** On garde donc la segmentation fine et on répare
après.

### Ce que cet enchaînement ignore

Deux informations disponibles et gratuites, qu'aucun étage n'utilise.

**Qui vient de parler.** Un tour de parole succède rarement à lui-même, et
presque jamais après un silence de dix secondes. Notre rattachement compare une
empreinte à des agrégats, et rien d'autre : deux phrases consécutives sont
traitées comme si l'ordre n'existait pas.

**Où la personne est assise.** Deux canaux donneraient une différence de temps
d'arrivée, qui est une mesure physique et non une ressemblance statistique. Un
micro pieuvre au centre d'une table détruit précisément cette information : il
entend tout le monde au même niveau, ce qui est confortable pour la
transcription et ruineux pour la séparation.

## 2. Ce qui existe

### Les empreintes

Le catalogue du moteur déjà installé (`sherpa-onnx`) porte vingt et un modèles
d'empreintes, dont neuf WeSpeaker et neuf 3D-Speaker. Notre TitaNet est l'un
des plus anciens du lot.

| Famille | Modèles notables | Taille |
|---|---|---|
| NeMo | titanet_large (en place), titanet_small, speakernet | 23 à 101 Mo |
| WeSpeaker | CAM++_LM, resnet34_LM, resnet221_LM, resnet293_LM | 26 à 114 Mo |
| 3D-Speaker | CAM++, ERes2Net, ERes2NetV2 | 26 à 220 Mo |

Ces modèles sont réputés meilleurs que TitaNet sur les épreuves de vérification
du locuteur. **Ce n'est pas notre épreuve** : celles-là portent sur des extraits
de plusieurs secondes, prononcés seul devant un micro. Le nôtre est un extrait
de deux secondes, dans une salle, avec du bruit et des chevauchements. D'où
`tools/compare_extractors.py`, qui mesure la seule chose qui nous importe :
l'écart entre « même personne » et « personnes différentes » sur des extraits
courts.

Aucun de ces modèles n'est entraîné sur du français. C'est moins gênant qu'il
n'y paraît : une empreinte vocale porte le timbre, pas la langue, mais cela
mérite d'être vérifié plutôt que supposé.

### Le regroupement

- **Clustering agglomératif** sur les embeddings, ce que fait sherpa et ce que
  notre recollage prolonge. Simple, sans mémoire du temps.
- **VBx / VB-HMM** (BUT Speech) : clustering bayésien variationnel avec un
  modèle de Markov caché sur la suite des locuteurs. C'est exactement
  l'information que nous ignorons, la continuité temporelle, et c'est le
  standard des meilleurs systèmes des campagnes DIHARD. **Piste la plus directe
  pour notre point faible.**
- **Multi-échelle** (NeMo MSDD) : comparer à plusieurs longueurs de fenêtre à la
  fois, de 0,5 à 3 secondes, et pondérer. Répond précisément à notre problème,
  où une fenêtre courte est bruitée et une longue enjambe deux locuteurs.

### Les approches de bout en bout

- **EEND** et ses suites traitent le chevauchement de parole nativement, ce que
  notre chaîne ne fait pas du tout : une phrase à cheval sur deux personnes ne
  désigne personne chez nous.
- **Sortformer** (NVIDIA) et **FS-EEND** visent le direct, avec une latence
  faible et un nombre de locuteurs non connu d'avance.

Ces approches remplaceraient deux de nos trois étages. Elles demandent d'être
disponibles en ONNX pour tenir dans la contrainte du projet : local, léger, sans
dépendance nouvelle, ce qui reste à vérifier.

## 3. Ce qu'il faudrait mesurer, dans cet ordre

Du moins coûteux au plus coûteux, chacun mesurable sur le corpus étiqueté que
nous avons déjà.

1. **Changer d'extracteur d'empreintes.** Une ligne de configuration, un modèle
   à télécharger, et `tools/compare_extractors.py` donne la réponse. Si la
   marge entre les deux distributions s'élargit, tous les seuils en profitent
   d'un coup.
2. **Tenir compte du locuteur précédent.** Une pénalité sur le changement de
   locuteur suffit à en avoir l'idée, avant d'envisager un VB-HMM complet.
3. **Extraire à plusieurs échelles.** Deux fenêtres au lieu d'une, moyennées ou
   pondérées. Le coût double ; il est aujourd'hui de 4,3 ms par phrase.
4. **Réviser les attributions déjà affichées.** Le fil est rejouable
   (`rejouer()`), donc c'est faisable sans toucher au reste. Personne ne l'a
   mesuré.
5. **Deux micros au lieu d'un.** À mesurer avant d'acheter : un enregistrement
   d'essai à deux points de captation dirait tout de suite ce que la différence
   de temps d'arrivée apporte.

### Comment juger

Trois chiffres, et pas un de plus, tous disponibles sur la réunion étiquetée :

- **la marge** entre le premier décile des « même personne » et le neuvième des
  « personnes différentes ». Négative, aucun seuil ne les sépare ;
- **le nombre de voix** rendues, contre le nombre de personnes présentes ;
- **la justesse des attributions**, part des phrases dans un groupe
  majoritairement juste.

Et une règle : **aucun changement de seuil sans la mesure qui l'accompagne.**
Trois des quatre seuils de ce projet ont d'abord été posés au jugé, et les trois
étaient faux.
