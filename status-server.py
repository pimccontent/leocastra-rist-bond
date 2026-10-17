#!/usr/bin/env python3
"""Web UI and process supervisor for the Ubuntu RIST bond kit."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from bond_plan import (
    bondable,
    iface_kind,
    local_srt_args,
    loopback_paths,
    parse_studio_urls,
    path_urls,
    receiver_args,
    ristsender_args,
    selected_paths,
)

ROOT = Path(__file__).resolve().parent
WEB = Path(os.environ.get("WEB_ROOT", ROOT / "web"))
DATA = Path(os.environ.get("CONFIG_DIR", ROOT / "data"))
CONFIG_PATH = DATA / "config.json"
PORT = int(os.environ.get("STATUS_PORT", "8089"))
FFMPEG = os.environ.get("FFMPEG_BIN", "ffmpeg")
RISTSENDER = os.environ.get("RISTSENDER_BIN", "ristsender")
RISTRECEIVER = os.environ.get("RISTRECEIVER_BIN", "ristreceiver")
JOIN = os.environ.get("RIST_BOND_JOIN", "") == "1"
JOIN_PORT = int(os.environ.get("RIST_BOND_JOIN_PORT", "6000"))

DEFAULT = {
    "studioHost": "",
    "basePort": 18180,
    "bufferMs": 2000,
    "encryption": 0,
    "secret": "",
    "mode": "seamless",
    "uplinkMode": "auto",
    "paths": [],
    "studioUrls": "",
    "studioPorts": [],
    "listenPort": 4011,
    "localUdp": 15000,
}


def load_config() -> dict:
    cfg = dict(DEFAULT)
    if CONFIG_PATH.exists():
        try:
            stored = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                cfg.update(stored)
        except (OSError, json.JSONDecodeError):
            pass
    cfg["mode"] = "split" if cfg.get("mode") == "split" else "seamless"
    cfg["uplinkMode"] = normalize_uplink(cfg.get("uplinkMode"))
    cfg["encryption"] = int(cfg.get("encryption") or 0)
    if cfg["encryption"] not in (0, 128, 256):
        cfg["encryption"] = 0
    cfg["paths"] = [str(name) for name in cfg.get("paths") or []]
    cfg["studioUrls"] = str(cfg.get("studioUrls") or "")
    cfg["studioPorts"] = [int(port) for port in cfg.get("studioPorts") or []]
    return cfg


def normalize_uplink(value) -> str:
    if value == "manual":
        return "manual"
    if value == "loopback":
        return "loopback"
    return "auto"


def active_paths(interfaces: list[dict], mode: str, manual: list[str]) -> list[dict]:
    if mode == "loopback":
        return loopback_paths()
    return selected_paths(interfaces, mode, manual)


def save_config(cfg: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def read_interfaces() -> list[dict]:
    try:
        raw = subprocess.check_output(["ip", "-j", "addr"], text=True, timeout=3)
        payload = json.loads(raw)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return []
    rows = []
    for item in payload:
        name = str(item.get("ifname") or "")
        kind = iface_kind(name)
        if kind == "ignore":
            continue
        address = ""
        for addr in item.get("addr_info") or []:
            if addr.get("family") == "inet" and addr.get("local"):
                address = str(addr["local"])
                break
        rows.append({
            "iface": name,
            "address": address,
            "kind": kind,
            "bondable": bondable(kind),
            "up": item.get("operstate") == "UP",
        })
    return rows


def lan_ip(interfaces: list[dict]) -> str:
    for row in interfaces:
        if row["kind"] == "ethernet" and row["address"] and not row["address"].startswith("127."):
            return row["address"]
    return "127.0.0.1"


class Supervisor:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.ffmpeg = None
        self.sender = None
        self.receiver = None
        self.note = "Idle"
        self.ffmpeg_line = ""
        self.sender_line = ""
        self.receiver_line = ""
        self.started = 0
        self.generation = 0

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "ffmpeg": self._alive(self.ffmpeg),
                "sender": self._alive(self.sender),
                "receiver": self._alive(self.receiver),
                "note": self.note,
                "ffmpegLine": self.ffmpeg_line,
                "senderLine": self.sender_line,
                "receiverLine": self.receiver_line,
            }

    def apply(self) -> None:
        self.stop()
        with self.lock:
            self.generation += 1
            generation = self.generation
        cfg = load_config()
        interfaces = read_interfaces()
        paths = active_paths(interfaces, cfg["uplinkMode"], cfg["paths"])
        if not cfg["studioHost"]:
            self._set_note("Set the studio host in Settings.")
            return
        if not paths:
            self._set_note("No modem or Wi-Fi path is up. Ethernet stays the encoder LAN.")
            return
        ports = cfg.get("studioPorts") or None
        if ports and len(ports) != len(paths):
            self._set_note(
                f"LeoCastra has {len(ports)} link(s) and this kit has {len(paths)} uplink(s). Use the same count."
            )
            return
        try:
            urls = path_urls(
                str(cfg["studioHost"]).strip(),
                int(cfg["basePort"]),
                paths,
                int(cfg["bufferMs"]),
                cfg["mode"],
                str(cfg.get("secret") or ""),
                int(cfg["encryption"]),
                pin_interface=cfg["uplinkMode"] != "loopback",
                ports=ports,
            )
            ffmpeg_cmd = local_srt_args(FFMPEG, int(cfg["listenPort"]), int(cfg["localUdp"]))
            sender_cmd = ristsender_args(RISTSENDER, int(cfg["localUdp"]), urls)
            join_cmd = None
            if JOIN:
                join_cmd = receiver_args(
                    RISTRECEIVER,
                    int(cfg["basePort"]),
                    len(paths),
                    int(cfg["bufferMs"]),
                    JOIN_PORT,
                )
        except (ValueError, OSError) as exc:
            self._set_note(str(exc))
            return
        with self.lock:
            if join_cmd:
                self.receiver = self._spawn(join_cmd, "receiver")
            self.sender = self._spawn(sender_cmd, "sender")
            self.started = int(time.time())
            if self.sender is None:
                self.note = "ristsender is not installed. Install rist-tools on this kit."
            elif join_cmd and self.receiver is None:
                self.note = "ristreceiver is not installed."
            else:
                self.note = f"Sending {len(paths)} path{'s' if len(paths) != 1 else ''}"
        threading.Thread(target=self._keep_ffmpeg, args=(generation, ffmpeg_cmd), daemon=True).start()

    def _keep_ffmpeg(self, generation: int, cmd: list[str]) -> None:
        """OBS disconnects close the SRT listener. Bring it back without touching the bond."""
        while True:
            with self.lock:
                if generation != self.generation:
                    return
                self.ffmpeg = self._spawn(cmd, "ffmpeg")
                proc = self.ffmpeg
            if proc is None:
                return
            while proc.poll() is None:
                time.sleep(0.3)
                with self.lock:
                    if generation != self.generation:
                        return
            time.sleep(0.4)

    def stop(self) -> None:
        with self.lock:
            self.generation += 1
            for proc in (self.ffmpeg, self.sender, self.receiver):
                if proc and proc.poll() is None:
                    proc.terminate()
            self.ffmpeg = None
            self.sender = None
            self.receiver = None

    def _set_note(self, note: str) -> None:
        with self.lock:
            self.note = note

    def _spawn(self, cmd: list[str], slot: str):
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        except OSError:
            return None
        threading.Thread(target=self._drain, args=(proc, slot), daemon=True).start()
        return proc

    def _drain(self, proc, slot: str) -> None:
        if not proc.stderr:
            return
        for line in proc.stderr:
            text = line.strip()
            if not text:
                continue
            with self.lock:
                if slot == "ffmpeg":
                    self.ffmpeg_line = text[-240:]
                elif slot == "receiver":
                    self.receiver_line = text[-240:]
                else:
                    self.sender_line = text[-240:]

    @staticmethod
    def _alive(proc) -> bool:
        return bool(proc and proc.poll() is None)


SUPER = Supervisor()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        return

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/status":
            self._json(self._status())
            return
        if path == "/api/config":
            cfg = load_config()
            cfg["secretSet"] = bool(cfg.get("secret"))
            cfg["secret"] = ""
            self._json(cfg)
            return
        if path == "/static/styles.css":
            self._file(WEB / "styles.css", "text/css")
            return
        if path == "/static/app.js":
            self._file(WEB / "app.js", "text/javascript")
            return
        if path in ("/", "/index.html"):
            self._file(WEB / "index.html", "text/html")
            return
        self.send_error(404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/restart":
            SUPER.apply()
            self._json(self._status())
            return
        if path == "/api/config":
            body = self._body()
            cfg = load_config()
            for key in ("studioHost", "mode", "uplinkMode"):
                if key in body:
                    cfg[key] = body[key]
            for key in ("basePort", "bufferMs", "encryption", "listenPort"):
                if key in body:
                    cfg[key] = int(body[key])
            if "paths" in body and isinstance(body["paths"], list):
                cfg["paths"] = [str(name) for name in body["paths"]]
            if "studioUrls" in body:
                text = str(body.get("studioUrls") or "").strip()
                if text:
                    try:
                        parsed = parse_studio_urls(text)
                    except ValueError as exc:
                        self._json({"ok": False, "note": str(exc)})
                        return
                    cfg["studioUrls"] = text
                    cfg["studioHost"] = parsed["studioHost"]
                    cfg["basePort"] = parsed["basePort"]
                    cfg["studioPorts"] = parsed["studioPorts"]
                    cfg["bufferMs"] = parsed["bufferMs"]
                    cfg["encryption"] = parsed["encryption"]
                    cfg["secret"] = parsed["secret"] if parsed["encryption"] else ""
                else:
                    cfg["studioUrls"] = ""
                    cfg["studioPorts"] = []
            if body.get("secret"):
                cfg["secret"] = str(body["secret"])
            if int(cfg["encryption"]) == 0:
                cfg["secret"] = ""
            cfg["mode"] = "split" if cfg.get("mode") == "split" else "seamless"
            cfg["uplinkMode"] = normalize_uplink(cfg.get("uplinkMode"))
            save_config(cfg)
            SUPER.apply()
            self._json({"ok": True, "note": SUPER.snapshot()["note"]})
            return
        self.send_error(404)

    def _status(self) -> dict:
        cfg = load_config()
        interfaces = read_interfaces()
        paths = active_paths(interfaces, cfg["uplinkMode"], cfg["paths"])
        runtime = SUPER.snapshot()
        stored_ports = [int(port) for port in cfg.get("studioPorts") or []]
        link_ports = stored_ports or [int(cfg["basePort"]) + index for index in range(len(paths))]
        return {
            "studioHost": cfg["studioHost"],
            "basePort": int(cfg["basePort"]),
            "linkPorts": link_ports,
            "studioUrls": cfg.get("studioUrls") or "",
            "bufferMs": int(cfg["bufferMs"]),
            "mode": cfg["mode"],
            "encryption": int(cfg["encryption"]),
            "listenPort": int(cfg["listenPort"]),
            "lanIp": lan_ip(interfaces),
            "networks": interfaces,
            "paths": paths,
            "bond": runtime,
        }

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        data = json.loads(raw.decode("utf-8") or "{}")
        return data if isinstance(data, dict) else {}

    def _json(self, payload: dict) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _file(self, path: Path, content_type: str) -> None:
        if not path.is_file():
            self.send_error(404)
            return
        raw = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def seed_loopback() -> None:
    if os.environ.get("RIST_BOND_LOOPBACK") != "1":
        return
    cfg = load_config()
    cfg["studioHost"] = os.environ.get("RIST_BOND_HOST", "127.0.0.1")
    cfg["uplinkMode"] = "loopback"
    cfg["mode"] = "seamless"
    cfg["encryption"] = 0
    cfg["basePort"] = int(os.environ.get("RIST_BOND_BASE", cfg["basePort"]))
    cfg["listenPort"] = int(os.environ.get("RIST_BOND_LISTEN", cfg["listenPort"]))
    cfg["bufferMs"] = int(os.environ.get("RIST_BOND_BUFFER", cfg["bufferMs"]))
    save_config(cfg)


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    seed_loopback()
    SUPER.apply()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"RIST Bond UI on :{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
