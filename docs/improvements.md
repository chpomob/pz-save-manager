# Propositions d'amélioration pour PZ Save Manager

Analyse realisee avec un regard produit + architecture sur `src/pz_save_manager/` et `tests/`.

Le projet a deja une base saine : sauvegardes atomiques, restauration prudente, watcher debounced, extraction metadata defensive, CLI utile, tests de robustesse. Les propositions ci-dessous partent donc d'un constat : le produit n'a pas besoin de "plus de code" au hasard, mais d'un modele plus explicite de l'historique des saves et d'une interface qui aide le joueur a choisir le bon point de restauration.

## 1. Evolutions fonctionnelles

### 1. Comparaison de saves avant/apres session

**Pourquoi**  
Aujourd'hui une backup est surtout un timestamp. Pour un joueur, la question importante est : "qu'est-ce qui a change depuis hier soir ?" ou "est-ce que ce backup est avant ma mort ?". Les extracteurs savent deja lire joueur, mort/vivant, position, mods, vehicules, map position et thumbnail. Il manque une couche de diff qui transforme ces donnees en decision.

**Comment concret**  
Ajouter une commande et un endpoint :

- `pz-saves diff <mode> <save> <timestamp-a> <timestamp-b>`
- `/api/backup/diff`

Le diff comparerait d'abord un manifeste metadata, pas tous les fichiers :

- statut joueur : vivant -> mort, nom, position, world version
- liste de mods : ajouts/retraits
- compte vehicules, joueurs, crafted objects si disponible
- thumbnail avant/apres
- taille totale, nombre de fichiers, nombre de chunks `map/*.bin` modifies
- fichiers crees/supprimes/modifies par hash optionnel

Implementation progressive : stocker un `manifest.json` dans chaque backup au moment de `create_backup()`, en utilisant les fonctions de `save_info.py` et un scan leger des fichiers. Pour les backups existants, generer le manifeste a la demande et le mettre en cache.

**ROI** : effort `medium`, impact `high`.

### 2. Timeline de backups orientee evenements

**Pourquoi**  
La liste actuelle est une pile chronologique. Elle ne raconte pas l'histoire : mort du personnage, changement de mods, nouvelle base, retour apres crash, session longue. Les notes existent (`.pz-note`), mais elles sont manuelles et isolees.

**Comment concret**  
Construire une vue "Timeline" par save :

- groupes par jour/session
- badges automatiques : `vivant`, `mort`, `mods changes`, `nouvelle position`, `taille +30%`, `manual`, `auto`
- detection d'evenements entre deux backups consecutifs avec le diff metadata
- notes affichables directement dans la timeline, sans prompt navigateur
- action "marquer comme jalon" qui cree un backup manuel avec une note obligatoire

Techniquement, cette vue peut utiliser `list_backups(mode, save)` + manifestes. Pas besoin d'une DB au debut.

**ROI** : effort `medium`, impact `high`.

### 3. Export/import portable de backups

**Pourquoi**  
Le besoin naturel apres "je protege mes saves" est "je les transfere". Aujourd'hui les backups sont des dossiers internes sous `~/.pz-save-manager/backups/<mode>/<save>/<timestamp>`. C'est simple mais pas portable : pas de manifeste, pas de verification, pas de conflit guide.

**Comment concret**  
Ajouter un format archive :

```text
pz-backup/
  manifest.json
  save/
    sandbox.lua
    players.db
    ...
```

Commandes :

- `pz-saves export <mode> <save> <timestamp> --output backup.pzsave.zip`
- `pz-saves import backup.pzsave.zip --as "New Save Name"`

Le manifeste devrait contenir :

- version de PZ Save Manager
- game mode, save name original, timestamp, auto/manual, note
- platform source, world version, mods, player status
- checksums et taille

Au moment de l'import : preflight anti-collision, option de renommage, verification des checksums, refus des chemins dangereux dans l'archive.

**ROI** : effort `medium`, impact `high`.

### 4. Politiques de retention plus intelligentes

**Pourquoi**  
`max_auto_backups` protege le disque, mais une limite brute peut supprimer une backup importante. Les backups manuelles sont preservees, ce qui est bien, mais les auto-backups gagneraient a etre decimees avec une logique temporelle.

**Comment concret**  
Remplacer ou completer `max_auto_backups` par une politique type :

- garder toutes les autos des 2 dernieres heures
- garder 1 par heure sur 24h
- garder 1 par jour sur 14 jours
- garder 1 par semaine ensuite
- ne jamais supprimer les backups avec evenement majeur : mort, changement de mods, note, jalon

Exposer cela comme presets : `compact`, `balanced`, `archival`, plus mode avance JSON. La fonction `prune_auto_backups()` deviendrait un moteur `RetentionPolicy` testable.

**ROI** : effort `medium`, impact `high`.

### 5. Verification d'integrite et "restore preview"

**Pourquoi**  
La restauration remplace la save live. Le code est prudent, mais le joueur a besoin de confiance avant de cliquer. Actuellement l'UI confirme avec `confirm()`, sans montrer ce qui sera ecrase.

**Comment concret**  
Ajouter avant restore :

- resume du backup cible : date, joueur, vivant/mort, position, mods, taille
- resume de la save actuelle
- diff rapide entre actuel et backup
- option "creer une backup de securite avant restore"
- verification : fichiers lisibles, `players.db` ouvrable si present, absence de symlink, checksums si manifeste

Cote implementation, `restore_backup()` pourrait accepter `safety_backup=True` ou etre precede par une orchestration de service.

**ROI** : effort `small` pour le preview simple, `medium` avec checksums, impact `high`.

### 6. Profils de saves et tags

**Pourquoi**  
Les saves Project Zomboid portent souvent des noms faibles : `World`, `test`, `Muldraugh 2`. Le produit gagnerait une memoire propre : tags, favoris, campagne, roleplay, serveur, modpack.

**Comment concret**  
Ajouter un sidecar par save gere par l'app :

```text
~/.pz-save-manager/index/saves/<stable-id>.json
```

Champs :

- alias d'affichage
- tags : `solo`, `coop`, `modded`, `hardcore`, `roleplay`
- couleur ou icone
- favori/archive
- dernier backup choisi comme "safe point"

Ne pas ecrire ces metadonnees dans le dossier live de PZ pour eviter de polluer les saves. Utiliser un identifiant derive du chemin + creation time ou un mapping explicite.

**ROI** : effort `medium`, impact `medium`.

### 7. Statistiques de progression

**Pourquoi**  
Le README promet des "Save insights", mais l'interface actuelle affiche surtout un instantane. Project Zomboid est un jeu de progression lente ; l'utilisateur veut voir survivance, pertes, evolution de base, vehicules, mods, morts.

**Comment concret**  
Enregistrer un snapshot metadata a chaque backup :

- statut vivant/mort
- position joueur
- world version
- nombre de vehicules
- nombre de joueurs
- nombre de mods
- nombre de chunks map
- taille de save

Afficher ensuite :

- courbe taille/chunks
- heatmap de positions si `player_x/y` evoluent
- nombre de backups par session
- "premiere mort detectee entre backup A et B"

Le temps joue exact n'est probablement pas fiable sans parser davantage les fichiers PZ. Le presenter comme "temps entre modifications/backups" tant qu'une source de temps de jeu n'est pas identifiee.

**ROI** : effort `medium`, impact `medium`.

### 8. Snapshot "avant lancement du jeu"

**Pourquoi**  
Le watcher sauvegarde apres modifications. Le moment le plus utile pour restaurer est souvent juste avant de lancer Project Zomboid. Sans integration au lancement, on peut ne pas avoir de point propre "pre-session".

**Comment concret**  
Ajouter une action "Launch PZ with safety backup" :

- detecter Steam ou demander le chemin executable
- creer une backup manuelle/auto speciale `pre-session`
- lancer `steam://rungameid/108600` ou executable configure
- activer le watcher
- afficher une session en cours dans l'UI

Ce serait optionnel et separe du watcher pour eviter de complexifier le coeur.

**ROI** : effort `medium`, impact `high` pour les utilisateurs non techniques.

### 9. File queue pour operations longues

**Pourquoi**  
Les saves PZ peuvent contenir beaucoup de fichiers. Backup, restore, export, import et hashing deviendront longs. Aujourd'hui l'API Flask execute les actions directement et recharge la page apres 600 ms.

**Comment concret**  
Introduire une queue locale en memoire :

- `Operation`: id, type, save, status, progress, started_at, error
- endpoints `/api/jobs`, `/api/jobs/<id>`
- UI avec progression et annulation quand c'est possible
- verrou par save pour eviter backup + restore simultanes

Au debut, un `ThreadPoolExecutor(max_workers=1 ou 2)` suffit. Pas besoin de Celery.

**ROI** : effort `medium`, impact `medium`.

### 10. Merge de saves : a traiter comme outil de recherche, pas comme feature principale

**Pourquoi**  
Un merge complet de saves PZ est risque : bases SQLite, chunks de carte, vehicles, players, mods et versions peuvent etre incoherents. Une mauvaise fusion peut creer une save corrompue avec une apparence de succes.

**Comment concret**  
Ne pas promettre "merge saves" au sens general. Proposer plutot des outils limites :

- comparer deux saves
- extraire une backup comme archive portable
- restaurer un sous-ensemble non destructif uniquement si le format est compris
- mode expert "copy selected files" avec avertissement et backup obligatoire

Exemples de merges plausibles mais a valider par recherche format :

- recuperer `thumb.png`, notes et metadonnees app : facile
- restaurer config `mods.txt` / `sandbox.lua` : moyen mais comprehensible
- fusionner chunks `map/*.bin` : dangereux si coordonnees/versions divergent
- fusionner `players.db` / `vehicles.db` : tres dangereux sans schema/versioning

**ROI** : effort `large`, impact `low` a `medium`, risque `high`. A repousser apres diff/export.

## 2. Architecture et dette technique

### 1. Sortir un modele de domaine explicite

**Pourquoi**  
Les concepts existent mais restent disperses : `SaveGame`, `BackupRecord`, dicts GUI, sidecars `.pz-*`, config globale, watcher global. Si l'app grossit, chaque nouvelle feature devra recoder son propre format de donnees.

**Comment concret**  
Introduire des dataclasses serialisables :

- `SaveIdentity(game_mode, save_name)`
- `BackupIdentity(game_mode, save_name, timestamp)`
- `SaveMetadata`
- `BackupManifest`
- `DiffSummary`

Puis faire retourner ces objets par une couche service, et laisser CLI/GUI seulement les presenter.

**ROI** : effort `medium`, impact `high`.

### 2. Creer une couche `services`

**Pourquoi**  
`gui.py` orchestre directement backup, restore, rename, watcher, config et rendu HTML. `cli.py` refait une partie de l'orchestration. Les futures features seront dupliquees entre CLI et web.

**Comment concret**  
Ajouter des services purs :

- `BackupService`: create, restore, delete, annotate, export, import
- `SaveService`: list, rename, metadata, tags
- `WatcherService`: watch/unwatch/start/stop avec config
- `DiffService`: compare save/backup

CLI et Flask appelleraient ces services. Les tests de comportement devraient viser les services, les tests Flask seulement le mapping HTTP.

**ROI** : effort `medium`, impact `high`.

### 3. Remplacer les sidecars implicites par des manifestes versionnes

**Pourquoi**  
`.pz-auto` et `.pz-note` sont simples et robustes, mais le prochain besoin ajoutera `.pz-tags`, `.pz-hash`, `.pz-exported`, etc. On voit deja le debut d'un protocole interne.

**Comment concret**  
Creer dans chaque backup :

```json
{
  "schema": 1,
  "created_at": "2026-05-26T14:03:00+02:00",
  "kind": "auto",
  "note": "...",
  "source": {"game_mode": "...", "save_name": "..."},
  "metadata": {...},
  "checksums": null
}
```

Garder la compatibilite : si le manifeste n'existe pas, lire `.pz-auto` et `.pz-note`. Lors de la prochaine modification du backup, ecrire le manifeste.

**ROI** : effort `medium`, impact `high`.

### 4. Isoler le rendu web hors de `render_template_string`

**Pourquoi**  
`gui.py` fait 500+ lignes et contient Python, HTML, CSS et JS dans un seul fichier. C'est pratique au demarrage, mais toute amelioration UI deviendra fragile : pas de lint JS, pas de composants, pas de templates reutilisables, pas de tests fins sur les fragments.

**Comment concret**  
Migration en deux etapes :

1. Deplacer le HTML dans `templates/index.html`, CSS dans `static/app.css`, JS dans `static/app.js`.
2. Si l'UI devient plus interactive, passer a HTMX/Alpine.js avant un framework lourd.

Flask peut rester. L'objectif n'est pas une SPA, mais une UI maintenable.

**ROI** : effort `small` a `medium`, impact `medium`.

### 5. Introduire un index local optionnel

**Pourquoi**  
`list_backups()` parcourt le filesystem et certaines proprietes (`file_count`, `size_mb`) font des `rglob`. L'UI evite deja certains calculs pour rester rapide. Avec diff, stats, export et retention, rescanner les dossiers deviendra le goulet.

**Comment concret**  
Creer un index SQLite local dans `~/.pz-save-manager/index.db` :

- table `backups`: mode, save, timestamp, path, kind, note, size, file_count, created_at
- table `metadata_snapshots`
- table `jobs`
- table `save_profiles`

Ne pas rendre l'index source de verite au debut : le filesystem reste canonique, l'index est un cache reconstructible via `pz-saves reindex`.

**ROI** : effort `large`, impact `high` a moyen terme.

### 6. Injecter explicitement les racines et la config

**Pourquoi**  
Les tests monkeypatchent `get_saves_root` et `get_backups_root` selon l'endroit ou les fonctions ont ete importees. Cela fonctionne, mais c'est un signe que les dependances globales rendent l'app plus difficile a composer.

**Comment concret**  
Creer un objet `AppContext` ou `Settings` :

```python
@dataclass
class AppContext:
    saves_root: Path
    backups_root: Path
    config: ConfigStore
```

Les services recoivent ce contexte. La CLI le construit depuis les options, Flask depuis la config utilisateur.

**ROI** : effort `medium`, impact `medium`.

### 7. Verrous par save et etats d'operation

**Pourquoi**  
Le code gere deja des races de creation de backup et pause le watcher pendant restore/rename. Mais a mesure que l'UI lance des jobs asynchrones, il faudra empecher les operations incompatibles.

**Comment concret**  
Ajouter un `SaveLockRegistry` :

- cle : `game_mode/save_name`
- operations exclusives : restore, rename, delete live, import
- operations partageables : metadata read, thumbnail read
- timeout et message utilisateur clair

Tests : restore + backup simultanes, rename + watcher event, export pendant delete.

**ROI** : effort `medium`, impact `high` si jobs asynchrones.

### 8. Typage et contrats de metadata

**Pourquoi**  
`extract_all()` retourne un `dict` heterogene. C'est souple, mais chaque appelant doit connaitre les cles exactes. La GUI copie quelques champs a la main.

**Comment concret**  
Retourner un `SaveMetadata` avec champs optionnels. Garder une methode `.to_dict()` pour JSON. Cela rend les diffs, manifestes et tests plus explicites.

**ROI** : effort `small`, impact `medium`.

### 9. Strategie de compatibilite avec les versions PZ

**Pourquoi**  
`world_version_to_build()` encode une connaissance communautaire. Les formats `players.db`, `vehicles.db`, `map_ver.bin` peuvent changer. Aujourd'hui les extracteurs echouent silencieusement, ce qui protege l'UI mais cache les regressions.

**Comment concret**  
Ajouter :

- logs structures quand un extracteur echoue
- endpoint `/api/diagnostics/metadata/<save>`
- tests fixtures par schema connu
- champ `extractor_warnings` dans les manifestes

**ROI** : effort `small`, impact `medium`.

## 3. UX/UI

### 1. Remplacer les prompts navigateur par des modales dediees

**Pourquoi**  
`prompt()` et `confirm()` sont rapides a coder mais limitent l'UX : pas de preview, pas de validation riche, pas de style coherent, pas de details avant action destructive.

**Comment concret**  
Creer trois modales :

- rename : nouveau nom, validation inline, collision detectee avant submit
- note : textarea, sauvegarde sans recharger toute la page
- restore : comparaison current vs backup, case "creer une backup de securite"

**ROI** : effort `small`, impact `high`.

### 2. Vue detail par save

**Pourquoi**  
La page actuelle melange toutes les saves et les 50 derniers backups. Des que l'utilisateur a plusieurs mondes, il lui faut un espace dedie pour une seule save.

**Comment concret**  
Ajouter `/save/<mode>/<name>` :

- header avec thumbnail, statut, joueur, derniere modification
- actions primaires : backup, restore last safe, watch/unwatch
- timeline de backups de cette save uniquement
- panneau stats
- panneau mods
- notes/jalons

La page d'accueil devient un tableau de bord compact.

**ROI** : effort `medium`, impact `high`.

### 3. Recherche, filtres et tri

**Pourquoi**  
`list_saves()` trie par modification recente et l'UI affiche les 50 backups. C'est suffisant au debut, mais la valeur d'une app de backup augmente avec l'historique, donc avec le volume.

**Comment concret**  
Ajouter :

- recherche par nom de save, note, tag
- filtres : manual/auto, alive/dead, avec note, avec changement de mods, favoris
- tri : date, taille, nom, dernier evenement
- bouton "archives" pour cacher les anciennes campagnes

**ROI** : effort `small`, impact `medium`.

### 4. Etat du watcher plus explicite

**Pourquoi**  
Le badge `RUNNING/STOPPED` ne dit pas quelles saves sont protegees ni pourquoi un backup ne part pas. Le cooldown et le debounce sont invisibles.

**Comment concret**  
Afficher :

- nombre de saves watched / total
- derniere auto-backup par save
- prochaine backup possible apres cooldown
- dernier evenement filesystem vu
- erreurs recentes du watcher

Ajouter une page diagnostic utilisateur, plus lisible que `/health`, avec actions correctives.

**ROI** : effort `medium`, impact `medium`.

### 5. Feedback de progression

**Pourquoi**  
Backup/restauration peuvent prendre du temps. Aujourd'hui le bouton se desactive puis la page recharge. Si une operation dure 20 secondes, l'utilisateur ne sait pas si tout va bien.

**Comment concret**  
Pour commencer sans queue complete :

- toast persistant "Backup en cours..."
- spinner sur carte concernee
- resultat inline avec timestamp cree
- pas de reload complet si l'API retourne les donnees necessaires

Avec la queue : barre de progression approximative par nombre de fichiers copies.

**ROI** : effort `small` pour feedback simple, impact `medium`.

### 6. Onboarding et etat vide utiles

**Pourquoi**  
L'etat vide dit "No saves found. Launch Project Zomboid!". C'est vrai, mais insuffisant si le chemin est faux, si l'utilisateur est sur un autre OS, ou si Steam/Proton change le dossier.

**Comment concret**  
Etat vide enrichi :

- chemin inspecte
- bouton "choisir un dossier de saves"
- bouton "ouvrir diagnostics"
- exemples de dossiers detectes
- statut permissions lecture/ecriture

**ROI** : effort `small`, impact `medium`.

### 7. Application desktop reelle

**Pourquoi**  
Flask dans un navigateur est efficace pour un outil solo, mais une vraie app desktop offrirait tray icon, notifications natives, autostart et integration au lancement du jeu.

**Comment concret**  
Deux chemins raisonnables :

- court terme : garder Flask, ajouter `pystray` pour tray icon + notifications, ouvrir le navigateur depuis le tray
- moyen terme : emballer l'UI dans `pywebview` ou Tauri, garder le backend Python comme process local

Fonctions desktop attendues :

- demarrage avec Windows/Linux session
- icone "watcher active"
- notification "Backup cree : WorldOne, joueur vivant"
- action rapide "Backup now"
- avertissement si le disque backup est deconnecte

**ROI** : effort `large`, impact `high` pour distribution grand public.

### 8. Restaurations moins anxiogenes

**Pourquoi**  
La restauration est l'action la plus risquee psychologiquement. Meme si le code est correct, l'interface doit la rendre reversible et comprehensible.

**Comment concret**  
Pattern d'interaction :

- bouton "Preview restore" au lieu de "Restore" direct dans la liste
- ecran recapitulatif avant/apres
- backup automatique de la save actuelle avant remplacement, active par defaut
- message post-restore : "ancienne save conservee comme backup de securite <timestamp>"
- bouton undo si possible via cette backup de securite

**ROI** : effort `medium`, impact `high`.

## 4. Synthese ROI

| Proposition | Effort | Impact | Priorite suggeree |
|---|---:|---:|---:|
| Restore preview + backup de securite | small/medium | high | P1 |
| Modales rename/note/restore | small | high | P1 |
| Manifestes versionnes par backup | medium | high | P1 |
| Comparaison de backups | medium | high | P1 |
| Vue detail par save + timeline | medium | high | P1 |
| Export/import `.pzsave.zip` | medium | high | P2 |
| Retention intelligente | medium | high | P2 |
| Snapshot pre-session + launch PZ | medium | high | P2 |
| Couche services partagee CLI/GUI | medium | high | P2 |
| Queue de jobs locale | medium | medium | P2 |
| Tags/profils/favoris | medium | medium | P3 |
| Statistiques de progression | medium | medium | P3 |
| Index SQLite reconstructible | large | high moyen terme | P3 |
| App desktop tray/notifications | large | high public large | P3 |
| Merge de saves general | large | low/medium, risque high | A eviter pour l'instant |

## Roadmap pragmatique

### Phase 1 : rendre les backups intelligibles

1. Ajouter `BackupManifest` compatible avec `.pz-auto` et `.pz-note`.
2. Generer un snapshot metadata a chaque backup.
3. Ajouter restore preview dans l'API et l'UI.
4. Remplacer `prompt()` / `confirm()` par des modales.

Resultat : l'utilisateur sait ce qu'il restaure et pourquoi.

### Phase 2 : raconter l'historique

1. Ajouter diff entre deux backups.
2. Creer une page detail par save.
3. Afficher une timeline avec evenements automatiques.
4. Ajouter recherche/filtres.

Resultat : PZ Save Manager devient un journal de campagne, pas seulement un dossier de copies.

### Phase 3 : portabilite et croissance

1. Export/import archive avec verification.
2. Retention intelligente.
3. Queue de jobs et verrous par save.
4. Index SQLite reconstructible si les scans deviennent couteux.

Resultat : le produit tient avec beaucoup de saves, beaucoup de backups et des operations longues.

### Phase 4 : experience desktop

1. Tray icon et notifications.
2. Snapshot pre-session + lancement du jeu.
3. Autostart configure.
4. Packaging desktop plus natif si le public le justifie.

Resultat : l'app devient invisible quand tout va bien et rassurante quand une decision importante arrive.

## Choix a ne pas faire tout de suite

- Ne pas construire un merge general de saves avant d'avoir diff, export, manifestes et recherche format plus solide.
- Ne pas migrer vers une SPA lourde avant d'avoir epuise Flask templates + JS leger ou HTMX/Alpine.
- Ne pas rendre SQLite obligatoire comme source de verite trop tot : garder le filesystem canonique tant que le format backup reste lisible a la main.
- Ne pas multiplier les extracteurs couteux sur la page d'accueil. Les fonctions lourdes doivent alimenter des manifestes ou des vues detail, pas bloquer le dashboard.

