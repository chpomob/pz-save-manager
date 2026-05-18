"""PyInstaller entry point — launches the GUI directly when the bundled exe runs."""

from pz_save_manager.gui import run_gui


if __name__ == "__main__":
    run_gui()
