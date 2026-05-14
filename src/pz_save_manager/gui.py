"""Flask web GUI for PZ Save Manager — compact cards + expandable detail."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template_string, request, send_file

from .backup import BackupError, BackupNotFound, create_backup, list_backups, restore_backup
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
h2{font-size:1rem;margin-bottom:.8rem;color:var(--muted);text-transform:uppercase;letter-spacing:1px}
/* Compact card */
.card{background:var(--card);border-radius:var(--radius);border:1px solid rgba(255,255,255,.05);margin-bottom:.7rem;overflow:hidden;transition:border .15s}
.card:hover{border-color:rgba(255,255,255,.15)}
.card-header{display:flex;align-items:center;padding:.8rem 1rem;cursor:pointer;gap:.8rem;user-select:none}
.card-header .thumb{width:72px;height:54px;border-radius:6px;object-fit:cover;flex-shrink:0;background:var(--accent2)}
.card-header .info{flex:1;min-width:0}
.card-header .info .name{font-weight:600;font-size:.95rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.card-header .info .sub{font-size:.78rem;color:var(--muted);margin-top:2px}
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
</div>
</header>
<div class="container">
<h2>📁 Saves ({{saves|length}})</h2>
{% if not saves %}<div class="empty">No saves found. Launch Project Zomboid!</div>{% endif %}
{% for save in saves %}
<div class="card" id="save-{{loop.index}}">
<div class="card-header" onclick="this.parentElement.classList.toggle('open')">
{% if save.has_thumbnail %}<img src="/thumb/{{save.game_mode}}/{{save.name}}" class="thumb" loading="lazy">{% else %}<div class="thumb"></div>{% endif %}
<div class="info">
<div class="name">{% if save.player %}{{save.player}} · {% endif %}{{save.name}}</div>
<div class="sub">{{save.game_mode}}{% if save.map_name %} · {{save.map_name}}{% endif %} · {{save.modified}}{% if save.size_mb %} · {{save.size_mb}} MB{% endif %}</div>
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
{% if save.crafted is not none %}<div class="detail-item"><strong>Crafted</strong> {{save.crafted}} objects</div>{% endif %}
{% if save.mod_count %}<div class="detail-item"><strong>Mods</strong> {{save.mod_count}}{% endif %}
{% if save.items %}<div class="detail-item"><strong>Items</strong> {{save.items}}</div>{% endif %}
{% if save.players %}<div class="detail-item"><strong>Players</strong> {{save.players}}</div>{% endif %}
</div>
<div class="actions">
<button class="btn btn-accent" onclick="event.stopPropagation();backup('{{save.game_mode}}','{{save.name}}',this)">💾 Backup</button>
<button class="btn btn-sm" style="background:var(--accent2);color:var(--text)" onclick="event.stopPropagation();toggleWatch('{{save.game_mode}}','{{save.name}}',this)">{{'⏸ Unwatch' if save.watched else '👁 Watch'}}</button>
</div>
<div class="backup-list">
<div style="font-size:.8rem;color:var(--muted);margin-bottom:.3rem">Backups:</div>
{% if save.backups %}
{% for b in save.backups[:5] %}
<div class="backup-item">
<span class="ts">{{b.age}} · {{b.size}} · {{b.files}} files {% if b.auto %}🤖{% endif %}</span>
<span style="flex:1"></span>
<button class="btn btn-sm btn-green" onclick="event.stopPropagation();restore('{{b.game_mode}}','{{b.save_name}}','{{b.timestamp}}',this)">↩</button>
</div>
{% endfor %}
{% else %}
<div class="backup-item"><span style="color:var(--muted)">None yet</span></div>
{% endif %}
</div>
</div>
</div>
{% endfor %}
</div>
<div id="toast" class="toast" style="display:none"></div>
<script>
function toast(m,c){var t=document.getElementById('toast');t.textContent=m;t.style.background=c||'var(--green)';t.style.display='block';setTimeout(function(){t.style.display='none'},2500)}
function api(m,u,b){return fetch(u,{method:m,headers:{'Content-Type':'application/json'},body:b?JSON.stringify(b):undefined})}
function backup(m,n,b){b.disabled=true;api('POST','/api/backup',{game_mode:m,save_name:n}).then(r=>r.json()).then(d=>{d.ok?toast('Backup created!'):toast(d.error,'var(--red)');location.reload()})}
function restore(m,n,t,b){if(!confirm('Restore '+m+'/'+n+' from '+t+'?'))return;b.disabled=true;api('POST','/api/restore',{game_mode:m,save_name:n,timestamp:t}).then(r=>r.json()).then(d=>{d.ok?toast('Restored!'):toast(d.error,'var(--red)');location.reload()})}
function toggleWatcher(){api('POST','/api/watcher/toggle').then(r=>r.json()).then(d=>{toast(d.message);location.reload()})}
function toggleWatch(m,n,b){b.disabled=true;api('POST','/api/watcher/save',{game_mode:m,save_name:n}).then(r=>r.json()).then(d=>{toast(d.message);location.reload()})}
</script>
</body>
</html>"""


def _save_info(save: SaveGame, manager: WatcherManager) -> dict:
    path = save.path
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
        "game_mode": save.game_mode, "name": save.name,
        "modified": modified, "file_count": file_count,
        "size_mb": round(total_size / (1024 * 1024), 1),
        "has_thumbnail": extra.get("has_thumbnail", False),
        "backups": [{"game_mode": b.game_mode, "save_name": b.save_name,
            "timestamp": b.timestamp, "auto": b.auto,
            "size": f"{b.size_mb} MB", "files": b.file_count, "age": b.age,
        } for b in backups[:5]],
        "watched": save.display_name in manager.watched_saves(),
    }
    for k in ("vehicles", "players", "items", "map_pos", "map_name", "mod_count", "crafted",
              "player", "player_dead", "player_x", "player_y", "player_world_version"):
        if k in extra:
            info[k] = extra[k]
    return info


@app.route("/")
def index():
    manager = get_manager()
    saves = list_saves()
    save_infos = [_save_info(s, manager) for s in saves]
    return render_template_string(PAGE, saves=save_infos, watcher_running=manager.running)


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


def run_gui(host: str = "127.0.0.1", port: int = 8080) -> None:
    import webbrowser
    url = f"http://{host}:{port}"
    print(f"\n  🧟 PZ Save Manager — {url}\n")
    webbrowser.open(url)
    app.run(host=host, port=port, debug=False)
