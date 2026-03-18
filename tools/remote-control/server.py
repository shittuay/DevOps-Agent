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

# ─── Quick Actions ----------------------------------------------------------──
# Customize these to suit your workflow.
ACTIONS = [
    {
        "id": "run_app",
        "label": "▶ Run App",
        "color": "#22c55e",
        "cmd": "cd /c/Users/shitt/Downloads/devops-agent && taskkill //F //IM python.exe 2>/dev/null; sleep 1; python app.py",
        "bg": True,   # run in background
    },
    {
        "id": "stop_app",
        "label": "⏹ Stop App",
        "color": "#ef4444",
        "cmd": "taskkill //F //IM python.exe 2>/dev/null && echo 'App stopped'",
        "bg": False,
    },
    {
        "id": "git_status",
        "label": "📋 Git Status",
        "color": "#3b82f6",
        "cmd": "cd /c/Users/shitt/Downloads/devops-agent && git status --short && echo '---' && git log --oneline -5",
        "bg": False,
    },
    {
        "id": "git_pull",
        "label": "⬇ Git Pull",
        "color": "#8b5cf6",
        "cmd": "cd /c/Users/shitt/Downloads/devops-agent && git pull origin main",
        "bg": False,
    },
    {
        "id": "health_check",
        "label": "❤ Health Check",
        "color": "#f59e0b",
        "cmd": "curl -s http://localhost:5000/health",
        "bg": False,
    },
    {
        "id": "view_logs",
        "label": "📜 View Logs",
        "color": "#06b6d4",
        "cmd": "cd /c/Users/shitt/Downloads/devops-agent && git log --oneline -20",
        "bg": False,
    },
    {
        "id": "run_tests",
        "label": "🧪 Run Tests",
        "color": "#ec4899",
        "cmd": "cd /c/Users/shitt/Downloads/devops-agent && python -m pytest tests/ -q --tb=short 2>&1 | tail -30",
        "bg": False,
    },
    {
        "id": "check_deploy",
        "label": "🚀 Deploy Status",
        "color": "#ff6b35",
        "cmd": "gh run list --limit 3 2>&1",
        "bg": False,
    },
]
# ----------------------------------------------------------───────────────────

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


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>DevOps Agent — Remote</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg: #07090f;
    --surface: #0f1117;
    --border: rgba(255,255,255,0.08);
    --text: #e8eaf0;
    --sub: #6b7280;
    --accent: #ff6b35;
  }
  body { background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; min-height: 100vh; }
  header { background: var(--surface); border-bottom: 1px solid var(--border); padding: 16px 20px; display: flex; align-items: center; gap: 12px; position: sticky; top: 0; z-index: 10; }
  .logo { width: 34px; height: 34px; background: linear-gradient(135deg,#ff6b35,#f7931e); border-radius: 8px; display: flex; align-items: center; justify-content: center; font-weight: 800; font-size: 16px; }
  header h1 { font-size: 16px; font-weight: 700; }
  header span { font-size: 12px; color: var(--sub); margin-left: auto; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; padding: 16px; }
  .btn {
    border: none; border-radius: 12px; padding: 18px 12px; cursor: pointer;
    font-size: 14px; font-weight: 600; color: white; text-align: center;
    transition: transform 0.1s, opacity 0.1s; letter-spacing: 0.2px;
    position: relative; overflow: hidden;
  }
  .btn:active { transform: scale(0.96); }
  .btn.running { opacity: 0.7; }
  .btn .spinner {
    display: none; width: 14px; height: 14px; border: 2px solid rgba(255,255,255,0.3);
    border-top-color: white; border-radius: 50%; animation: spin 0.7s linear infinite;
    margin: 0 auto 6px;
  }
  .btn.running .spinner { display: block; }
  @keyframes spin { to { transform: rotate(360deg); } }
  #output-panel {
    margin: 0 16px 16px; background: #0a0c12; border: 1px solid var(--border);
    border-radius: 12px; display: none;
  }
  #output-panel.visible { display: block; }
  .output-header { padding: 12px 16px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; }
  .output-header span { font-size: 13px; font-weight: 600; color: var(--accent); }
  .close-btn { background: none; border: none; color: var(--sub); cursor: pointer; font-size: 18px; padding: 0 4px; }
  #output { font-family: 'SF Mono', 'Fira Code', monospace; font-size: 12px; line-height: 1.6;
    color: #a3e635; padding: 14px 16px; max-height: 55vh; overflow-y: auto; white-space: pre-wrap; word-break: break-all; }
  .status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 6px; }
  .dot-running { background: #f59e0b; animation: pulse 1s ease-in-out infinite; }
  .dot-ok { background: #22c55e; }
  .dot-err { background: #ef4444; }
  @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.4; } }
</style>
</head>
<body>
<header>
  <div class="logo">D</div>
  <h1>DevOps Agent</h1>
  <span id="clock"></span>
</header>

<div class="grid" id="grid"></div>
<div id="output-panel">
  <div class="output-header">
    <span><span class="status-dot" id="status-dot"></span><span id="output-title">Output</span></span>
    <button class="close-btn" onclick="closeOutput()">✕</button>
  </div>
  <div id="output"></div>
</div>

<script>
const ACTIONS = __ACTIONS_JSON__;
let currentAction = null;
let pollTimer = null;

function renderButtons() {
  const grid = document.getElementById('grid');
  grid.innerHTML = ACTIONS.map(a => `
    <button class="btn" id="btn-${a.id}" style="background:${a.color}"
      onclick="runAction('${a.id}','${a.label}')">
      <div class="spinner"></div>${a.label}
    </button>
  `).join('');
}

function runAction(id, label) {
  const btn = document.getElementById('btn-' + id);
  if (btn.classList.contains('running')) return;
  btn.classList.add('running');
  currentAction = id;
  openOutput(label);

  fetch('/run/' + id, { method: 'POST' })
    .then(r => r.json())
    .then(() => {
      pollOutput(id, btn);
    })
    .catch(e => {
      appendOutput('Error: ' + e);
      btn.classList.remove('running');
    });
}

function openOutput(label) {
  document.getElementById('output').textContent = '';
  document.getElementById('output-title').textContent = label;
  setDot('running');
  document.getElementById('output-panel').classList.add('visible');
}

function closeOutput() {
  clearTimeout(pollTimer);
  document.getElementById('output-panel').classList.remove('visible');
}

function setDot(state) {
  const dot = document.getElementById('status-dot');
  dot.className = 'status-dot dot-' + state;
}

function appendOutput(text) {
  const el = document.getElementById('output');
  el.textContent += text + '\\n';
  el.scrollTop = el.scrollHeight;
}

function pollOutput(id, btn) {
  fetch('/output/' + id)
    .then(r => r.json())
    .then(data => {
      const el = document.getElementById('output');
      el.textContent = data.lines.join('\\n');
      el.scrollTop = el.scrollHeight;

      if (data.done) {
        btn.classList.remove('running');
        setDot(data.rc === 0 ? 'ok' : 'err');
      } else {
        pollTimer = setTimeout(() => pollOutput(id, btn), 800);
      }
    })
    .catch(() => {
      btn.classList.remove('running');
      setDot('err');
    });
}

// Clock
function updateClock() {
  document.getElementById('clock').textContent = new Date().toLocaleTimeString();
}
setInterval(updateClock, 1000);
updateClock();

renderButtons();
</script>
</body>
</html>
""".replace("__ACTIONS_JSON__", json.dumps([{"id": a["id"], "label": a["label"], "color": a["color"]} for a in ACTIONS]))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # silence access logs

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
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

        elif path.startswith("/output/"):
            action_id = path[len("/output/"):]
            with output_lock:
                data = output_store.get(action_id, {"lines": [], "done": True, "rc": 0})
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
