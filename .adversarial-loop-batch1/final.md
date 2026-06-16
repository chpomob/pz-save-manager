# Adversarial Code Loop — Final Report
Date: 2026-06-16T21:31:09.691890

## Summary
- **Final verdict**: APPROVED
- **Cycles**: 2
- **Arbitrated**: No

## Specification
```
# Batch 1: Fix auto-backup callback cluster + auto-refresh loop

Project: /home/chpo/pz-save-manager (Flask app, Python 3.10+, 75 tests in tests/)

## Root Cause (C1)
The `gui.py` file has a private `_on_auto_backup` closure inside `create_app()` that correctly updates `last_auto_backup`. But `routes_api.py` cannot access it, so `api_watcher_toggle` and `api_watcher_save` reimplement the logic incorrectly (or not at all).

## Fixes required

### 1. Extract shared recorder (C1)
In `gui.py`, extract `_on_auto_backup` into a module-level function:
```python
def make_auto_backup_recorder(app):
    """Return a callback that records the last auto-backup time on the given app."""
    import time
    def record(backup):
        app.config["last_auto_backup"] = time.time()
    return record
```
Replace the inline closure in `create_app()` (line ~242) with a call to `make_auto_backup_recorder(flask_app)`.
Export this function so `routes_api.py` can import it.

### 2. Fix api_watcher_toggle callback (A2/B1)
In `routes_api.py`, `api_watcher_toggle()` line 158 — the lambda is broken:
```python
on_backup=lambda b: setattr(current_app.config, "last_auto_backup", __import__("time").time()),
```
Replace with:
```python
from .gui import make_auto_backup_recorder
# inside the function:
on_backup=make_auto_backup_recorder(current_app._get_current_object()),
```
Note: use `current_app._get_current_object()` to get the real Flask app object (not the proxy), because the callback runs outside request context in a Timer thread.

### 3. Fix api_watcher_save callback (B2)
In `routes_api.py`, `api_watcher_save()` line ~183 — `manager.watch()` is called with NO `on_backup` argument. Add the same `on_backup=make_auto_backup_recorder(current_app._get_current_object())` here.

### 4. Fix auto-refresh infinite loop (B3)
In `templates/index.html`, the JavaScript `_lastAuto` is initialized to 0 on every page load. Once `/api/backup/last-auto` returns any positive timestamp, the first poll triggers a reload, which resets `_lastAuto` to 0, creating an infinite 5-second reload loop.

Fix: pass `last_auto_backup` from the server to the template, and seed `_lastAuto` from it:
- In `gui.py` `_render_page()`, add `last_auto_backup=current_app.config.get("last_auto_backup", 0.0)`
- In `index.html`, replace `var _lastAuto = 0;` with `var _lastAuto = {{ last_auto_backup }};`

### 5. Wrap callback invocation in try/except (C2)
In `watcher.py`, `_do_backup()` line ~158 — `callback(backup)` is called outside the try/except/finally block. If the callback raises (e.g. the RuntimeError from B1), the Timer thread crashes silently.

Move the callback invocation inside the `finally` block's protection, or add a separate try/except around it:
```python
if backup is not None and callback:
    try:
        callback(backup)
    except Exception:
        import logging
        logging.getLogger(__name__).error("auto-backup callback failed", exc_info=True)
```

## Verification
After all changes, run: `.venv/bin/pytest tests/ -x -q`
All 75 tests must pass. Add a test that verifies `make_auto_backup_recorder` works outside request context (create a Flask app, get the recorder, call it — verify `app.config["last_auto_backup"]` is updated).

## Files to modify
- src/pz_save_manager/gui.py
- src/pz_save_manager/routes_api.py
- src/pz_save_manager/watcher.py
- src/pz_save_manager/templates/index.html

```

## Final Code
Implemented the batch.

Changed:
- Added `make_auto_backup_recorder()` in [gui.py](/home/chpo/pz-save-manager/src/pz_save_manager/gui.py).
- Reused it in `create_app()`, `/api/watcher/toggle`, and `/api/watcher/save`.
- Passed `last_auto_backup` into the template and seeded `_lastAuto` from it to stop the reload loop.
- Wrapped watcher auto-backup callback execution in `try/except` with error logging.
- Added a regression test proving the recorder works outside request context.

Verification:
- `.venv/bin/pytest tests/ -x -q`
- Result: `76 passed in 1.73s`

I also moved the `register_api_routes` import inside `create_app()` to avoid a circular import now that `routes_api.py` imports the shared recorder from `gui.py`.
