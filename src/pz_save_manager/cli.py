"""Click command line interface for PZ Save Manager."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import click
from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table

from .backup import BackupError, BackupNotFound, create_backup, delete_backup, list_backups, restore_backup
from .config import ConfigStore
from .platforms import get_backups_root, get_saves_root, resolve_path
from .saves import SaveNotFound, get_save_modified_time, list_saves
from .watcher import get_manager


console = Console()


def _path_option(value: str | None) -> Path | None:
    return resolve_path(value)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--saves-dir", type=click.Path(file_okay=False, dir_okay=True), help="Override the Project Zomboid saves directory.")
@click.option("--backups-dir", type=click.Path(file_okay=False, dir_okay=True), help="Override the backup storage directory.")
@click.pass_context
def main(ctx: click.Context, saves_dir: str | None, backups_dir: str | None) -> None:
    """Manage Project Zomboid save backups."""
    ctx.ensure_object(dict)
    config_store = ConfigStore()
    saves_root = _path_option(saves_dir) or get_saves_root()
    backups_root = _path_option(backups_dir) or config_store.get_backups_dir() or get_backups_root()
    manager = get_manager(config=config_store, saves_root=saves_root, backups_root=backups_root)
    ctx.obj.update(
        {
            "config": config_store,
            "manager": manager,
            "saves_root": saves_root,
            "backups_root": backups_root,
        }
    )


@main.command("list")
@click.pass_context
def list_saves_command(ctx: click.Context) -> None:
    """List discovered Project Zomboid saves."""
    saves_root: Path = ctx.obj["saves_root"]
    saves = list_saves(saves_root)
    if not saves:
        if saves_root.exists():
            console.print(f"[yellow]No saves found in {saves_root}[/yellow]")
        else:
            console.print(f"[yellow]Project Zomboid saves directory not found: {saves_root}[/yellow]")
        return

    table = Table(title="Project Zomboid Saves")
    table.add_column("Game Mode", style="cyan")
    table.add_column("Save")
    table.add_column("Modified")
    table.add_column("Path", overflow="fold")
    for save in saves:
        modified = datetime.fromtimestamp(get_save_modified_time(save)).strftime("%Y-%m-%d %H:%M:%S")
        table.add_row(save.game_mode, save.name, modified, str(save.path))
    console.print(table)


@main.command("backup")
@click.argument("game_mode")
@click.argument("save_name")
@click.pass_context
def backup_command(ctx: click.Context, game_mode: str, save_name: str) -> None:
    """Create a timestamped backup for a save."""
    try:
        with Progress(
            TextColumn("[cyan]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task_id = progress.add_task(f"Backing up {game_mode}/{save_name}…", total=None)

            def _on_progress(copied: int, total: int, path: "Path") -> None:
                progress.update(task_id, completed=copied, total=total,
                                description=f"Copying {path}")

            backup = create_backup(
                game_mode,
                save_name,
                saves_root=ctx.obj["saves_root"],
                backups_root=ctx.obj["backups_root"],
                config=ctx.obj["config"],
                progress_callback=_on_progress,
            )
    except (SaveNotFound, BackupError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(f"[green]Backup created:[/green] {backup.path}")


@main.command("list-backups")
@click.argument("game_mode", required=False)
@click.argument("save_name", required=False)
@click.pass_context
def list_backups_command(ctx: click.Context, game_mode: str | None, save_name: str | None) -> None:
    """List available backups."""
    try:
        backups = list_backups(game_mode, save_name, backups_root=ctx.obj["backups_root"])
    except BackupError as exc:
        raise click.ClickException(str(exc)) from exc
    if not backups:
        console.print("[yellow]No backups found.[/yellow]")
        return
    table = Table(title="Project Zomboid Backups")
    table.add_column("Game Mode", style="cyan")
    table.add_column("Save")
    table.add_column("Timestamp")
    table.add_column("Path", overflow="fold")
    for backup in backups:
        table.add_row(backup.game_mode, backup.save_name, backup.timestamp, str(backup.path))
    console.print(table)


@main.command("restore")
@click.argument("game_mode")
@click.argument("save_name")
@click.argument("timestamp")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation.")
@click.pass_context
def restore_command(ctx: click.Context, game_mode: str, save_name: str, timestamp: str, yes: bool) -> None:
    """Restore a save from a backup timestamp."""
    if not yes:
        click.confirm(f"Restore {game_mode}/{save_name} from {timestamp}? The current save directory will be replaced.", abort=True)
    try:
        with Progress(
            TextColumn("[cyan]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task_id = progress.add_task(f"Restoring {game_mode}/{save_name}…", total=None)

            def _on_progress(copied: int, total: int, path: "Path") -> None:
                progress.update(task_id, completed=copied, total=total,
                                description=f"Copying {path}")

            save = restore_backup(
                game_mode,
                save_name,
                timestamp,
                saves_root=ctx.obj["saves_root"],
                backups_root=ctx.obj["backups_root"],
                progress_callback=_on_progress,
            )
    except (BackupNotFound, BackupError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(f"[green]Save restored:[/green] {save.path}")


@main.command("delete")
@click.argument("game_mode")
@click.argument("save_name")
@click.argument("timestamp")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation.")
@click.pass_context
def delete_command(ctx: click.Context, game_mode: str, save_name: str, timestamp: str, yes: bool) -> None:
    """Delete a backup timestamp."""
    if not yes:
        click.confirm(f"Delete backup {game_mode}/{save_name}/{timestamp}?", abort=True)
    try:
        backup = delete_backup(game_mode, save_name, timestamp, backups_root=ctx.obj["backups_root"])
    except (BackupNotFound, BackupError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(f"[green]Backup deleted:[/green] {backup.display_name}")


@main.command("gui")
@click.option("--host", default="127.0.0.1", help="Host to bind to.")
@click.option("--port", default=8080, type=int, help="Port to listen on.")
@click.option("--no-browser", is_flag=True, help="Don't open browser automatically.")
@click.option("--debug", is_flag=True, help="Enable Flask debug mode (shows tracebacks in browser).")
@click.pass_context
def gui_command(ctx: click.Context, host: str, port: int, no_browser: bool, debug: bool) -> None:
    """Launch the web GUI."""
    from .gui import run_gui
    saves_root = ctx.obj.get("saves_root")
    backups_root = ctx.obj.get("backups_root")
    run_gui(
        host,
        port,
        saves_root=saves_root,
        backups_root=backups_root,
        open_browser=not no_browser,
        config=ctx.obj["config"],
        manager=ctx.obj["manager"],
        debug=debug,
    )


@main.command("config")
@click.argument("key", required=False)
@click.argument("value", required=False)
@click.pass_context
def config_command(ctx: click.Context, key: str | None, value: str | None) -> None:
    """View or set configuration. 'pz-saves config' shows all."""
    config_store: ConfigStore = ctx.obj["config"]

    if key is None:
        cfg = config_store.get_all()
        console.print("[bold]Configuration:[/bold]")
        for k, v in cfg.items():
            console.print(f"  {k}: {v}")
        return

    if value is None:
        console.print(f"{key} = {config_store.get(key)}")
        return

    # Convert types
    try:
        from .config import _coerce
        coerced = _coerce(key, value)
        # _coerce returns None to signal clearing (backups_dir empty/null)
        if coerced is None and key == "backups_dir":
            value = None
        else:
            value = coerced
    except (ValueError, TypeError) as e:
        raise click.ClickException(f"Invalid value for '{key}': {e}") from e

    config_store.set(key, value)
    console.print(f"[green]{key} = {value}[/green]")


@main.command("rename")
@click.argument("game_mode")
@click.argument("old_name")
@click.argument("new_name")
@click.pass_context
def rename_command(ctx: click.Context, game_mode: str, old_name: str, new_name: str) -> None:
    """Rename a save (and move its backups)."""
    from .saves import SaveManagerError, rename_save
    from .backup import BackupError, preflight_rename, rename_backups_for_save
    try:
        preflight_rename(game_mode, old_name, new_name, backups_root=ctx.obj["backups_root"])
        new_save = rename_save(game_mode, old_name, new_name, saves_root=ctx.obj["saves_root"])
        n = rename_backups_for_save(game_mode, old_name, new_name, backups_root=ctx.obj["backups_root"])
    except (SaveManagerError, BackupError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(f"[green]Saved renamed to[/green] {new_save.name}")
    if n:
        console.print(f"[dim]{n} backup(s) moved[/dim]")


@main.command("annotate")
@click.argument("game_mode")
@click.argument("save_name")
@click.argument("timestamp")
@click.argument("note", required=False)
@click.pass_context
def annotate_command(ctx: click.Context, game_mode: str, save_name: str, timestamp: str, note: str | None) -> None:
    """Add or read a note on a backup. Omit note to read existing."""
    from .backup import BackupNotFound, get_backup, get_backup_note, set_backup_note
    try:
        backup = get_backup(game_mode, save_name, timestamp, backups_root=ctx.obj["backups_root"])
    except BackupNotFound as exc:
        raise click.ClickException(str(exc)) from exc
    if note is None:
        existing = get_backup_note(backup.path)
        if existing:
            console.print(existing)
        else:
            console.print("[dim](no note)[/dim]")
    else:
        set_backup_note(backup.path, note)
        console.print(f"[green]Note saved for[/green] {backup.display_name}")
