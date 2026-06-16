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