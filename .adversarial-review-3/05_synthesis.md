# Code Review — pz-save-manager

## Executive Summary
The filesystem safety core (TOCTOU-safe backup creation, path-traversal guards, symlink skipping, atomic config writes) is solid and well-tested. However, the Flask HTTP layer has **zero authentication or CSRF protection** over destructive endpoints, the `WatcherManager` has **multiple concurrency races** under the default threaded server, and backup atomicity is **incomplete** (partial backups indistinguishable from complete ones). Combined with duplicated validation logic and several config-propagation bugs, the tool needs hardening at the HTTP, threading, and backup-publication boundaries.

---

## 🟢 Cross-Validated Findings (high confidence)
*Found independently by both reviewers.*

| ID | Severity | File | Line(s) | Category | Description |
|----|----------|------|---------|----------|-------------|
| CV1 | **🔴 MAJOR** | `backup.py` | 160–202, 245–248 | bug | **Backup is visible before complete.** `_unique_destination` reserves the final timestamp directory via `mkdir` before any data is written; `copytree` writes into a sibling `.tmp-*` dir in the same parent; items are moved one-by-one into the final destination. `list_backups()` accepts **any** directory (no timestamp/dot filtering), so the empty final directory and stale `.tmp-*` sibling are returned as valid `BackupRecord`s. A crash mid-copy leaves both permanently. Restoring the empty one restores an empty save. |
| CV2 | **🔴 MAJOR** | `watcher.py` | ~95–135 | concurrency | **`_do_backup` holds the watcher lock across the entire `copytree`.** The lock serializes small bookkeeping (timer/timestamps) but also long I/O (hundreds of MB). This stalls `on_modified()`, `pause()`, `resume()`, and `cancel_pending()` for the full copy duration, defeating debouncing and backing up the watchdog event queue. |

---

## 🟡 Consensus Findings
*Found by one reviewer, validated by the other in cross-review (not challenged).*

### 🔴 MAJOR

| ID | Severity | File | Line(s) | Category | Description |
|----|----------|------|---------|----------|-------------|
| C1 | **🔴 MAJOR** | `gui.py` | 1 (global) | security | **No auth/CSRF/Host protection on mutating endpoints.** `/api/restore`, `/api/backup/delete`, `/api/save/rename`, `/api/config`, `/api/shutdown`, and `/api/watcher/toggle` are all unauthenticated POST routes. No Host header allow-list, no CSRF token, no Origin/Referer check. Reachable via DNS rebinding (malicious site rebinds to 127.0.0.1) and same-origin requests to port 8080. `--host 0.0.0.0` exposes all to LAN with zero auth. (Reviewer B missed this, then explicitly validated it as `your_miss: true`.) |
| C2 | **🔴 MAJOR** | `watcher.py` | ~120–160 | concurrency | **WatcherManager mutates shared state without synchronization.** Under Flask's default `threaded=True`, `/api/watcher/toggle`, `/api/watcher/save`, `/api/restore` (via `pause_for`), and `/api/save/rename` execute concurrently. All mutate `_watchers`, `_watches`, `_running`, and call `_observer.schedule/unschedule` with no lock. Races can corrupt watch maps, double-schedule observers, or crash a request. (Reviewer B missed this, validated in cross-review.) |
| C3 | **🔴 MAJOR** | `watcher.py` | ~205 | concurrency | **`get_manager()` lazy singleton has a check-then-act race.** Two concurrent first requests can both observe `_manager is None` and each construct a separate `WatcherManager` (each with its own `Observer`). The discarded instance may already be started/scheduled, leaking an observer thread and producing inconsistent state. (Reviewer B missed this, validated in cross-review.) |
| C4 | **🔴 MAJOR** | `backup.py` | ~357–361 | bug | **Backup rename does not normalize the new name.** `rename_save` strips whitespace via `new_name.strip()`, but `rename_backups_for_save` uses the raw `new_save_name`. A CLI rename with surrounding whitespace (e.g., `'  Clean  '`) moves the save to `'Clean'` but backups to `'  Clean  '`, splitting history. `preflight_rename` normalizes only for its own collision check, masking the inconsistency. (Reviewer A validated this in cross-review.) |
| C5 | **🔴 MAJOR** | `gui.py` | ~205–217 | bug | **Unknown player state renders as alive.** `_save_info` only copies `player_dead`/`player_x`/`player_y` into `info` when present in `extra`. For saves without `players.db`, `extract_all` omits these keys entirely. In Jinja2, a missing dict key is `Undefined`, not `None`: `Undefined is none` → `False` → falls through to "🟢 Alive", and `Undefined is not none` → `True` → renders `'(, )'` with blank coordinates. Misreports save state on main UI cards. Backup cards are not affected (they use `pi.get('is_dead')`). (Reviewer A validated this in cross-review.) |
| C6 | **🔴 MAJOR** | `cli.py` | ~143 | bug | **GUI command ignores global directory overrides.** The Click group stores `--saves-dir`/`--backups-dir` in `ctx.obj`, but `gui_command` lacks `@click.pass_context`, so `run_gui()` always uses default/config directories. `pz-saves --saves-dir X --backups-dir Y gui` silently ignores X and Y. (Reviewer A validated this in cross-review.) |
| C7 | **🔴 MAJOR** | `installer.py` | ~12 | bug | **Installer shortcuts point at wrong launcher location.** `PROJECT_DIR = Path(__file__).parent.parent` resolves to `src/` (or site-packages when pip-installed). `launcher.sh`/`launcher.bat` live one level above in the repo root, so generated `.desktop` Exec and Windows shortcut `TargetPath` are broken. No existence check before writing. (Reviewer A validated this in cross-review.) |

### 🟠 MINOR

| ID | Severity | File | Line(s) | Category | Description |
|----|----------|------|---------|----------|-------------|
| C8 | 🟠 MINOR | `gui.py` | ~372 | security | **`/api/config` writes arbitrary keys with no allow-list.** Any key in the posted JSON is persisted via `config_set()`. No allow-list of known `DEFAULTS` keys. Can pollute `config.json` or repoint `backups_dir` to arbitrary user-writable paths. (Reviewer B validated this in cross-review.) |
| C9 | 🟠 MINOR | `backup.py` / `saves.py` | multiple | design | **Path-component validation duplicated three ways.** `get_save()` inline check (rejects `..`, `/`, `\`, `\x00`), `saves._validate_name()` (adds empty/IP/length/`_SANE_NAME_RE`), and `backup._validate_component()` (adds empty/`'.'`/timestamp) diverge subtly. `CLAUDE.md` explicitly says to reuse `_validate_component`. Security boundary drift risk. (Reviewer B validated this in cross-review.) |
| C10 | 🟠 MINOR | `gui.py` | ~339–451 | bug | **Per-save watcher ignores configured cooldown.** `api_watcher_toggle` passes `backup_cooldown_seconds` from config, but `api_watcher_save` (`Watch` button for a single save) calls `manager.watch(save)` with hardcoded defaults (cooldown=300s, debounce=5s). Different auto-backup timing depending on which UI control is used. (Reviewer A validated this in cross-review.) |
| C11 | 🟠 MINOR | `gui.py` | ~430–451 | bug | **Configured `debounce_seconds` never applied on any watch path.** Neither `api_watcher_toggle` nor `api_watcher_save` ever passes `debounce_seconds` from config to `manager.watch()`. All watch paths fall back to the hardcoded 5.0s default, even though config exposes/accepts `debounce_seconds`. (Reviewer A added this in cross-review based on code analysis; Reviewer B had no objection.) |
| C12 | 🟠 MINOR | `watcher.py` | ~149–150 | bug | **Existing watcher settings never update.** `WatcherManager.watch()` returns an existing watcher unchanged when the key is already present, never applying new debounce/cooldown values. After changing settings and restarting the watcher, previously watched saves keep stale timing. (Reviewer A validated this in cross-review.) |
| C13 | 🟠 MINOR | `backup.py` | multiple | architecture | **No backup completion marker.** `create_backup` reserves the destination dir first, copies into sibling temp, then moves items one-by-one. No sentinel file (e.g., `.pz-complete`) is written as final step. A crash mid-move leaves a half-populated directory that `list_backups()` treats as a complete and restorable backup. (Reviewer B validated this in cross-review.) |
| C14 | 🟠 MINOR | `save_info.py` | ~164 | edge_case | **`count_players` can raise despite defensive extractor contract.** `path.stat()` is called outside the `try` block after `is_file()`. A TOCTOU deletion between calls raises `FileNotFoundError` (OSError subclass), escaping the module contract that extractors return `None`/defaults on any failure. `count_vehicles` and other extractors do not have this issue. (Reviewer A validated this in cross-review.) |
| C15 | 🟠 MINOR | `cli.py` | ~166–177 | error_handling | **Invalid CLI config values not converted to `ClickException`.** `config_command` does `float()`/`int()` outside `try/except`, so `pz-saves config port abc` raises raw `ValueError` with traceback. Other commands (backup, restore) wrap errors in `ClickException`. GUI `api_config` already wraps identical conversions with 400. (Reviewer A validated this in cross-review.) |

### ⚪ NIT

| ID | Severity | File | Line(s) | Category | Description |
|----|----------|------|---------|----------|-------------|
| C16 | ⚪ NIT | `gui.py` | ~339 | design | **Inconsistent default for `backup_cooldown_minutes`.** `config_get_all().get('backup_cooldown_minutes', 5)` hardcodes `5` as fallback, but `config.DEFAULTS` sets it to `1`. Since `get_all` always merges defaults, the literal `5` is dead code — but still misleading. (Reviewer B validated this in cross-review.) |
| C17 | ⚪ NIT | `cli.py` | ~158 | design | **Dead import in `--no-browser` branch.** `gui_command --no-browser` does `import flask` but never uses it, then duplicates the `app.run` startup path instead of reusing `run_gui` with browser opening disabled. (Reviewer B validated this in cross-review.) |

### ⚠️ PARTIAL — Downgraded in cross-review

| ID | Severity | File | Line(s) | Category | Description |
|----|----------|------|---------|----------|-------------|
| P1 | ⚠️ MINOR | `watcher.py` | ~100 | bug | **Watcher backs up by default roots instead of watched path.** `SaveWatcher` stores a `SaveGame` with an explicit `.path`, but `_do_backup` calls `create_backup(game_mode, name)` which re-resolves via `get_save()` against the default saves root. **Downgrading**: Reviewer A validated the code pattern but noted that all current callers use default roots, so the watched path always matches the default resolution and no actual misdirected backup occurs today. Latent correctness gap, not an active major bug. |

---

## 🔴 Disputed Findings

| ID | Positions |
|----|-----------|
| **B2** | **Reviewer B (original)**: `restore_backup` only catches `OSError` but `shutil.copytree` can raise `shutil.Error` for aggregated copy failures, which would escape the `except OSError` block, skip cleanup/rollback, and reach the caller as an uncategorized exception instead of `BackupError`.<br><br>**Reviewer A (cross-review challenge)**: In CPython 3, `shutil.Error` is defined as `class Error(OSError): pass` — it **is** a subclass of `OSError`. The `except OSError` at line 290 **does** catch `shutil.Error`, the cleanup path runs, and the error is wrapped in `BackupError`. The described gap does not exist. Broadening to `except Exception` would be defensible but is not necessary for this specific case. |

---

## Summary Statistics

| Category | Count |
|----------|-------|
| 🟢 Cross-validated | 2 |
| 🟡 Consensus (validated) | 17 |
| ⚠️ Partial (downgraded) | 1 |
| 🔴 Disputed | 1 |
| **Total unique findings** | **21** |
| 🔴 MAJOR (blocker-level) | 8 |
| 🟠 MINOR | 9 |
| ⚪ NIT | 2 |
| 🏷️ Added in cross-review (new) | 1 |

---

## Recommendations

### Immediate (P0 — fix before next release)
1. **Fix backup publication atomicity (CV1 + C13):** Either copy fully into a hidden temp directory that `list_backups()` explicitly ignores and do a single atomic rename, or add a `.pz-complete` sentinel as the final step. Filter `list_backups()` to timestamp-shaped directories and skip dot-prefixed entries.
2. **Add HTTP protection (C1):** Validate `Host` header against `127.0.0.1:PORT` / `localhost:PORT`, require `Origin`/`Referer` same-origin check on all mutating POST routes, or generate a startup token required as a header on `/api/*` calls. Reject `--host 0.0.0.0` unless an explicit `--allow-remote` flag is provided.
3. **Fix WatcherManager concurrency (C2, C3, C4):** Add a `threading.RLock` guarding `_watchers`/`_watches`/`_running`/`_observer`. Make `get_manager()` thread-safe (double-checked locking or eager init). Move `create_backup()` outside the `SaveWatcher._lock` critical section.

### High priority (P1)
4. **Normalize backup rename paths (C5):** Strip whitespace in `rename_backups_for_save` before constructing `new_dir`. Add integration test for whitespace rename with backups.
5. **Fix GUI player state rendering (C6):** Initialize `player_dead`, `player_x`, `player_y` to `None` in `_save_info` info dict before merging, or use Jinja `defined` checks.
6. **Propagate CLI roots to GUI (C7):** Add `@click.pass_context` to `gui_command` and thread `ctx.obj` into the GUI layer.
7. **Fix installer launcher paths (C8):** Compute `PROJECT_DIR` relative to the actual launcher file location, and validate target existence before writing shortcuts.

### Medium priority (P2)
8. **Add config allow-list (C9):** Restrict `/api/config` writes to known `DEFAULTS` keys; validate `backups_dir` is an absolute, writable directory.
9. **Centralize validation (C10):** Unify `get_save`, `_validate_name`, and `_validate_component` into one `validate_component(value, label)` function, keeping the strictest superset.
10. **Fix watcher config propagation (C11, C12, C13):** Read `debounce_seconds` and `backup_cooldown_minutes` from config consistently in both watch entry points; update existing watchers when re-watched with new settings.
11. **Fix `count_players` TOCTOU (C15):** Move `stat()` inside the `try` block or wrap the whole existence/size check in `try/except OSError`.
12. **Fix CLI config error handling (C16):** Wrap `float()`/`int()` conversions in `try/except (ValueError, TypeError)` → `click.ClickException`.

### Low priority (P3)
13. **Remove dead default literal (C17):** Drop the `.get('backup_cooldown_minutes', 5)` fallback; rely on `DEFAULTS`.
14. **Clean up `--no-browser` branch (C18):** Remove unused `import flask`; refactor `run_gui` to accept an `open_browser: bool` flag.
15. **Make `SaveWatcher` carry roots (P1):** Pass `saves_root`/`backups_root` through `SaveWatcher` → `_do_backup` → `create_backup` for correctness under non-default roots.

### Human review required
16. **B2 (disputed):** Reviewer B says `shutil.Error` escapes `except OSError`; Reviewer A demonstrates it subclasses `OSError`. Broadening to `except Exception` is a safe defensive choice regardless, but the specific claimed vulnerability does not exist in Python 3.