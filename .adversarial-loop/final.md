# Adversarial Code Loop — Final Report
Date: 2026-06-16T09:51:01.995811

## Summary
- **Final verdict**: APPROVED
- **Cycles**: 4
- **Arbitrated**: No

## Specification
```
# pz-save-manager — Architectural Refactor (3 majors)

Refactor `~/pz-save-manager` to fix 3 architectural issues:

1. **God object** — Extract template, split routes, factor CSRF from gui.py
2. **No DI** — Pass explicit dependencies through CLI main() and Flask create_app()
3. **Layering** — Extract backup_service.py + save_service.py for orchestration logic

Run `uv run pytest tests/ -v` after each phase. Update any test that breaks.

## Phase 1: Extract template + split routes (god object)

### 1a. Extract inline HTML template
- Move the 250-line inline HTML/CSS/JS template from `gui.py` (the `PAGE` variable or the big f-string/html template inside `_render_page` or `index`) to `src/pz_save_manager/templates/index.html`
- Use `pathlib.Path(__file__).parent / "templates" / "index.html"` to load it at runtime
- If Flask's `render_template` is available and easy, use it; otherwise just `read_text()` + `.format()` or `.replace()` — keep it simple, no extra deps

### 1b. Split route handlers from gui.py
- Create a new file `src/pz_save_manager/routes_api.py` containing:
  - `api_backup()`, `api_restore()`, `api_rename()`, `api_config`, `api_config_get`, `api_watcher_toggle`, `api_watcher_save`, `api_shutdown`
  - These are Flask route functions currently in `gui.py`
  - Import them back in `gui.py` (or register them via `app.route()` in `create_app()`)
- Keep `index()`, `_render_page()`, `/health` in `gui.py` as the main page handlers
- Keep CSRF middleware and `create_app()` in `gui.py` for now

### 1c. Factor CSRF
- Extract CSRF token generation/validation from `gui.py` to `src/pz_save_manager/csrf.py`
- Keep `_generate_csrf_token()` and `_validate_csrf()` (or `_check_csrf()`) there
- Import into gui.py and routes_api.py

## Phase 2: Dependency injection

### 2a. Make config injectable
- `config.py`: instead of module-level `_cache = {}` with `get()` reading from the singleton, wrap config in a class `ConfigStore`
- `ConfigStore.__init__(self, path: Path = CONFIG_PATH)` — takes a path, has its own cache
- Keep a module-level `default_store = ConfigStore()` for backward compat
- `get(key)` and `set(key, value)` become methods on ConfigStore
- `_load()` and `_save()` become private methods

### 2b. Make backup manager injectable
- Currently `get_manager()` returns a module-level singleton with hardcoded paths
- Change it to accept `config: ConfigStore` and `saves_root: Path, backups_root: Path`
- `gui.py`: `create_app()` receives a `ConfigStore` and creates a manager with it
- `cli.py`: `main()` creates a `ConfigStore` and passes it to commands via `ctx.obj`

### 2c. Wire it through CLI and GUI
- `cli.py`: `@click.pass_context` passes `ctx.obj = {"config": config_store, "manager": manager}`
- `gui.py`: `create_app(config: ConfigStore)` creates the manager, registers routes with it
- Routes receive config/manager from the app context or from `create_app()`'s closure

## Phase 3: Service layer extraction

### 3a. Create `backup_service.py`
- `src/pz_save_manager/backup_service.py`
- Extract from `gui.py` the orchestration logic:
  - `restore_save(manager, save_id, backup_ts)` — pause watcher, call manager.restore, resume watcher
  - `rename_save(manager, save_id, new_name, ...)` — the rollback logic when backup rename fails
- These are called by route handlers, keep them as plain functions taking explicit dependencies

### 3b. Create `save_service.py`
- `src/pz_save_manager/save_service.py`
- Extract from `gui.py`:
  - `backup_save(manager, save_id)` — the orchestration around manager.create_backup

### 3c. Route handlers become thin
- After extraction, route handlers should look like:
  ```python
  @app.route("/api/restore", methods=["POST"])
  def api_restore():
      data = request.get_json()
      result = restore_save(current_app.config["manager"], data["save"], data["timestamp"])
      return jsonify(result)
  ```
  No watcher pause/unpause, no rollback logic, no cleanup orchestration — just HTTP in/out.

## Constraints
- Do NOT add new features
- Do NOT change the public CLI interface (flags, commands, help text)
- Do NOT change the HTTP API interface (endpoint paths, request/response format)
- Run tests after each phase: `uv run pytest tests/ -v`
- If a test breaks because of DI changes, update the test to inject dependencies
- Keep `pyproject.toml` dependencies unchanged
- Keep the CSRF token mechanism working (all existing tests must pass)

```

## Final Code
"""Flask web GUI for PZ Save Manager."""

from __future__ import annotations

from datetime import datetime
from html import escape
from ipaddress import ip_address
from pathlib import Path

from flask import Flask, abort, current_app, render_template, request, send_file

from .backup import get_backup, get_backup_note, list_backups
from .config import ConfigStore, default_store
from .csrf import CSRF_TOKEN as _CSRF_TOKEN
from .csrf import _generate_csrf_token
from .platforms import get_backups_root, get_saves_root
from .routes_api import register_api_routes
from .save_info import extract_all, player_info
from .saves import SaveGame, get_save_modified_time, list_saves
from .watcher import WatcherManager
from .watcher_service import start_watching_saves


def _saves_root() -> Path | None:
    """Return the Flask-configured saves root override, or None for default."""
    return current_app.config.get("_saves_root_override")


def _backups_root() -> Path | None:
    """Return the Flask-configured backups root override, or None for default."""
    return current_app.config.get("_backups_root_override")


def _config_store() -> ConfigStore:
    store = current_app.config.get("config_store")
    if isinstance(store, ConfigStore):
        return store
    return default_store


def _manager() -> WatcherManager:
    manager = current_app.config.get("manager")
    if isinstance(manager, WatcherManager):
        return manager
    raise RuntimeError("Flask app is missing a WatcherManager dependency")


def _render_page(
    *,
    saves: list[dict],
    all_backups: list[dict],
    backup_count: int,
    watcher_running: bool,
    csrf_token: str,
) -> str:
    """Render the main page from the extracted package template."""
    return render_template(
        "index.html",
        saves=saves,
        all_backups=all_backups,
        backup_count=backup_count,
        watcher_running=watcher_running,
        csrf_token=csrf_token,
    )


def _save_info(save: SaveGame, manager: WatcherManager) -> dict:
    path = save.path
    modified = datetime.fromtimestamp(get_save_modified_time(save)).strftime("%Y-%m-%d %H:%M")
    extra = extract_all(path)
    info = {
        "game_mode": save.game_mode,
        "name": save.name,
        "full_name": save.name,
        "modified": modified,
        "has_thumbnail": extra.get("has_thumbnail", False),
        "watched": save.display_name in manager.watched_saves(),
    }
    info["player_dead"] = None
    info["player_x"] = None
    info["player_y"] = None
    for key in ("mod_count", "player", "player_dead", "player_x", "player_y", "player_world_version"):
        if key in extra:
            info[key] = extra[key]
    return info


def index():
    manager = _manager()
    saves = list_saves(saves_root=_saves_root())
    save_infos = []
    for save in saves:
        try:
            save_infos.append(_save_info(save, manager))
        except Exception:
            import logging

            logging.getLogger(__name__).warning("could not read save %s", save.display_name, exc_info=True)
    all_backups = list_backups(backups_root=_backups_root())
    backup_count = len(all_backups)
    all_b = []
    for backup in all_backups[:50]:
        pi = player_info(backup.path) or {}
        all_b.append(
            {
                "game_mode": backup.game_mode,
                "save_name": backup.save_name,
                "real_save_name": backup.save_name,
                "timestamp": backup.timestamp,
                "auto": backup.auto,
                "age": backup.age,
                "formatted": backup.formatted,
                "has_thumbnail": (backup.path / "thumb.png").is_file(),
                "player": pi.get("name"),
                "player_dead": pi.get("is_dead"),
                "note": get_backup_note(backup.path),
            }
        )
    return _render_page(
        saves=save_infos,
        all_backups=all_b,
        backup_count=backup_count,
        watcher_running=manager.running,
        csrf_token=_generate_csrf_token(),
    )


def health():
    """Plain-text diagnostic page with resolved paths and discovery status."""
    import json
    import platform as _platform
    import sys

    from . import __version__

    try:
        if not ip_address(request.remote_addr or "").is_loopback:
            abort(403)
    except ValueError:
        abort(403)

    saves_root = _saves_root() or get_saves_root()
    backups_root = _backups_root() or get_backups_root()
    info: dict = {
        "version": __version__,
        "python": sys.version,
        "executable": sys.executable,
        "platform": _platform.platform(),
        "frozen": getattr(sys, "frozen", False),
        "saves_root": str(saves_root),
        "saves_root_exists": saves_root.is_dir(),
        "backups_root": str(backups_root),
        "backups_root_exists": backups_root.is_dir(),
        "errors": [],
    }
    try:
        saves = list_saves(saves_root=_saves_root())
        info["save_count"] = len(saves)
        info["saves"] = [{"game_mode": save.game_mode, "name": save.name, "path": str(save.path)} for save in saves]
    except Exception as exc:
        info["errors"].append(f"list_saves: {exc!r}")
    try:
        info["backup_count"] = len(list_backups(backups_root=_backups_root()))
    except Exception as exc:
        info["errors"].append(f"list_backups: {exc!r}")
    if saves_root.is_dir():
        try:
            info["saves_root_children"] = sorted(path.name for path in saves_root.iterdir())
        except Exception as exc:
            info["errors"].append(f"iterdir saves_root: {exc!r}")

    return (
        "<!doctype html><meta charset='utf-8'>"
        "<style>body{font-family:monospace;background:#111;color:#eee;padding:2rem}"
        "pre{white-space:pre-wrap;background:#222;padding:1rem;border-radius:6px}</style>"
        "<h2>PZ Save Manager — /health</h2>"
        f"<pre>{escape(json.dumps(info, indent=2, default=str))}</pre>"
    )


def serve_backup_thumbnail(game_mode: str, save_name: str, timestamp: str):
    try:
        backup = get_backup(game_mode, save_name, timestamp, backups_root=_backups_root())
        thumb = backup.path / "thumb.png"
        if thumb.is_file():
            return send_file(thumb, mimetype="image/png")
    except Exception:
        pass
    return "", 404


def serve_thumbnail(game_mode: str, save_name: str):
    from .saves import get_save

    try:
        save = get_save(game_mode, save_name, saves_root=_saves_root())
        thumb = save.path / "thumb.png"
        if thumb.is_file():
            return send_file(thumb, mimetype="image/png")
    except Exception:
        pass
    return "", 404


def _register_page_routes(flask_app: Flask) -> None:
    flask_app.add_url_rule("/", "index", index)
    flask_app.add_url_rule("/health", "health", health)
    flask_app.add_url_rule(
        "/thumb-backup/<game_mode>/<save_name>/<timestamp>",
        "serve_backup_thumbnail",
        serve_backup_thumbnail,
    )
    flask_app.add_url_rule("/thumb/<game_mode>/<save_name>", "serve_thumbnail", serve_thumbnail)


def create_app(
    config: ConfigStore | None = None,
    *,
    saves_root: Path | None = None,
    backups_root: Path | None = None,
    manager: WatcherManager | None = None,
) -> Flask:
    """Create a Flask GUI app with explicit runtime dependencies."""
    config_store = config or default_store
    resolved_backups_root = backups_root
    if resolved_backups_root is None:
        configured_backups_dir = config_store.get_backups_dir()
        if configured_backups_dir is not None:
            resolved_backups_root = configured_backups_dir
    watcher_manager = manager or WatcherManager(
        config=config_store,
        saves_root=saves_root,
        backups_root=resolved_backups_root,
    )
    flask_app = Flask(__name__, template_folder="templates")
    flask_app.config["config_store"] = config_store
    flask_app.config["manager"] = watcher_manager
    flask_app.config["_saves_root_override"] = saves_root
    flask_app.config["_backups_root_override"] = resolved_backups_root
    _register_page_routes(flask_app)
    register_api_routes(flask_app)
    if config_store.get("auto_start_watcher"):
        start_watching_saves(
            watcher_manager,
            config_store,
            saves_root=saves_root,
            backups_root=resolved_backups_root,
        )
    return flask_app


def run_gui(
    host: str = "127.0.0.1",
    port: int = 8080,
    saves_root: Path | None = None,
    backups_root: Path | None = None,
    open_browser: bool = True,
    config: ConfigStore | None = None,
    manager: WatcherManager | None = None,
) -> None:
    import webbrowser

    url = f"http://{host}:{port}"
    config_store = config or default_store
    if saves_root is None:
        saves_root = get_saves_root()
    if backups_root is None:
        backups_root = config_store.get_backups_dir() or get_backups_root()
    flask_app = create_app(
        config_store,
        saves_root=saves_root,
        backups_root=backups_root,
        manager=manager,
    )
    try:
        save_count = len(list_saves(saves_root=saves_root))
    except Exception as exc:
        save_count = f"error: {exc!r}"
    print(f"\n  PZ Save Manager - {url}")
    print(f"  Saves dir : {saves_root} (exists={saves_root.is_dir()})")
    print(f"  Backups   : {backups_root}")
    print(f"  Found     : {save_count} save(s)")
    print(f"  Diagnostics: {url}/health\n")
    if open_browser:
        webbrowser.open(url)
    flask_app.run(host=host, port=port, debug=False)

