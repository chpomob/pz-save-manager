# Revue Codex - PZ Save Manager

Date: 2026-05-26

Portee: tous les fichiers Python de `src/pz_save_manager/` et `tests/`.

Verification executee: `.venv/bin/pytest -q` -> `43 passed in 1.48s`.

## Synthese

Le projet est compact, lisible et les invariants principaux de backup ont deja une bonne base: validation de composants sur les operations critiques, reservation de destination par `mkdir(exist_ok=False)`, copie sans suivre les symlinks, restauration par staging puis `rename`, et tests adversariaux pour plusieurs risques P0.

Les risques les plus importants restants sont:

- Les fichiers internes de backups (`.pz-note`, `.pz-auto`) sont restaures dans la sauvegarde live, puis peuvent contaminer les backups suivants et les classer a tort comme automatiques.
- Le renommage combine save + backups n'est pas transactionnel: si le rename des backups echoue, la save a deja ete renommee.
- Le watcher peut encore creer un backup apres `stop()` ou `unwatch()` car les timers en attente ne sont pas annules.
- Plusieurs routes Flask locales sont sans authentification/CSRF et deviennent dangereuses si l'utilisateur lance `--host 0.0.0.0`.
- La GUI expose trop de details techniques en cas d'erreur (`traceback`, chemins locaux, environnement) et certaines pages de diagnostic ne sont pas echappees HTML.

## Findings prioritaires

### P0/P1 - Les metadonnees internes sont restaurees dans les saves live

Fichiers:

- `src/pz_save_manager/backup.py:197-203`
- `src/pz_save_manager/backup.py:278-279`
- `src/pz_save_manager/backup.py:237-238`

`create_backup(..., auto=True)` ajoute un marqueur `.pz-auto` dans le repertoire de backup, et `set_backup_note()` ajoute `.pz-note`. Lors d'une restauration, `restore_backup()` copie tout le repertoire de backup vers la save live avec seulement les symlinks ignores:

```python
shutil.copytree(backup.path, temp_target, copy_function=shutil.copy2,
                ignore=_skip_symlinks)
```

Cela restaure aussi `.pz-auto` et `.pz-note` dans `~/Zomboid/Saves/...`. Ensuite, un backup manuel cree depuis cette save live recopie `.pz-auto`, et `list_backups()` le classera comme auto parce qu'il teste uniquement `(backup_dir / ".pz-auto").is_file()`.

Impact:

- Pollution des saves Project Zomboid avec des fichiers propres au gestionnaire.
- Classification fausse manual/auto.
- Pruning possible d'un backup manuel faussement marque auto.

Recommendation:

- Exclure explicitement les fichiers internes du restore: `.pz-auto`, `.pz-note`, et tout futur namespace interne.
- Exclure aussi ces fichiers lors de `create_backup()` au cas ou une save live est deja contaminee.
- Ajouter un test: creer un backup auto + note, restaurer, verifier que la save live ne contient aucun `.pz-*`, puis creer un backup manuel et verifier qu'il n'est pas auto.

### P1 - Rename save + backups peut laisser un etat incoherent

Fichiers:

- `src/pz_save_manager/cli.py:193-194`
- `src/pz_save_manager/gui.py:395-397`
- `src/pz_save_manager/backup.py:342-346`

Le flux CLI et GUI fait d'abord `rename_save()`, puis `rename_backups_for_save()`:

```python
new_save = rename_save(...)
n = rename_backups_for_save(...)
```

Si le renommage de backups echoue, par exemple parce que la destination de backups existe deja, la save live est deja renommee. Les backups restent sous l'ancien nom.

Impact:

- Historique de backups separe de la save renommee.
- Les boutons GUI sur la nouvelle save ne retrouvent plus l'ancien historique.
- Correction manuelle necessaire par l'utilisateur.

Recommendation:

- Preflighter le rename des backups avant de renommer la save live.
- Ou implementer une operation combinee dans un seul module qui sait rollback la save si le rename backups echoue.
- Ajouter un test d'integration CLI/GUI: destination backup deja existante -> la save live doit garder son ancien nom.

### P1 - Le watcher peut creer un backup apres stop/unwatch

Fichiers:

- `src/pz_save_manager/watcher.py:69-71`
- `src/pz_save_manager/watcher.py:126-130`
- `src/pz_save_manager/watcher.py:142-148`

`SaveWatcher.on_modified()` arme un `threading.Timer`. `WatcherManager.stop()` arrete l'observer watchdog, mais ne parcourt pas les watchers pour annuler leurs timers. `WatcherManager.unwatch()` supprime le watcher des dictionnaires, mais n'appelle pas `watcher.pause()` ni n'annule le timer existant.

Impact:

- Un backup automatique peut partir apres que l'utilisateur a clique Stop Watcher ou Unwatch.
- Effet particulierement surprenant apres une restauration ou un renommage.

Recommendation:

- Ajouter une methode `SaveWatcher.close()` ou `cancel_pending()` qui annule le timer sous lock.
- L'appeler dans `stop()` pour tous les watchers et dans `unwatch()` pour le watcher retire.
- Ajouter des tests avec `debounce_seconds` court: evenement -> stop/unwatch -> attendre -> aucun appel a `create_backup`.

### P1 - Race condition dans `_do_backup()`

Fichiers:

- `src/pz_save_manager/watcher.py:73-94`

`_do_backup()` lit et modifie `_last_backup_time`, `_last_backup_mtime` et `_backups` sans lock. Deux timers peuvent courir en parallele si un timer deja lance n'est pas annule a temps. Les deux peuvent passer le cooldown avant que l'un mette a jour `_last_backup_time`.

Impact:

- Backups automatiques dupliques.
- Etat interne non coherent entre `_backups`, cooldown et mtime.

Recommendation:

- Proteger tout `_do_backup()` ou au minimum la section check/update par `self._lock`.
- Eviter d'appeler `create_backup()` sous lock si l'operation est longue: reserver l'intention sous lock, relacher pour copier, puis finaliser sous lock avec une verification.

### P1 - `SaveWatcher` ignore le chemin reel de la save

Fichier:

- `src/pz_save_manager/watcher.py:89`

Le watcher stocke un `SaveGame` avec `save.path`, mais `_do_backup()` appelle:

```python
create_backup(self.save.game_mode, self.save.name, auto=True)
```

Il ne passe ni `saves_root` ni un chemin source explicite. Si le watcher est construit sur une save provenant d'un root custom, d'un test, ou d'une future configuration de saves, le backup sera tente contre le root par defaut.

Impact:

- Le watcher peut echouer silencieusement cote utilisateur, ou backuper une autre save de meme nom dans le root par defaut.

Recommendation:

- Soit `create_backup()` accepte un `SaveGame`/`source_path`, soit `SaveWatcher` stocke `saves_root` et `backups_root`.
- Tester un watcher sur un `tmp_path` avec `create_backup` non monkeypatche.

### P1 - Surface Flask dangereuse si exposee hors localhost

Fichiers:

- `src/pz_save_manager/cli.py:131-142`
- `src/pz_save_manager/gui.py:334-545`

La valeur par defaut `127.0.0.1` est raisonnable, mais le CLI permet `--host`. Si l'utilisateur lance `--host 0.0.0.0`, toutes les actions mutantes sont accessibles sans authentification ni CSRF:

- `/api/backup`
- `/api/restore`
- `/api/backup/delete`
- `/api/save/rename`
- `/api/backup/annotate`
- `/api/config`
- `/api/shutdown`

`/api/shutdown` peut aller jusqu'a `os._exit(0)` (`src/pz_save_manager/gui.py:541`).

Impact:

- Une page web visitee par l'utilisateur peut declencher des POST locaux si le service est accessible.
- Sur reseau local, une autre machine peut supprimer/restaurer/renommer des saves ou eteindre l'app.

Recommendation:

- Ajouter un token CSRF/session genere au demarrage et exige par toutes les routes POST.
- Refuser ou avertir fortement pour `--host` non loopback.
- Ne pas exposer `/api/shutdown` sans token.

### P1 - Fuite d'informations et XSS potentiel dans les pages de diagnostic

Fichiers:

- `src/pz_save_manager/gui.py:251-264`
- `src/pz_save_manager/gui.py:268-324`

En cas d'erreur de rendu, la page renvoie le traceback complet au navigateur. `/health` expose version Python, executable, plateforme, chemins locaux, noms de saves et enfants du repertoire Zomboid.

Ces pages sont construites avec des f-strings HTML:

```python
f"<pre>{tb}</pre>"
f"<pre>{json.dumps(info, indent=2, default=str)}</pre>"
```

Le contenu n'est pas echappe HTML. Un nom de save contenant `</pre><script>...` pourrait etre interprete par le navigateur sur `/health`, surtout sur Linux ou les noms de fichiers sont permissifs.

Impact:

- Fuite de chemins locaux et environnement.
- XSS local si une save ou un chemin contient du HTML.

Recommendation:

- Echappement via `html.escape()` pour `tb` et le JSON.
- Garder les tracebacks pour logs serveur; afficher une erreur courte dans la GUI.
- Proteger `/health` derriere un mode debug explicite ou un token local.

### P2 - Validation de chemins incomplete ou incoherente

Fichiers:

- `src/pz_save_manager/saves.py:113-123`
- `src/pz_save_manager/backup.py:214-243`
- `src/pz_save_manager/backup.py:350-389`

`get_save()` rejette `..`, `/`, `\` et null byte, mais ne rejette pas `""` ni `"."`. Il rejette aussi tout nom contenant `..` comme sous-chaine, ce qui interdit des noms legitimes comme `World..old`.

`list_backups()` ne valide pas ses filtres `game_mode` et `save_name` avant de construire `root / game_mode / save_name`. `prune_auto_backups()` ne valide pas non plus `game_mode` et `save_name`.

Impact:

- API interne moins robuste que `create_backup()`/`get_backup()`, qui utilisent `_validate_component()`.
- Risque de traversal en lecture avec `list_backups()` si appele avec entree utilisateur.
- Risque destructif avec `prune_auto_backups()` si appele directement avec entree hostile et un chemin contenant des `.pz-auto`.

Recommendation:

- Centraliser la validation de composants et l'utiliser dans `get_save()`, `list_backups()` avec filtres, et `prune_auto_backups()`.
- Rejeter seulement les composants exactement `"."`/`".."`, pas toute sous-chaine `..`, sauf decision produit explicite.

### P2 - `rename_save()` peut remplacer un repertoire vide selon l'OS

Fichier:

- `src/pz_save_manager/saves.py:157-160`

Le code calcule `new_path` puis appelle `old.path.rename(new_path)` sans verifier explicitement `new_path.exists()`. Sur POSIX, renommer un repertoire vers un repertoire vide existant peut remplacer la destination; sur Windows, le comportement differe.

Impact:

- Comportement cross-platform non deterministe.
- Un repertoire destination vide peut disparaitre sans message clair.

Recommendation:

- Tester explicitement `if new_path.exists(): raise SaveManagerError(...)` avant le rename.
- Ajouter un test pour destination vide.

### P2 - Configuration exposee mais partiellement inutilisee

Fichiers:

- `src/pz_save_manager/config.py:17-24`
- `src/pz_save_manager/gui.py:421-432`
- `src/pz_save_manager/gui.py:449-451`
- `src/pz_save_manager/cli.py:130-143`

La configuration contient `debounce_seconds`, `backup_cooldown_minutes`, `max_auto_backups`, `auto_start_watcher` et `port`. Dans la GUI:

- `backup_cooldown_minutes` est utilise seulement par `/api/watcher/toggle` (`src/pz_save_manager/gui.py:428-430`).
- `/api/watcher/save` utilise les valeurs par defaut de `manager.watch(save)` et ignore la config (`src/pz_save_manager/gui.py:449`).
- `debounce_seconds` n'est pas applique.
- `auto_start_watcher` n'est applique nulle part.
- `port` n'est pas utilise par la commande `pz-saves gui`, qui garde `8080` par defaut.

Impact:

- L'utilisateur peut modifier des options qui ne changent pas le comportement attendu.
- Deux chemins GUI differents creent des watchers avec des cooldowns differents.

Recommendation:

- Creer une fonction unique `watcher_settings()` et l'utiliser partout.
- Au lancement GUI, lire `port` si aucun `--port` explicite n'est passe.
- Implementer ou retirer `auto_start_watcher`.

### P2 - Bug de type dans la route config

Fichier:

- `src/pz_save_manager/gui.py:477`

Le code utilise:

```python
elif key in ("auto_start_watcher"):
```

Ce n'est pas un tuple, c'est une chaine. Des cles arbitraires qui sont des sous-chaines de `"auto_start_watcher"` peuvent entrer dans cette branche. En pratique, la route accepte deja des cles inconnues et les persiste.

Recommendation:

- Remplacer par `elif key == "auto_start_watcher":` ou `elif key in ("auto_start_watcher",):`.
- Refuser les cles hors schema.

### P2 - Installer pointe probablement vers le mauvais repertoire

Fichiers:

- `src/pz_save_manager/installer.py:12`
- `src/pz_save_manager/installer.py:21-27`
- `src/pz_save_manager/installer.py:47-48`

`PROJECT_DIR = Path(__file__).resolve().parent.parent` donne `.../src`, pas la racine du repo dans une installation editable (`.../pz-save-manager`). Les launchers sont a la racine (`launcher.sh`, `launcher.bat`), donc le raccourci Linux vise probablement `.../src/launcher.sh`.

Autres points:

- `shutil` est importe mais inutilise (`src/pz_save_manager/installer.py:7`).
- `pythoncom`/`win32com` ne sont pas declares dans `pyproject.toml`; `install_windows()` echouera si `pywin32` n'est pas installe.
- `desktop_file.write_text(...)` n'indique pas `encoding`.

Recommendation:

- Resoudre la racine de projet correctement en mode source, ou generer un raccourci vers l'entree console `pz-saves gui`.
- Declarer l'extra Windows ou gerer proprement l'absence de `pywin32`.

## Code quality

### Points solides

- `backup.py` isole bien les operations sensibles et expose des exceptions dediees.
- `_unique_destination()` (`src/pz_save_manager/backup.py:144-160`) evite la collision de timestamps concurrente par creation atomique.
- `restore_backup()` stage dans un repertoire temporaire puis renomme (`src/pz_save_manager/backup.py:272-282`), ce qui est une bonne base d'atomicite.
- Les extracteurs de `save_info.py` sont defensifs et n'interrompent pas la GUI sur un fichier corrompu.
- Les tests adversariaux documentent des invariants de securite importants (`tests/test_adversarial.py:19-142`).

### Dette technique

- `gui.py` melange Flask routes, HTML, CSS et JavaScript dans un seul fichier de 562 lignes. Pour une petite app c'est acceptable, mais cela rend les tests UI et la maintenance plus difficiles.
- Plusieurs `except Exception` masquent les causes (`save_info.py:57-64`, `save_info.py:93`, `gui.py:493-508`). C'est parfois volontaire pour la robustesse, mais il faudrait logguer au moins dans les chemins GUI/thumbnail.
- `config.py` ne valide pas le schema: n'importe quelle cle peut etre ecrite (`src/pz_save_manager/config.py:63-67`).
- `config.py` fait des writes atomiques avec `os.replace`, mais sans verrou. Deux POST `/api/config` concurrents peuvent perdre des mises a jour.
- `platformdirs` est une dependance (`pyproject.toml:14`) mais n'est pas utilisee; les chemins sont faits a la main dans `platforms.py`.

## Atomicite et operations fichier

### Backup creation

Fichiers:

- `src/pz_save_manager/backup.py:178-196`

La destination finale est reservee avant la copie, puis le contenu est deplace depuis un temp sibling vers cette destination. C'est TOCTOU-safe pour le nom, mais pas une publication completement atomique: pendant la copie, un autre processus ou la GUI peut voir un repertoire de backup vide deja present.

Recommendation:

- Publier seulement une fois la copie terminee, par exemple avec un repertoire temporaire complet puis un rename final.
- Si la reservation du nom est necessaire, utiliser un lock/marker interne non liste comme backup complet.

### Restore

Fichiers:

- `src/pz_save_manager/backup.py:270-296`

La strategie de restore est raisonnable, mais:

- Elle copie les sidecars `.pz-*` internes, point critique decrit plus haut.
- Elle ne verifie pas l'espace disque avant de copier.
- Si `target.rename(previous_target)` reussit puis `temp_target.rename(target)` echoue, le rollback tente de remettre l'ancien repertoire (`src/pz_save_manager/backup.py:286-287`), ce qui est bien, mais ce cas merite un test dedie.

## Securite

### Path traversal

Les operations critiques `create_backup()`, `get_backup()`, `delete_backup()` et `restore_backup()` passent par `_validate_component()` ou `get_backup()`, ce qui couvre les routes mutantes principales. Les exceptions sont `get_save()`, `list_backups()` filtre, et `prune_auto_backups()` comme indique plus haut.

### Symlinks

Les symlinks sont ignores a la creation et a la restauration (`src/pz_save_manager/backup.py:185-188`, `src/pz_save_manager/backup.py:276-279`). C'est bon pour eviter la materialisation de fichiers externes, mais cela peut surprendre un utilisateur qui avait volontairement des symlinks dans une save. Ce comportement devrait etre documente dans l'UI ou README.

### SQLite URI

Fichiers:

- `src/pz_save_manager/save_info.py:76`
- `src/pz_save_manager/save_info.py:151`
- `src/pz_save_manager/save_info.py:167`

Les DB sont ouvertes avec `sqlite3.connect(f"file:{path}?mode=ro", uri=True)`. Si un chemin contient `?` ou `#`, l'URI peut etre interpretee de facon inattendue. Ce n'est pas le cas courant sur Windows, mais c'est possible sur Linux.

Recommendation:

- Construire une URI correctement encodee, ou ouvrir autrement en read-only si possible.

## UI/UX Flask

### Parcours actuel

La page principale liste les saves, permet backup, watch/unwatch et rename sur chaque save, puis liste les 50 premiers backups avec restore/delete/note. Le flux principal est present, mais les actions rechargent toute la page et perdent l'etat d'expansion des cartes.

### Problemes UX

Fichiers:

- `src/pz_save_manager/gui.py:85-110`
- `src/pz_save_manager/gui.py:127-151`
- `src/pz_save_manager/gui.py:172-191`

Observations:

- Les cartes sont des `<div>` cliquables sans role, tabindex, ni support clavier (`src/pz_save_manager/gui.py:86`, `src/pz_save_manager/gui.py:128`).
- Les boutons icon-only settings/shutdown manquent de libelle accessible clair; shutdown a un `title`, settings non (`src/pz_save_manager/gui.py:76-77`).
- Les actions longues affichent seulement un bouton disabled puis un reload; pas de progression pour un backup/restauration volumineux.
- `doAction()` force un `location.reload()` apres chaque succes (`src/pz_save_manager/gui.py:178`), ce qui perd le contexte.
- Les erreurs serveur non JSON deviennent "Network error" car le code appelle toujours `r.json()` (`src/pz_save_manager/gui.py:177-180`).
- `toggleSettings()` n'a pas de `.catch()` et peut echouer silencieusement (`src/pz_save_manager/gui.py:189`).
- `prompt()` pour rename/note ne permet pas d'editer confortablement des notes longues et n'a pas de validation riche (`src/pz_save_manager/gui.py:186-187`).
- Texte melange anglais/francais: `manuel` dans une UI majoritairement anglaise (`src/pz_save_manager/gui.py:132`).
- Les thumbnails dans `src="/thumb/{{save.game_mode}}/{{save.full_name}}"` ne sont pas URL-encodees (`src/pz_save_manager/gui.py:87`, `src/pz_save_manager/gui.py:129`). Des noms contenant `?`, `#` ou `%` peuvent casser l'URL.

### Responsive/CSS

Fichier:

- `src/pz_save_manager/gui.py:24-68`

La CSS est compacte et les cartes devraient fonctionner sur mobile grace aux grids `auto-fill`, mais:

- Le header `display:flex; justify-content:space-between` sans wrap peut deborder sur petits ecrans avec les trois boutons de statut (`src/pz_save_manager/gui.py:28`, `src/pz_save_manager/gui.py:30`).
- Les styles inline nombreux rendent les etats focus/hover difficiles a harmoniser.
- Aucun style `:focus-visible` n'est defini pour la navigation clavier.
- Les couleurs muted sur fond sombre peuvent etre limites en contraste (`--muted:#8892b0` sur `--card:#16213e`).

### Ameliorations concretes

- Remplacer les headers de cartes par des `<button>` ou ajouter `role="button"`, `tabindex="0"`, `aria-expanded` et gestion Enter/Space.
- Ajouter un composant modal pour rename/note au lieu de `prompt()`.
- Mettre a jour seulement la carte concernee via AJAX au lieu de recharger toute la page.
- Ajouter des etats "backup en cours", "restore en cours", et empecher les doubles clics globalement sur la meme action.
- Ajouter `url_for()` ou des routes query-string pour les thumbnails: `/thumb?game_mode=...&save_name=...`.
- Ajouter un banner clair quand aucun save root n'est trouve, avec le chemin detecte et un lien vers `/health`.
- Ajouter pagination ou "Load more" pour les backups au lieu de `all_backups[:50]` (`src/pz_save_manager/gui.py:118`).

## User flows

### CLI

Commandes presentes:

- `list` / `list-saves`
- `backup`
- `list-backups`
- `restore`
- `delete`
- `gui`
- `config`
- `rename`
- `annotate`
- `install`

Points positifs:

- Les operations destructives `restore` et `delete` demandent confirmation (`src/pz_save_manager/cli.py:104-105`, `src/pz_save_manager/cli.py:121-122`).
- Les overrides `--saves-dir` et `--backups-dir` sont utiles pour tests et usages avances.

Manques ou incoherences:

- Pas de commande CLI pour demarrer le watcher sans GUI.
- `config` accepte des cles inconnues et les persiste (`src/pz_save_manager/cli.py:179`).
- Les erreurs de conversion de config (`float(value)`, `int(value)`) ne sont pas converties en `ClickException` (`src/pz_save_manager/cli.py:165-179`).
- La sortie `list-backups` n'indique pas auto/manual, age, taille, ni note, alors que ces infos existent dans `BackupRecord`.
- `backup` ne permet pas de definir une note au moment de la creation.
- `restore` exige un timestamp exact; une selection interactive ou affichage du dernier backup serait plus ergonomique.

### GUI

Le flux lister saves -> backup -> restore -> annoter -> renommer existe. Les points bloquants:

- Apres rename, si les backups ne suivent pas a cause d'une collision, l'utilisateur n'a pas de correction guidee.
- Les notes sont cachees dans les cards backup; pas de vue detail dediee.
- Les 50 backups maximum peuvent masquer des backups anciens sans message explicite.
- Le watcher demarre soit pour toutes les saves, soit par save, mais les reglages appliques divergent.

### Watcher

Le flow auto-backup n'est pas assez observable:

- Pas de dernier backup auto visible par save dans la card.
- Pas de raison affichee quand un evenement est ignore par cooldown ou mtime.
- Pas de log accessible dans la GUI.
- `auto_start_watcher` existe en config mais n'a pas d'effet.

Recommendation:

- Afficher par save: watched on/off, dernier auto-backup, prochain backup possible apres cooldown.
- Ajouter une petite page/log "Watcher activity".

## Tests

### Couverture existante

Tests lus:

- `tests/test_backup.py`
- `tests/test_adversarial.py`
- `tests/test_cli.py`
- `tests/test_gui.py`
- `tests/test_platforms.py`
- `tests/test_rename.py`
- `tests/test_saves.py`
- `tests/test_watcher.py`
- `tests/conftest.py`

La suite couvre bien:

- Cycle backup/restore/delete de base (`tests/test_backup.py:17-56`).
- Collision de timestamps concurrente (`tests/test_adversarial.py:52-84`).
- Symlink non suivi au restore (`tests/test_adversarial.py:30-49`).
- Cleanup failure au restore (`tests/test_adversarial.py:87-117`).
- Path traversal basique dans `get_save()` (`tests/test_adversarial.py:19-28`, `tests/test_saves.py:61-72`).
- CLI happy path (`tests/test_cli.py:19-45`).
- GUI index/API backup/restore invalid/watcher toggle minimal (`tests/test_gui.py:29-60`).
- Rename et pruning auto (`tests/test_rename.py:21-270`).
- Pause watcher pendant restore (`tests/test_watcher.py:48-95`).

### Gaps prioritaires

1. Sidecars internes:
   - Restore d'un backup auto/note ne doit pas copier `.pz-auto`/`.pz-note` dans la save live.
   - Un backup manuel apres restore ne doit pas etre classe auto.

2. Rename transactionnel:
   - Si `rename_backups_for_save()` echoue, la save live ne doit pas avoir ete renommee.
   - Meme test via CLI et route `/api/save/rename`.

3. Watcher timers:
   - Timer pending + `manager.stop()` -> aucun backup.
   - Timer pending + `manager.unwatch()` -> aucun backup.
   - Deux `_do_backup()` concurrents -> un seul backup si cooldown actif.

4. Config appliquee:
   - `/api/watcher/save` respecte `backup_cooldown_minutes` et `debounce_seconds`.
   - `auto_start_watcher` soit teste, soit retire.
   - CLI `gui` respecte `port` config si c'est le comportement voulu.

5. Securite Flask:
   - POST sans token refuse quand CSRF est ajoute.
   - `/health` et page erreur echappent les noms contenant HTML.
   - `/api/shutdown` protege.

6. `save_info.py`:
   - Aucun test dedie aujourd'hui.
   - Ajouter tests pour `mods.txt`, `map_ver.bin`, `players.db`, `vehicles.db`, `InGameMap.ini`, fichiers corrompus, DB schema manquant, chemins avec caracteres speciaux.

7. Installer:
   - Verifier que `install_linux()` pointe vers un launcher existant.
   - Tester absence de `pywin32` sur Windows ou isoler derriere extra.

8. GUI template/JS:
   - Tester que les URLs de thumbnails fonctionnent avec espaces et caracteres reserves.
   - Tester les erreurs serveur non JSON.
   - Eventuellement ajouter tests Playwright/a11y si la GUI devient un axe important.

## Recommandations d'ordre d'execution

1. Corriger la contamination `.pz-*` au restore/create backup et ajouter les tests associes.
2. Rendre le rename save+backups transactionnel ou preflighte.
3. Annuler les timers watcher dans `stop()`/`unwatch()` et verrouiller `_do_backup()`.
4. Clarifier et appliquer la configuration watcher/port/auto-start dans un seul chemin.
5. Ajouter protection CSRF/token pour les routes POST et echappement HTML sur diagnostics.
6. Extraire progressivement le template GUI si de nouvelles fonctionnalites UI sont ajoutees.

