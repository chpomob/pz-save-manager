# PZ Save Manager

Gestionnaire de sauvegardes pour Project Zomboid — multi-plateforme (Windows/Linux/macOS).

## Fonctionnalités prévues

### V1 — Backup Manager
- Backup complet d'une sauvegarde avec timestamp
- Restauration complète
- Liste et gestion des backups
- Détection automatique du dossier Zomboid

### V2 — Restauration par chunks
- Backup/restore de chunks individuels (cellules 10x10)
- Restaurer sa base sans toucher au reste du monde
- Intégration pzdataspec pour parsing binaire

### V3 — Sauvegarde de personnage
- Extraction du joueur d'un chunk
- Réinjection dans une autre sauvegarde
- Contourne la permadeath

## Stack technique

- Python 3.10+
- kaitaistruct — parsing binaire
- sqlite3 — vehicles.db, players.db (stdlib)
- platformdirs — chemins cross-platform
- click — CLI
- pzdataspec — spécifications de format (intégré)

## Structure du projet

```
pz-save-manager/
├── README.md
├── docs/
│   └── project_zomboid_save_format_research.md
├── src/
│   └── pz_save_manager/
│       ├── __init__.py
│       ├── cli.py
│       ├── saves.py
│       ├── backup.py
│       └── platforms.py
├── tests/
├── pyproject.toml
└── .gitignore
```

## Sources

- pzdataspec (GitHub: cff29546/pzdataspec) — specs Kaitai Struct
- pzmap2dzi (109 ⭐) — rendu de carte
- pz-webmap (62 ⭐) — carte web interactive
- Save location: `~/Zomboid/Saves/<GameMode>/<SaveName>/`
