#!/usr/bin/env python3
"""
MiniJarvis PC Agent (Windows).

Runs on your gaming PC, listens on the LAN, and executes a small WHITELIST of
commands forwarded by the Mac MiniJarvis server: launch apps/games, open URLs,
volume / media keys, close apps.

Setup:
  1. Copy this file to the PC.
  2. Set a unique TOKEN below (must match PC_AGENT_TOKEN on the Mac).
  3. Run:  python pc_agent.py
  4. Find the PC's LAN IP (ipconfig -> IPv4 Address) and set on the Mac:
        PC_AGENT_URL   = "http://<that-ip>:6001"
        PC_AGENT_TOKEN = "<same token>"
  5. Allow Python through the Windows Firewall when prompted (Private network).

Customize PC_APPS / PC_ALIASES / CLOSE_EXE below to match what's installed.
"""
import json
import os
import subprocess
import urllib.parse

try:
    import ctypes  # Windows media/volume keys
except Exception:
    ctypes = None

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ================= CONFIG =================
HOST = "0.0.0.0"
PORT = 6001
TOKEN = "change-me-please"   # MUST match PC_AGENT_TOKEN on the Mac

# canonical key -> (method, value)
#   steam : launch a Steam game by app id  (CS2=730, Dota2=570)
#   uri   : open a protocol/URI (steam://, spotify:, com.epicgames.launcher:)
#   start : `start <name>` — works for apps on PATH / App Paths (chrome, notepad)
#   path  : full path to an .exe
PC_APPS = {
    "cs2":      ("steam", "730"),
    "dota2":    ("steam", "570"),
    "valorant": ("start", "valorant"),
    "steam":    ("uri",   "steam://open/main"),
    "epic":     ("uri",   "com.epicgames.launcher:"),
    "chrome":   ("start", "chrome"),
    "discord":  ("start", "discord"),
    "spotify":  ("uri",   "spotify:"),
    "obs":      ("start", "obs64"),
    "notepad":  ("start", "notepad"),
    "explorer": ("start", "explorer"),
    # Example of a full path if `start` can't find an app:
    # "myapp":  ("path", r"C:\\Program Files\\MyApp\\myapp.exe"),
}

# spoken alias (lowercase) -> canonical name. For anything NOT in PC_APPS, the
# canonical is matched against your Start Menu / Desktop shortcut names, so it
# just needs to resemble the app's shortcut (e.g. "notion" -> Notion.lnk).
PC_ALIASES = {
    # --- games (launched via PC_APPS Steam ids) ---
    "counter strike": "cs2", "counter-strike": "cs2", "cs": "cs2", "cs2": "cs2",
    "csgo": "cs2", "cs go": "cs2", "cs 2": "cs2",
    "контр страйк": "cs2", "контер страйк": "cs2", "кс": "cs2", "кс2": "cs2",
    "ксго": "cs2", "кс го": "cs2", "контрстрайк": "cs2", "кс два": "cs2",
    "dota": "dota2", "dota 2": "dota2", "dota2": "dota2",
    "дота": "dota2", "дота 2": "dota2", "дота2": "dota2", "дота два": "dota2",
    "valorant": "valorant", "валорант": "valorant",
    "minecraft": "minecraft", "майнкрафт": "minecraft", "майн": "minecraft",
    # --- launchers / stores ---
    "steam": "steam", "стим": "steam",
    "epic": "epic", "epic games": "epic", "эпик": "epic",
    # --- browsers ---
    "chrome": "chrome", "google chrome": "chrome", "google": "chrome",
    "хром": "chrome", "гугл": "chrome", "гугл хром": "chrome", "гугл chrome": "chrome",
    "edge": "edge", "microsoft edge": "edge", "эдж": "edge", "едж": "edge",
    # --- chat / social ---
    "discord": "discord", "дискорд": "discord",
    "telegram": "telegram", "телеграм": "telegram", "телеграмм": "telegram", "телега": "telegram",
    "whatsapp": "whatsapp", "ватсап": "whatsapp", "вотсап": "whatsapp", "вацап": "whatsapp",
    "skype": "skype", "скайп": "skype",
    # --- media ---
    "spotify": "spotify", "спотифай": "spotify", "спотифи": "spotify",
    "obs": "obs", "обс": "obs",
    # --- dev / tools ---
    "vscode": "visual studio code", "vs code": "visual studio code",
    "visual studio code": "visual studio code", "вс код": "visual studio code",
    "вижуал студио": "visual studio code", "код": "visual studio code",
    "github": "github desktop", "гитхаб": "github desktop", "github desktop": "github desktop",
    "arduino": "arduino", "ардуино": "arduino", "arduino ide": "arduino",
    "kicad": "kicad", "кикад": "kicad", "кад": "kicad",
    "notion": "notion", "ноушн": "notion", "ноушен": "notion", "ноушон": "notion",
    "claude": "claude", "клод": "claude", "клауд": "claude", "claude code": "claude",
    "fusion": "fusion", "фьюжн": "fusion", "фьюжен": "fusion", "autodesk fusion": "fusion",
    # --- office ---
    "word": "word", "ворд": "word", "microsoft word": "word",
    "powerpoint": "powerpoint", "поверпоинт": "powerpoint", "презентация": "powerpoint",
    "excel": "excel", "эксель": "excel",
    # --- utilities ---
    "radmin": "radmin", "радмин": "radmin", "radmin vpn": "radmin", "vpn": "radmin",
    "aida": "aida64", "aida64": "aida64", "аида": "aida64", "аида64": "aida64",
    "gpuz": "gpu-z", "gpu z": "gpu-z", "гпу з": "gpu-z",
    "cpuz": "cpu-z", "cpu z": "cpu-z", "цпу з": "cpu-z",
    "nvidia": "nvidia", "нвидиа": "nvidia", "нвидия": "nvidia", "nvidia app": "nvidia",
    "logitech": "logitech g hub", "g hub": "logitech g hub", "джихаб": "logitech g hub",
    "obs studio": "obs",
    "notepad": "notepad", "блокнот": "notepad",
    "explorer": "explorer", "проводник": "explorer",
}

# canonical key -> process image name for taskkill
CLOSE_EXE = {
    "chrome": "chrome.exe", "discord": "Discord.exe", "cs2": "cs2.exe",
    "dota2": "dota2.exe", "steam": "steam.exe", "spotify": "Spotify.exe",
    "obs": "obs64.exe", "notepad": "notepad.exe", "valorant": "VALORANT.exe",
    "edge": "msedge.exe", "telegram": "Telegram.exe", "whatsapp": "WhatsApp.exe",
    "skype": "Skype.exe", "visual studio code": "Code.exe", "github desktop": "GitHubDesktop.exe",
    "arduino": "Arduino IDE.exe", "kicad": "kicad.exe", "notion": "Notion.exe",
    "fusion": "Fusion360.exe", "word": "WINWORD.EXE", "powerpoint": "POWERPNT.EXE",
    "excel": "EXCEL.EXE", "radmin": "Radmin.exe", "aida64": "aida64.exe",
    "gpu-z": "GPU-Z.exe", "cpu-z": "cpuz.exe", "nvidia": "NVIDIA App.exe",
    "logitech g hub": "lghub.exe", "minecraft": "Minecraft.Windows.exe",
    "claude": "claude.exe", "epic": "EpicGamesLauncher.exe",
}

# ---- Scene modes: close one set of apps, open another. Edit freely. ----
PC_MODES = {
    "game": {
        "open":  ["discord", "steam"],
        "close": ["chrome", "edge", "word", "excel", "powerpoint", "notion",
                  "kicad", "claude"],
    },
    "work": {
        "open":  ["claude", "chrome", "kicad"],
        "close": ["steam", "discord", "spotify", "cs2", "dota2", "minecraft",
                  "epic", "valorant"],
    },
}

# Windows virtual key codes
_VK = {"volup": 0xAF, "voldown": 0xAE, "mute": 0xAD,
       "playpause": 0xB3, "next": 0xB0, "prev": 0xB1}


def _canon(target: str) -> str:
    t = (target or "").strip().lower()
    return PC_ALIASES.get(t, t)


def _startfile(arg: str):
    # os.startfile is Windows-only; fall back to 'start' for portability.
    if hasattr(os, "startfile"):
        os.startfile(arg)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["cmd", "/c", "start", "", arg])


def _start_menu_dirs():
    dirs = []
    for env in ("ProgramData", "APPDATA"):
        base = os.environ.get(env)
        if base:
            dirs.append(os.path.join(base, "Microsoft", "Windows",
                                     "Start Menu", "Programs"))
    for env in ("USERPROFILE", "PUBLIC"):
        base = os.environ.get(env)
        if base:
            dirs.append(os.path.join(base, "Desktop"))
    return [d for d in dirs if os.path.isdir(d)]


def _find_shortcut(name: str):
    """Find the best-matching .lnk/.url in the Start Menu / Desktop by name."""
    name_l = (name or "").strip().lower()
    if not name_l:
        return None
    exact = None
    best = None  # (stem_length, path) — shortest stem wins as closest match
    for d in _start_menu_dirs():
        for root, _dirs, files in os.walk(d):
            for f in files:
                low = f.lower()
                if not (low.endswith(".lnk") or low.endswith(".url")):
                    continue
                stem = os.path.splitext(low)[0]
                if stem == name_l:
                    exact = os.path.join(root, f)
                elif name_l in stem or stem in name_l:
                    if best is None or len(stem) < best[0]:
                        best = (len(stem), os.path.join(root, f))
        if exact:
            return exact
    return exact or (best[1] if best else None)


def do_launch(target: str):
    key = _canon(target)
    spec = PC_APPS.get(key)
    if spec:
        method, val = spec
        try:
            if method == "steam":
                _startfile(f"steam://rungameid/{val}")
            elif method == "uri":
                _startfile(val)
            elif method == "path":
                subprocess.Popen([val])
            elif method == "start":
                subprocess.Popen(["cmd", "/c", "start", "", val])
            else:
                return False, f"bad method: {method}"
            return True, key
        except Exception as e:
            return False, str(e)

    # Fallback: launch by matching a Start Menu / Desktop shortcut (covers any
    # installed app without hardcoding a path).
    lnk = _find_shortcut(key) or _find_shortcut(target)
    if lnk:
        try:
            _startfile(lnk)
            return True, os.path.splitext(os.path.basename(lnk))[0]
        except Exception as e:
            return False, str(e)
    return False, f"not found: {target}"


def do_mode(name: str):
    scene = PC_MODES.get((name or "").strip().lower())
    if not scene:
        return False, f"unknown mode: {name}"
    closed, opened = [], []
    for app in scene.get("close", []):
        ok, _ = do_close(app)
        if ok:
            closed.append(app)
    for app in scene.get("open", []):
        ok, _ = do_launch(app)
        if ok:
            opened.append(app)
    return True, {"opened": opened, "closed": closed}


def do_power(mode: str):
    try:
        if mode == "shutdown":
            subprocess.Popen(["shutdown", "/s", "/t", "5"])
        elif mode == "restart":
            subprocess.Popen(["shutdown", "/r", "/t", "5"])
        elif mode == "logoff":
            subprocess.Popen(["shutdown", "/l"])
        elif mode == "lock":
            subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
        elif mode == "sleep":
            # Note: disable hibernate (powercfg /h off) or this may hibernate.
            subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
        else:
            return False, f"bad power mode: {mode}"
        return True, mode
    except Exception as e:
        return False, str(e)


def do_close(target: str):
    key = _canon(target)
    exe = CLOSE_EXE.get(key)
    if not exe:
        return False, f"unknown app: {target}"
    try:
        r = subprocess.run(["taskkill", "/IM", exe, "/F"],
                           capture_output=True, text=True)
        return (r.returncode == 0), (r.stdout or r.stderr or "").strip()
    except Exception as e:
        return False, str(e)


def _press(vk: int, times: int = 1):
    if ctypes is None:
        raise RuntimeError("ctypes unavailable (not Windows?)")
    for _ in range(max(1, times)):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)   # key down
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)   # key up (KEYEVENTF_KEYUP)


def do_volume(direction: str, steps: int = 4):
    try:
        if direction == "mute":
            _press(_VK["mute"]); return True, "mute"
        vk = _VK["volup"] if direction == "up" else _VK["voldown"]
        _press(vk, steps); return True, direction
    except Exception as e:
        return False, str(e)


def do_media(action: str):
    vk = {"playpause": _VK["playpause"], "next": _VK["next"],
          "previous": _VK["prev"], "prev": _VK["prev"]}.get(action)
    if not vk:
        return False, f"bad media action: {action}"
    try:
        _press(vk); return True, action
    except Exception as e:
        return False, str(e)


def do_open_url(url: str):
    if not (url.startswith("http://") or url.startswith("https://")):
        return False, "bad url"
    try:
        _startfile(url); return True, url
    except Exception as e:
        return False, str(e)


def do_search(query: str):
    q = urllib.parse.quote((query or "").strip())
    if not q:
        return False, "empty query"
    try:
        _startfile(f"https://www.google.com/search?q={q}"); return True, query
    except Exception as e:
        return False, str(e)


def handle(cmd: dict) -> dict:
    action = cmd.get("action")
    if action == "launch":
        ok, info = do_launch(cmd.get("target", ""))
    elif action == "close":
        ok, info = do_close(cmd.get("target", ""))
    elif action == "volume":
        ok, info = do_volume(cmd.get("direction", "up"), int(cmd.get("steps", 4)))
    elif action == "media":
        ok, info = do_media(cmd.get("media", "playpause"))
    elif action == "open_url":
        ok, info = do_open_url(cmd.get("url", ""))
    elif action == "search":
        ok, info = do_search(cmd.get("query", ""))
    elif action == "power":
        ok, info = do_power(cmd.get("mode", ""))
    elif action == "mode":
        ok, info = do_mode(cmd.get("name", ""))
    else:
        ok, info = False, f"unknown action: {action}"
    return {"ok": ok, "info": info if ok else None, "error": None if ok else info}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        b = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _auth(self) -> bool:
        return self.headers.get("X-Token", "") == TOKEN

    def do_GET(self):
        if self.path == "/ping":
            if not self._auth():
                return self._send(401, {"ok": False, "error": "unauthorized"})
            return self._send(200, {"ok": True,
                                    "host": os.environ.get("COMPUTERNAME", "pc")})
        self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if self.path != "/command":
            return self._send(404, {"ok": False, "error": "not found"})
        if not self._auth():
            return self._send(401, {"ok": False, "error": "unauthorized"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            cmd = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except Exception as e:
            return self._send(400, {"ok": False, "error": f"bad json: {e}"})
        print("CMD:", cmd, flush=True)
        try:
            res = handle(cmd)
        except Exception as e:
            res = {"ok": False, "error": str(e)}
        print("  ->", res, flush=True)
        self._send(200, res)

    def log_message(self, *a):
        pass  # quiet default access logs


def main():
    if TOKEN == "change-me-please":
        print("WARNING: set a unique TOKEN (must match the Mac side).")
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"MiniJarvis PC agent listening on {HOST}:{PORT}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
