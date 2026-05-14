# Notes techniques — Format de sauvegarde Project Zomboid

## Chemins des sauvegardes

| Plateforme | Chemin |
|-----------|--------|
| Windows | `%UserProfile%\Zomboid\Saves\<Mode>\<Nom>\` |
| Linux | `~/Zomboid/Saves/<Mode>/<Nom>/` |
| macOS | `~/Zomboid/Saves/<Mode>/<Nom>/` |

Modes : Apocalypse, Survivor, Builder, Sandbox, Multiplayer...

## Structure d'une sauvegarde

```
<SaveName>/
├── sandbox.lua              # Paramètres monde (texte Lua)
├── WorldDictionary.bin      # Dictionnaire ID → nom objets (binaire BE)
├── vehicles.db              # Véhicules (SQLite)
├── players.db               # Joueurs multi (SQLite)
├── visited.bin              # Zones explorées (binaire)
├── map_*.bin                # Métadonnées carte
├── map/
│   ├── <x>_<y>.bin          # Chunk : objets, inventaire, joueur (binaire BE)
│   ├── <x>_<y>.lotheader    # Métadonnées cellule (binaire LE)
│   └── world_<x>_<y>.lotpack # Tiles compressées (binaire LE)
└── *.zpop                   # Population zombie (certaines versions)
```

## Endianness

| Fichiers | Endianness |
|----------|-----------|
| `map/*.bin` (chunks) | Big-endian |
| `WorldDictionary.bin` | Big-endian |
| `*.lotheader` | Little-endian |
| `*.lotpack` | Little-endian |
| `*.tiles` | Little-endian |

## Versions du format

| Build | World Version |
|-------|--------------|
| 41.78.7-19 | 195 |
| 42.13.2 | 241 |
| 42.14.1 | 243 |
| 42.15.0 | 244 |
| 42.16.0-17.0 | 245 |

## Structure d'un chunk (.bin)

1. debug (u1)
2. world_version (u4)
3. size (u4)
4. crc (u8)
5. Blood splats
6. Grid squares (100 = 10×10)
7. Erosion data
8. Generators
9. Vehicles (références vers vehicles.db)
10. Loot respawn data

Chaque grid square contient : erosion, flags, objets (avec class-ID dispatch), corps, pièges, KahluaTable modData.

## Objets et Class IDs

Les objets utilisent un système de dispatch par class ID (u1) :
- 1 = IsoPlayer (joueur)
- 3 = IsoZombie
- 17 = IsoDoor
- 26 = IsoWindow
- 28 = IsoTree
- ... (35+ classes connues)

## Joueur (IsoPlayer, class ID 1)

Données sérialisées : descripteur survivant, apparence, inventaire, stats, dégâts corporels, XP, recettes connues, fitness, équipement...

**Le joueur est intégré dans le chunk où il se trouve physiquement. Il n'y a pas de fichier joueur séparé.**

## Fichiers indépendants (restaurables séparément)

| Fichier | Format | Indépendant |
|---------|--------|------------|
| sandbox.lua | Texte Lua | ✅ Oui |
| vehicles.db | SQLite | ✅ Oui |
| players.db | SQLite | ✅ Oui |
| visited.bin | Binaire | ✅ Oui |
| WorldDictionary.bin | Binaire BE | ✅ Oui (doit matcher la version) |
| Chunk <x>_<y>.bin | Binaire BE | ⚠️ Quasi-indépendant |
| .zpop | Binaire | ⚠️ Par chunk |

## Outils communautaires

- **pzdataspec** — specs Kaitai Struct + parsers Python (B41→B42)
- **pzmap2dzi** — rendu carte Deep Zoom
- **pz-webmap** — carte web interactive
- **Kaitai Struct** — framework de parsing binaire multi-langage

## Strings

- UTF-8 avec préfixe u2be (longueur) — chunks, WorldDictionary
- LF-terminated (0x0A) — lotheader, lotpack, tile_def

## KahluaTable

Format de sérialisation Lua binaire pour données flexibles clé-valeur.
Supporte : strings, floats, booleans, tables imbriquées.
Utilisé pour modData dans les chunks.
