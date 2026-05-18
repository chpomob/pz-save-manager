"""Flask web GUI for PZ Save Manager — compact cards + expandable detail."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template_string, request, send_file

from .backup import BackupError, BackupNotFound, create_backup, delete_backup, get_backup, get_backup_note, list_backups, restore_backup, set_backup_note
from .config import get_all as config_get_all, set_ as config_set
from .platforms import get_backups_root, get_saves_root
from .save_info import extract_all, player_info
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
.card-header .info .name{font-weight:600;font-size:.85rem;white-space:normal;word-break:break-word;max-width:100%;display:block}
.card-header .info .sub{font-size:.7rem;color:var(--muted);margin-top:1px;white-space:normal;word-break:break-word;max-width:100%;display:block}
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
.help{display:inline-block;width:16px;height:16px;line-height:16px;text-align:center;border-radius:50%;background:var(--accent2);color:var(--text);font-size:.65rem;font-weight:700;cursor:help;margin-left:4px;vertical-align:middle}
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
<div class="name" title="{{save.full_name}}">{{save.name}}</div>
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
<div class="detail-item"><strong>Modified</strong> {{save.modified}}</div>
{% if save.mod_count %}<div class="detail-item"><strong>Mods</strong> {{save.mod_count}}</div>{% endif %}
{% if save.players %}<div class="detail-item"><strong>Players</strong> {{save.players}}</div>{% endif %}
</div>
<div class="actions">
<button class="btn btn-accent" onclick='event.stopPropagation();backup({{save.game_mode|tojson}},{{save.full_name|tojson}},this)'>💾 Backup</button>
<button class="btn btn-sm" style="background:var(--accent2);color:var(--text)" onclick='event.stopPropagation();toggleWatch({{save.game_mode|tojson}},{{save.full_name|tojson}},this)'>{{'⏸ Unwatch' if save.watched else '👁 Watch'}}</button>
<button class="btn btn-sm" style="background:var(--accent2);color:var(--text)" onclick='event.stopPropagation();renameSave({{save.game_mode|tojson}},{{save.full_name|tojson}},this)'>✏️ Rename</button>
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
{% if b.has_thumbnail %}<img src="/thumb-backup/{{b.game_mode}}/{{b.real_save_name}}/{{b.timestamp}}" class="thumb" loading="lazy">{% else %}<div class="thumb"></div>{% endif %}
<div class="info">
<div class="name" title="{{b.formatted}}">{{b.formatted}}</div>
<div class="sub">{{b.age}}{% if b.auto %} · 🤖 auto{% else %} · ✋ manuel{% endif %}</div>
</div>
<div class="status-dot {% if b.player_dead is none %}status-unknown{% elif b.player_dead %}status-dead{% else %}status-alive{% endif %}"></div>
<span class="arrow">▾</span>
</div>
<div class="card-body">
<div class="detail-grid">
<div class="detail-item"><strong>Status</strong> {% if b.player_dead is none %}Unknown{% elif b.player_dead %}💀 Dead{% else %}🟢 Alive{% endif %}</div>
{% if b.player %}<div class="detail-item"><strong>Player</strong> {{b.player}}</div>{% endif %}
<div class="detail-item"><strong>Timestamp</strong> {{b.formatted}}</div>
<div class="detail-item"><strong>Age</strong> {{b.age}}</div>
<div class="detail-item"><strong>Type</strong> {% if b.auto %}🤖 Automatic{% else %}✋ Manual{% endif %}</div>
<div class="detail-item"><strong>Save</strong> {{b.game_mode}} / {{b.save_name[:30]}}</div>
</div>
{% if b.note %}<div style="background:rgba(233,69,96,.08);border-left:3px solid var(--accent);padding:.5rem .8rem;margin-bottom:.6rem;border-radius:4px;font-size:.78rem;color:var(--text);max-height:80px;overflow-y:auto;white-space:pre-wrap;word-break:break-word">{{b.note}}</div>{% endif %}
<div class="actions">
<button class="btn btn-green" onclick='event.stopPropagation();restore({{b.game_mode|tojson}},{{b.real_save_name|tojson}},{{b.timestamp|tojson}},this)'>↩ Restore</button>
<button class="btn btn-red btn-sm" onclick='event.stopPropagation();deleteBackup({{b.game_mode|tojson}},{{b.real_save_name|tojson}},{{b.timestamp|tojson}},this)'>🗑 Delete</button>
<button class="btn btn-sm" style="background:var(--accent2);color:var(--text)" onclick='event.stopPropagation();annotate({{b.game_mode|tojson}},{{b.real_save_name|tojson}},{{b.timestamp|tojson}},this)'>📝 Note</button>
</div>
</div>
</div>
{% endfor %}
{% if ns.open %}</div>{% endif %}
<div id="toast" class="toast" style="display:none"></div>
<div id="settings-overlay" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.7);z-index:100;justify-content:center;align-items:center" onclick="if(event.target===this)toggleSettings()">
<div style="background:var(--surface);padding:2rem;border-radius:var(--radius);max-width:450px;width:90%;border:1px solid var(--accent)">
<h3 style="margin-bottom:1rem">⚙ Settings</h3>
<div style="margin-bottom:1rem"><label style="font-size:.85rem;color:var(--muted)">Backup directory <span class="help" title="Where backups are stored. Default: ~/.pz-save-manager/backups">?</span></label>
<input id="cfg-backups-dir" style="width:100%;padding:.5rem;margin-top:.3rem;background:var(--bg);border:1px solid var(--accent2);color:var(--text);border-radius:6px" placeholder="Default: ~/.pz-save-manager/backups"></div>
<div style="margin-bottom:1rem"><label style="font-size:.85rem;color:var(--muted)">Min interval between backups (minutes) <span class="help" title="After an auto-backup, the watcher waits at least this long before making another one. Prevents backup spam during intense gameplay.">?</span></label>
<input id="cfg-cooldown" type="number" step="1" min="1" max="1440" style="width:100%;padding:.5rem;margin-top:.3rem;background:var(--bg);border:1px solid var(--accent2);color:var(--text);border-radius:6px"></div>
<div style="margin-bottom:1rem"><label style="font-size:.85rem;color:var(--muted)">Max auto-backups per save <span class="help" title="Maximum number of automatic backups kept per save. Oldest auto-backups are deleted when this limit is reached. Manual backups are never pruned.">?</span></label>
<input id="cfg-max-auto" type="number" step="1" min="1" max="999" style="width:100%;padding:.5rem;margin-top:.3rem;background:var(--bg);border:1px solid var(--accent2);color:var(--text);border-radius:6px"></div>
<div style="display:flex;gap:.5rem;justify-content:flex-end">
<button class="btn btn-sm" style="background:var(--accent2);color:var(--text)" onclick="toggleSettings()">Cancel</button>
<button class="btn btn-sm btn-green" onclick="saveSettings()">Save</button>
</div>
</div>
</div>
<script>
function toast(m,c){var t=document.getElementById('toast');t.textContent=m;t.style.background=c||'var(--green)';t.style.display='block';setTimeout(function(){t.style.display='none'},2500)}
function api(m,u,b){return fetch(u,{method:m,headers:{'Content-Type':'application/json'},body:b?JSON.stringify(b):undefined})}
function doAction(b,url,body,okMsg){
  if(b)b.disabled=true;
  return api('POST',url,body).then(r=>r.json()).then(d=>{
    if(d.ok){toast(okMsg||d.message||'OK');setTimeout(function(){location.reload()},600)}
    else{toast(d.error||d.message||'Error','var(--red)');if(b)b.disabled=false}
  }).catch(function(){toast('Network error','var(--red)');if(b)b.disabled=false})
}
function backup(m,n,b){doAction(b,'/api/backup',{game_mode:m,save_name:n},'Backup created!')}
function restore(m,n,t,b){if(!confirm('Restore '+m+'/'+n+' from '+t+'?'))return;doAction(b,'/api/restore',{game_mode:m,save_name:n,timestamp:t},'Restored!')}
function deleteBackup(m,n,t,b){if(!confirm('Delete backup '+t+'?'))return;doAction(b,'/api/backup/delete',{game_mode:m,save_name:n,timestamp:t},'Deleted!')}
function toggleWatcher(){doAction(null,'/api/watcher/toggle',null)}
function renameSave(m,n,b){var name=prompt('New name for '+n+':');if(!name||name.trim()===''||name.trim()===n)return;doAction(b,'/api/save/rename',{game_mode:m,old_name:n,new_name:name.trim()},'Renamed to '+name.trim()+'!')}
function annotate(m,n,t,b){var note=prompt('Note for '+t+' (empty to remove):');if(note===null)return;doAction(b,'/api/backup/annotate',{game_mode:m,save_name:n,timestamp:t,note:note},note?'Note saved':'Note removed')}
function toggleWatch(m,n,b){doAction(b,'/api/watcher/save',{game_mode:m,save_name:n})}
function toggleSettings(){var o=document.getElementById('settings-overlay');if(o.style.display==='flex'){o.style.display='none'}else{o.style.display='flex';api('GET','/api/config').then(r=>r.json()).then(d=>{document.getElementById('cfg-backups-dir').value=d.backups_dir||'';document.getElementById("cfg-cooldown").value=d.backup_cooldown_minutes;document.getElementById("cfg-max-auto").value=d.max_auto_backups})}}
function saveSettings(){var data={backups_dir:document.getElementById('cfg-backups-dir').value,backup_cooldown_minutes:document.getElementById("cfg-cooldown").value,max_auto_backups:document.getElementById("cfg-max-auto").value};doAction(null,'/api/config',data,'Settings saved!')}
function shutdown(){if(!confirm('Close PZ Save Manager?'))return;api('POST','/api/shutdown').then(function(){document.body.innerHTML='<div style="text-align:center;padding:4rem;color:#888"><h2>👋 Goodbye</h2><p>You can close this window.</p></div>'}).catch(function(){toast('Network error','var(--red)')})}
</script>
</body>
</html>"""




def _save_info(save: SaveGame, manager: WatcherManager) -> dict:
    path = save.path
    modified = datetime.fromtimestamp(get_save_modified_time(save)).strftime("%Y-%m-%d %H:%M")
    backups = list_backups(save.game_mode, save.name)
    extra = extract_all(path)
    info = {
        "game_mode": save.game_mode, "name": save.name, "full_name": save.name,
        "modified": modified,
        "has_thumbnail": extra.get("has_thumbnail", False),
        "backups": [{"game_mode": b.game_mode, "save_name": b.save_name,
            "timestamp": b.timestamp, "auto": b.auto, "age": b.age, "formatted": b.formatted,
        } for b in backups[:5]],
        "watched": save.display_name in manager.watched_saves(),
    }
    for k in ("players", "map_pos", "map_name", "mod_count",
              "player", "player_dead", "player_x", "player_y", "player_world_version"):
        if k in extra:
            info[k] = extra[k]
    return info


@app.route("/")
def index():
    try:
        manager = get_manager()
        saves = list_saves()
        # Per-save try/except: a single corrupt save shouldn't blank the page.
        save_infos = []
        for s in saves:
            try:
                save_infos.append(_save_info(s, manager))
            except Exception:
                import logging
                logging.getLogger(__name__).warning("could not read save %s", s.display_name, exc_info=True)
        all_backups = list_backups()
        all_b = []
        for b in all_backups:
            # Only player_dead is used in the card; reading just players.db is
            # O(1) versus extract_all which reads every metadata file. Backups
            # also have b.size_mb / b.file_count properties that rglob — skip
            # those in the list view, surface them lazily if/when needed.
            pi = player_info(b.path) or {}
            display_name = b.save_name
            all_b.append({
                "game_mode": b.game_mode, "save_name": display_name, "real_save_name": b.save_name,
                "timestamp": b.timestamp, "auto": b.auto, "age": b.age, "formatted": b.formatted,
                "has_thumbnail": (b.path / "thumb.png").is_file(),
                "player": pi.get("name"),
                "player_dead": pi.get("is_dead"),
                "note": get_backup_note(b.path),
            })
        return render_template_string(PAGE, saves=save_infos, all_backups=all_b, watcher_running=manager.running)
    except Exception:
        import traceback
        tb = traceback.format_exc()
        import logging
        logging.getLogger(__name__).exception("index render failed")
        return (
            "<!doctype html><meta charset='utf-8'>"
            "<style>body{font-family:monospace;background:#111;color:#eee;padding:2rem}"
            "pre{white-space:pre-wrap;background:#222;padding:1rem;border-radius:6px}"
            "a{color:#e94560}</style>"
            "<h2>PZ Save Manager — internal error</h2>"
            f"<p>The page failed to render. <a href='/health'>Open /health</a> for diagnostics.</p>"
            f"<pre>{tb}</pre>",
            500,
        )


@app.route("/health")
def health():
    """Plain-text diagnostic page — shows resolved paths and what was discovered.

    Useful when a user reports a blank page: navigating to /health bypasses
    most of the rendering code and surfaces the underlying environment.
    """
    import json
    import platform as _platform
    import sys
    from . import __version__

    saves_root = get_saves_root()
    backups_root = get_backups_root()
    info: dict = {
        "version": __version__,
        "python": sys.version,
        "executable": sys.executable,
        "platform": _platform.platform(),
        "frozen": getattr(sys, "frozen", False),
        "saves_root": str(saves_root),
        "saves_root_exists": saves_root.is_dir(),
        "backups_root": str(backups_root),
        "backups_root_exists": backups_root.is_dir(),
        "errors": [],
    }
    try:
        saves = list_saves()
        info["save_count"] = len(saves)
        info["saves"] = [{"game_mode": s.game_mode, "name": s.name, "path": str(s.path)} for s in saves]
    except Exception as e:
        info["errors"].append(f"list_saves: {e!r}")
    try:
        info["backup_count"] = len(list_backups())
    except Exception as e:
        info["errors"].append(f"list_backups: {e!r}")
    if saves_root.is_dir():
        try:
            info["saves_root_children"] = sorted(p.name for p in saves_root.iterdir())
        except Exception as e:
            info["errors"].append(f"iterdir saves_root: {e!r}")
    else:
        zomboid = saves_root.parent
        info["zomboid_dir_exists"] = zomboid.is_dir()
        if zomboid.is_dir():
            try:
                info["zomboid_dir_children"] = sorted(p.name for p in zomboid.iterdir())
            except Exception as e:
                info["errors"].append(f"iterdir zomboid: {e!r}")

    return (
        "<!doctype html><meta charset='utf-8'>"
        "<style>body{font-family:monospace;background:#111;color:#eee;padding:2rem}"
        "pre{white-space:pre-wrap;background:#222;padding:1rem;border-radius:6px}</style>"
        "<h2>PZ Save Manager — /health</h2>"
        f"<pre>{json.dumps(info, indent=2, default=str)}</pre>"
    )


def _need(data: dict | None, *keys: str):
    """Return (data, None) if all keys present, else (None, error_response)."""
    if not isinstance(data, dict) or not all(k in data and data[k] for k in keys):
        return None, (jsonify({"ok": False, "error": f"Missing fields: {', '.join(keys)}"}), 400)
    return data, None


@app.route("/api/backup", methods=["POST"])
def api_backup():
    data, err = _need(request.get_json(silent=True), "game_mode", "save_name")
    if err:
        return err
    try:
        b = create_backup(data["game_mode"], data["save_name"])
        return jsonify({"ok": True, "timestamp": b.timestamp})
    except (SaveNotFound, BackupError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/restore", methods=["POST"])
def api_restore():
    data, err = _need(request.get_json(silent=True), "game_mode", "save_name", "timestamp")
    if err:
        return err
    from contextlib import nullcontext
    from .saves import get_save
    manager = get_manager()
    # If the target save is currently being watched, suppress watcher events
    # while restore writes files in — otherwise the watcher would create an
    # immediate auto-backup of the just-restored content.
    try:
        live_save = get_save(data["game_mode"], data["save_name"])
        pause_ctx = manager.pause_for(live_save)
    except SaveNotFound:
        pause_ctx = nullcontext()
    with pause_ctx:
        try:
            restore_backup(data["game_mode"], data["save_name"], data["timestamp"])
            return jsonify({"ok": True})
        except (BackupNotFound, BackupError) as e:
            return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/backup/delete", methods=["POST"])
def api_delete_backup():
    data, err = _need(request.get_json(silent=True), "game_mode", "save_name", "timestamp")
    if err:
        return err
    try:
        delete_backup(data["game_mode"], data["save_name"], data["timestamp"])
        return jsonify({"ok": True, "message": "Backup deleted"})
    except (BackupNotFound, BackupError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/save/rename", methods=["POST"])
def api_rename_save():
    data, err = _need(request.get_json(silent=True), "game_mode", "old_name", "new_name")
    if err:
        return err
    from .saves import SaveManagerError, rename_save
    from .backup import rename_backups_for_save
    manager = get_manager()
    try:
        # Resolve the save before renaming so we can pause the watcher
        from .saves import get_save
        live_save = get_save(data["game_mode"], data["old_name"])
        with manager.pause_for(live_save):
            new_save = rename_save(data["game_mode"], data["old_name"], data["new_name"])
            # Move backups alongside
            n = rename_backups_for_save(data["game_mode"], data["old_name"], data["new_name"])
            # Update watcher if the old name was watched
            if live_save.display_name in manager.watched_saves():
                manager.unwatch(live_save)
                manager.watch(new_save)
    except (SaveManagerError, BackupError, SaveNotFound) as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "message": f"Save renamed to {data['new_name']}", "backups_moved": n})


@app.route("/api/backup/annotate", methods=["POST"])
def api_annotate_backup():
    data, err = _need(request.get_json(silent=True), "game_mode", "save_name", "timestamp")
    if err:
        return err
    note = (data or {}).get("note", "")
    try:
        backup = get_backup(data["game_mode"], data["save_name"], data["timestamp"])
        set_backup_note(backup.path, note)
    except (BackupNotFound, BackupError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "message": "Note saved" if note else "Note removed"})


@app.route("/api/watcher/toggle", methods=["POST"])
def api_watcher_toggle():
    manager = get_manager()
    if manager.running:
        manager.stop()
        return jsonify({"ok": True, "message": "Watcher stopped"})
    saves = list_saves()
    cooldown = config_get_all().get("backup_cooldown_minutes", 5) * 60
    for s in saves:
        manager.watch(s, backup_cooldown_seconds=cooldown)
    manager.start()
    return jsonify({"ok": True, "message": f"Watcher started ({len(saves)} saves)"})


@app.route("/api/watcher/save", methods=["POST"])
def api_watcher_save():
    data, err = _need(request.get_json(silent=True), "game_mode", "save_name")
    if err:
        return err
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
    data = request.get_json(silent=True) or {}
    try:
        for key, value in data.items():
            # Allow clearing string-typed settings (e.g. resetting backups_dir to default)
            if key == "backups_dir":
                config_set(key, value if value else None)
                continue
            if value is None or value == "":
                continue
            if key == "debounce_seconds":
                value = float(value)
            elif key == "backup_cooldown_minutes":
                value = int(value)
            elif key == "max_auto_backups":
                value = int(value)
            elif key == "port":
                value = int(value)
            elif key in ("auto_start_watcher"):
                if not isinstance(value, bool):
                    value = str(value).lower() in ("true", "1", "yes")
            config_set(key, value)
    except (ValueError, TypeError) as e:
        return jsonify({"ok": False, "error": f"Invalid value: {e}"}), 400
    return jsonify({"ok": True, "message": "Settings saved", "config": config_get_all()})


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

    # Capture the Werkzeug shutdown function while we're still inside the
    # Flask request context.  The Timer callback runs in a different thread
    # where flask.request (a thread-local proxy) is empty.
    shutdown_func = request.environ.get("werkzeug.server.shutdown")

    def _shutdown() -> None:
        import sys
        if shutdown_func is not None:
            try:
                shutdown_func()
                return
            except Exception:
                pass
        # Fallback: sys.exit triggers atexit handlers, unlike os._exit.
        sys.exit(0)

    from threading import Timer
    Timer(1.0, _shutdown).start()
    return jsonify({"ok": True, "message": "Shutting down..."})


def run_gui(host: str = "127.0.0.1", port: int = 8080) -> None:
    import webbrowser
    url = f"http://{host}:{port}"
    saves_root = get_saves_root()
    try:
        save_count = len(list_saves())
    except Exception as e:
        save_count = f"error: {e!r}"
    print(f"\n  PZ Save Manager - {url}")
    print(f"  Saves dir : {saves_root} (exists={saves_root.is_dir()})")
    print(f"  Backups   : {get_backups_root()}")
    print(f"  Found     : {save_count} save(s)")
    print(f"  Diagnostics: {url}/health\n")
    webbrowser.open(url)
    app.run(host=host, port=port, debug=False)
