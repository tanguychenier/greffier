# Calibrage des seuils de reconnaissance des voix

Les seuils de `domaine/empreintes.py` ne sont pas des intuitions : ils viennent
d'une mesure. Ce document dit laquelle, pour qu'elle puisse être refaite quand
le matériel, l'acoustique ou le modèle changent.

## Méthode

```sh
.venv/bin/python outils/calibrer_seuils.py <enregistrement.wav>
.venv/bin/python outils/verifier_fusion.py <enregistrement.wav>
```

Le premier segmente l'enregistrement, extrait une empreinte par prise de parole
d'au moins 3 s, puis compare :

- **intra** — deux extraits d'une même voix : doit être élevé ;
- **inter** — deux voix différentes, empreintes agrégées : doit être nettement
  plus bas.

L'écart entre les deux distributions dicte le seuil. Une première tentative
reconstruisait les tours de parole depuis le fichier texte des locuteurs : les
extraits contenaient alors des silences, les empreintes étaient bruitées et les
deux distributions se chevauchaient presque entièrement. **Il faut partir des
bornes exactes de la segmentation.**

## Mesure du 2026-08-24

Réunion du 2026-08-20, 11,8 min, environ 6 participants, en salle, micro de
portable, un seul canal actif (aucun son système capté).

| | Médiane | Étendue |
|---|---|---|
| Deux extraits d'une **même** voix | 0,74 | 0,62 – 0,79 sur les voix bien fournies |
| Deux voix **différentes** | 0,41 | jusqu'à 0,66 |

D'où `SEUIL_RECONNAISSANCE = 0.70` : au-dessus du pire cas de voix distinctes,
au niveau du cas courant d'une même voix. La valeur de 0,55 retenue au jugé
avant cette mesure laissait passer des confusions.

## Sur-découpage et recollage

La segmentation automatique a produit **27 voix pour 6 participants**. C'est le
défaut connu de l'approche : une personne qui change de posture ou s'éloigne du
micro devient un nouveau groupe.

`fusionner_voix` recolle les groupes dont les empreintes agrégées dépassent
`SEUIL_FUSION = 0.75`, de la paire la plus évidente à la moins évidente, en
recalculant l'agrégat après chaque réunion. Sur le même enregistrement :

```
AVANT : 27 voix distinctes sur 172 segments
APRÈS : 22 voix, dont 5 avec au moins 10 s de parole

  v0      6.1 min (54.7 %)  ← recolle v8, v14, v2, v26
  v4      2.6 min (23.3 %)
  v49     0.7 min ( 6.4 %)
  v32     0.6 min ( 5.8 %)  ← recolle v10
  v17     0.5 min ( 4.1 %)

plus fort rapprochement restant : 0.645 (v17 ↔ v4)
```

Cinq voix porteuses, une répartition du temps de parole crédible, et le
rapprochement le plus fort restant tombe sous le seuil : le recollage s'arrête
au bon endroit. Cela supprime le besoin d'indiquer le nombre de participants à
la main, qui était jusqu'ici le réglage dont dépendait toute la qualité de
l'identification en présentiel.

## Seuil de clustering brut mesuré (2026-09-01)

Le seuil `threshold = 0.8` de `DiariseurSherpa` (passé à
`FastClusteringConfig`) n'avait jamais été mesuré comme le sont
`SEUIL_RECONNAISSANCE`/`SEUIL_FUSION` ci-dessus — il datait des exemples de
sherpa-onnx. Sur un jeu d'essai synthétique à trois locuteurs
(`outils/fabriquer_cas_difficiles.py --cas trois-voix`, deux timbres
proches), il fusionnait dès le clustering brut deux locuteurs distincts en un
seul, **avant même que `fusionner_voix` n'intervienne** : la segmentation ne
rendait que 2 voix pour 3 personnes, et `fusionner_voix` ne peut pas séparer
ce qui a déjà été fondu en amont.

Mesure directe (`DiariseurSherpa.decouper` isolé, hors chaîne complète), sur
deux fixtures — `deux-voix` (`outils/fabriquer_reunion.py`, référence
existante) et `trois-voix` — en balayant `threshold` :

| `threshold` | `deux-voix` | `trois-voix` |
|---|---|---|
| 0,30 | 3 voix (sur-découpe) | 3 voix (correct) |
| 0,40 – 0,50 | **2 voix (correct)** | **3 voix (correct)** |
| 0,55 – 0,88 | 2 voix (correct) | 2 voix (fusion à tort) |
| ≥ 0,90 | 1 voix (fusion à tort) | 1 voix (fusion à tort) |

Le sens du paramètre est contre-intuitif : plus il est **bas**, plus le
clustering est sensible et distingue de voix, jusqu'à sur-découper à 0,30. La
plage `[0,40 ; 0,50]` est correcte sur les deux fixtures. `threshold = 0.45`
retenu (milieu de plage). À revalider sur un enregistrement réel via
`outils/calibrer_seuils.py`/`outils/verifier_fusion.py` — cette mesure n'a
porté que sur de la synthèse vocale.

## Garde de matière avant fusion

Complément au réglage ci-dessus, pas son remplacement : `fusionner_voix`
(`domaine/empreintes.py`) fusionne deux groupes dès que leurs empreintes
agrégées dépassent `SEUIL_FUSION`, sans regarder combien de matière porte
chaque agrégat — un agrégat tiré de deux ou trois secondes est bruité, et sa
similarité avec un autre petit groupe n'est plus un signal fiable. La fonction
exige désormais, en plus du score, que le **plus grand** des deux groupes
candidats porte au moins `MATIERE_MINIMALE_FUSION = 6.0` s (deux fois
`DUREE_UTILE`) avant d'accepter la fusion. L'asymétrie est volontaire : une
voix déjà établie (`v0`, 6,1 min dans la mesure ci-dessus) continue d'absorber
des fragments minces sans contrainte nouvelle ; seuls deux petits groupes
encore fragiles ne peuvent plus se fondre entre eux sur un hasard statistique.
Valeur de départ, à revalider par la même méthode que ci-dessus.

## Limites connues

- Le modèle d'empreintes est `nemo_en_titanet_large`, entraîné sur de l'anglais.
  Il fonctionne sur des voix françaises — le timbre dépend peu de la langue —
  mais un modèle multilingue serait préférable.
- Une seule réunion mesurée, en salle. Les seuils doivent être revérifiés sur
  de la visio, où le signal est bien plus propre et où les valeurs intra
  devraient monter.
- Les voix totalisant moins de 10 s de parole restent éclatées : trop peu de
  matière pour une empreinte stable. Elles doivent être présentées comme
  indéterminées plutôt que comme des participants.
