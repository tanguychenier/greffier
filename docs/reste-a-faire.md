# Ce qui reste à faire

État au 2026-09-01, après la correction des trois derniers défauts du
diagnostic initial (segmentation, proposition perdue, texte du direct).

Les huit lots de portage sont faits depuis le 25 août. Ce document ne liste plus
qu'une chose : **ce que l'usage a cassé, ce qui a été corrigé, et ce qui reste
ouvert.** L'historique des lots est dans `git log` ; le répéter ici ne servait
plus.

## Ce que la première réunion réelle a appris

Une heure d'échange, quatre personnes. Le compte rendu est sorti, et il était
faux sur plusieurs points. Chaque défaut ci-dessous a été mesuré sur cet
enregistrement, pas supposé.

| Défaut | Ce qu'il coûtait | État |
|---|---|---|
| Le mixage des canaux avant la segmentation | **13 min de parole absentes** du compte rendu, et le document affirmait que la personne n'avait pas parlé | corrigé |
| Le modèle inventait des phrases sur signal faible | « Merci d'avoir regardé cette vidéo ! » là où la personne disait « Test, test de réunion » | corrigé |
| Un nom appuyé sur des interpellations seules devenait ferme | Le prénom d'un absent attribué à la voix qui tenait 64 % du temps de parole | corrigé |
| Tout mot capitalisé était candidat prénom | « Ouais » promu prénom, avec 13 min de temps de parole | corrigé |
| Le courriel partait en MacRoman, en Markdown brut | Tout compte rendu français arrivait en `r√©union` | corrigé |
| L'envoi sauté sans un mot, et l'icône affichait « Compte rendu envoyé » | Rien n'était parti, l'interface affirmait le contraire | corrigé |
| Le compte rendu parlait de l'outil | 31 % du document sur la plomberie, 9 % sur les décisions | corrigé |
| Le matériel changeant en cours de réunion | Un casque branché en route et la voix de qui enregistre est perdue | corrigé |
| Trois réglages à faire à la main | Sortie système, micro, gain : sans eux les canaux système restaient muets | corrigé |
| La couverture faible n'alertait personne | 22 % de l'audio sans texte, passé en silence | corrigé |
| L'icône aveugle pendant un retraitement | Quinze minutes affichant la phase précédente | corrigé |
| Rien ne s'affichait pendant la réunion | Une attribution fausse ne se voyait qu'au compte rendu, une heure trop tard | corrigé |
| `greffier assister` visait le fichier recollé, qui n'existe qu'après l'arrêt | Il ne transcrivait **rien**, et personne ne s'en apercevait puisque rien n'affichait son travail | corrigé |
| Rien ne lançait `assister` | La commande existait, la fenêtre ne lançait que la veille du matériel | corrigé |

Détail et mesures dans les messages de commit, qui portent chacun le chiffre
qui a motivé le changement.

## Ce que le direct a appris

Le fil affiché pendant la réunion a été éprouvé sur une visio synthétique de
30 s, trois canaux, rejouée en temps réel — donc à travers la vraie commande, le
vrai découpage en tranches et les vrais modèles. Chaque défaut ci-dessous y a
été **mesuré**, et corrigé.

| Défaut | Ce qu'il coûtait | État |
|---|---|---|
| La tranche transcrite sans mise à niveau des canaux | **Une question sur six n'était pas transcrite du tout** — celle de la personne au micro, 6 dB sous la boucle. Le même défaut que le mixage d'origine, reproduit dans le direct | corrigé |
| La dédoublonnage sur le seul début de phrase | Une phrase perdue sur six : la même est datée 13,60 dans une tranche et 12,80 dans la suivante | corrigé |
| L'empreinte prélevée sur le bloc entier | 0,6 s de voix locale en tête d'un extrait de 1,5 s suffisait à faire de la même personne deux participants, et une correction ne se propageait pas | corrigé |
| Le verdict visio recalculé à chaque tranche | Sur une tranche où seule la personne au micro parle, aucune boucle ne domine : sa voix devenait un participant distant de plus | corrigé |
| Le seuil d'apprentissage à 6 s, sans seconde chance | Une correction saisie à la deuxième phrase n'entrait **jamais** en banque : elle s'affichait, puis ne servait ni à la réunion suivante ni au compte rendu | corrigé |
| La position suivie sur l'horloge de la réunion | Après une pause, l'horloge et l'audio écrit divergent de tout le temps d'arrêt, et ffmpeg lisait au-delà de la fin du fichier | corrigé |
| Les dernières secondes jamais lues | On finissait sa phrase devant un fil qui s'arrêtait avant elle | corrigé |

## Ce que la mesure directe a corrigé (2026-09-01)

Les trois derniers défauts du diagnostic initial, mesurés cette fois avec les
modèles présents et non plus seulement supposés à partir des symptômes.

| Défaut | Ce qu'il coûtait | État |
|---|---|---|
| Le seuil de clustering brut jamais mesuré (`threshold=0.8`) fusionnait deux voix dès la segmentation | Sur un jeu d'essai à trois locuteurs, 2 voix trouvées au lieu de 3, avant même que le recollage du domaine n'intervienne | corrigé — `threshold=0.45`, mesuré et documenté dans `docs/calibrage.md` |
| `fusionner_voix` fusionnait des agrégats trop peu fournis | Deux petits groupes récents franchissaient `SEUIL_FUSION` par accident statistique | corrigé — garde de matière asymétrique, `MATIERE_MINIMALE_FUSION` |
| `voix_a_nommer` écartait toute voix de moins de dix secondes, proposition comprise | Un prénom détecté dans une réponse brève ne s'affichait jamais — ni dans l'écran de nommage, ni dans le résumé CLI | corrigé — une voix courte qui porte déjà un nom ou une proposition échappe au filtre |
| Le texte du direct dupliquait la fin d'une phrase à la frontière de deux tranches | « dernier. » puis « dernier. Sandy, tu peux nous dire… » : le locuteur était juste, le texte non | corrigé — `retirer_repetition`, recouvrement mot à mot entre deux tranches |

Tests : cas synthétiques `trois-voix` et `proposition-breve` rejoués à travers
la vraie chaîne (`tests/integration/test_cas_difficiles.py`), et un test
déterministe du direct à travers `Veilleur → Suivi.accueillir → Fil`
(`tests/application/test_veiller.py`), doublure uniquement sur le port
`Transcripteur`.

## Nommer une voix régénère maintenant le compte rendu (2026-09-01)

`voix_a_nommer` et le fichier maître ne perdaient rien, mais rien ne rejouait
la rédaction : il fallait relancer tout le traitement — segmentation et
transcription comprises — pour qu'un compte rendu porte les bons noms.

`rendre_transcription` est sortie de `Traitement` pour devenir une fonction
libre dans `application/restituer.py`, aux côtés des fonctions d'en-tête
qu'elle complète : `ReunionEnregistree` (le fichier maître relu du disque)
satisfait le même protocole `Transcrite` que `Resultat`, sans conversion.
`regenerer_compte_rendu(reunion, redacteur)` rejoue uniquement cette étape.
`evenements_materiel` (ce que la veille du matériel a constaté) est
maintenant persisté dans le fichier maître, sans quoi la régénération aurait
rendu le compte rendu moins fiable que l'original.

Branchée à trois endroits : `greffier voix --nommer`, `--accepter-propositions`,
et la relance interactive après `greffier traiter` ; côté fenêtre, dans un fil
séparé (le rédacteur peut appeler une API distante) sur le modèle déjà en
place pour « traiter » et « envoyer ».

## La fenêtre ne s'annonce plus « python3 » sur macOS (2026-09-01)

`Contents/MacOS/Greffier` est maintenant une copie de l'interpréteur du venv,
pas un script qui l'appelle — c'est l'exécutable réellement lancé qui donne
son nom au Dock et à la barre de menus, jamais `argv[0]`. Le déplacer hors de
son venv lui faisait perdre son environnement (`@rpath/libpython3.13.dylib`
introuvable, `import numpy` en échec) : deux réglages suffisent à le lui
rendre, tous deux calculés par `macos/construire.sh` à partir de
l'interpréteur lui-même, jamais devinés :

- un lien symbolique `Contents/lib` vers `sys.base_prefix` (là où vivent la
  bibliothèque standard et le `.dylib`, pas le venv) ;
- `PYTHONPATH`, posé par `LSEnvironment` dans `Info.plist`, vers les paquets
  du venv et `src/`.

macOS lance l'exécutable du paquet sans argument : `lanceur_sitecustomize.py`
(chargé automatiquement par le mécanisme `site` de Python, via `PYTHONPATH`)
tient lieu du `python -m greffier fenetre` qu'appelait l'ancien script. Piège
mesuré au passage : un `sys.exit()` qui s'échappe de `sitecustomize` — un
module chargé par `site`, pas un script — n'est pas traité comme une sortie
propre par l'interpréteur, qui l'annonce comme une « Fatal Python error » ;
`os._exit()` évite le problème.

Vérifié en construisant et lançant réellement le paquet sur ce Mac : la barre
de menus affiche « Greffier », confirmé par une capture d'écran, par
`osascript` (nom du process, fenêtre présente) et par le journal système
unifié (chaque ligne porte `Greffier[pid]`, pas `python3[pid]`).

## Le paquet macOS ne trouvait ni claude ni ffmpeg (2026-09-01)

Défaut trouvé en cliquant réellement « Demander » (onglet Conversation) et
« Écouter » (onglet Voix) dans l'app construite plus haut — pas en se
contentant d'ouvrir la fenêtre. Deux erreurs : « claude » introuvable dans le
PATH pour la rédaction, `[Errno 2] No such file or directory: 'ffmpeg'` pour
l'extrait audio, alors que les deux sont installés et fonctionnent en ligne de
commande.

Cause : macOS lance un paquet `.app` avec un PATH minimal
(`/usr/bin:/bin:...`), pas celui du shell — ni Homebrew, ni `~/.local/bin` n'y
figurent. Premier correctif posé, insuffisant : `construire.sh` mettait `PATH`
dans `LSEnvironment`, à côté de `PYTHONPATH`. Rejoué en vraie condition
(relancé depuis le Launchpad, pas juste `open` en terminal) : `PYTHONPATH`
arrive intact sur le process, `PATH` non — retombé sur le minimum
(`/usr/bin:/bin:/usr/sbin:/sbin`), constaté via `ps eww` sur le process réel.
`LSEnvironment` n'est donc pas fiable pour `PATH` précisément, pour une raison
qui reste à comprendre (macOS semble le réimposer après coup).

Correctif retenu : `PATH` n'est plus confié à `LSEnvironment`, mais fixé en
Python dans `lanceur_sitecustomize.py` (`os.environ["PATH"] = ... +
os.environ.get("PATH", "")`) — là, rien d'autre ne peut plus l'écraser.
`construire.sh` génère ce fichier à partir d'un gabarit (`macos/lanceur_sitecustomize.py`
dans le dépôt, un espace réservé remplacé par le PATH mesuré sur la machine
qui construit le paquet — toujours mesuré, jamais deviné, ni ffmpeg ni claude
n'ayant d'emplacement fixe d'une machine à l'autre).

Spécifique à macOS : Linux et Windows n'ont pas encore d'icône de bureau,
`greffier fenetre` s'y lance depuis un terminal qui a déjà le vrai PATH — rien
à corriger côté code multiplateforme.

Vérifié en relançant réellement l'app (Launchpad, pas un raccourci de test) et
en relisant `PATH` du process avec `ps eww` : il porte maintenant Homebrew et
`~/.local/bin`. Effet secondaire à surveiller : reconstruire l'app plusieurs
fois de suite pendant les essais a fait ressurgir l'alerte macOS « éditeur
inconnu » à chaque fois (la signature ad hoc change à chaque reconstruction) —
gênant pendant un test, sans rapport avec le défaut lui-même.

## Ce qui reste ouvert

### Les premières phrases peuvent manquer le « Toi »

Le verdict visio se lit sur l'écart entre les canaux : tant que personne d'autre
n'a parlé, il n'y a rien à comparer, et la première prise de parole peut
s'afficher comme une voix à nommer plutôt que « Toi ». Une fois le verdict
établi il tient jusqu'au bout, donc cela ne concerne que le tout début — et un
clic le corrige. Rejuger les tours déjà inscrits demanderait de garder les
tranches, ce qui n'a pas paru valoir le coût.

### L'interface reste austère

Premier passage fait le 2026-09-01 : la fenêtre changeait de taille à chaque
changement d'onglet (`racine.geometry()` posée une fois pour toutes le
corrige — `pack` calculait sinon la taille du parent d'après le seul enfant
affiché) ; deux listes (Réunions, Voix) n'avaient **aucun** ascenseur, sans
qu'il manque, le contenu au-delà de la première poignée de lignes restait
simplement inaccessible ; les deux `Text` qui en avaient un utilisaient
l'ascenseur natif de Tk (gris, à bords carrés), hors de la palette du reste de
la fenêtre. Un `Defileur` dessiné (`interface/apparence.py`) remplace les deux
et couvre les deux listes qui n'en avaient pas ; les cartes portent désormais
une ombre légère (deux cadres dans la même cellule de grille, décalés de
quelques pixels, plutôt qu'un `Canvas` qui aurait cassé la remontée de taille
depuis le contenu).

Vérifié en pilotant la vraie fenêtre depuis un script (`Onglets.montrer(...)`
appelé directement, capture d'écran après chaque onglet) plutôt qu'en
simulant des clics à l'aveugle sur des coordonnées écran — trop fragile,
essayé d'abord, abandonné.

Ce qui reste : Tkinter a un plafond réel (pas de CSS, pas de vraie
transparence, un `Canvas` par forme non standard) — un rendu au niveau d'une
interface web moderne n'est pas atteignable avec cette boîte à outils. Ce qui
a été fait retire les deux défauts concrets signalés (redimensionnement,
ascenseurs manquants ou moches) ; l'austérité qui reste au-delà est une
question de goût, à affiner point par point plutôt que par une itération
sans fin.

## Ce qui n'est pas à faire

- **Le commit `wip` ne sera pas réécrit.** Contrairement à ce que disait la
  version précédente de ce document, il n'est pas orphelin : c'est un commit
  ordinaire de l'historique de `main`, entre `d7b65df` et `78c0bf2`, portant
  595 lignes de l'installeur. Le renommer imposerait de réécrire un historique
  que plusieurs personnes clonent désormais. Un message pauvre ne vaut pas ça.
- **Le démon local (FastAPI) reste écarté.** Le fichier d'état suffit, et la
  fenêtre le lit comme le faisait l'icône.
- **La visibilité du dépôt reste privée.** Les quatre contributeurs ont un accès
  nominatif en *Developer* ; passer en *Internal* n'a d'intérêt que pour ouvrir
  la lecture à toute l'école.

## Ce qui n'a jamais été éprouvé

Ces points fonctionnent en théorie et n'ont pas rencontré le réel.

- **Un branchement physique en cours de réunion.** L'adaptation au matériel est
  éprouvée sur 35 scénarios et par deux reprises simulées, jamais en débranchant
  un vrai casque pendant une vraie réunion.
- **Le direct en réunion réelle.** Éprouvé sur une visio synthétique rejouée en
  temps réel, et sur une seule voix distante. Le coût en calcul d'une heure à
  quatre personnes, et le comportement quand deux personnes se coupent
  réellement, n'ont pas rencontré le réel.
- **Le direct en présentiel**, en réunion réelle. La chaîne, elle, est
  désormais éprouvée sur une réunion de table synthétisée : voir plus bas.

## Le présentiel est éprouvé, et il a trouvé un défaut (2026-09-03)

Tout ce qui avait servi jusqu'ici était une visio, où le canal identifie avec
certitude la personne qui enregistre. Autour d'une table, tout le monde parle
dans le même micro : la provenance ne désigne plus personne. Le cas est
maintenant tenu par une preuve rejouable.

Le fichier d'essai (`outils/fabriquer_reunion.py --presentiel`) est **stéréo**,
comme ce que rend le périphérique : trois voix de synthèse sur le micro, et sur
la boucle système la fuite mesurée sur la vraie réunion de table, -53 dB au lieu
du silence attendu. Un second canal muet aurait rendu l'épreuve trop facile :
c'est précisément cette fuite qui faisait conclure « visio » à tort.

### Ce que la mesure confirme

| Vérification | Mesuré |
|---|---|
| Verdict de canal | `en_visio` rend faux ; fuite à -50,5 dB de crête pour un micro à -21,7 dB de médiane |
| Le micro sert de référence aux deux canaux | `distante` faux, `systeme` identique au micro |
| Passages déclarés locaux | **aucun** — le canal ne désigne personne, et personne n'est étiqueté « moi » |
| Participants | plusieurs voix, jamais fondues en une seule |
| Auto-présentation | « moi c'est Jacques » désigne toujours celui qui parle |

### Le défaut : une phrase à cheval était donnée au plus bavard

`_attacher_voix` donnait chaque réplique à la voix qui parlait le plus pendant
sa durée. La transcription coupe à la phrase, la segmentation au changement de
locuteur : quand une réplique **enjambe** un changement, le plus bavard
emportait les mots de l'autre. En visio, `soustraire` rattrapait le cas grâce au
canal ; en présentiel, rien ne protégeait.

Mesuré sur la réunion de table : « Merci Pierre. On garde donc jeudi… », dit par
Jacques, attribué à Pierre — la réplique couvrait 9,6 s du tour de Pierre pour
6,1 s de celui de Jacques, soit 0,61 pour le meneur.

Corrigé par `domaine/attribution.py` : sous une part de 0,80, la réplique ne
désigne **personne**. Elle garde son texte et son horodatage, elle n'attribue
plus à tort — la règle déjà retenue pour une banque de voix qui se contredit.

Le seuil est mesuré, pas choisi : sur 29 répliques de cinq réunions
synthétisées, 26 tiennent 0,98 ou plus (24 à 1,00 exactement) et les 3 qui
enjambent un changement de locuteur tiennent 0,50, 0,52 et 0,61. Rien entre
0,62 et 0,97 ; le seuil est posé au milieu de cette bande vide.

### Ce que la preuve ne mesure pas

La qualité de la transcription. Les voix de synthèse rendent un texte
approximatif — la même réplique donne « L.S. Dominé, Depuis, I.S.W.A. » d'une
voix à l'autre, et la voix « Rocko » est purement et simplement ignorée par le
détecteur de parole de whisper. Un test qui les comparerait mesurerait `say`, pas
Greffier. Les assertions ne portent donc que sur ce qui ne dépend pas du timbre.

## L'envoi SMTP et la fenêtre hors macOS sont éprouvés (2026-09-03)

Deux promesses tenaient sur de la documentation, pas sur une exécution.

### SMTP, contre de vrais serveurs

Le code disait lui-même n'avoir « pas encore rencontré un vrai serveur ». Un
serveur d'essai monté dans le processus n'y aurait rien changé : il répond ce
qu'on lui a appris à répondre. `tests/integration/test_smtp_vrais_serveurs.py`
**se connecte** — `smtp.gmail.com` en 465 et en 587, `smtp.office365.com` en
587, les deux fournisseurs que le commentaire du code nommait.

Ce qui est éprouvé, sur les trois : la connexion aboutit (`NOOP` à 250), la
session est chiffrée (`ssl.SSLSocket`, version TLS), et le serveur annonce
`AUTH` — donc il a bien vu un client chiffré et se tient prêt à recevoir un mot
de passe. Se tromper de convention n'arrive jamais jusque-là : un `SMTP` nu sur
465, ou un `SMTP_SSL` sur 587, échoue au premier octet.

Aucun mot de passe n'est nécessaire, donc rien n'est authentifié ni expédié :
envoyer un courriel chez un tiers depuis une suite de tests n'est pas une
preuve, c'est un courriel de trop.

Pour que cela soit possible, `ExpediteurSmtp` expose deux coutures :
`message()` compose le courriel sans rien ouvrir — ce qu'un destinataire reçoit
se vérifie donc **sans réseau** (`tests/test_courriel_smtp.py` : sujet accentué
entier, double version du corps, pièce jointe, texte en UTF-8) — et `session()`
ouvre la connexion. `envoyer()` n'est plus que l'assemblage des deux.

Un défaut corrigé au passage : la session n'était complète qu'au moment
d'expédier. RFC 3207 demande de resaluer après STARTTLS, les capacités
annoncées en clair ne valant plus ; `smtplib` le fait à la demande, `session()`
le fait maintenant à l'ouverture, `AUTH` compris.

### La fenêtre s'ouvre sous Linux

`outils/preuve-fenetre-linux.Dockerfile` construit une image Debian trixie nue,
y pose `python3-tk` — la seule dépendance système de l'interface, exactement la
ligne du README — et ouvre la vraie fenêtre sous `xvfb`. Mesuré : **Tk 8.6 /
Tcl 8.6**, fenêtre 880x660, **cinq onglets peints sans exception**.

Debian plutôt que l'image `python:3.13-slim` : cette dernière compile son
interpréteur sans Tk, et le `python3-tk` de Debian s'adresse au python de
Debian. Aucun modèle n'est téléchargé — ouvrir la fenêtre n'en demande aucun —
donc l'image se construit en quelques minutes, là où la preuve d'installation en
prend dix.

### Le défaut trouvé au passage : la fenêtre ne s'ouvrait pas depuis le dépôt

`.venv/bin/greffier` échouait sur « This probably means that Tcl wasn't
installed properly ». L'interpréteur distribué par uv porte le chemin de la
machine qui l'a compilé : Tk cherchait `init.tcl` dans `/tools/deps/lib/tcl9.0`,
qui n'existe sur aucun poste, alors que Tcl est là, à côté de l'interpréteur.
Le paquet macOS n'avait jamais rencontré le défaut : il embarque ses propres
copies.

`situer_tcl()` — dans `emplacements.py`, avec les autres chemins, parce que
`fenetre.py` importe Tk et qu'aucun exécuteur d'intégration continue ne le
démarre — pose `TCL_LIBRARY` et `TK_LIBRARY` depuis `sys.base_prefix` quand
elles sont vides, et ne touche à rien sinon — un poste dont le Tk vient du
système garde le sien. La fenêtre s'ouvre désormais des deux façons, et
`outils/preuve_fenetre.py` sert la preuve sur les deux systèmes.

## Second passage sur l'interface, capture en main (2026-09-03)

Le premier passage avait retiré les deux défauts signalés (redimensionnement,
ascenseurs). Celui-ci part des captures des cinq onglets, prises en pilotant la
vraie fenêtre, et ne retient que ce qui est vérifiable — pas des questions de
goût.

| Défaut | Ce qu'il coûtait | État |
|---|---|---|
| Les lignes de continuation du direct repartaient contre la marge | Une réplique longue redescendait sous l'heure et le nom : l'œil perdait la colonne du texte, sur le seul onglet qu'on regarde pendant une réunion | corrigé — `lmargin2` à 90 px, la largeur mesurée de l'heure et du nom |
| Le champ de nommage des voix n'avait **aucun** intitulé | Un rectangle gris à côté d'un bouton « Nommer » : rien ne disait qu'on y tape un prénom, et non le numéro de la voix | corrigé — intitulé « Prénom » |
| Les listes gardaient le cadre de « clam » | Un liseré vert-de-gris à angles droits contre des boutons et des listes déroulantes dessinés : la « pièce étrangère » déjà retirée aux menus revenait par les listes. `borderwidth=0` n'y fait rien, le cadre vient des trois couleurs de l'élément `Treeview.field` | corrigé — `bordercolor`, `lightcolor` et `darkcolor` au fond de la carte |
| Deux formulations pour la même valeur de micro | « automatique (le mieux entendu) » en tête de fenêtre, « Automatique — le mieux entendu au démarrage » dans les Réglages : le même choix paraissait être deux réglages différents | corrigé — une seule formulation |
| « Micro » comme intitulé de ligne sous un bloc « Micro » | Répétition sans information, quand la ligne devrait nommer ce qu'on choisit | corrigé — « Appareil » |

Ce qui reste, et qui ne sera pas poursuivi ici : l'état vide des listes (des
en-têtes au-dessus de rien, sans un mot) et l'austérité générale, qui tient au
plafond de Tkinter.

## Le paquet macOS est autonome et signé de façon stable (2026-09-02)

Constat d'usage : « ça n'arrête pas de demander des droits ». Trois causes,
chacune vérifiée sur l'application installée, pas supposée.

| Cause | Ce qu'elle coûtait | État |
|---|---|---|
| Signature **ad hoc** (`codesign --sign -`) : l'identité de l'application est le hachage de son binaire | Chaque reconstruction en faisait une application inconnue — micro et Outlook redemandés, le garde du poste aussi | corrigé — signée avec une identité stable (`macos/identite-de-signature.sh`) : un certificat Apple du trousseau, sinon un certificat local créé une fois |
| Paquet **non autonome** : `Contents/lib` liait `~/.local/share/uv/…`, `PYTHONPATH` visait le `.venv` du dépôt | Chaque lancement et chaque processus auxiliaire (veille, direct) lisaient des dossiers cachés que le garde du poste conteste ; le 1er septembre, une écriture refusée (`Operation not permitted`) a arrêté le direct en pleine réunion | corrigé — interpréteur, bibliothèque standard, dépendances et code copiés dans le paquet (mesuré : 56 Mo + 181 Mo), plus rien ne pointe hors de `/Applications` |
| L'installeur gardait **ses propres chemins XDG** (`~/.local/share/greffier`, `~/.config/greffier`) alors que l'application avait déménagé dans Application Support | Relancé, il aurait cherché les modèles au mauvais endroit et retéléchargé 1,6 Go dans un dossier caché ; la configuration restait dans `~/.config` | corrigé — une seule définition, `greffier/emplacements.py`, sans dépendance, lue par l'installeur comme par l'application ; l'installeur déménage ce qui traîne |

Mesuré au passage : la signature ad hoc ne prend pas non plus les bibliothèques
natives en compte, et un certificat auto-signé importé sans confiance explicite
n'est pas vu par `codesign` (« 0 valid identities ») — d'où le passage par
`security add-trusted-cert`, qui demande le mot de passe de session une fois.

Ce qu'il en coûte : une modification du code ne se voit dans l'application
qu'après reconstruction. C'est le comportement d'un logiciel installé ;
`.venv/bin/greffier` suit le code pour développer.

Les autorisations que macOS demande **une fois** à la première utilisation
(micro, automatisation d'Outlook) restent : aucune application n'y échappe. Ce
qui disparaît, c'est leur retour à chaque reconstruction.

### Mesuré dans le fichier de règles du garde, pas déduit

Le fichier de règles du garde garde une ligne par
autorisation accordée : chemin protégé, programme, identité du programme,
horodatage. Il porte donc l'historique exact des dialogues subis.

| | Avant | Après |
|---|---|---|
| Règles écrites pour Greffier pendant une seule réunion (2026-09-01) | **174** | — |
| Identités différentes du même binaire ce jour-là | **10** | — |
| Règles écrites après une reconstruction et une relance | — | **0** |
| Règles écrites par une chaîne complète, réunion traitée de bout en bout | — | **2** |

Dix identités pour un seul programme en une journée : c'est la signature ad hoc,
refaite à chaque reconstruction. Le garde voyait dix programmes inconnus et
redemandait pour chacun. Les 171 règles portant sur `~/.local/` disent l'autre
moitié du problème.

Après correction, le binaire est identifié par l'**équipe du certificat**
(`QULSPZ72V4`), plus par un condensat : une seule règle, sur `~/Library/`. Les
deux règles restantes ne concernent pas les données de Greffier mais le fichier
de configuration de Claude Code (`~/.claude.json`), accédé par le rédacteur.

### Ce qui a été éprouvé, et ne demande plus rien

Une réunion de synthèse de 45 s, deux voix, passée **par l'exécutable du
paquet** — donc avec la même filiation de processus qu'un double-clic, ce que
le garde prend en compte. Segmentation, transcription, identification des voix,
rédaction, envoi : aboutis. Puis, séparément, les deux auxiliaires qui tournent
en boucle pendant une réunion : le listeur de périphériques du paquet, trois
découpes `ffmpeg` et une transcription `whisper-cli`, tous lisant et écrivant
dans Application Support. **Aucune règle nouvelle, donc aucun dialogue.**

### Le chemin du rédacteur doit être stable, pas seulement présent

Le garde retient le chemin du programme tel qu'il le voit, sans résoudre les
liens symboliques. Un outil installé par Homebrew vit sous
`/opt/homebrew/Caskroom/<outil>/<version>/` : le chemin change à chaque mise à
jour, la règle accordée meurt avec l'ancienne version, et le dialogue revient —
en pleine réunion pour `claude`, qui rédige le compte rendu. Le même outil sous
`~/.local/bin` est un lien de nom fixe, que les mises à jour ne déplacent pas.

`macos/construire.sh` place donc `~/.local/bin` **en tête** du PATH gravé dans
le paquet. Mesuré : le paquet rédigeait avec le Claude Code 2.1.195 du Caskroom
alors que le 2.1.258 était installé sous `~/.local/bin` ; après correction il
prend le second, et la régénération d'un compte rendu n'écrit aucune règle.

## On règle depuis la fenêtre, et le modèle du rédacteur est un choix (2026-09-02)

La configuration était **lue** de trois sources et modifiable seulement à la
main ou par l'assistant, qui écrivait un `.env`. Régler son micro demandait
d'ouvrir un fichier — pour un outil dont la promesse est « on installe et ça
marche », c'était le dernier accroc.

`greffier/reglages.py` sait désormais **écrire** `config.toml`, au même endroit
que celui d'où le reste de la chaîne lit : deux fichiers qui se contredisent
valent moins que pas de fichier du tout. Le fichier est régénéré, commentaires
compris, donc ceux-ci ne mentent jamais sur le réglage voisin ; la version
précédente est conservée en `config.toml.precedent`. Écriture atomique, parce
qu'on enregistre pendant qu'une réunion peut tourner et qu'un processus
auxiliaire lisant un fichier à moitié écrit s'arrêterait sur une erreur de
syntaxe.

L'onglet **Réglages** propose micro, modèle de transcription et langue,
rédacteur et son modèle, destinataire, direct, apparence. Ce qui est une liste —
vocabulaire, mots qui ne sont jamais des prénoms — reste au fichier : un
formulaire les tronquerait. `chemins` n'est délibérément jamais écrit : les
figer est précisément ce qui faisait lire l'ancien dossier à un poste déménagé.

| Défaut | Ce qu'il coûtait | État |
|---|---|---|
| Le formulaire dépassait la fenêtre, sans ascenseur | Rédaction et apparence **hors d'atteinte**, sans rien qui l'indique — constaté en capture d'écran | corrigé — `Canvas` défilant, molette liée à tous les enfants sauf les listes déroulantes, qui la gardent pour changer de valeur |
| Le thème n'était pas un réglage | La fenêtre suivait le système, sans recours | corrigé — `apparence.theme` : `systeme`, `clair` ou `sombre` |
| Le modèle du rédacteur n'était jamais demandé | Claude Code suivait le réglage personnel de qui l'a installé : le compte rendu changeait de rédacteur sans décision, et pouvait consommer le haut de gamme | corrigé — `--model` explicite, **`opus` par défaut** |

**Pourquoi le second de la gamme.** Rédiger depuis une transcription déjà
découpée et attribuée est de la synthèse, pas du raisonnement long. Le premier
rend le même document en entamant un quota bien plus vite : une réunion par jour
suffit à le sentir. Le réglage reste offert dans les deux sens, et l'assistant
d'installation pose la question, abonnement Claude vérifié d'abord.

Mesuré : formulaire de 676 px dans une zone de 170 px à la taille minimale de
fenêtre, entièrement atteignable au défilement ; aller-retour d'écriture et de
relecture fidèle sur les sept sections, accents et guillemets compris ; une
écriture qui échoue laisse le fichier en place intact.

## Un skill pour réparer, puisque le rédacteur est Claude Code (2026-09-02)

Greffier dépend d'une instance Claude Code authentifiée. C'est donc vers elle
qu'on se tourne quand un maillon lâche — et sans rien à lire, elle tâtonne :
elle ne peut pas deviner que les données vivent dans Application Support et non
dans un dossier caché, que la signature du paquet doit rester stable, ni que le
modèle par défaut est le second de la gamme à dessein.

`skills/greffier/SKILL.md` porte ce savoir : commencer par `greffier
diagnostic`, où sont les journaux et l'état, symptôme par symptôme ce qu'il
signifie, les deux pièges du garde du poste avec la commande qui les mesure, et
les trois contrôles à passer avant de proposer un correctif. L'installeur le
copie dans `~/.claude/skills/greffier/` — une copie et non un lien, le dépôt
pouvant être déplacé — et ne le pose pas si Claude Code est absent.

## Les réglages s'appliquent seuls, et le compte Claude se voit (2026-09-02)

Trois défauts signalés à l'usage dans l'heure qui a suivi la livraison de
l'onglet, tous les trois réels.

| Défaut | Ce qu'il coûtait | État |
|---|---|---|
| Le bouton « Enregistrer » vivait **dans** la zone défilante | Il descendait sous le bord de la fenêtre : on changeait le thème, aucun bouton n'était visible, **rien n'était écrit** — vérifié, `config.toml` n'avait pas bougé depuis la veille | corrigé — plus de bouton du tout |
| Un bouton d'enregistrement en pied de formulaire | Mauvais motif : un panneau de réglages s'applique en direct, comme celui du système | corrigé — chaque liste, case et champ enregistre de lui-même ; les deux champs de saisie au moment de les quitter ou de valider, jamais à la frappe, sinon une adresse courriel produirait vingt fichiers et autant de sauvegardes |
| Le thème n'était appliqué qu'« au prochain lancement » | Le réglage paraissait ne rien faire | corrigé — la fenêtre est repeinte sur le champ |
| Rien ne montrait ni ne gérait le compte Claude | C'est lui qui rédige : sans session, tout marche sauf le compte rendu, et l'échec n'arrive qu'après la transcription | corrigé — bloc **Compte Claude** : version, adresse, organisation, formule, et trois actions |

**Repeindre sans relancer.** Les couleurs sont lues à la construction de chaque
composant, plusieurs les dessinant eux-mêmes sur un canevas : changer de thème
demande donc de reconstruire l'intérieur de la fenêtre. Ce qui porte l'état ne
bouge pas — la capture vit dans un processus séparé, la veille et le direct
aussi, le fil affiché se relit du journal. Deux pièges mesurés au passage : le
repeint est différé après le retour de l'événement, sans quoi la liste
déroulante qui vient d'être choisie serait détruite au milieu du traitement de
son propre événement ; et `Vumetre._pas`, réarmé toutes les 30 ms, vérifie
désormais que son canevas existe encore, sinon chaque pas restant lèverait une
`TclError` dans la boucle de Tk. Éprouvé sur la vraie fenêtre, dans les deux
sens : `#f5f5f7` → `#1a1a1d` → `#f5f5f7`, onglet conservé, confirmation
d'enregistrement reportée sur la ligne d'état neuve.

**Se connecter ouvre un terminal.** La connexion est interactive : navigateur,
puis code à coller. Rien de cela ne se pilote depuis une fenêtre Tk, et il ne
faut pas essayer. Un fichier `.command` ouvert par `open`, plutôt qu'un
`osascript` qui pilote Terminal : le second réclamerait l'autorisation
« Automatisation », soit un dialogue système de plus pour le même résultat.

`diagnostic.compte_claude()` lit le fichier de session, jamais le réseau :
l'onglet l'affiche à chaque ouverture, et un appel distant y ferait attendre
pour rien. Aucun jeton n'est lu, seulement de quoi reconnaître le compte —
un test le vérifie.

## L'interface passe une revue, et la langue n'est plus un champ libre (2026-09-02)

Quatre remarques d'usage, dont trois se mesurent plutôt qu'elles ne se jugent.

| Défaut | Ce qu'il coûtait | État |
|---|---|---|
| La palette n'avait **aucun accent** : `accent` valait le noir de l'encre | La fenêtre était uniformément grise et rien ne guidait l'œil | corrigé — un indigo, 6,83:1 sur la carte en clair, 5,67:1 en sombre, choisi loin du rouge d'enregistrement et des vumètres |
| Les filets à **1,28:1** de la carte | Bordures et séparateurs invisibles : l'interface paraissait plate quoi qu'on fasse | corrigé — 1,50 et 1,44, avec un test qui les garde perceptibles |
| `ttk.Combobox`, avec la flèche carrée grise du thème « clam » | À côté des boutons et ascenseurs dessinés, elle se lisait comme une pièce étrangère | corrigé — `Liste`, dessinée : même arrondi, même liseré, même survol, chevron en deux segments, menu qui prolonge le champ |
| « Se connecter » proposé à qui l'est déjà | Laisse croire que la session n'est pas vue | corrigé — une seule action, dont l'intitulé suit l'état ; plus de bouton « Actualiser », l'état se relit à l'affichage de l'onglet |
| La **langue** était un champ de saisie libre | « fr » ne se devine pas, et une faute de code faisait transcrire dans la mauvaise langue, en silence, une heure durant | corrigé — une liste de seize langues, détection automatique comprise |
| La ligne du bas gardait « … en cours… » | Après une mise à jour de Claude Code, elle laissait croire qu'elle tournait encore | corrigé — la dernière tâche qui s'achève l'efface |

**La langue vide veut dire « reconnais-la toi-même »**, comme le micro vide
laisse l'écoute décider. Les deux moteurs ne l'expriment pas pareil, et se
tromper est silencieux : `whisper-cli` reçoit `-l auto`, faster-whisper reçoit
`language=None` — la chaîne « auto » y serait refusée. Deux tests tiennent cette
correspondance.

`Liste` porte elle-même ses couples (clef, libellé) : l'appelant règle et lit
des **clefs**, jamais le texte affiché. La version précédente devait retrouver
la clef en comparant des libellés, ce qui cassait au premier renommage.

Le README porte enfin deux schémas **SVG animés** — la chaîne étape par étape,
et les cinq vues de la fenêtre qui défilent. Ils suivent le thème clair ou
sombre du lecteur par `prefers-color-scheme`, et s'immobilisent pour qui a
demandé moins d'animations (`prefers-reduced-motion`). Rien de rasterisé : le
texte reste sélectionnable et le fichier pèse quelques kilooctets.

## Une banque de voix qui se contredit ne doit plus affirmer (2026-09-02)

Constat en réunion réelle : quatre voix pour deux personnes, et un prénom
attribué à quelqu'un alors que personne ne l'avait prononcé. Mesuré sur
l'enregistrement, pas déduit du symptôme.

Les empreintes vocales identifient des personnes : ce document les désigne par
**« A »** et **« B »**, et n'en nomme aucune. Les chiffres suffisent au
raisonnement, et un dépôt n'a pas à porter la signature vocale de qui que ce
soit sous son nom.

### Le prénom venait de la banque, pas de la parole

| Voix du direct | Parole | contre « A » | contre « B » | Verdict de la banque |
|---|---|---|---|---|
| v4 | 57,0 s | **0,78** | 0,94 | « A », marge 0,24 — affirmé |
| v3 | 56,9 s | 0,46 | 0,55 | une troisième entrée, marge 0,44 |

Les deux contrôles étaient satisfaits, seuil et marge : l'outil n'a pas eu tort
d'affirmer, il a eu tort de croire sa banque. Car dans celle-ci :

| Paire de la banque | Ressemblance |
|---|---|
| « A » et « B » | **0,77** |
| les huit autres paires | 0,22 à 0,53 |

Deux personnes différentes se mesurent à 0,41 d'après `docs/calibrage.md`. Une
paire à 0,77 dit qu'un des deux noms porte la voix de l'autre. L'empreinte « A »
avait été versée huit jours plus tôt depuis un groupe de 85 s, dans une réunion
de 992 tours où aucun canal n'avait identifié le locuteur local — le terrain
d'une confusion.

### Ce qui a été corrigé, et ce qui a été écarté

**Écarté : relever le seuil.** Il faudrait connaître la ressemblance d'une même
personne entre deux séances, et la seule paire élevée de la banque est
justement celle dont on doute. Choisir un nombre ici serait le deviner, ce que
ce projet refuse ailleurs.

**Retenu : refuser d'affirmer quand la banque se contredit.**
`noms_en_conflit()` compare les personnes connues deux à deux ; toute paire au
seuil de reconnaissance signifie qu'un nom est faux sans qu'on sache lequel, et
`reconnaitre()` ne rend alors plus ce nom. La voix s'affiche à nommer, ce qui
appelle la correction humaine — la seule source que rien ne discute. Les noms
hors conflit continuent d'être reconnus : une entrée douteuse ne rend pas toute
la banque muette. Le défaut devient visible au lieu de se confirmer seul.

### Réunir des voix existait déjà, mais rien ne le disait

Nommer une voix du nom d'une autre les **réunit** : les tours passent à la voix
survivante, les empreintes se cumulent — ce qui enrichit l'entrée versée en
banque — et cela vaut pour autant de voix que la segmentation en a créées. Le
menu de correction se contentait d'afficher le nom. Il annonce désormais
« ⟵ réunir les deux voix » sur les noms déjà portés ailleurs dans la réunion.

### Le direct a enfin la seconde chance du recollage

Symptôme rapporté : « il me détecte à chaque fois une voix différente ». Mesuré
sur la même réunion, 27 phrases, empreintes prélevées phrase à phrase.

| | Même personne | Personnes différentes |
|---|---|---|
| Médiane | **0,69** | 0,35 |
| 1er quartile | 0,57 | 0,26 |
| Au-dessus du seuil de 0,75 | **28 %** | 2 % |

Le seuil était donc **au-dessus de la médiane d'une même personne** : trois
reprises de parole sur quatre créaient une voix. La durée explique tout — les
phrases de cette réunion durent 2 à 4 s en médiane :

| Durée des phrases | Médiane « même personne » | Au-dessus du seuil |
|---|---|---|
| ≥ 1 s | 0,69 | 28 % |
| ≥ 3 s | 0,77 | 64 % |
| ≥ 5 s | 0,79 | 89 % |

**Le seuil n'était pourtant pas en cause, et rien n'a été recalibré.** Sur les
agrégats accumulés, les deux voix de la même personne montent à **0,79** et les
deux personnes différentes restent à **0,63** : à 0,75, la séparation est nette.
Le rattachement d'un bloc compare une empreinte courte à l'agrégat d'une voix,
une fois, et ne refait jamais la comparaison quand la matière s'accumule.

`Fil.recoller()` la refait, à chaque tranche, en appelant `fusionner_voix` —
celle du traitement final, même seuil, même garde de matière minimale. Deux voix
nommées par un humain sous des noms différents ne sont jamais réunies : une
correction humaine ne se défait pas sur une mesure. La réunion voyage par le
journal (`genre: "reunion"`), la fenêtre reconstruisant le fil sans jamais
calculer d'empreinte.

Vérifié en rejouant le fil réel de la réunion : les quatre voix deviennent
trois, la voix de 8 s rejoint celle de 56 s de la même personne — 13 tours au
lieu de 10 — et l'autre personne reste séparée. La voix restante, une seule
phrase de 5,3 s à 0,60 et 0,52 des deux autres, est réellement ambiguë : un clic
la réunit, et le menu le dit maintenant.

## Une réunion terminée depuis la fenêtre ne laissait rien (2026-09-02)

Le plus grave de la journée, et il expliquait plusieurs symptômes d'un coup :
« ces réunions ne s'affichent pas dans la liste », « le compte rendu ne dit pas
qui était présent ».

**L'écriture n'existait que dans la commande en ligne.** `greffier traiter`
déposait le fichier maître, la transcription et le compte rendu ; la fenêtre,
elle, appelait la même chaîne puis n'écrivait rien. Une réunion terminée par le
bouton était donc transcrite, rédigée, envoyée par courriel — et perdue :
absente de la liste des réunions, impossible à relire, impossible à renommer
une voix après coup, donc rien n'entrait en banque.

`Traitement` garde désormais la réunion lui-même, derrière un port
`DepotReunions` et deux dossiers de sortie facultatifs. Tous ses appelants en
profitent, et la commande en ligne ne fait plus que dire où. **Gardé avant
l'envoi** : un serveur de courriel injoignable ne doit pas faire perdre une
heure de transcription et sa rédaction — un test le vérifie.

### La ligne de contexte est composée, plus rédigée

Deux comptes rendus du même jour, tous deux corrects selon les consignes :
« 2 septembre 2026, 15 h 50, durée 2 minutes. Participants : Tanguy, Paul. »
et « 2 septembre 2026, 3 min. » — sans heure, sans participants. Une date et une
heure ne sont pas matière à style.

`entete_contexte` compose maintenant la ligne et demande de la reproduire mot
pour mot : date, **horaires de début et de fin** (la fin se déduit de la durée),
durée, participants. Et quand aucune voix n'a été nommée, elle dit **combien**
de personnes ont parlé — « 3 personnes ont parlé, aucune nommée » — au lieu de
taire la question. Un compte rendu qui ne dit pas qui était là laisse son
lecteur sans réponse, et l'absence de nom se corrige d'un clic.

### Un traitement ne se lance plus pendant une réunion

Le fichier d'état est unique : c'est par lui que la fenêtre suit la réunion en
cours. Un traitement lancé en parallèle y publie ses propres phases, jusqu'à
« terminé », et la fenêtre en conclut que la réunion est finie — le fil du
direct s'arrête et les processus d'écoute se retirent, alors que la capture
continue. Provoqué pour de vrai ce jour-là, en réunion réelle, par un
traitement lancé à côté. `greffier traiter` refuse désormais tant qu'une réunion
s'enregistre, et `--quand-meme` reste pour qui sait ce qu'il fait.

### Mots déformés : ce que le rédacteur doit en faire

La transcription rend parfois un mot par un autre qui sonne pareil sans exister
(« diemandie » pour « demander »). Trois règles, dans cet ordre : rétablir le
mot quand la phrase ne laisse aucun doute et sans signaler la correction ; ne
jamais citer entre guillemets une forme devinée ; ne jamais deviner ce qui porte
l'information — un nom, un chiffre, une échéance — mais le signaler en annexe
plutôt que d'inscrire une valeur inventée.

### Reste ouvert

- **Aucun moyen de supprimer une réunion** depuis l'onglet Réunions.
- **En présentiel, le canal ne désigne personne** : mesuré sur une réunion
  réelle, deux des trois canaux enregistrés sont du silence numérique, la boucle
  système n'ayant rien à capter. Tout repose alors sur les empreintes, et rien
  ne prévient l'utilisateur que c'est le cas.
- **Le nombre de participants** est réglable (il force autant de groupes dans le
  traitement final) mais rien ne le suggère quand le compte détecté paraît trop
  élevé.

