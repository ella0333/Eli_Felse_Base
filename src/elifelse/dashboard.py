"""Localhost dashboard: status, memory viewer, and agent controls.

Serves a single-page web UI on http://127.0.0.1:{port}. Launched via the
/dashboard runtime command (not auto-started). The HTTP server runs in a
daemon thread so it never blocks the main async loop.
"""

from __future__ import annotations

import json
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

from elifelse.textutils import print_system

if TYPE_CHECKING:
    from elifelse.app import App


class _ThreadedServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class Dashboard:
    """Lightweight localhost web dashboard for monitoring and memory browsing."""

    def __init__(self, app: App, port: int = 8080) -> None:
        self.app = app
        self.port = port
        self._server: _ThreadedServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._server is not None:
            return
        handler = _make_handler(self.app)
        self._server = _ThreadedServer(("127.0.0.1", self.port), handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )
        self._thread.start()
        print_system(f"dashboard running on http://127.0.0.1:{self.port}")

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server = None
            self._thread = None


def _make_handler(app: App):
    """Create an HTTP handler class with access to the App instance."""

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002
            pass  # silence per-request logs

        def _send_json(self, data: Any, status: int = 200) -> None:
            body = json.dumps(data, default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            params = parse_qs(parsed.query)

            if path in ("/", "/index.html"):
                self._send_html(_PAGE_HTML)
            elif path == "/api/status":
                self._handle_status()
            elif path == "/api/memories":
                self._handle_memories(params)
            elif path == "/api/search":
                self._handle_search(params)
            elif path == "/api/count":
                self._handle_count(params)
            elif path == "/api/food-options":
                self._handle_food_options_get()
            else:
                self.send_error(404)

        def do_POST(self):  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path

            length = int(self.headers.get("Content-Length", 0))
            body: dict = {}
            if length > 0:
                raw = self.rfile.read(length)
                try:
                    body = json.loads(raw)
                except json.JSONDecodeError:
                    pass

            if path == "/api/control":
                self._handle_control(body)
            elif path == "/api/delete":
                self._handle_delete(body)
            elif path == "/api/food-options":
                self._handle_food_options_post(body)
            else:
                self.send_error(404)

        # ~~~ GET handlers ~~~

        def _handle_status(self):
            now = app.clock()
            uptime = ""
            if app.status.started:
                delta = (now - app.status.started).total_seconds()
                if delta < 60:
                    uptime = "just now"
                elif delta < 3600:
                    uptime = f"{int(delta // 60)}m"
                else:
                    uptime = f"{int(delta // 3600)}h {int((delta % 3600) // 60)}m"

            counters = app.stats.data.get("counters", {})

            data: dict[str, Any] = {
                "agent_name": app.persona.name,
                "activity": app.status.activity,
                "details": app.status.details,
                "activity_started": uptime,
                "paused": app.control.pause_requested,
                "stopping": app.control.stop_requested,
                "total_sessions": app.stats.data.get("total_sessions", 0),
                "days_alive": app.stats.days_since_first_start,
                "counters": counters,
                "timestamp": now.isoformat(),
            }

            if app.memory is not None:
                try:
                    store = app.memory.store
                    data["memory_counts"] = {
                        "facts": store._coll("facts").count(),
                        "memories": store._coll("memories").count(),
                        "summaries": store._coll("summaries").count(),
                    }
                except Exception:
                    data["memory_counts"] = {}
            else:
                data["memory_counts"] = {}

            self._send_json(data)

        def _handle_memories(self, params: dict):
            collection = params.get("collection", ["facts"])[0]
            if collection not in ("facts", "memories", "summaries"):
                self._send_json({"error": "invalid collection"}, 400)
                return
            if app.memory is None:
                self._send_json([])
                return
            try:
                coll = app.memory.store._coll(collection)
                results = coll.get(include=["documents", "metadatas"])
                items = []
                for i, doc_id in enumerate(results["ids"]):
                    items.append({
                        "id": doc_id,
                        "text": results["documents"][i],
                        "metadata": results["metadatas"][i] or {},
                    })
                self._send_json(items)
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        def _handle_search(self, params: dict):
            query = params.get("q", [""])[0]
            n = int(params.get("n", ["20"])[0])
            collection = params.get("collection", ["memories"])[0]

            if not query or collection not in ("facts", "memories", "summaries"):
                self._send_json([])
                return
            if app.memory is None:
                self._send_json([])
                return
            try:
                coll = app.memory.store._coll(collection)
                total = coll.count()
                if total == 0:
                    self._send_json([])
                    return
                results = coll.query(
                    query_texts=[query],
                    n_results=min(n, total),
                    include=["documents", "metadatas", "distances"],
                )
                items = []
                for i, doc_id in enumerate(results["ids"][0]):
                    items.append({
                        "id": doc_id,
                        "text": results["documents"][0][i],
                        "metadata": results["metadatas"][0][i] or {},
                        "relevance": round(1 - results["distances"][0][i], 4),
                    })
                self._send_json(items)
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        def _handle_count(self, params: dict):
            collection = params.get("collection", ["facts"])[0]
            if app.memory is None:
                self._send_json({"count": 0})
                return
            try:
                count = app.memory.store._coll(collection).count()
                self._send_json({"count": count})
            except Exception:
                self._send_json({"count": 0})

        # ~~~ POST handlers ~~~

        def _handle_control(self, body: dict):
            action = body.get("action", "")
            if action == "pause":
                app.control.request_pause()
                self._send_json({"ok": True, "message": "pause requested"})
            elif action == "resume":
                app.control.resume()
                self._send_json({"ok": True, "message": "resumed"})
            elif action == "stop":
                app.control.request_stop()
                for channel in app.channels.values():
                    try:
                        channel.interrupt()
                    except Exception:
                        pass
                self._send_json({"ok": True, "message": "stop requested"})
            else:
                self._send_json({"ok": False, "message": "unknown action"}, 400)

        def _handle_delete(self, body: dict):
            collection = body.get("collection", "")
            doc_id = body.get("id", "")
            if not collection or not doc_id:
                self._send_json({"ok": False, "message": "missing collection or id"}, 400)
                return
            if collection not in ("facts", "memories", "summaries"):
                self._send_json({"ok": False, "message": "invalid collection"}, 400)
                return
            if app.memory is None:
                self._send_json({"ok": False, "message": "memory not enabled"}, 400)
                return
            try:
                app.memory.store._coll(collection).delete(ids=[doc_id])
                self._send_json({"ok": True})
            except Exception as e:
                self._send_json({"ok": False, "message": str(e)}, 500)

        def _handle_food_options_get(self):
            from elifelse.activities.builtin.eat import load_overrides
            data_dir = app.paths.activity_dir("eat")
            overrides = load_overrides(data_dir)
            self._send_json({
                "foods": overrides.get("foods", []),
                "drinks": overrides.get("drinks", []),
            })

        def _handle_food_options_post(self, body: dict):
            from elifelse.activities.builtin.eat import save_overrides
            foods = [s.strip() for s in body.get("foods", []) if isinstance(s, str) and s.strip()]
            drinks = [s.strip() for s in body.get("drinks", []) if isinstance(s, str) and s.strip()]
            data_dir = app.paths.activity_dir("eat")
            save_overrides(data_dir, {"foods": foods, "drinks": drinks})
            self._send_json({"ok": True})

    return Handler


# ---------------------------------------------------------------------------
# Embedded frontend
# ---------------------------------------------------------------------------

_PAGE_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>eli felse</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#0d1117;--bg2:#161b22;--border:#30363d;
  --text:#e6edf3;--dim:#8b949e;
  --accent:#3fb950;--accent-dim:#238636;
  --orange:#d29922;--purple:#bc8cff;--blue:#58a6ff;--red:#da3633;
  --radius:6px;
}
body{
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
  background:var(--bg);color:var(--text);font-size:14px;line-height:1.5;
}
.nav{
  display:flex;align-items:center;gap:16px;
  padding:12px 24px;background:var(--bg2);border-bottom:1px solid var(--border);
}
.nav-logo{font-weight:700;font-size:16px;color:var(--accent);margin-right:8px}
.nav-links{display:flex;gap:4px}
.nav-link{
  background:none;border:1px solid transparent;color:var(--dim);
  padding:6px 12px;border-radius:var(--radius);cursor:pointer;
  font-size:13px;font-family:inherit;
}
.nav-link:hover{color:var(--text);background:var(--bg)}
.nav-link.active{color:var(--text);background:var(--bg);border-color:var(--border)}
.nav-right{margin-left:auto;display:flex;align-items:center;gap:8px;font-size:12px;color:var(--dim)}
.dot{width:8px;height:8px;border-radius:50%;background:var(--accent)}
.dot.paused{background:var(--orange)}
.dot.stopped{background:var(--red)}

.main{max-width:960px;margin:24px auto;padding:0 24px}
.page{display:none}.page.active{display:block}
.card{
  background:var(--bg2);border:1px solid var(--border);
  border-radius:var(--radius);padding:16px;margin-bottom:16px;
}
.card-title{font-size:13px;font-weight:600;color:var(--dim);text-transform:lowercase;margin-bottom:12px}

.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:12px}
.stat{background:var(--bg);border:1px solid var(--border);border-radius:var(--radius);padding:12px}
.stat-label{font-size:11px;color:var(--dim);text-transform:lowercase}
.stat-value{font-size:18px;font-weight:600;margin-top:4px}
.stat-value.accent{color:var(--accent)}

.controls{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
.btn{
  background:var(--bg);border:1px solid var(--border);color:var(--text);
  padding:6px 14px;border-radius:var(--radius);cursor:pointer;font-size:13px;font-family:inherit;
}
.btn:hover{border-color:var(--dim)}
.btn.active{border-color:var(--accent);color:var(--accent)}
.btn.danger{color:var(--red)}.btn.danger:hover{border-color:var(--red)}
.search-input{
  background:var(--bg);border:1px solid var(--border);color:var(--text);
  padding:6px 12px;border-radius:var(--radius);font-size:13px;font-family:inherit;
  flex:1;min-width:200px;
}
.search-input::placeholder{color:var(--dim)}
.search-input:focus{outline:none;border-color:var(--accent)}

.mem-list{max-height:600px;overflow-y:auto}
.mem-item{
  background:var(--bg);border:1px solid var(--border);border-left:3px solid var(--accent);
  padding:10px 12px;margin:6px 0;border-radius:var(--radius);
}
.mem-item.fact{border-left-color:var(--orange)}
.mem-item.episodic{border-left-color:var(--purple)}
.mem-item.summary{border-left-color:var(--blue)}
.mem-meta{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:6px}
.tag{
  font-size:10px;padding:1px 6px;border-radius:8px;
  background:var(--bg2);border:1px solid var(--border);
}
.tag.type{color:var(--accent);border-color:var(--accent-dim)}
.tag.date{color:var(--orange);border-color:rgba(210,153,34,0.3)}
.tag.source{color:var(--purple);border-color:rgba(188,140,255,0.3)}
.tag.rel{color:var(--blue);border-color:rgba(88,166,255,0.3)}
.mem-text{font-size:13px;line-height:1.5}
.mem-foot{font-size:10px;color:var(--dim);margin-top:6px;display:flex;justify-content:space-between;align-items:center}
.del-btn{
  background:none;border:none;color:var(--dim);cursor:pointer;
  font-size:11px;padding:2px 6px;border-radius:3px;
}
.del-btn:hover{color:var(--red);background:rgba(218,54,51,0.1)}
.empty{text-align:center;padding:40px;color:var(--dim)}
.mem-stats{font-size:12px;color:var(--dim);margin-bottom:8px}

.ctrl-grid{display:flex;gap:12px}
.ctrl-btn{
  padding:12px 24px;font-size:14px;font-weight:600;border-radius:var(--radius);
  border:1px solid var(--border);background:var(--bg);color:var(--text);
  cursor:pointer;font-family:inherit;
}
.ctrl-btn:hover{border-color:var(--dim)}
.ctrl-btn.pause{color:var(--orange)}.ctrl-btn.pause:hover{border-color:var(--orange)}
.ctrl-btn.resume{color:var(--accent)}.ctrl-btn.resume:hover{border-color:var(--accent)}
.ctrl-btn.stop{color:var(--red)}.ctrl-btn.stop:hover{border-color:var(--red)}
.ctrl-status{margin-top:12px;font-size:13px;color:var(--dim)}
</style>
</head>
<body>
<nav class="nav">
  <div class="nav-logo">eli felse</div>
  <div class="nav-links">
    <button class="nav-link active" data-page="status" onclick="showPage('status')">status</button>
    <button class="nav-link" data-page="memory" onclick="showPage('memory')">memory</button>
    <button class="nav-link" data-page="food" onclick="showPage('food')">food</button>
    <button class="nav-link" data-page="controls" onclick="showPage('controls')">controls</button>
  </div>
  <div class="nav-right">
    <div class="dot" id="dot"></div>
    <span id="nav-activity">loading...</span>
  </div>
</nav>

<main class="main">
  <!-- STATUS -->
  <div id="page-status" class="page active">
    <div class="card">
      <div class="card-title">agent status</div>
      <div class="grid">
        <div class="stat"><div class="stat-label">agent</div><div class="stat-value accent" id="s-name">...</div></div>
        <div class="stat"><div class="stat-label">activity</div><div class="stat-value" id="s-activity">...</div></div>
        <div class="stat"><div class="stat-label">in activity for</div><div class="stat-value" id="s-duration">...</div></div>
        <div class="stat"><div class="stat-label">state</div><div class="stat-value" id="s-state">...</div></div>
      </div>
    </div>
    <div class="card">
      <div class="card-title">stats</div>
      <div class="grid">
        <div class="stat"><div class="stat-label">days alive</div><div class="stat-value" id="s-days">0</div></div>
        <div class="stat"><div class="stat-label">sessions</div><div class="stat-value" id="s-sessions">0</div></div>
        <div class="stat"><div class="stat-label">facts</div><div class="stat-value" id="s-facts">0</div></div>
        <div class="stat"><div class="stat-label">memories</div><div class="stat-value" id="s-memories">0</div></div>
        <div class="stat"><div class="stat-label">summaries</div><div class="stat-value" id="s-summaries">0</div></div>
      </div>
    </div>
    <div class="card" id="counters-card" style="display:none">
      <div class="card-title">activity counters</div>
      <div class="grid" id="counters-grid"></div>
    </div>
  </div>

  <!-- MEMORY -->
  <div id="page-memory" class="page">
    <div class="card">
      <div class="card-title">memory viewer</div>
      <div class="controls">
        <input type="text" class="search-input" id="mem-search"
               placeholder="search memories..." onkeydown="if(event.key==='Enter')doSearch()">
        <button class="btn" id="mode-btn" onclick="toggleMode()">semantic</button>
        <button class="btn active" id="btn-facts" onclick="toggleCol('facts')">facts</button>
        <button class="btn active" id="btn-memories" onclick="toggleCol('memories')">memories</button>
        <button class="btn active" id="btn-summaries" onclick="toggleCol('summaries')">summaries</button>
      </div>
      <div class="mem-stats" id="mem-stats"></div>
      <div class="mem-list" id="mem-list"><div class="empty">loading memories...</div></div>
    </div>
  </div>

  <!-- FOOD -->
  <div id="page-food" class="page">
    <div class="card">
      <div class="card-title">food &amp; drink overrides</div>
      <p style="color:var(--dim);font-size:12px;margin-bottom:12px">
        Set custom options below. Leave empty to use model-generated options.
        First food item is treated as the meal, rest as snacks.
      </p>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
        <div>
          <div style="font-size:12px;color:var(--dim);margin-bottom:6px">foods (1 meal + snacks)</div>
          <div id="food-list"></div>
          <button class="btn" style="margin-top:6px" onclick="addFoodRow()">+ add food</button>
        </div>
        <div>
          <div style="font-size:12px;color:var(--dim);margin-bottom:6px">drinks (water is always included)</div>
          <div id="drink-list"></div>
          <button class="btn" style="margin-top:6px" onclick="addDrinkRow()">+ add drink</button>
        </div>
      </div>
      <div style="margin-top:12px;display:flex;gap:8px;align-items:center">
        <button class="ctrl-btn resume" onclick="saveFoodOptions()">save</button>
        <button class="btn danger" onclick="clearFoodOptions()">clear all</button>
        <span id="food-status" style="font-size:12px;color:var(--dim)"></span>
      </div>
    </div>
  </div>

  <!-- CONTROLS -->
  <div id="page-controls" class="page">
    <div class="card">
      <div class="card-title">agent controls</div>
      <div class="ctrl-grid">
        <button class="ctrl-btn pause" onclick="sendCtrl('pause')">pause</button>
        <button class="ctrl-btn resume" onclick="sendCtrl('resume')">resume</button>
        <button class="ctrl-btn stop" onclick="sendCtrl('stop')">stop</button>
      </div>
      <div class="ctrl-status" id="ctrl-status"></div>
    </div>
  </div>
</main>

<script>
let mode='semantic',cols={facts:true,memories:true,summaries:true},all=[];

function showPage(n){
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.nav-link').forEach(l=>l.classList.remove('active'));
  document.getElementById('page-'+n).classList.add('active');
  document.querySelector('[data-page="'+n+'"]').classList.add('active');
  if(n==='memory'&&all.length===0)loadMem();
  if(n==='food')loadFoodOptions();
}

async function poll(){
  try{
    const r=await fetch('/api/status');
    const d=await r.json();
    document.getElementById('s-name').textContent=d.agent_name||'...';
    document.getElementById('s-activity').textContent=d.activity||'idle';
    document.getElementById('s-duration').textContent=d.activity_started||'...';
    document.getElementById('nav-activity').textContent=d.activity||'idle';
    let st='running';const dot=document.getElementById('dot');dot.className='dot';
    if(d.stopping){st='stopping';dot.classList.add('stopped')}
    else if(d.paused){st='paused';dot.classList.add('paused')}
    document.getElementById('s-state').textContent=st;
    document.getElementById('s-days').textContent=d.days_alive||0;
    document.getElementById('s-sessions').textContent=d.total_sessions||0;
    const mc=d.memory_counts||{};
    document.getElementById('s-facts').textContent=mc.facts||0;
    document.getElementById('s-memories').textContent=mc.memories||0;
    document.getElementById('s-summaries').textContent=mc.summaries||0;
    const c=d.counters||{},keys=Object.keys(c).sort();
    const g=document.getElementById('counters-grid'),card=document.getElementById('counters-card');
    if(keys.length){card.style.display='block';g.innerHTML=keys.map(k=>`<div class="stat"><div class="stat-label">${k.replace('activity.','')}</div><div class="stat-value">${c[k]}</div></div>`).join('')}
  }catch(e){
    document.getElementById('nav-activity').textContent='disconnected';
    document.getElementById('dot').className='dot stopped';
  }
}

async function loadMem(){
  all=[];
  const active=Object.entries(cols).filter(([_,v])=>v).map(([k])=>k);
  for(const col of active){
    try{
      const r=await fetch('/api/memories?collection='+col);
      const d=await r.json();
      if(Array.isArray(d)){d.forEach(m=>{m._col=col});all=all.concat(d)}
    }catch(e){}
  }
  render(all);
}

function esc(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML}

function render(items){
  const el=document.getElementById('mem-list');
  document.getElementById('mem-stats').textContent=items.length+' entries';
  if(!items.length){el.innerHTML='<div class="empty">no memories found</div>';return}
  el.innerHTML=items.map(m=>{
    const meta=m.metadata||{},col=m._col||'memories';
    const cls=col==='facts'?'fact':col==='summaries'?'summary':'episodic';
    let tags=`<span class="tag type">${col}</span>`;
    if(meta.activity_type)tags+=`<span class="tag type">${esc(meta.activity_type)}</span>`;
    if(meta.source)tags+=`<span class="tag source">${esc(meta.source)}</span>`;
    if(meta.timestamp){const dt=meta.timestamp.split('T')[0];tags+=`<span class="tag date">${dt}</span>`}
    if(meta.keywords)tags+=`<span class="tag">${esc(meta.keywords)}</span>`;
    if(m.relevance!=null)tags+=`<span class="tag rel">${Math.round(m.relevance*100)}%</span>`;
    return`<div class="mem-item ${cls}"><div class="mem-meta">${tags}</div><div class="mem-text">${esc(m.text)}</div><div class="mem-foot"><span>${m.id}</span><button class="del-btn" onclick="delMem('${col}','${m.id}')">delete</button></div></div>`;
  }).join('');
}

function toggleMode(){mode=mode==='semantic'?'keyword':'semantic';document.getElementById('mode-btn').textContent=mode}
function toggleCol(n){cols[n]=!cols[n];document.getElementById('btn-'+n).classList.toggle('active',cols[n]);loadMem()}

async function doSearch(){
  const q=document.getElementById('mem-search').value.trim();
  if(!q){loadMem();return}
  if(mode==='semantic'){
    let res=[];
    const active=Object.entries(cols).filter(([_,v])=>v).map(([k])=>k);
    for(const col of active){
      try{
        const r=await fetch(`/api/search?q=${encodeURIComponent(q)}&n=20&collection=${col}`);
        const d=await r.json();
        if(Array.isArray(d)){d.forEach(m=>{m._col=col});res=res.concat(d)}
      }catch(e){}
    }
    res.sort((a,b)=>(b.relevance||0)-(a.relevance||0));
    render(res);
  }else{
    const lq=q.toLowerCase();
    render(all.filter(m=>m.text.toLowerCase().includes(lq)||(m.metadata?.activity_type||'').toLowerCase().includes(lq)||(m.metadata?.source||'').toLowerCase().includes(lq)));
  }
}

async function delMem(col,id){
  if(!confirm('Delete this memory?'))return;
  try{await fetch('/api/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({collection:col,id})});loadMem()}catch(e){}
}

async function sendCtrl(action){
  try{
    const r=await fetch('/api/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action})});
    const d=await r.json();
    document.getElementById('ctrl-status').textContent=d.message||'';
    poll();
  }catch(e){document.getElementById('ctrl-status').textContent='request failed'}
}

function makeRow(container,value){
  const row=document.createElement('div');
  row.style.cssText='display:flex;gap:4px;margin:3px 0';
  const inp=document.createElement('input');
  inp.type='text';inp.value=value||'';inp.className='search-input';inp.style.flex='1';
  const del=document.createElement('button');del.className='del-btn';del.textContent='x';
  del.onclick=()=>row.remove();
  row.appendChild(inp);row.appendChild(del);container.appendChild(row);
}
function addFoodRow(v){makeRow(document.getElementById('food-list'),v)}
function addDrinkRow(v){makeRow(document.getElementById('drink-list'),v)}

function getListValues(id){
  return Array.from(document.getElementById(id).querySelectorAll('input'))
    .map(i=>i.value.trim()).filter(Boolean);
}

async function loadFoodOptions(){
  try{
    const r=await fetch('/api/food-options');const d=await r.json();
    document.getElementById('food-list').innerHTML='';
    document.getElementById('drink-list').innerHTML='';
    (d.foods||[]).forEach(f=>addFoodRow(f));
    (d.drinks||[]).forEach(d=>addDrinkRow(d));
  }catch(e){}
}

async function saveFoodOptions(){
  const foods=getListValues('food-list'),drinks=getListValues('drink-list');
  try{
    await fetch('/api/food-options',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({foods,drinks})});
    document.getElementById('food-status').textContent='saved';
    setTimeout(()=>document.getElementById('food-status').textContent='',2000);
  }catch(e){document.getElementById('food-status').textContent='failed'}
}

async function clearFoodOptions(){
  document.getElementById('food-list').innerHTML='';
  document.getElementById('drink-list').innerHTML='';
  await saveFoodOptions();
}

poll();setInterval(poll,3000);
</script>
</body>
</html>
"""
