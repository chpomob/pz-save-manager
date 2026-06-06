# Code Review — pz-save-manager

## Executive Summary
9 unique major findings (4 cross-validated, 5 consensus) and 11 minor/edge findings across 6 files. The core backup logic is sound (TOCTOU-safe atomic creation, symlink skipping), but concurrency bugs in watcher/manager/config pose silent data-loss risks, and the GUI auth model matches local-desktop norms but has narrow CSRF exposure. Fix concurrency and invariant bugs first; treat auth as a hardening item.

---

## 🟢 Cross-Validated Findings (high confidence)

Both reviewers independently identified these. Fix first.

### 🔴 MAJOR

| ID | Severity | File | Line | Description |
|----|----------|------|------|-------------|
| **A6/B3** | major | `watcher.py` | ~100 | **`_do_backup` holds `self._lock` across entire `create_backup()` call** — blocks pause/cancel/on_modified for 30–120s during large-save copies. Restore requests stall waiting for pause(), making shutdown/unwatch unresponsive. Cross-validated by both reviewers. |
| **A4** | major | `watcher.py` | ~119 | **`WatcherManager` has no lock over `_observer`, `_watchers`, `_watches`, `_running`** — concurrent Flask routes (threaded by default) can double-schedule saves, unschedule during start, or observe inconsistent state. A4 by Architect, validated by Inspector's cross-review. |
| **A5** | major | `config.py` | ~52 | **Config `set_()` does load-modify-save without file lock** — concurrent `api_config` requests each overwrite the same old config. Multi-key writes are not atomic (each key persisted independently). A5 by Architect, validated by Inspector. |
| **A7** | major | `backup.py` | ~169 | **Backup directory exposed before content is complete** — `_unique_destination` creates the final destination dir before copy starts; `list_backups` treats any directory as valid. A concurrent restore/delete sees an incomplete backup. A7 by Architect, validated by Inspector. |

### 🟡 MINOR

| ID | Severity | File | Line | Description |
|----|----------|------|------|-------------|
| **A8** | minor | `backup.py` | ~152 | **`max_auto_backups=0` silently disables pruning** — docstring says "at most max_count remain" but `<= 0` returns immediately. GUI `min='1'` prevents setting via UI, but direct config edit or `/api/config` bypass this. Semantic contract broken. |

---

## 🟡 Consensus Findings (single reviewer, validated by the other)

Found by one reviewer, not challenged in cross-review. Fix after cross-validated items.

### 🔴 MAJOR

| ID | Severity | File | Line | Description |
|----|----------|------|------|-------------|
| **A3** | major | `gui.py:403` (rename), `backup.py` | ~288 | **Rename flow is not transactional** — `rename_save` succeeds but `rename_backups_for_save` can fail (permissions, cross-device, concurrent creator after preflight), leaving live save under new name and backup history under old name. No rollback attempted. Both reviewers confirmed. |
| **B1** | major | `backup.py` | ~214 | **`get_backup()` always returns `auto=False`** — never reads `.pz-auto` marker file. Direct callers (annotate/restore/delete routes) get wrong metadata. `list_backups()` reads it correctly, so index cards are fine, but the returned `BackupRecord.auto` is always `False`. |
| **B2** | major | `watcher.py` | ~177 | **`get_manager()` singleton race** — unlocked `if _manager is None: _manager = WatcherManager()`. Two concurrent threads can create two `WatcherManager` instances; second orphaning the first's observer and registered watches. Cross-review B added this as N1; both reviewers agree. |
| **DA2** | major | `watcher.py` | ~119 | **`WatcherManager.watch/unwatch/start/stop` mutate shared state unsynchronized** — even after fixing singleton creation, these methods lack a manager-level lock. Concurrent Flask requests can double-schedule, unschedule during start, or observe inconsistent state. Related to A4 but distinct (A4 identifies absence of lock; DA2 specifies the consequence across methods). |
| **B7** | major | `gui.py` | ~348 | **Per-save watcher ignores configured `backup_cooldown_minutes`** — `api_watcher_save` calls `manager.watch(save)` without passing cooldown, defaulting to hardcoded 300s. Global watcher button respects config, but per-save 👁 button doesn't. Also worsens DA1 (rename also drops configured cooldown). |

### 🟡 MINOR

| ID | Severity | File | Line | Description |
|----|----------|------|------|-------------|
| **B4** | minor | `save_info.py` | ~58 | **Falsy coordinate check treats `x=0.0` and `NULL` identically** — `row[2] if row[2] else 0` converts `None` (NULL in DB) to `0`, making unknown positions appear known. `round(0.0)` also returns `0`, so actual-zero and missing are indistinguishable. GUI shows `(0, 0, 0)` for missing data. |
| **B6** | minor | `cli.py` | ~153 | **CLI config casts raise raw `ValueError`** — `float(value)`/`int(value)` on bad input produces a Python traceback, not a clean Click error. Affects `debounce_seconds`, `backup_cooldown_minutes`, `max_auto_backups`, `port`. |
| **B8** | minor | `gui.py` | ~182 | **Backup list silently truncated at 50** — `{% for b in all_backups[:50] %}` with no indication that older entries exist. User with 51+ backups sees missing entries with no explanation. |
| **B5** | minor | `save_info.py` | ~52 | **`sqlite3.Connection` context manager doesn't close** — `with sqlite3.connect(...)` only commits/rolls back, doesn't call `.close()`. Inspector flagged accumulating handle leak; Architect challenged that CPython GC reclaims locals. Both agree `contextlib.closing()` would be cleaner and more portable (especially Windows). **Downgraded from "bug" to "minor/quality" by cross-review consensus.** |
| **N3** | minor | `backup.py` | ~263 | **`rename_backups_for_save` relies on OS error for collision detection** — `old_dir.rename(new_dir)` fails with `OSError: Directory not empty` on Linux, caught and re-raised as generic `BackupError`. `preflight_rename` has a clearer explicit check; adding it guard-level would improve diagnostics. |
| **DA1** | minor | `gui.py` | ~403 | **Renaming a watched save drops configured cooldown** — `api_rename_save` recreates watcher via `manager.watch(new_save)` without passing `backup_cooldown_seconds`. Save reverts to 300s default after rename. |

---

## ⚠️ Partial / Downgraded Findings

Findings where cross-review adjusted severity or scope.

| ID | Original | After Cross-Review | Rationale |
|----|----------|-------------------|-----------|
| **B3** | major bug (inotify overflow, silent event loss) | **Incorporated into A6/B3** — the lock-holding issue is cross-validated; the inotify-overflow mechanism was challenged. The core problem (long I/O under lock) stands. |
| **B5** | minor bug (accumulating file handle leak) | **Kept as minor** — real issue on Windows/pre-3.13 CPython; Architect noted GC reclaims locals so "accumulating across long session" is overstated. Both agree `contextlib.closing()` is the right fix regardless. |

---

## 🔴 Disputed Findings

| ID | Original Severity | Positions |
|----|-------------------|-----------|
| **A1** | major (security) | **Architect**: Unauthenticated GUI exposes destructive filesystem operations. CSRF possible on `/api/shutdown` and `/api/watcher/toggle` (no JSON body required). `--host 0.0.0.0` exposes to LAN. **Inspector**: Severity is overstated. Default bind is `127.0.0.1` (standard for local desktop UIs). Destructive routes (restore, delete, rename) require JSON body via `_need(request.get_json(...))`, blocking form-POST CSRF. Residual CSRF is limited to stop/shutdown — annoying, not data-destructive. `--host 0.0.0.0` requires explicit user override. **Recommendation**: Add `--host` warning and keep localhost default; consider adding a CSRF token to the two unguarded routes as hardening rather than a full auth system. |
| **A2** | major (security) | **Architect**: `/health` leaks local paths, save names, and directory listings without authentication — dangerous if GUI is LAN-exposed. **Inspector**: `/health` is a documented troubleshooting endpoint. On localhost only the user can access it — "leak" is a misnomer (user knows their own paths). Severity collapses if A1's LAN-exposure doesn't materialize. **Recommendation**: Add loopback-only guard in `run_gui()` plus CLI warning on non-loopback binds (resolves both A1 and A2). Gate `/health` behind `--debug` flag if path redaction is desired. |

---

## Nits (validated, no runtime impact)

| ID | File | Line | Description |
|----|------|------|-------------|
| **N1 (B)** | `cli.py` | 131 | Dead `import flask` in `gui_command()` — never used |
| **N2 (B)** | `saves.py` | 100 | Dead `len(value.strip()) > 200` check — `_SANE_NAME_RE` already enforces `{1,200}` |

---

## Summary Statistics

| Category | Count |
|----------|-------|
| 🟢 Cross-validated | 5 (4 major, 1 minor) |
| 🟡 Consensus | 11 (5 major, 6 minor) |
| ⚠️ Partial / Downgraded | 2 |
| 🔴 Disputed | 2 (both major → hardening item) |
| **Total unique findings** | **20** |
| — Major | 11 (including 2 disputed) |
| — Minor | 7 |
| — Nit | 2 |

---

## Recommendations

1. **Fix cross-validated concurrency bugs first** (A6/B3, A4, A5, A7) — these have the highest blast radius (silent data loss, incomplete backups, config corruption).

2. **Fix consensus majors next** — A3 (rename rollback), B1 (auto flag), B2 (singleton race), DA2 (manager locking), B7 (watcher cooldown). Several are one-line fixes.

3. **Resolve disputed A1/A2 pragmatically**: add `--host` warning, loopback-only guard for `/health`, and a CSRF token on `/api/shutdown` and `/api/watcher/toggle`. No full auth system needed for a local desktop tool.

4. **Fix minors and nits** in a cleanup pass — most are trivial (dead imports, explicit collision checks, `contextlib.closing()`, coordinate NULL handling, CLI error wrapping, backup list notice).

5. **Review A8 (pruning semantic)** with a human — decide whether `max_auto_backups=0` means "keep all" or "keep none," then align code and documentation.