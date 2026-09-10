# Le workflow de publication, à mettre en place à la main

`publier.yml.a-mettre-en-place` est le workflow qui fabrique un artefact par
système et l'attache à chaque publication. Il n'est **pas** en place.

## Pourquoi il n'y est pas

Un jeton OAuth sans le droit `workflow` ne peut ni créer ni modifier un fichier
sous `.github/workflows/`, et GitHub refuse le push entier :

    refusing to allow an OAuth App to create or update workflow
    `.github/workflows/publier.yml` without `workflow` scope

Le mettre en place demande donc un geste depuis un compte qui en a le droit :

```sh
git mv outils/publier.yml.a-mettre-en-place .github/workflows/publier.yml
git commit -m "ci: publier un artefact par système à chaque version"
git push
```

## Ce qu'il fait, et ce qu'il ne fait pas

Il n'a **jamais tourné** au moment d'écrire ces lignes : les exécuteurs de
GitHub sont le seul banc d'essai Windows du projet, et il faut l'avoir poussé
pour les atteindre. Ce qui suit est donc une intention, pas une mesure.

- **macOS** : le paquet que `construire.sh` produit déjà. Signé **ad hoc** sur
  l'exécuteur, faute du certificat du poste de développement : Gatekeeper le
  refusera au premier lancement, et il faudra un clic droit puis « Ouvrir ». Le
  résoudre demande un Developer ID et une notarisation, donc un compte payant et
  une décision qui n'est pas prise.
- **Windows** : un dossier avec un `.exe`, par PyInstaller, autour de
  `outils/lanceur_windows.py`. Jamais lancé sur une vraie machine Windows :
  seul `--version` a été éprouvé, et depuis un Mac.
- **Linux** : l'arbre des sources et son installeur. Un AppImage serait plus
  commode, et reste à faire.

Le but visé est le double-clic. Que l'installeur télécharge ensuite les modèles
est normal : 1,7 Go de whisper et la voix de l'assistant ne tiennent pas dans
une pièce jointe.
