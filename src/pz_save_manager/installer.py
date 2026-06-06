"""One-command installer — creates launchers, desktop shortcuts, auto-start."""

from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path


# Resolve to project root by finding pyproject.toml.
_MODULE_PATH = Path(__file__).resolve()
PROJECT_DIR = _MODULE_PATH.parent.parent
for parent in _MODULE_PATH.parents:
    if (parent / "pyproject.toml").is_file():
        PROJECT_DIR = parent
        break
ICON = "🧟"


def install_linux() -> None:
    """Create .desktop entry for Linux app menus."""
    desktop_dir = Path.home() / ".local" / "share" / "applications"
    desktop_dir.mkdir(parents=True, exist_ok=True)

    desktop_file = desktop_dir / "pz-save-manager.desktop"
    launcher = PROJECT_DIR / "launcher.sh"

    desktop_file.write_text(f"""[Desktop Entry]
Name=PZ Save Manager
Comment=Backup manager for Project Zomboid
Exec={launcher}
Icon=utilities-terminal
Terminal=true
Type=Application
Categories=Game;Utility;
""")
    os.chmod(desktop_file, 0o755)
    print(f"  ✓ Desktop entry: {desktop_file}")


def install_windows() -> None:
    """Create Start Menu shortcut for Windows."""
    import pythoncom
    from win32com.client import Dispatch

    startup = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    shortcut_path = startup / "PZ Save Manager.lnk"

    shell = Dispatch("WScript.Shell")
    shortcut = shell.CreateShortcut(str(shortcut_path))
    shortcut.TargetPath = str(PROJECT_DIR / "launcher.bat")
    shortcut.WorkingDirectory = str(PROJECT_DIR)
    shortcut.IconLocation = "shell32.dll,13"
    shortcut.Save()
    print(f"  ✓ Start Menu shortcut: {shortcut_path}")


def install() -> None:
    """Create launchers and desktop shortcuts."""
    print(f"\n  {ICON} Installing PZ Save Manager...\n")

    system = platform.system()
    if system == "Linux":
        install_linux()
    elif system == "Windows":
        install_windows()
    elif system == "Darwin":
        print("  macOS: double-click launcher.sh")
    else:
        print(f"  Unknown OS: {system} — use launcher.sh directly")

    print(f"\n  Done! Launch with: {PROJECT_DIR}/launcher.{'bat' if system == 'Windows' else 'sh'}\n")


if __name__ == "__main__":
    install()
