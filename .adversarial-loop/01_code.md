Implemented the 3-phase architectural refactor.

Key changes:
- Extracted the GUI template to [index.html](/home/chpo/pz-save-manager/src/pz_save_manager/templates/index.html).
- Split API handlers into [routes_api.py](/home/chpo/pz-save-manager/src/pz_save_manager/routes_api.py).
- Moved CSRF helpers into [csrf.py](/home/chpo/pz-save-manager/src/pz_save_manager/csrf.py).
- Added `ConfigStore` with compatibility wrappers in [config.py](/home/chpo/pz-save-manager/src/pz_save_manager/config.py).
- Added Flask `create_app(...)` dependency injection in [gui.py](/home/chpo/pz-save-manager/src/pz_save_manager/gui.py).
- Wired CLI context with explicit `config`, `manager`, `saves_root`, and `backups_root` in [cli.py](/home/chpo/pz-save-manager/src/pz_save_manager/cli.py).
- Added orchestration services:
  - [backup_service.py](/home/chpo/pz-save-manager/src/pz_save_manager/backup_service.py)
  - [save_service.py](/home/chpo/pz-save-manager/src/pz_save_manager/save_service.py)
- Updated GUI tests to use injected app dependencies in [test_gui.py](/home/chpo/pz-save-manager/tests/test_gui.py).

Validation:
- Phase 1: `uv run pytest tests/ -v` → `62 passed`
- Phase 2: `uv run pytest tests/ -v` → `62 passed`
- Phase 3: `uv run pytest tests/ -v` → `62 passed`

I did not change `pyproject.toml` dependencies or the public CLI/HTTP interfaces. Note: the worktree already contained unrelated modified/deleted files before this work; I did not revert them.