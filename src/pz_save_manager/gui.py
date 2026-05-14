"""Flask web GUI for PZ Save Manager — Plex-like dark UI."""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template_string, request

from .backup import BackupError, BackupNotFound, create_backup, delete_backup, list_backups, restore_backup
from .platforms import get_backups_root, get_saves_root
from .saves import SaveGame, SaveNotFound, get_save_modified_time, list_saves
from .watcher import WatcherManager, get_manager

app = Flask(__name__)

# ---- HTML template (Plex-like dark theme) ----

PAGE = """<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PZ Save Manager</title>
<style>
:root{--bg:#0d0d0d;--surface:#1a1a2e;--card:#16213e;--accent:#e94560;--accent2:#0f3460;--text:#eaeaea;--muted:#8892b0;--radius:10px;--green:#2ecc71;--red:#e74c3c}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--bg);color:var(--text);min-height:100vh}
header{background:var(--surface);padding:1.2rem 2rem;display:flex;align-items:center;justify-content:space-between;border-bottom:2px solid var(--accent)}
header h1{font-size:1.4rem;font-weight:700;letter-spacing:-0.5px}
header h1 span{color:var(--accent)}
.status{display:flex;gap:1rem;align-items:center;font-size:.85rem}
.badge{background:var(--accent2);padding:.35rem .75rem;border-radius:20px;font-weight:500}
.badge.on{background:var(--green);color:#000}
.badge.off{background:var(--accent2)}
.container{max-width:1100px;margin:0 auto;padding:2rem}
h2{font-size:1.1rem;margin-bottom:1rem;color:var(--muted);text-transform:uppercase;letter-spacing:1px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:1.2rem}
.card{background:var(--card);border-radius:var(--radius);padding:1.3rem;border:1px solid rgba(255,255,255,.05);transition:border .2s}
.card:hover{border-color:var(--accent)}
.card h3{font-size:1rem;margin-bottom:.3rem}
.card .mode{font-size:.8rem;color:var(--accent);margin-bottom:.8rem;text-transform:uppercase}
.card .meta{font-size:.8rem;color:var(--muted);margin-bottom:1rem;line-height:1.5}
.card .actions{display:flex;gap:.5rem;flex-wrap:wrap}
.btn{padding:.5rem 1rem;border:none;border-radius:6px;cursor:pointer;font-size:.82rem;font-weight:600;text-decoration:none;display:inline-block;transition:filter .15s,transform .1s}
.btn:hover{filter:brightness(1.15);transform:translateY(-1px)}
.btn:active{transform:translateY(0)}
.btn-accent{background:var(--accent);color:#fff}
.btn-secondary{background:var(--accent2);color:var(--text)}
.btn-green{background:var(--green);color:#000}
.btn-red{background:var(--red);color:#fff}
.btn-sm{padding:.3rem .7rem;font-size:.75rem}
.backup-list{margin-top:1rem;border-top:1px solid rgba(255,255,255,.08);padding-top:.8rem}
.backup-item{display:flex;justify-content:space-between;align-items:center;padding:.4rem 0;font-size:.82rem}
.backup-item .ts{color:var(--muted);font-family:monospace}
.empty{text-align:center;padding:3rem;color:var(--muted)}
.toast{position:fixed;bottom:1rem;right:1rem;background:var(--green);color:#000;padding:.8rem 1.2rem;border-radius:var(--radius);font-weight:600;z-index:99;animation:slidein .3s ease}
@keyframes slidein{from{transform:translateY(60px);opacity:0}to{transform:translateY(0);opacity:1}}
.spin{animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
</style>
</head>
<body>
<header>
  <h1>🧟 <span>PZ</span> Save Manager</h1>
  <div class="status">
    <span>Watcher: <span class="badge {{'on' if watcher_running else 'off'}}">{{'RUNNING' if watcher_running else 'STOPPED'}}</span></span>
    <span>Saves: <span class="badge">{{saves|length}}</span></span>
    <button class="btn btn-sm {{'btn-red' if watcher_running else 'btn-green'}}" onclick="toggleWatcher()">
      {{'Stop Watcher' if watcher_running else 'Start Watcher'}}
    </button>
  </div>
</header>
<div class="container">
  <h2>📁 Your Saves</h2>
  {% if not saves %}
  <div class="empty">No saves found. Launch Project Zomboid to create one!</div>
  {% endif %}
  <div class="grid">
  {% for save in saves %}
  <div class="card" id="save-{{loop.index}}">
    <h3>{{save.name}}</h3>
    <div class="mode">{{save.game_mode}}</div>
    <div class="meta">
      Modified: {{save.modified}}<br>
      Files: {{save.file_count}} &middot; {{save.size_mb}} MB
    </div>
    <div class="actions">
      <button class="btn btn-accent" onclick="backup('{{save.game_mode}}','{{save.name}}',this)">💾 Backup now</button>
      <button class="btn btn-secondary btn-sm" onclick="toggleWatch('{{save.game_mode}}','{{save.name}}',this)">
        {{'⏸ Unwatch' if save.watched else '👁 Watch'}}
      </button>
    </div>
    <div class="backup-list" id="backups-{{save.game_mode}}-{{save.name}}">
      {% for b in save.backups[:5] %}
      <div class="backup-item">
        <span class="ts">{{b.timestamp}}</span>
        <button class="btn btn-sm btn-green" onclick="restore('{{b.game_mode}}','{{b.save_name}}','{{b.timestamp}}',this)">↩ Restore</button>
      </div>
      {% endfor %}
      {% if not save.backups %}
      <div class="backup-item"><span style="color:var(--muted)">No backups yet</span></div>
      {% endif %}
    </div>
  </div>
  {% endfor %}
  </div>
  <h2 style="margin-top:2rem">📋 All Backups</h2>
  {% if not all_backups %}
  <div class="empty">No backups created yet.</div>
  {% else %}
  <div class="grid">
  {% for b in all_backups[:20] %}
  <div class="card">
    <h3>{{b.save_name}}</h3>
    <div class="mode">{{b.game_mode}} &middot; {{b.timestamp}}</div>
    <button class="btn btn-green btn-sm" onclick="restore('{{b.game_mode}}','{{b.save_name}}','{{b.timestamp}}',this)">↩ Restore</button>
  </div>
  {% endfor %}
  </div>
  {% endif %}
</div>
<div id="toast" class="toast" style="display:none"></div>
<script>
function toast(msg,color='var(--green)'){var t=document.getElementById('toast');t.textContent=msg;t.style.background=color;t.style.display='block';setTimeout(function(){t.style.display='none'},2500)}
function api(method,url,body){return fetch(url,{method:method,headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined})}
function backup(mode,name,btn){btn.disabled=true;btn.textContent='...';api('POST','/api/backup',{game_mode:mode,save_name:name}).then(r=>r.json()).then(d=>{if(d.ok){toast('Backup created!');location.reload()}else{toast(d.error,'var(--red)');btn.disabled=false;btn.textContent='💾 Backup now'}})}
function restore(mode,name,ts,btn){if(!confirm('Restore '+mode+'/'+name+' from '+ts+'? Current save will be replaced.'))return;btn.disabled=true;btn.textContent='...';api('POST','/api/restore',{game_mode:mode,save_name:name,timestamp:ts}).then(r=>r.json()).then(d=>{if(d.ok){toast('Restored!');location.reload()}else{toast(d.error,'var(--red)')}})}
function toggleWatcher(){api('POST','/api/watcher/toggle').then(r=>r.json()).then(d=>{toast(d.message);location.reload()})}
function toggleWatch(mode,name,btn){btn.disabled=true;api('POST','/api/watcher/save',{game_mode:mode,save_name:name}).then(r=>r.json()).then(d=>{toast(d.message);location.reload()})}
</script>
</body>
</html>"""


# ---- Helpers ----

def _save_info(save: SaveGame, manager: WatcherManager) -> dict:
    path = save.path
    try:
        file_count = sum(1 for _ in path.rglob("*") if _.is_file())
        total_size = sum(_.stat().st_size for _ in path.rglob("*") if _.is_file())
    except OSError:
        file_count = 0
        total_size = 0
    modified = datetime.fromtimestamp(get_save_modified_time(save)).strftime("%Y-%m-%d %H:%M:%S")
    backups = list_backups(save.game_mode, save.name)
    return {
        "game_mode": save.game_mode,
        "name": save.name,
        "path": str(save.path),
        "modified": modified,
        "file_count": file_count,
        "size_mb": round(total_size / (1024 * 1024), 1),
        "backups": [{"game_mode": b.game_mode, "save_name": b.save_name, "timestamp": b.timestamp} for b in backups[:5]],
        "watched": save.display_name in manager.watched_saves(),
    }


# ---- Routes ----

@app.route("/")
def index():
    manager = get_manager()
    saves = list_saves()
    save_infos = [_save_info(s, manager) for s in saves]
    all_backups = list_backups()
    all_b = [{"game_mode": b.game_mode, "save_name": b.save_name, "timestamp": b.timestamp} for b in all_backups]
    return render_template_string(
        PAGE,
        saves=save_infos,
        all_backups=all_b,
        watcher_running=manager.running,
    )


@app.route("/api/backup", methods=["POST"])
def api_backup():
    data = request.get_json()
    try:
        backup = create_backup(data["game_mode"], data["save_name"])
        return jsonify({"ok": True, "timestamp": backup.timestamp, "path": str(backup.path)})
    except (SaveNotFound, BackupError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/restore", methods=["POST"])
def api_restore():
    data = request.get_json()
    try:
        restore_backup(data["game_mode"], data["save_name"], data["timestamp"])
        return jsonify({"ok": True, "message": "Save restored"})
    except (BackupNotFound, BackupError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/watcher/toggle", methods=["POST"])
def api_watcher_toggle():
    manager = get_manager()
    if manager.running:
        manager.stop()
        return jsonify({"ok": True, "message": "Watcher stopped"})
    else:
        saves = list_saves()
        for s in saves:
            manager.watch(s)
        manager.start()
        return jsonify({"ok": True, "message": f"Watcher started, watching {len(saves)} saves"})


@app.route("/api/watcher/save", methods=["POST"])
def api_watcher_save():
    data = request.get_json()
    try:
        from .saves import get_save
        save = get_save(data["game_mode"], data["save_name"])
    except SaveNotFound:
        return jsonify({"ok": False, "error": "Save not found"}), 404
    manager = get_manager()
    if save.display_name in manager.watched_saves():
        manager.unwatch(save)
        return jsonify({"ok": True, "message": f"Stopped watching {save.name}"})
    else:
        manager.watch(save)
        if not manager.running:
            manager.start()
        return jsonify({"ok": True, "message": f"Watching {save.name}"})


def run_gui(host: str = "127.0.0.1", port: int = 8080) -> None:
    """Launch the web GUI."""
    import webbrowser
    url = f"http://{host}:{port}"
    print(f"\n  🧟 PZ Save Manager — {url}\n")
    webbrowser.open(url)
    app.run(host=host, port=port, debug=False)
