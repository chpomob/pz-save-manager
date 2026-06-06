# Code Review — pz-save-manager

## Executive Summary

The codebase has sound low-level invariants (symlink skipping, path traversal guard, restore rollback), but two critical architectural gaps undermine them: **(1) a fully unauthenticated HTTP API that can create/restore/delete backups, mutate config, rename saves, and kill the process**, and **(2) a non-atomic backup creation procedure where a crash leaves a partial/empty directory that the listing and restore code treat as a valid backup — a concrete data-loss path.** Several major bugs in configuration plumbing, performance hot paths, and error handling complete the picture. The single-threaded Flask default limits some race conditions, but watcher and config concurrency issues remain real.

**Verdict:** REJECT — 3 blockers, 12 majors, 10 minors/nits, 2 disputed.

---

## 🟢 Cross-Validated Findings (high confidence)

Both reviewers independently identified these. Fix them first.

### 🔴 BLOCKER

| ID | Severity | File:Line | Title |
|----|----------|-----------|-------|
| **A1** | blocker | `gui.py:335+` | **Unauthenticated HTTP API for all destructive operations** — Every mutating endpoint (`/api/backup`, `/api/restore`, `/api/backup/delete`, `/api/save/rename`, `/api/config`, `/api/watcher/*`, `/api/shutdown`) requires no authentication, no CSRF token, and no Origin/Host validation. `--host` exposes this to arbitrary bind addresses. Body-bearing endpoints are partially shielded from classic form CSRF (they require `Content-Type: application/json`, triggering CORS preflight), but `/api/shutdown` and `/api/watcher/toggle` take no body and remain fully CSRF-able. **Fix:** Require a per-session random token for all mutating endpoints; validate Origin/Host; refuse non-loopback binds unless auth is explicitly configured. |
| **A3** | blocker | `backup.py:194-201` | **Backup creation is not atomic — crash leaves a partial/empty directory that looks valid** — `_unique_destination` creates the final destination directory via `mkdir(exist_ok=False)` *first*, then `copytree` copies into a sibling temp dir, and contents are moved item-by-item into the already-visible destination. If the process dies mid-copy/mid-move, the directory remains as a partial or empty backup. `list_backups` and `get_backup` accept any directory unconditionally, so a subsequent restore from that partial backup overwrites the live save with incomplete content → **silent data loss.** Also: the sibling `.tmp-*` temp dir surfaces as a restorable backup during the copy. **Fix:** Copy fully into a temp directory outside the visible backup namespace, then atomically `rename(temp → destination)` as the final step, and require a completion marker before listing/restore/delete accept a directory. |

### 🔴 MAJOR

| ID | Severity | File:Line | Title |
|----|----------|-----------|-------|
| **A2+B_xA** | major* | `backup.py:306-314`, `gui.py:462` | **Backup deletion trusts directory shape; arbitrary-key config writes create the escalation path** — `delete_backup` calls `rmtree` on any directory under `backups_dir` whose component names pass basic character filters. `backups_dir` is user-configurable with no validation against `/`, `$HOME`, or the saves root. Setting `backups_dir='/'` makes `delete(game_mode='home', save_name='<user>', timestamp='Documents')` → `rmtree /home/<user>/Documents`. This is a footgun standing alone; it becomes **remote arbitrary-delete in combination with A1**, because `api_config` accepts arbitrary unvalidated keys (no allowlist, no value validation for `backups_dir`), letting an attacker `POST /api/config {backups_dir:'/'}` then `POST /api/backup/delete` — and the malicious config survives restart. **(B_xA filed separately; consolidated here.)** **Fix:** Add a key allowlist and validate `backups_dir` (canonicalize, reject `/`, home dir, saves root) at the config boundary. Add a manager-owned metadata marker so backup ops only act on known backups. |
| **A4** | major | `gui.py:396-403` | **Save rename is not transactional** — `api_rename_save` renames the live save first, then the backup history, then updates watchers. If `rename_backups_for_save` fails (permissions, IO error, TOCTOU race past `preflight_rename`), the live save is already renamed but backups are orphaned under the old name and watcher state is stale, breaking the save↔history identity invariant. `preflight_rename` reduces the most common failure, so practical blast radius is narrower, but the invariant violation is real. **Fix:** Move to a domain service with staged temp-name renaming; commit only when both sides succeed, with rollback on failure. |
| **B4** | major | `gui.py:360` | **`index()` does O(all-backups) SQLite reads for only 50 rows** — Loop builds detailed backup info (including `players.db` open + `note` read) for *every* backup across *every* save, then template slices to `[:50]`. With hundreds/thousands of backups this opens hundreds of SQLite connections per page load while discarding most of the work. **Fix:** Slice before the loop: `for b in all_backups[:50]:`. |
| **B5** | major | `gui.py:320` | **`_save_info` computes per-save `list_backups` never rendered** — Calls `list_backups(save.game_mode, save.name)` for every save, building a 5-element list into the returned dict. The saves card template never references `save.backups`. Wasted directory-walk per save on the hot page-render path. **Fix:** Remove the unused per-save `list_backups` computation. |
| **B6** | major | `cli.py:205` | **CLI config value conversion raises uncaught `ValueError`** — `config_command` does `value = float(value)` / `int(value)` with no try/except. `pz-saves config debounce_seconds abc` raises an unhandled exception with full Python traceback instead of a friendly `ClickException`. **Fix:** Wrap in try/except, raise `click.ClickException`. |
| **B7** | major | `watcher.py:110` | **`_do_backup` holds lock across entire `copytree`** — `create_backup` (full directory copy, potentially seconds to minutes) runs under `self._lock`, which blocks `on_modified` (watchdog observer thread), `pause`, `cancel_pending`, and `resume`. A restore's `pause_for()` can be forced to wait for an in-flight backup. **Fix:** Read/update bookkeeping under lock, release lock, run `create_backup` outside it; guard re-entrancy with an `_in_progress` flag. |

\* A2 is marked as "blocker" by Reviewer A in combination with A1; classified here as major standalone (footgun requiring misconfiguration). B_xA provides the remote escalation path.

---

## 🟡 Consensus Findings

One reviewer found, the other explicitly validated in cross-review. Fix these.

### 🔴 MAJOR

| ID | Severity | File:Line | Title |
|----|----------|-----------|-------|
| **B2** | major | `backup.py:247` | **`list_backups` surfaces in-progress `.tmp-*` and empty destination dirs as backups** — No dotfile/temp-dir filter. Concurrent backups and orphaned post-crash `.tmp-*` dirs appear as restorable backups. Restoring them yields garbage/empty saves. **(Related to A3; fix together.)** |
| **B3** | major | `gui.py:470` | **Debounce/cooldown config inconsistent between watch entry points** — `api_watcher_toggle` passes only `cooldown` (with a `.get(..., 5)` fallback), ignoring `debounce_seconds`. `api_watcher_save` (per-save Watch button) passes no arguments, using hardcoded 300s cooldown / 5s debounce. Defaults conflict: `config.DEFAULTS['backup_cooldown_minutes']` = 1, `SaveWatcher` default = 300s, GUI fallback = 5. **Fix:** Centralize watcher config reading in one place. |

### 🟡 MINOR

| ID | Severity | File:Line | Title |
|----|----------|-----------|-------|
| **A6** | major* | `gui.py:253,264,269` | **Diagnostics leak tracebacks and filesystem details** — Index error handler renders `escape(tb)` (full traceback) to browser. `/health` exposes Python version, `sys.executable`, absolute paths, save names, directory listings. For the default loopback single-user desktop deployment, this is the user's own data → low intrinsic risk. Escalates to a real info leak only when bound non-loopback (inherits severity from A1). **Reclassified as minor; escalates to major under A1. Fix:** Generic error page, log server-side, gate `/health` behind auth/debug mode. |
| **B8** | minor | `backup.py:322` | **`rename_backups_for_save` collision handling platform-dependent, contradicts docstring** — Docstring says it "Raises BackupError if the new name already has backups," but no explicit check exists — it relies on `rename` failing. On POSIX, `rename` onto an existing *empty* directory succeeds silently. The existing `preflight_rename` check in callers reduces blast radius. **Fix:** Add explicit `if new_dir.exists(): raise BackupError(...)`. |
| **B13** | minor | `save_info.py:92` | **`player_info` conflates NULL coordinates with `0`** — `"x": round(row[2]) if row[2] else 0` maps both `None` and genuine `0.0` to `0`, making it impossible to distinguish "unknown" from "at origin." **Fix:** Use explicit `is not None` check. |
| **B14** | minor | `tests/test_watcher.py:22` | **Debounce test doesn't verify backup behavior** — Only asserts `watcher._last_event > 0` was set; does not verify the debounce timer fires or that backup suppression works. Comment admits "backup may fail in test." **Fix:** Monkeypatch `create_backup` and assert it is invoked once after debounce interval, not before. |
| **B15** | minor | `config.py:70` | **`set_` read-modify-write not synchronized** — Two concurrent `set_` calls can interleave `_load()`/`_save()`, causing lost updates. File write is atomic (`temp + os.replace`), but the read-modify-write is not. **(Guard with `threading.Lock`.)** |
| **B17** | minor | `save_info.py:45` | **`map_name` ASCII fallback can return binary garbage** — Fallback scans every byte 32..126 across the file remainder, takes first 80 chars as a "map name." For binary files this produces meaningless ASCII soup surfaced in the UI. **Fix:** Return `None` when confidence is low; require contiguous printable runs. |
| **B20** | minor | `gui.py:540` | **`api_shutdown` falls back to `os._exit`** — `werkzeug.server.shutdown` was removed in Werkzeug 2.1+, so the 3s Timer fallback to `os._exit(0)` is the real path. Bypasses atexit/finally; could interrupt in-flight write operations. **Fix:** Document that `os._exit` is the mechanism; join all write operations before shutdown. |

### 🟡 NITS

| ID | Severity | File:Line | Title |
|----|----------|-----------|-------|
| **B9** | nit | `save_info.py:137` | Dead initial assignments (`total/vanilla/modded = 0`) overwritten before use. |
| **B10** | nit | `saves.py:110` | `_should_skip` returns `re.Match|None`, not `bool`, despite annotation. |
| **B11** | nit | `watcher.py:30` | `on_backup: callable` uses builtin predicate, not `typing.Callable`. |
| **B12** | nit | `cli.py:150` | Unused `import flask` in `--no-browser` branch. |
| **B16** | minor† | `watcher.py:195` | `get_backups` reads `_watchers[key]._backups` without lock, while `_do_backup` appends under lock. On CPython, list copying is unlikely to crash but yields a racey snapshot. |
| **B19** | nit | `backup.py:49` | Underscore loop variable `_` dereferenced in `file_count`/`size_mb` — misleading convention. |

† B16 was validated by Reviewer A with the caveat that "can raise" is overstated on CPython but the racey snapshot concern stands.

---

## 🔴 Disputed Findings

| ID | Positions |
|----|-----------|
| **A5** | **Reviewer A (major):** *"WatcherManager mutates shared observer state without synchronization — concurrent Flask requests can race on watcher toggles, renames, duplicate watches, or two singleton managers."* **Reviewer B (challenge):** *"Overstated. `app.run(debug=False)` uses Werkzeug with `threaded=False` (confirmed); nothing sets `threaded=True` or `processes>1`. Request handlers are serialized. Watchdog observer and Timer callbacks only enter `SaveWatcher._do_backup`, which is guarded by `SaveWatcher._lock` and doesn't touch `WatcherManager` dicts. No cross-thread mutation of unsynchronized state occurs today. Valid as latent/defense-in-depth concern (becomes real under gunicorn or `threaded=True`), but as written claims an active bug that the single-threaded server prevents. Downgrade to minor latent/hardening."* **Rapporteur's assessment:** B's challenge is technically correct for the shipped configuration. A5 should be accepted as a hardening item (add `RLock`, serialize observer lifecycle) but not as an active race bug. Classify as **minor/latent**. |
| **B18** | **Reviewer B (minor):** *"`watch()` schedules on a dead Observer after `stop()` — `start()` recreates it, but the initial schedule on dead observer is fragile."* **Reviewer A (challenge):** *"Not a demonstrated bug. The normal fresh-manager path also calls `watch()` before `start()`, and `start()` reschedules from `_watchers`. Without evidence watchdog raises or starts emitters on a dead Observer, this is at most unnecessary bookkeeping."* **Rapporteur's assessment:** A's challenge is reasonable. No demonstrated failure mode. Downgrade to **nit/cleanup** — add a guard to only schedule when `_observer.is_alive()`. |

---

## Summary Statistics

| Category | Count |
|----------|-------|
| Cross-validated blockers | 2 (A1, A3) |
| Cross-validated majors | 5 (A2/B_xA, A4, B4, B5, B6, B7) |
| Consensus majors | 2 (B2, B3) |
| Consensus minors | 7 (A6, B8, B13, B14, B15, B17, B20) |
| Consensus nits | 5 (B9, B10, B11, B12, B16, B19) |
| Disputed | 2 (A5, B18) |
| **Total unique findings** | **23** |

By severity: **3 blockers** · **7 majors** · **7 minors** · **6 nits**

---

## Recommendations

1. **Fix the atomicity of backup creation (A3, B2) first** — this is the concrete data-loss path. Keep in-progress backups outside the visible namespace and add a completion marker.
2. **Add authentication to all mutating endpoints (A1)** — a per-session random token, Origin/Host validation, and a loopback-only guard unless auth is explicitly configured. This closes the remote escalation path for A2, A6, and B_xA.
3. **Add a config key allowlist and validate `backups_dir` at the config boundary (A2, B_xA)** — reject `/`, home directory, saves root; canonicalize; require a manager-owned metadata marker before backup ops treat a directory as valid.
4. **Centralize watcher config (B3)** — single code path for debounce/cooldown, reading from config in one place.
5. **Fix the performance hot paths (B4, B5)** — slice before the loop and remove unused `_save_info` `list_backups`.
6. **Fix CLI error handling (B6)** — wrap numeric conversions in try/except.
7. **Narrow lock scope in `_do_backup` (B7)** — release lock before `copytree`.
8. **Review disputed items A5 and B18 with a human** — determine whether to accept as hardening or defer.
9. **Address the remaining minors and nits** as time permits — none are blockers but collectively improve robustness and maintainability.