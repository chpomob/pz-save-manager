# PZ Save Manager

Gestionnaire de sauvegardes pour Project Zomboid — simple, visuel, automatique.

## Vision

Un outil qui tourne en arrière-plan, détecte automatiquement quand tu joues,
sauvegarde tes parties **sans que tu aies à y penser**, et te permet de
restaurer n'importe quelle version en un clic.

## Fonctionnalités

- **Auto-détection** : surveille les sauvegardes et crée un backup dès qu'un fichier change
- **Interface graphique** : pas de ligne de commande, une vraie UI
- **Visualisation** : aperçu de la carte et des infos de la sauvegarde
- **Restore one-click** : retour à n'importe quelle version précédente
- **Multi-plateforme** : Windows, Linux, macOS
- **Git-friendly** : les backups sont versionnés

## Installation

```bash
pip install pz-save-manager
pz-saves gui    # lance l'interface graphique
```

## Développement

```bash
git clone https://github.com/chpomob/pz-save-manager.git
cd pz-save-manager
pip install -e ".[dev]"
pytest
```

## Stack

- **UI** : Textual (TUI riche) ou Tkinter
- **Watchdog** : surveillance des fichiers en temps réel
- **Parsing** : pzdataspec (Kaitai Struct) pour la lecture des sauvegardes
- **Visualisation** : rendu de carte via pzmap2dzi

## Structure

```
pz-save-manager/
├── docs/           # Documentation et recherches
├── src/pz_save_manager/
│   ├── cli.py      # Commandes CLI
│   ├── gui.py      # Interface graphique
│   ├── saves.py    # Découverte des sauvegardes
│   ├── backup.py   # Backup/restore
│   ├── watcher.py  # Surveillance auto
│   └── platforms.py # Chemins cross-platform
├── tests/
└── pyproject.toml
```

## Licence

MIT
