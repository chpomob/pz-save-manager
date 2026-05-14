# 🧟 PZ Save Manager

> Backup manager for Project Zomboid — automatic, visual, effortless.

Never lose a save again. PZ Save Manager watches your Zomboid saves and creates
timestamped backups automatically. Restore any version in one click from a
clean web interface.

![Python](https://img.shields.io/badge/python-3.10+-blue)
![Platform](https://img.shields.io/badge/platform-Windows%20|%20Linux%20|%20macOS-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)
![Tests](https://img.shields.io/badge/tests-16%20passed-brightgreen)

## Features

- **🔄 Auto-backup** — detects save changes and creates backups automatically
- **🖼️ Visual preview** — shows the in-game thumbnail for each save
- **📊 Save insights** — player name, status (alive/dead), position, vehicles, mods, map chunks
- **⚙ Configurable** — set custom backup directory, debounce delay, port
- **🖥️ Web GUI** — clean dark-themed interface, works in any browser
- **🚀 One-click launch** — `.bat`/`.sh` launchers, no terminal needed
- **🌍 Cross-platform** — Windows, Linux, macOS

## Screenshots

```
┌──────────────────────────────────────────────────────┐
│  🧟 PZ Save Manager    Watcher: RUNNING  [Stop] ⚙ ✕ │
├──────────────────────────────────────────────────────┤
│  📁 Saves (2)                                        │
│  ┌──────────────────────────────────────────────┐    │
│  │ [thumb] Miriam Hyde · 2026-05-14_16-12-25     │    │
│  │ APOCALYPSE · Rosewood, KY · 38 MB    🟢      │    │
│  │ ▸ Backups: 3 min ago · 45 MB · 🤖 auto  [↩] │    │
│  └──────────────────────────────────────────────┘    │
│  ┌──────────────────────────────────────────────┐    │
│  │ [thumb] 149.202.88.99_...                     │    │
│  │ MULTIPLAYER · 187 files · 45 MB      🟡      │    │
│  └──────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────┘
```

## Quick Start

### Windows

1. Download and extract the project
2. Double-click `launcher.bat`
3. The web UI opens in your browser → done!

### Linux / macOS

```bash
git clone https://github.com/chpomob/pz-save-manager.git
cd pz-save-manager
./launcher.sh
```

The first run installs everything automatically. Open http://127.0.0.1:8080.

### Install desktop shortcut

```bash
pz-saves install
```

Adds a menu entry so you can launch it like any other app.

## How It Works

```
~/Zomboid/Saves/                   ~/.pz-save-manager/backups/
├── Apocalypse/                    ├── Apocalypse/
│   └── my-world/    ──watch──▶    │   └── my-world/
├── Survivor/                      │       ├── 20260514-160140/
│   └── other/                     │       ├── 20260514-160905/
└── ...                            │       └── ...
                                   └── ...
```

The watcher monitors your save directory. When Project Zomboid writes save files,
the watcher waits 5 seconds (configurable), then snapshots the entire save.

## Commands

| Command | Description |
|---------|-------------|
| `pz-saves gui` | Launch the web interface |
| `pz-saves list` | List all saves in the terminal |
| `pz-saves backup <mode> <name>` | Manual backup (CLI) |
| `pz-saves restore <mode> <name> <ts>` | Restore a backup (CLI) |
| `pz-saves config` | View/set configuration |
| `pz-saves install` | Create desktop shortcut |

## Configuration

```bash
pz-saves config backups_dir /media/external/pz-backups   # Custom backup location
pz-saves config debounce_seconds 10                       # Wait 10s before auto-backup
```

Or use the ⚙ settings panel in the web UI.

## Development

```bash
git clone https://github.com/chpomob/pz-save-manager.git
cd pz-save-manager
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest                    # 16 tests
```

## Tech Stack

- **Python 3.10+** — zero external runtime dependencies
- **Flask** — web server
- **watchdog** — file system monitoring
- **Click + Rich** — CLI
- **SQLite** — save data extraction (stdlib)

## License

MIT — do whatever you want with it.
