"""Click command line interface for PZ Save Manager."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from .backup import BackupError, BackupNotFound, create_backup, delete_backup, list_backups, restore_backup
from .gui import run_gui
from .platforms import get_backups_root, get_saves_root
from .saves import SaveNotFound, get_save_modified_time, list_saves


console = Console()


def _path_option(value: str | None) -> Path | None:
    return Path(value).expanduser() if value else None


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--saves-dir", type=click.Path(file_okay=False, dir_okay=True), help="Override the Project Zomboid saves directory.")
@click.option("--backups-dir", type=click.Path(file_okay=False, dir_okay=True), help="Override the backup storage directory.")
@click.pass_context
def main(ctx: click.Context, saves_dir: str | None, backups_dir: str | None) -> None:
    """Manage Project Zomboid save backups."""
    ctx.ensure_object(dict)
    ctx.obj["saves_root"] = _path_option(saves_dir) or get_saves_root()
    ctx.obj["backups_root"] = _path_option(backups_dir) or get_backups_root()


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
        backup = create_backup(game_mode, save_name, saves_root=ctx.obj["saves_root"], backups_root=ctx.obj["backups_root"])
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
        save = restore_backup(game_mode, save_name, timestamp, saves_root=ctx.obj["saves_root"], backups_root=ctx.obj["backups_root"])
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
def gui_command(host: str, port: int, no_browser: bool) -> None:
    """Launch the web GUI."""
    if no_browser:
        import flask
        # We still want the GUI but without browser open
        from .gui import app
        print(f"\n  🧟 PZ Save Manager — http://{host}:{port}\n")
        app.run(host=host, port=port, debug=False)
    else:
        run_gui(host, port)


@main.command("config")
@click.argument("key", required=False)
@click.argument("value", required=False)
def config_command(key: str | None, value: str | None) -> None:
    """View or set configuration. 'pz-saves config' shows all."""
    from .config import get_all, set_

    if key is None:
        cfg = get_all()
        console.print("[bold]Configuration:[/bold]")
        for k, v in cfg.items():
            console.print(f"  {k}: {v}")
        return

    if value is None:
        from .config import get
        console.print(f"{key} = {get(key)}")
        return

    # Convert types
    if key == "debounce_seconds":
        value = float(value)  # type: ignore
    elif key == "backup_cooldown_minutes":
        value = int(value)  # type: ignore
    elif key == "max_auto_backups":
        value = int(value)  # type: ignore
    elif key == "port":
        value = int(value)  # type: ignore
    elif key in ("auto_start_watcher",):
        value = value.lower() in ("true", "1", "yes")  # type: ignore
    elif key == "backups_dir" and value in ("", "none", "null"):
        value = None  # type: ignore

    set_(key, value)
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


@main.command("install")
def install_command() -> None:
    """Create desktop shortcuts and launchers."""
    from .installer import install
    install()


main.add_command(list_saves_command, "list-saves")
