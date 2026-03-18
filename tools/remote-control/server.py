"""
DevOps Agent — Remote Control Server
Access from your phone at http://<your-ip>:9090
"""

import subprocess
import threading
import socket
import os
import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

# ─── Quick Actions ────────────────────────────────────────────────────────────
# Customize these to suit your workflow.
ACTIONS = [
    {
        "id": "run_app",
        "label": "Run App",
        "icon": "▶",
        "color": "#22c55e",
        "cmd": "cd /c/Users/shitt/Downloads/devops-agent && taskkill //F //IM python.exe 2>/dev/null; sleep 1; python app.py",
        "bg": True,
    },
    {
        "id": "stop_app",
        "label": "Stop App",
        "icon": "⏹",
        "color": "#ef4444",
        "cmd": "taskkill //F //IM python.exe 2>/dev/null && echo 'App stopped'",
        "bg": False,
    },
    {
        "id": "git_status",
        "label": "Git Status",
        "icon": "📋",
        "color": "#3b82f6",
        "cmd": "cd /c/Users/shitt/Downloads/devops-agent && git status --short && echo '---' && git log --oneline -5",
        "bg": False,
    },
    {
        "id": "git_pull",
        "label": "Git Pull",
        "icon": "⬇",
        "color": "#8b5cf6",
        "cmd": "cd /c/Users/shitt/Downloads/devops-agent && git pull origin main",
        "bg": False,
    },
    {
        "id": "health_check",
        "label": "Health Check",
        "icon": "❤",
        "color": "#f59e0b",
        "cmd": "curl -s http://localhost:5000/health",
        "bg": False,
    },
    {
        "id": "view_logs",
        "label": "View Logs",
        "icon": "📜",
        "color": "#06b6d4",
        "cmd": "cd /c/Users/shitt/Downloads/devops-agent && git log --oneline -20",
        "bg": False,
    },
    {
        "id": "run_tests",
        "label": "Run Tests",
        "icon": "🧪",
        "color": "#ec4899",
        "cmd": "cd /c/Users/shitt/Downloads/devops-agent && python -m pytest tests/ -q --tb=short 2>&1 | tail -30",
        "bg": False,
    },
    {
        "id": "check_deploy",
        "label": "Deploy Status",
        "icon": "🚀",
        "color": "#ff6b35",
        "cmd": "gh run list --limit 3 2>&1",
        "bg": False,
    },
]
# ─────────────────────────────────────────────────────────────────────────────

PORT = 9090
output_store = {}   # action_id -> {"lines": [], "done": bool, "rc": int|None}
output_lock = threading.Lock()


def run_cmd(action_id, cmd, bg):
    with output_lock:
        output_store[action_id] = {"lines": [], "done": False, "rc": None, "started": time.time()}

    def execute():
        try:
            proc = subprocess.Popen(
                cmd, shell=True, executable="C:/Program Files/Git/bin/bash.exe",
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            for line in proc.stdout:
                with output_lock:
                    output_store[action_id]["lines"].append(line.rstrip())
            proc.wait()
            with output_lock:
                output_store[action_id]["done"] = True
                output_store[action_id]["rc"] = proc.returncode
        except Exception as e:
            with output_lock:
                output_store[action_id]["lines"].append(f"ERROR: {e}")
                output_store[action_id]["done"] = True
                output_store[action_id]["rc"] = 1

    t = threading.Thread(target=execute, daemon=True)
    t.start()
    if not bg:
        t.join(timeout=60)


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>DevOps Remote</title>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
:root {
  --bg: #08090e;
  --surface: #0f1117;
  --surface2: #161820;
  --border: rgba(255,255,255,0.07);
  --border2: rgba(255,255,255,0.12);
  --text: #e8eaf0;
  --sub: #6b7280;
  --sub2: #9ca3af;
  --accent: #ff6b35;
  --green: #22c55e;
  --red: #ef4444;
  --safe-top: env(safe-area-inset-top, 0px);
  --safe-bottom: env(safe-area-inset-bottom, 0px);
}
html, body { height: 100%; background: var(--bg); }
body {
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', sans-serif;
  overscroll-behavior: none;
  padding-top: var(--safe-top);
}

/* ── Header ── */
header {
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 14px 18px;
  display: flex;
  align-items: center;
  gap: 12px;
  position: sticky;
  top: 0;
  z-index: 100;
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
}
.logo {
  width: 36px; height: 36px; flex-shrink: 0;
  background: linear-gradient(135deg, #ff6b35 0%, #f7931e 100%);
  border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  font-weight: 900; font-size: 17px; color: white;
  box-shadow: 0 2px 8px rgba(255,107,53,0.35);
}
.header-text h1 { font-size: 15px; font-weight: 700; letter-spacing: -0.2px; }
.header-text p { font-size: 11px; color: var(--sub); margin-top: 1px; }
.header-right { margin-left: auto; display: flex; align-items: center; gap: 10px; }
#clock { font-size: 12px; color: var(--sub); font-variant-numeric: tabular-nums; }

/* ── App Status Bar ── */
#status-bar {
  margin: 14px 16px 0;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 11px 14px;
  display: flex;
  align-items: center;
  gap: 10px;
}
.status-label { font-size: 12px; color: var(--sub2); flex: 1; }
.app-status-pill {
  display: flex; align-items: center; gap: 6px;
  font-size: 12px; font-weight: 600;
  padding: 4px 10px;
  border-radius: 20px;
  transition: all 0.3s;
}
.app-status-pill.online { background: rgba(34,197,94,0.15); color: #4ade80; }
.app-status-pill.offline { background: rgba(239,68,68,0.12); color: #f87171; }
.app-status-pill.checking { background: rgba(107,114,128,0.15); color: var(--sub2); }
.status-led {
  width: 7px; height: 7px; border-radius: 50%;
  background: currentColor;
  box-shadow: 0 0 6px currentColor;
}
.app-status-pill.online .status-led { animation: ledPulse 2s ease-in-out infinite; }
@keyframes ledPulse { 0%,100% { opacity:1; } 50% { opacity:0.5; } }

/* ── Section heading ── */
.section-title {
  font-size: 11px; font-weight: 600; letter-spacing: 0.6px;
  text-transform: uppercase; color: var(--sub);
  padding: 18px 18px 8px;
}

/* ── Button Grid ── */
.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  padding: 0 16px 16px;
}
.btn {
  position: relative; overflow: hidden;
  border: none; border-radius: 14px;
  padding: 0; cursor: pointer;
  color: white; text-align: left;
  transition: transform 0.12s, box-shadow 0.12s;
  min-height: 80px;
  display: flex; flex-direction: column; justify-content: flex-end;
}
.btn::before {
  content: '';
  position: absolute; inset: 0;
  background: linear-gradient(160deg, rgba(255,255,255,0.18) 0%, transparent 60%);
  pointer-events: none;
}
.btn:active { transform: scale(0.95); }
.btn.running { animation: btnPulse 1.2s ease-in-out infinite; }
@keyframes btnPulse { 0%,100% { opacity:1; } 50% { opacity:0.72; } }

.btn-inner { padding: 14px 14px 13px; position: relative; }
.btn-icon { font-size: 22px; display: block; margin-bottom: 6px; line-height: 1; }
.btn-label { font-size: 13px; font-weight: 700; letter-spacing: -0.1px; display: block; }
.btn-hint { font-size: 10px; opacity: 0.7; display: block; margin-top: 2px; font-weight: 500; }

.spinner-wrap {
  position: absolute; top: 10px; right: 10px;
  width: 18px; height: 18px;
  display: none;
}
.btn.running .spinner-wrap { display: block; }
.spinner-ring {
  width: 100%; height: 100%;
  border: 2px solid rgba(255,255,255,0.25);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* ── Output Sheet (slides from bottom) ── */
#sheet-backdrop {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.55);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  z-index: 200;
  opacity: 0; pointer-events: none;
  transition: opacity 0.25s;
}
#sheet-backdrop.visible { opacity: 1; pointer-events: all; }

#output-sheet {
  position: fixed; bottom: 0; left: 0; right: 0;
  background: #0d0f16;
  border-top: 1px solid var(--border2);
  border-radius: 20px 20px 0 0;
  z-index: 201;
  transform: translateY(100%);
  transition: transform 0.3s cubic-bezier(0.32, 0.72, 0, 1);
  max-height: 75vh;
  display: flex; flex-direction: column;
  padding-bottom: var(--safe-bottom);
}
#output-sheet.open { transform: translateY(0); }

.sheet-handle {
  width: 40px; height: 4px; border-radius: 2px;
  background: rgba(255,255,255,0.2);
  margin: 12px auto 0;
  flex-shrink: 0;
}
.sheet-header {
  padding: 12px 16px 10px;
  display: flex; align-items: center; gap: 10px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.sheet-title { font-size: 14px; font-weight: 700; flex: 1; }
.sheet-status {
  display: flex; align-items: center; gap: 5px;
  font-size: 11px; font-weight: 600;
  padding: 3px 9px; border-radius: 20px;
}
.sheet-status.running { background: rgba(245,158,11,0.15); color: #fbbf24; }
.sheet-status.ok { background: rgba(34,197,94,0.15); color: #4ade80; }
.sheet-status.err { background: rgba(239,68,68,0.12); color: #f87171; }
.sheet-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.sheet-status.running .sheet-dot { animation: pulse 0.8s ease-in-out infinite; }
@keyframes pulse { 0%,100%{opacity:1}50%{opacity:0.35} }

.sheet-close {
  background: rgba(255,255,255,0.08); border: none;
  color: var(--sub2); cursor: pointer; font-size: 15px;
  width: 28px; height: 28px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  transition: background 0.15s;
}
.sheet-close:active { background: rgba(255,255,255,0.16); }

#output {
  font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace;
  font-size: 12px; line-height: 1.65;
  color: #a3e635;
  padding: 14px 16px;
  overflow-y: auto;
  flex: 1;
  white-space: pre-wrap;
  word-break: break-all;
  -webkit-overflow-scrolling: touch;
}
#output .line-err { color: #f87171; }
#output .line-warn { color: #fbbf24; }
#output.empty::before {
  content: 'Running…';
  color: var(--sub);
  font-style: italic;
}

/* ── Toast ── */
#toast {
  position: fixed; bottom: calc(20px + var(--safe-bottom));
  left: 50%; transform: translateX(-50%) translateY(20px);
  background: var(--surface2);
  border: 1px solid var(--border2);
  border-radius: 24px;
  padding: 10px 20px;
  font-size: 13px; font-weight: 600;
  white-space: nowrap;
  z-index: 300;
  opacity: 0;
  transition: opacity 0.2s, transform 0.2s;
  pointer-events: none;
}
#toast.show {
  opacity: 1;
  transform: translateX(-50%) translateY(0);
}
#toast.toast-ok { color: #4ade80; border-color: rgba(34,197,94,0.3); }
#toast.toast-err { color: #f87171; border-color: rgba(239,68,68,0.25); }
#toast.toast-bg { color: #60a5fa; border-color: rgba(96,165,250,0.25); }
</style>
</head>
<body>

<header>
  <div class="logo">D</div>
  <div class="header-text">
    <h1>DevOps Remote</h1>
    <p>Control your dev environment</p>
  </div>
  <div class="header-right">
    <span id="clock"></span>
  </div>
</header>

<div id="status-bar">
  <span class="status-label">DevOps Agent app</span>
  <div class="app-status-pill checking" id="app-status-pill">
    <span class="status-led"></span>
    <span id="app-status-text">Checking...</span>
  </div>
</div>

<div class="section-title">Quick Actions</div>
<div class="grid" id="grid"></div>

<!-- Output bottom sheet -->
<div id="sheet-backdrop" onclick="closeSheet()"></div>
<div id="output-sheet">
  <div class="sheet-handle"></div>
  <div class="sheet-header">
    <span class="sheet-title" id="sheet-title">Output</span>
    <span class="sheet-status running" id="sheet-status">
      <span class="sheet-dot"></span>
      <span id="sheet-status-text">Running</span>
    </span>
    <button class="sheet-close" onclick="closeSheet()">✕</button>
  </div>
  <div id="output" class="empty"></div>
</div>

<div id="toast"></div>

<script>
const ACTIONS = __ACTIONS_JSON__;
let pollTimer = null;
let appStatusTimer = null;

// ── Render buttons ────────────────────────────────────────────────────────────
function renderButtons() {
  const grid = document.getElementById('grid');
  grid.innerHTML = ACTIONS.map(a => `
    <button class="btn" id="btn-${a.id}" style="background:${a.color}"
      onclick="runAction('${a.id}','${a.label}','${a.icon}')">
      <div class="spinner-wrap"><div class="spinner-ring"></div></div>
      <div class="btn-inner">
        <span class="btn-icon">${a.icon}</span>
        <span class="btn-label">${a.label}</span>
      </div>
    </button>
  `).join('');
}

// ── Run action ────────────────────────────────────────────────────────────────
function runAction(id, label, icon) {
  const btn = document.getElementById('btn-' + id);
  if (btn.classList.contains('running')) return;
  if ('vibrate' in navigator) navigator.vibrate(40);
  btn.classList.add('running');
  openSheet(icon + ' ' + label);

  fetch('/run/' + id, { method: 'POST' })
    .then(r => r.json())
    .then(() => pollOutput(id, btn, label))
    .catch(e => {
      appendOutput('Error: ' + e);
      btn.classList.remove('running');
      setSheetStatus('err', 'Failed');
    });
}

// ── Output sheet ──────────────────────────────────────────────────────────────
function openSheet(title) {
  clearTimeout(pollTimer);
  const el = document.getElementById('output');
  el.innerHTML = '';
  el.className = 'empty';
  document.getElementById('sheet-title').textContent = title;
  setSheetStatus('running', 'Running');
  document.getElementById('output-sheet').classList.add('open');
  document.getElementById('sheet-backdrop').classList.add('visible');
}

function closeSheet() {
  clearTimeout(pollTimer);
  document.getElementById('output-sheet').classList.remove('open');
  document.getElementById('sheet-backdrop').classList.remove('visible');
}

function setSheetStatus(state, text) {
  const el = document.getElementById('sheet-status');
  el.className = 'sheet-status ' + state;
  document.getElementById('sheet-status-text').textContent = text;
}

function appendOutput(lines) {
  const el = document.getElementById('output');
  el.className = '';
  if (!Array.isArray(lines)) lines = [lines];
  lines.forEach(line => {
    const span = document.createElement('span');
    if (/error|exception|fail|fatal/i.test(line)) span.className = 'line-err';
    else if (/warn|warning/i.test(line)) span.className = 'line-warn';
    span.textContent = line + '\n';
    el.appendChild(span);
  });
  el.scrollTop = el.scrollHeight;
}

function pollOutput(id, btn, label) {
  fetch('/output/' + id)
    .then(r => r.json())
    .then(data => {
      const el = document.getElementById('output');
      el.innerHTML = '';
      el.className = data.lines.length === 0 ? 'empty' : '';
      if (data.lines.length > 0) appendOutput(data.lines);

      if (data.done) {
        btn.classList.remove('running');
        if (data.rc === 0) {
          setSheetStatus('ok', 'Done');
          showToast('✓ ' + label + ' completed', 'ok');
        } else {
          setSheetStatus('err', 'Exit ' + data.rc);
          showToast('✗ ' + label + ' failed', 'err');
        }
        if ('vibrate' in navigator) navigator.vibrate(data.rc === 0 ? [40] : [40,60,40]);
        checkAppStatus();
      } else {
        pollTimer = setTimeout(() => pollOutput(id, btn, label), 700);
      }
    })
    .catch(() => {
      btn.classList.remove('running');
      setSheetStatus('err', 'Error');
    });
}

// ── Toast ─────────────────────────────────────────────────────────────────────
let toastTimer;
function showToast(msg, type) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'show toast-' + type;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = ''; }, 2800);
}

// ── App Status ────────────────────────────────────────────────────────────────
function checkAppStatus() {
  fetch('/app-status')
    .then(r => r.json())
    .then(data => {
      const pill = document.getElementById('app-status-pill');
      const text = document.getElementById('app-status-text');
      if (data.online) {
        pill.className = 'app-status-pill online';
        text.textContent = 'Online';
      } else {
        pill.className = 'app-status-pill offline';
        text.textContent = 'Offline';
      }
    })
    .catch(() => {
      document.getElementById('app-status-pill').className = 'app-status-pill offline';
      document.getElementById('app-status-text').textContent = 'Offline';
    });
}

// ── Clock ─────────────────────────────────────────────────────────────────────
function updateClock() {
  const now = new Date();
  document.getElementById('clock').textContent =
    now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}
setInterval(updateClock, 1000);
updateClock();

// ── Init ──────────────────────────────────────────────────────────────────────
renderButtons();
checkAppStatus();
setInterval(checkAppStatus, 8000);
</script>
</body>
</html>
""".replace("__ACTIONS_JSON__", json.dumps([{"id": a["id"], "label": a["label"], "icon": a["icon"], "color": a["color"]} for a in ACTIONS]))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # silence access logs

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            body = HTML_TEMPLATE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)

        elif path == "/app-status":
            import urllib.request
            try:
                urllib.request.urlopen("http://localhost:5000/health", timeout=2)
                self.send_json({"online": True})
            except Exception:
                self.send_json({"online": False})

        elif path.startswith("/output/"):
            action_id = path[len("/output/"):]
            with output_lock:
                data = dict(output_store.get(action_id, {"lines": [], "done": True, "rc": 0}))
                data.pop("started", None)
            self.send_json(data)

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/run/"):
            action_id = path[len("/run/"):]
            action = next((a for a in ACTIONS if a["id"] == action_id), None)
            if not action:
                self.send_json({"error": "unknown action"}, 404)
                return
            threading.Thread(
                target=run_cmd, args=(action_id, action["cmd"], action["bg"]), daemon=True
            ).start()
            self.send_json({"started": True})
        else:
            self.send_response(404)
            self.end_headers()


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


if __name__ == "__main__":
    ip = get_local_ip()
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"\n  DevOps Agent Remote Control")
    print(f"  -----------------------------")
    print(f"  Open on your phone: http://{ip}:{PORT}")
    print(f"  (must be on the same WiFi)")
    print(f"\n  Press Ctrl+C to stop\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
