"""HTTP API route handlers for the Flask GUI."""

from __future__ import annotations

from flask import Flask, current_app, jsonify, request

from .backup import BackupError, BackupNotFound, delete_backup, get_backup, set_backup_note
from .backup_service import rename_save, restore_save
from .config import ConfigStore, default_store
from .csrf import _check_csrf
from .gui import make_auto_backup_recorder
from .save_service import backup_save
from .saves import SaveNotFound
from .watcher import WatcherManager
from .watcher_service import start_watching_saves


def _saves_root():
    """Return the Flask-configured saves root override, or None for default."""
    return current_app.config.get("_saves_root_override")


def _backups_root():
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


def _need(data: dict | None, *keys: str):
    """Return (data, None) if all keys present, else (None, error_response)."""
    if not isinstance(data, dict) or not all(k in data and data[k] for k in keys):
        return None, (jsonify({"ok": False, "error": f"Missing fields: {', '.join(keys)}"}), 400)
    return data, None


def api_backup():
    csrf_err = _check_csrf()
    if csrf_err:
        return csrf_err
    data, err = _need(request.get_json(silent=True), "game_mode", "save_name")
    if err:
        return err
    try:
        result = backup_save(
            data["game_mode"],
            data["save_name"],
            saves_root=_saves_root(),
            backups_root=_backups_root(),
            config=_config_store(),
        )
        return jsonify(result)
    except (SaveNotFound, BackupError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


def api_restore():
    csrf_err = _check_csrf()
    if csrf_err:
        return csrf_err
    data, err = _need(request.get_json(silent=True), "game_mode", "save_name", "timestamp")
    if err:
        return err
    try:
        result = restore_save(
            _manager(),
            data["game_mode"],
            data["save_name"],
            data["timestamp"],
            saves_root=_saves_root(),
            backups_root=_backups_root(),
        )
        return jsonify(result)
    except (BackupNotFound, BackupError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


def api_delete_backup():
    csrf_err = _check_csrf()
    if csrf_err:
        return csrf_err
    data, err = _need(request.get_json(silent=True), "game_mode", "save_name", "timestamp")
    if err:
        return err
    try:
        delete_backup(data["game_mode"], data["save_name"], data["timestamp"], backups_root=_backups_root())
        return jsonify({"ok": True, "message": "Backup deleted"})
    except (BackupNotFound, BackupError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


def api_rename():
    csrf_err = _check_csrf()
    if csrf_err:
        return csrf_err
    data, err = _need(request.get_json(silent=True), "game_mode", "old_name", "new_name")
    if err:
        return err
    from .saves import SaveManagerError

    try:
        result = rename_save(
            _manager(),
            data["game_mode"],
            data["old_name"],
            data["new_name"],
            saves_root=_saves_root(),
            backups_root=_backups_root(),
        )
    except (SaveManagerError, BackupError, SaveNotFound) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify(result)


api_rename_save = api_rename


def api_annotate_backup():
    csrf_err = _check_csrf()
    if csrf_err:
        return csrf_err
    data, err = _need(request.get_json(silent=True), "game_mode", "save_name", "timestamp")
    if err:
        return err
    note = (data or {}).get("note", "")
    try:
        backup = get_backup(data["game_mode"], data["save_name"], data["timestamp"], backups_root=_backups_root())
        set_backup_note(backup.path, note)
    except (BackupNotFound, BackupError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "message": "Note saved" if note else "Note removed"})


def api_watcher_toggle():
    csrf_err = _check_csrf()
    if csrf_err:
        return csrf_err
    manager = _manager()
    if manager.running:
        manager.stop()
        return jsonify({"ok": True, "message": "Watcher stopped"})
    save_count = start_watching_saves(
        manager,
        _config_store(),
        saves_root=_saves_root(),
        backups_root=_backups_root(),
        on_backup=make_auto_backup_recorder(current_app._get_current_object()),
    )
    return jsonify({"ok": True, "message": f"Watcher started ({save_count} saves)"})


def api_watcher_save():
    csrf_err = _check_csrf()
    if csrf_err:
        return csrf_err
    data, err = _need(request.get_json(silent=True), "game_mode", "save_name")
    if err:
        return err
    from .saves import get_save

    try:
        save = get_save(data["game_mode"], data["save_name"], saves_root=_saves_root())
    except SaveNotFound:
        return jsonify({"ok": False, "error": "Save not found"}), 404
    manager = _manager()
    if save.display_name in manager.watched_saves():
        manager.unwatch(save)
        return jsonify({"ok": True, "message": f"Unwatched {save.name}"})
    cfg = _config_store().get_all()
    cooldown = cfg.get("backup_cooldown_minutes", 5) * 60
    debounce = cfg.get("debounce_seconds", 5.0)
    manager.watch(
        save,
        debounce_seconds=debounce,
        backup_cooldown_seconds=cooldown,
        saves_root=_saves_root(),
        backups_root=_backups_root(),
        on_backup=make_auto_backup_recorder(current_app._get_current_object()),
    )
    if not manager.running:
        manager.start()
    return jsonify({"ok": True, "message": f"Watching {save.name}"})


def api_config_get():
    return jsonify(_config_store().get_all())


def api_config():
    """Update configuration."""
    csrf_err = _check_csrf()
    if csrf_err:
        return csrf_err
    data = request.get_json(silent=True) or {}
    from .config import _coerce

    allowed = {
        "backups_dir",
        "debounce_seconds",
        "backup_cooldown_minutes",
        "max_auto_backups",
        "port",
        "auto_start_watcher",
    }
    errors: dict[str, str] = {}
    for key, value in data.items():
        if key not in allowed:
            continue
        if value is None or value == "":
            if key == "backups_dir":
                _config_store().set(key, None)
            continue
        try:
            coerced_value = _coerce(key, value)
        except (ValueError, TypeError):
            errors[key] = f"Invalid value for {key}"
            continue
        _config_store().set(key, coerced_value)
    if errors:
        return jsonify({"ok": False, "error": "Invalid values", "fields": errors}), 400
    return jsonify({"ok": True, "message": "Settings saved", "config": _config_store().get_all()})


def api_shutdown():
    """Gracefully stop the server."""
    csrf_err = _check_csrf()
    if csrf_err:
        return csrf_err
    manager = _manager()
    if manager.running:
        manager.stop()
    shutdown_func = request.environ.get("werkzeug.server.shutdown")

    def _shutdown() -> None:
        if callable(shutdown_func):
            shutdown_func()
            return
        import _thread

        _thread.interrupt_main()

    from threading import Timer

    timer = Timer(3.0, _shutdown)
    timer.daemon = True
    timer.start()
    return jsonify({"ok": True, "message": "Shutting down..."})


def api_backup_last_auto():
    """Return the Unix timestamp of the most recent auto-backup (0 = never)."""
    return {"last_auto": current_app.config.get("last_auto_backup", 0.0)}


def register_api_routes(app: Flask) -> None:
    app.add_url_rule("/api/backup", "api_backup", api_backup, methods=["POST"])
    app.add_url_rule("/api/restore", "api_restore", api_restore, methods=["POST"])
    app.add_url_rule("/api/backup/delete", "api_delete_backup", api_delete_backup, methods=["POST"])
    app.add_url_rule("/api/save/rename", "api_rename", api_rename, methods=["POST"])
    app.add_url_rule("/api/backup/annotate", "api_annotate_backup", api_annotate_backup, methods=["POST"])
    app.add_url_rule("/api/watcher/toggle", "api_watcher_toggle", api_watcher_toggle, methods=["POST"])
    app.add_url_rule("/api/watcher/save", "api_watcher_save", api_watcher_save, methods=["POST"])
    app.add_url_rule("/api/config", "api_config_get", api_config_get, methods=["GET"])
    app.add_url_rule("/api/config", "api_config", api_config, methods=["POST"])
    app.add_url_rule("/api/backup/last-auto", "api_backup_last_auto", api_backup_last_auto, methods=["GET"])
    app.add_url_rule("/api/shutdown", "api_shutdown", api_shutdown, methods=["POST"])
