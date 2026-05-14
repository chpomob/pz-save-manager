"""Flask web GUI for PZ Save Manager — compact cards + expandable detail."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template_string, request, send_file

from .backup import BackupError, BackupNotFound, create_backup, delete_backup, list_backups, restore_backup
from .config import get_all as config_get_all, set_ as config_set
from .platforms import get_backups_root, get_saves_root
from .save_info import extract_all
from .saves import SaveGame, SaveNotFound, get_save_modified_time, list_saves
from .watcher import WatcherManager, get_manager

app = Flask(__name__)

PAGE = """<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PZ Save Manager</title>
<style>
:root{--bg:#0d0d0d;--surface:#1a1a2e;--card:#16213e;--accent:#e94560;--accent2:#0f3460;--text:#eaeaea;--muted:#8892b0;--radius:10px;--green:#2ecc71;--red:#e74c3c;--yellow:#f39c12;--dead:#7f8c8d}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--bg);color:var(--text);min-height:100vh}
header{background:var(--surface);padding:1rem 2rem;display:flex;align-items:center;justify-content:space-between;border-bottom:2px solid var(--accent)}
header h1{font-size:1.3rem;font-weight:700}header h1 span{color:var(--accent)}
.status{display:flex;gap:1rem;align-items:center;font-size:.82rem}
.badge{background:var(--accent2);padding:.3rem .7rem;border-radius:20px;font-weight:500}
.badge.on{background:var(--green);color:#000}.badge.off{background:var(--accent2)}
.container{max-width:900px;margin:0 auto;padding:1.5rem}
h2{font-size:1rem;margin-bottom:.8rem;color:var(--accent);text-transform:uppercase;letter-spacing:1px;padding:.4rem 0;border-bottom:1px solid rgba(255,255,255,.08)}
h3{font-size:.85rem;color:var(--muted);margin:1.2rem 0 .4rem;padding:0;font-weight:500}
/* Compact card */
.card{background:var(--card);border-radius:var(--radius);border:1px solid rgba(255,255,255,.05);margin-bottom:.7rem;overflow:hidden;transition:border .15s}
.card:hover{border-color:rgba(255,255,255,.15)}
.card-header{display:flex;align-items:center;padding:.7rem .9rem;cursor:pointer;gap:.6rem;user-select:none;overflow:hidden}
.card-header .thumb{width:48px;height:36px;border-radius:4px;object-fit:cover;flex-shrink:0;background:var(--accent2)}
.card-header .info{flex:1 1 0;min-width:0;overflow:hidden}
.card-header .info .name{font-weight:600;font-size:.85rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%;display:block}
.card-header .info .sub{font-size:.7rem;color:var(--muted);margin-top:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%;display:block}
.card-header .status-dot{width:12px;height:12px;border-radius:50%;flex-shrink:0}
.status-alive{background:var(--green);box-shadow:0 0 8px var(--green)}
.status-dead{background:var(--dead)}
.status-unknown{background:var(--yellow)}
.card-header .arrow{color:var(--muted);font-size:1.2rem;transition:transform .2s;flex-shrink:0}
.card.open .card-header .arrow{transform:rotate(180deg)}
/* Detail panel */
.card-body{display:none;padding:0 1rem 1rem;border-top:1px solid rgba(255,255,255,.06)}
.card.open .card-body{display:block}
.card-body .detail-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:.5rem;margin-bottom:.8rem}
.detail-item{font-size:.8rem;color:var(--muted)}
.detail-item strong{color:var(--text);display:block}
.backup-list{border-top:1px solid rgba(255,255,255,.06);padding-top:.6rem;margin-top:.5rem}
.backup-item{display:flex;justify-content:space-between;align-items:center;padding:.3rem 0;font-size:.78rem}
.backup-item .ts{font-family:monospace;color:var(--muted);margin-right:1rem}
.btn{padding:.4rem .85rem;border:none;border-radius:6px;cursor:pointer;font-size:.78rem;font-weight:600;transition:filter .15s}
.btn:hover{filter:brightness(1.15)}.btn:active{transform:translateY(1px)}
.btn-accent{background:var(--accent);color:#fff}.btn-green{background:var(--green);color:#000}.btn-red{background:var(--red);color:#fff}
.btn-sm{padding:.25rem .6rem;font-size:.72rem}
.actions{display:flex;gap:.4rem;margin-top:.5rem;flex-wrap:wrap}
.empty{text-align:center;padding:3rem;color:var(--muted)}
.toast{position:fixed;bottom:1rem;right:1rem;background:var(--green);color:#000;padding:.7rem 1.2rem;border-radius:var(--radius);font-weight:600;z-index:99;animation:slidein .3s ease}
@keyframes slidein{from{transform:translateY(60px);opacity:0}to{transform:translateY(0);opacity:1}}
</style>
</head>
<body>
<header>
<h1>🧟 <span>PZ</span> Save Manager</h1>
<div class="status">
<span>Watcher: <span class="badge {{'on' if watcher_running else 'off'}}">{{'RUNNING' if watcher_running else 'STOPPED'}}</span></span>
<button class="btn btn-sm {{'btn-red' if watcher_running else 'btn-green'}}" onclick="toggleWatcher()">{{'Stop' if watcher_running else 'Start'}} Watcher</button>
<button class="btn btn-sm" style="background:var(--accent2);color:var(--text)" onclick="toggleSettings()">⚙</button>
<button class="btn btn-sm btn-red" onclick="shutdown()" title="Close app">✕</button>
</div>
</header>
<div class="container">
<h2>📁 Saves ({{saves|length}})</h2>
{% if not saves %}<div class="empty">No saves found. Launch Project Zomboid!</div>{% endif %}
<div class="grid">
{% for save in saves %}
<div class="card" id="save-{{loop.index}}">
<div class="card-header" onclick="this.parentElement.classList.toggle('open')">
{% if save.has_thumbnail %}<img src="/thumb/{{save.game_mode}}/{{save.full_name}}" class="thumb" loading="lazy">{% else %}<div class="thumb"></div>{% endif %}
<div class="info">
<div class="name" title="{{save.full_name}}">{% if save.player %}{{save.player}} · {% endif %}{{save.name}}</div>
<div class="sub">{{save.game_mode}}{% if save.map_name %} · {{save.map_name[:18]}}{% endif %} · {{save.modified}}</div>
</div>
<div class="status-dot {% if save.player_dead is none %}status-unknown{% elif save.player_dead %}status-dead{% else %}status-alive{% endif %}" title="{% if save.player_dead is none %}Unknown{% elif save.player_dead %}Dead{% else %}Alive{% endif %}"></div>
<span class="arrow">▾</span>
</div>
<div class="card-body">
<div class="detail-grid">
<div class="detail-item"><strong>Status</strong> {% if save.player_dead is none %}Unknown{% elif save.player_dead %}💀 Dead{% else %}🟢 Alive{% endif %}</div>
{% if save.player %}<div class="detail-item"><strong>Player</strong> {{save.player}}</div>{% endif %}
{% if save.player_x is not none %}<div class="detail-item"><strong>Position</strong> ({{save.player_x}}, {{save.player_y}})</div>{% endif %}
{% if save.player_world_version %}<div class="detail-item"><strong>World Version</strong> {{save.player_world_version}}</div>{% endif %}
<div class="detail-item"><strong>Files</strong> {{save.file_count}}</div>
<div class="detail-item"><strong>Size</strong> {{save.size_mb}} MB</div>
<div class="detail-item"><strong>Modified</strong> {{save.modified}}</div>
{% if save.vehicles is not none %}<div class="detail-item"><strong>Vehicles</strong> {{save.vehicles}}</div>{% endif %}
{% if save.chunks is not none %}<div class="detail-item"><strong>Chunks loaded</strong> {{save.chunks}}</div>{% endif %}
{% if save.mod_count %}<div class="detail-item"><strong>Mods</strong> {{save.mod_count}}{% endif %}
{% if save.items %}<div class="detail-item"><strong>Items</strong> {{save.items}}</div>{% endif %}
{% if save.players %}<div class="detail-item"><strong>Players</strong> {{save.players}}</div>{% endif %}
</div>
<div class="actions">
<button class="btn btn-accent" onclick="event.stopPropagation();backup('{{save.game_mode}}','{{save.full_name}}',this)">💾 Backup</button>
<button class="btn btn-sm" style="background:var(--accent2);color:var(--text)" onclick="event.stopPropagation();toggleWatch('{{save.game_mode}}','{{save.full_name}}',this)">{{'⏸ Unwatch' if save.watched else '👁 Watch'}}</button>
</div>
</div>
</div>
{% endfor %}
</div>

<h2 style="margin-top:2rem">📋 Backups ({{all_backups|length}})</h2>
{% if not all_backups %}<div class="empty">No backups yet.</div>{% endif %}
{% set ns = namespace(current='', open=false) %}
{% for b in all_backups[:50] %}
{% set key = b.game_mode + '/' + b.save_name %}
{% if key != ns.current %}
{% if ns.open %}</div>{% endif %}
{% set ns.current = key %}
{% set ns.open = true %}
<h3>{{b.game_mode}} / {{b.save_name[:28]}}</h3>
<div class="grid">
{% endif %}
<div class="card">
<div class="card-header" onclick="this.parentElement.classList.toggle('open')">
{% if b.has_thumbnail %}<img src="/thumb-backup/{{b.game_mode}}/{{b.save_name}}/{{b.timestamp}}" class="thumb" loading="lazy">{% else %}<div class="thumb"></div>{% endif %}
<div class="info">
<div class="name" title="{{b.timestamp}}">{{b.timestamp}}</div>
<div class="sub">{{b.age}} · {{b.size}} · {{b.files}} fichiers{% if b.auto %} · 🤖 auto{% else %} · ✋ manuel{% endif %}</div>
</div>
<div class="status-dot {% if b.player_dead is none %}status-unknown{% elif b.player_dead %}status-dead{% else %}status-alive{% endif %}"></div>
<span class="arrow">▾</span>
</div>
<div class="card-body">
<div class="detail-grid">
<div class="detail-item"><strong>Status</strong> {% if b.player_dead is none %}Unknown{% elif b.player_dead %}💀 Dead{% else %}🟢 Alive{% endif %}</div>
<div class="detail-item"><strong>Timestamp</strong> {{b.timestamp}}</div>
<div class="detail-item"><strong>Age</strong> {{b.age}}</div>
<div class="detail-item"><strong>Size</strong> {{b.size}}</div>
<div class="detail-item"><strong>Files</strong> {{b.files}}</div>
<div class="detail-item"><strong>Type</strong> {% if b.auto %}🤖 Automatic{% else %}✋ Manual{% endif %}</div>
<div class="detail-item"><strong>Save</strong> {{b.game_mode}} / {{b.save_name[:30]}}</div>
</div>
<div class="actions">
<button class="btn btn-green" onclick="event.stopPropagation();restore('{{b.game_mode}}','{{b.save_name}}','{{b.timestamp}}',this)">↩ Restore</button>
<button class="btn btn-red btn-sm" onclick="event.stopPropagation();deleteBackup('{{b.game_mode}}','{{b.save_name}}','{{b.timestamp}}',this)">🗑 Delete</button>
</div>
</div>
</div>
{% endfor %}
{% if ns.open %}</div>{% endif %}
<div id="toast" class="toast" style="display:none"></div>
<div id="settings-overlay" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.7);z-index:100;justify-content:center;align-items:center" onclick="if(event.target===this)toggleSettings()">
<div style="background:var(--surface);padding:2rem;border-radius:var(--radius);max-width:450px;width:90%;border:1px solid var(--accent)">
<h3 style="margin-bottom:1rem">⚙ Settings</h3>
<div style="margin-bottom:1rem"><label style="font-size:.85rem;color:var(--muted)">Backup directory</label>
<input id="cfg-backups-dir" style="width:100%;padding:.5rem;margin-top:.3rem;background:var(--bg);border:1px solid var(--accent2);color:var(--text);border-radius:6px" placeholder="Default: ~/.pz-save-manager/backups"></div>
<div style="margin-bottom:1rem"><label style="font-size:.85rem;color:var(--muted)">Auto-backup delay (seconds)</label>
<input id="cfg-debounce" type="number" step="1" min="1" max="60" style="width:100%;padding:.5rem;margin-top:.3rem;background:var(--bg);border:1px solid var(--accent2);color:var(--text);border-radius:6px"></div>
<div style="display:flex;gap:.5rem;justify-content:flex-end">
<button class="btn btn-sm" style="background:var(--accent2);color:var(--text)" onclick="toggleSettings()">Cancel</button>
<button class="btn btn-sm btn-green" onclick="saveSettings()">Save</button>
</div>
</div>
</div>
<script>
function toast(m,c){var t=document.getElementById('toast');t.textContent=m;t.style.background=c||'var(--green)';t.style.display='block';setTimeout(function(){t.style.display='none'},2500)}
function api(m,u,b){return fetch(u,{method:m,headers:{'Content-Type':'application/json'},body:b?JSON.stringify(b):undefined})}
function backup(m,n,b){b.disabled=true;api('POST','/api/backup',{game_mode:m,save_name:n}).then(r=>r.json()).then(d=>{d.ok?toast('Backup created!'):toast(d.error,'var(--red)');location.reload()})}
function restore(m,n,t,b){if(!confirm('Restore '+m+'/'+n+' from '+t+'?'))return;b.disabled=true;api('POST','/api/restore',{game_mode:m,save_name:n,timestamp:t}).then(r=>r.json()).then(d=>{d.ok?toast('Restored!'):toast(d.error,'var(--red)');location.reload()})}
function toggleWatcher(){api('POST','/api/watcher/toggle').then(r=>r.json()).then(d=>{toast(d.message);location.reload()})}
function toggleWatch(m,n,b){b.disabled=true;api('POST','/api/watcher/save',{game_mode:m,save_name:n}).then(r=>r.json()).then(d=>{toast(d.message);location.reload()})}
function toggleSettings(){var o=document.getElementById('settings-overlay');if(o.style.display==='flex'){o.style.display='none'}else{o.style.display='flex';api('GET','/api/config').then(r=>r.json()).then(d=>{document.getElementById('cfg-backups-dir').value=d.backups_dir||'';document.getElementById('cfg-debounce').value=d.debounce_seconds})}}
function saveSettings(){var data={backups_dir:document.getElementById('cfg-backups-dir').value,debounce_seconds:document.getElementById('cfg-debounce').value};api('POST','/api/config',data).then(r=>r.json()).then(d=>{d.ok?toast('Settings saved! Reloading...'):toast('Error','var(--red)');setTimeout(function(){location.reload()},1000)})}
function shutdown(){if(confirm('Close PZ Save Manager?')){api('POST','/api/shutdown').then(function(){document.body.innerHTML='<div style=\\\"text-align:center;padding:4rem;color:var(--muted)\\\"><h2>👋 Goodbye</h2><p>You can close this window.</p></div>'})}}
function deleteBackup(m,n,t,b){if(!confirm('Delete backup '+t+'?'))return;b.disabled=true;api('POST','/api/backup/delete',{game_mode:m,save_name:n,timestamp:t}).then(r=>r.json()).then(d=>{d.ok?toast('Deleted!')&&setTimeout(function(){location.reload()},800):toast(d.error,'var(--red)')})}
</script>
</body>
</html>"""


def _save_info(save: SaveGame, manager: WatcherManager) -> dict:
    path = save.path
    # Truncate display name for compact view
    short_name = save.name if len(save.name) <= 24 else save.name[:21] + "..."
    try:
        file_count = sum(1 for _ in path.rglob("*") if _.is_file())
        total_size = sum(_.stat().st_size for _ in path.rglob("*") if _.is_file())
    except OSError:
        file_count = 0
        total_size = 0
    modified = datetime.fromtimestamp(get_save_modified_time(save)).strftime("%Y-%m-%d %H:%M")
    backups = list_backups(save.game_mode, save.name)
    extra = extract_all(path)
    info = {
        "game_mode": save.game_mode, "name": short_name, "full_name": save.name,
        "modified": modified, "file_count": file_count,
        "size_mb": round(total_size / (1024 * 1024), 1),
        "has_thumbnail": extra.get("has_thumbnail", False),
        "backups": [{"game_mode": b.game_mode, "save_name": b.save_name,
            "timestamp": b.timestamp, "auto": b.auto,
            "size": f"{b.size_mb} MB", "files": b.file_count, "age": b.age,
        } for b in backups[:5]],
        "watched": save.display_name in manager.watched_saves(),
    }
    for k in ("vehicles", "players", "items", "map_pos", "map_name", "mod_count",
              "player", "player_dead", "player_x", "player_y", "player_world_version"):
        if k in extra:
            info[k] = extra[k]
    # Count map chunks loaded
    map_dir = save.path / "map"
    if map_dir.is_dir():
        try:
            info["chunks"] = sum(1 for _ in map_dir.glob("*.bin"))
        except OSError:
            pass
    return info


@app.route("/")
def index():
    manager = get_manager()
    saves = list_saves()
    save_infos = [_save_info(s, manager) for s in saves]
    all_backups = list_backups()
    all_b = []
    for b in all_backups:
        pi = extract_all(b.path)
        all_b.append({
            "game_mode": b.game_mode, "save_name": b.save_name,
            "timestamp": b.timestamp, "auto": b.auto,
            "size": f"{b.size_mb} MB", "files": b.file_count, "age": b.age,
            "has_thumbnail": (b.path / "thumb.png").is_file(),
            "player_dead": pi.get("player_dead"),
        })
    return render_template_string(PAGE, saves=save_infos, all_backups=all_b, watcher_running=manager.running)


@app.route("/api/backup", methods=["POST"])
def api_backup():
    data = request.get_json()
    try:
        b = create_backup(data["game_mode"], data["save_name"])
        return jsonify({"ok": True, "timestamp": b.timestamp})
    except (SaveNotFound, BackupError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/restore", methods=["POST"])
def api_restore():
    data = request.get_json()
    try:
        restore_backup(data["game_mode"], data["save_name"], data["timestamp"])
        return jsonify({"ok": True})
    except (BackupNotFound, BackupError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/backup/delete", methods=["POST"])
def api_delete_backup():
    data = request.get_json()
    try:
        delete_backup(data["game_mode"], data["save_name"], data["timestamp"])
        return jsonify({"ok": True, "message": "Backup deleted"})
    except (BackupNotFound, BackupError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/watcher/toggle", methods=["POST"])
def api_watcher_toggle():
    manager = get_manager()
    if manager.running:
        manager.stop()
        return jsonify({"ok": True, "message": "Watcher stopped"})
    saves = list_saves()
    for s in saves:
        manager.watch(s)
    manager.start()
    return jsonify({"ok": True, "message": f"Watcher started ({len(saves)} saves)"})


@app.route("/api/watcher/save", methods=["POST"])
def api_watcher_save():
    data = request.get_json()
    from .saves import get_save
    try:
        save = get_save(data["game_mode"], data["save_name"])
    except SaveNotFound:
        return jsonify({"ok": False, "error": "Save not found"}), 404
    manager = get_manager()
    if save.display_name in manager.watched_saves():
        manager.unwatch(save)
        return jsonify({"ok": True, "message": f"Unwatched {save.name}"})
    manager.watch(save)
    if not manager.running:
        manager.start()
    return jsonify({"ok": True, "message": f"Watching {save.name}"})


@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    """Get or update configuration."""
    if request.method == "GET":
        return jsonify(config_get_all())
    data = request.get_json()
    for key, value in data.items():
        if value == "" or value is None:
            continue
        if key in ("debounce_seconds", "port"):
            value = float(value) if "." in str(value) else int(value)
        config_set(key, value)
    return jsonify({"ok": True, "config": config_get_all()})


@app.route("/thumb-backup/<game_mode>/<save_name>/<timestamp>")
def serve_backup_thumbnail(game_mode: str, save_name: str, timestamp: str):
    from .backup import get_backup
    try:
        backup = get_backup(game_mode, save_name, timestamp)
        thumb = backup.path / "thumb.png"
        if thumb.is_file():
            return send_file(thumb, mimetype="image/png")
    except Exception:
        pass
    return "", 404


@app.route("/thumb/<game_mode>/<save_name>")
def serve_thumbnail(game_mode: str, save_name: str):
    from .saves import get_save
    try:
        save = get_save(game_mode, save_name)
        thumb = save.path / "thumb.png"
        if thumb.is_file():
            return send_file(thumb, mimetype="image/png")
    except Exception:
        pass
    return "", 404


@app.route("/api/shutdown", methods=["POST"])
def api_shutdown():
    """Gracefully stop the server."""
    manager = get_manager()
    if manager.running:
        manager.stop()

    def shutdown_server():
        import os
        os._exit(0)

    from threading import Timer
    Timer(0.5, shutdown_server).start()
    return jsonify({"ok": True, "message": "Shutting down..."})


def run_gui(host: str = "127.0.0.1", port: int = 8080) -> None:
    import webbrowser
    url = f"http://{host}:{port}"
    print(f"\n  🧟 PZ Save Manager — {url}\n")
    webbrowser.open(url)
    app.run(host=host, port=port, debug=False)
