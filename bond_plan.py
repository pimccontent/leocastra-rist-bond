"""RIST bond plan for the Ubuntu field kit. No I/O."""

from __future__ import annotations

import re
from typing import Iterable

HOST_RE = re.compile(r"^[A-Za-z0-9._:-]+$")
IFACE_RE = re.compile(r"^[A-Za-z0-9._:-]{1,32}$")
STUDIO_URL_RE = re.compile(
    r"^rist://(?P<host>\[[^\]]+\]|[^:/?#]+):(?P<port>\d+)(?:\?(?P<query>.*))?$",
    re.IGNORECASE,
)


def recovery_window(buffer_ms: int) -> tuple[int, int, int]:
    """Match the studio rule: 500 ms or less stays fixed; above that, 200 ms is the floor."""
    max_ms = max(200, min(8000, int(buffer_ms)))
    if max_ms <= 500:
        return max_ms, max_ms, 25
    return 200, max_ms, 50


def iface_kind(name: str) -> str:
    n = (name or "").lower()
    if n == "lo" or n.startswith(("docker", "br-", "veth", "virbr", "tun", "tap")):
        return "ignore"
    if n.startswith(("wlan", "wlp", "wlx", "wwan", "usb", "rmnet", "enx")):
        return "uplink"
    if n.startswith(("eth", "eno", "enp", "ens", "em")):
        return "ethernet"
    return "other"


def bondable(kind: str) -> bool:
    """Kit Ethernet stays the OBS LAN. Modems and Wi-Fi are the bond."""
    return kind == "uplink"


def selected_paths(interfaces: Iterable[dict], mode: str, manual: Iterable[str]) -> list[dict]:
    rows = [row for row in interfaces if row.get("address") and bondable(row.get("kind", ""))]
    if mode == "manual":
        wanted = {name for name in manual if name}
        rows = [row for row in rows if row.get("iface") in wanted]
    rows.sort(key=lambda row: str(row.get("iface")))
    return rows


def loopback_paths() -> list[dict]:
    """Two RIST peers on one machine. Used to prove the bond before the modems are attached."""
    return [
        {"iface": "lo", "address": "127.0.0.1", "kind": "local", "bondable": True},
        {"iface": "lo", "address": "127.0.0.1", "kind": "local", "bondable": True},
    ]


def parse_studio_urls(text: str) -> dict:
    """Read the link lines copied from one LeoCastra RIST stream."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        raise ValueError("Paste the RIST link lines from LeoCastra.")
    if len(lines) > 4:
        raise ValueError("A RIST bond accepts 1 to 4 links.")
    hosts: list[str] = []
    ports: list[int] = []
    buffer_ms = 2000
    encryption = 0
    secret = ""
    for line in lines:
        match = STUDIO_URL_RE.match(line)
        if not match:
            raise ValueError("Each line must be a rist:// URL from the LeoCastra RIST stream.")
        host = match.group("host").strip("[]")
        if not HOST_RE.match(host):
            raise ValueError("Studio host must be a hostname or IP.")
        port = int(match.group("port"))
        if port < 1 or port > 65535:
            raise ValueError("A bond link port is out of range.")
        query = {}
        for part in (match.group("query") or "").split("&"):
            if "=" in part:
                key, value = part.split("=", 1)
                query[key] = value
        hosts.append(host)
        ports.append(port)
        if query.get("buffer-max", "").isdigit():
            buffer_ms = int(query["buffer-max"])
        aes = query.get("aes-type", "")
        if aes in ("128", "256"):
            encryption = int(aes)
            secret = query.get("secret") or ""
        elif "aes-type" not in query:
            encryption = 0
            secret = ""
    if len(set(hosts)) != 1:
        raise ValueError("Every link must use the same LeoCastra host.")
    if len(set(ports)) != len(ports):
        raise ValueError("Each link needs its own port.")
    return {
        "studioHost": hosts[0],
        "basePort": ports[0],
        "studioPorts": ports,
        "bufferMs": buffer_ms,
        "encryption": encryption,
        "secret": secret,
    }


def path_urls(
    host: str,
    base_port: int,
    paths: list[dict],
    buffer_ms: int,
    mode: str,
    secret: str,
    encryption: int,
    pin_interface: bool = True,
    ports: list[int] | None = None,
) -> list[str]:
    if not HOST_RE.match(host or ""):
        raise ValueError("Studio host must be a hostname or IP.")
    port0 = int(base_port)
    if port0 < 1 or port0 > 65535:
        raise ValueError("Base port is out of range.")
    if ports is not None and len(ports) != len(paths):
        raise ValueError(
            f"LeoCastra has {len(ports)} link(s) and this kit has {len(paths)} uplink(s). Use the same count."
        )
    weight = "0" if mode != "split" else "5"
    min_ms, max_ms, reorder = recovery_window(buffer_ms)
    urls = []
    for index, path in enumerate(paths):
        iface = str(path.get("iface") or "")
        if not IFACE_RE.match(iface):
            raise ValueError(f"Interface name is not usable: {iface}")
        port = int(ports[index]) if ports is not None else port0 + index
        if port < 1 or port > 65535:
            raise ValueError("A bond path port is past 65535.")
        query = [
            f"buffer-min={min_ms}",
            f"buffer-max={max_ms}",
            f"reorder-buffer={reorder}",
            "congestion-control=1",
            "min-retries=6",
            "max-retries=20",
            "session-timeout=10000",
            "keepalive-interval=1000",
            "cname=leocastra",
            "timing-mode=0",
            f"weight={weight}",
        ]
        if pin_interface:
            query.append(f"miface={iface}")
        if encryption in (128, 256):
            if not secret or any(ch in secret for ch in ",& "):
                raise ValueError("Passphrase cannot contain spaces, commas, or &.")
            query.append(f"aes-type={encryption}")
            query.append(f"secret={secret}")
            query.append("key-rotation=60000")
        urls.append(f"rist://{host}:{port}?{'&'.join(query)}")
    return urls


def ristsender_args(binary: str, local_udp: int, urls: list[str]) -> list[str]:
    if not urls:
        raise ValueError("Select at least one modem or Wi-Fi path.")
    return [
        binary,
        "-p",
        "1",
        "-v",
        "4",
        "-i",
        f"udp://127.0.0.1:{int(local_udp)}",
        "-o",
        ",".join(urls),
    ]


def receiver_args(binary: str, base_port: int, count: int, buffer_ms: int, out_port: int) -> list[str]:
    """One joiner for the local proof. The studio joiner is still the production receiver."""
    if count < 1:
        raise ValueError("The joiner needs at least one RIST path.")
    min_ms, max_ms, reorder = recovery_window(buffer_ms)
    urls = []
    for index in range(count):
        port = int(base_port) + index
        urls.append(
            f"rist://@0.0.0.0:{port}?buffer-min={min_ms}&buffer-max={max_ms}"
            f"&reorder-buffer={reorder}&cname=leocastra"
        )
    return [
        binary,
        "-p",
        "1",
        "-v",
        "4",
        "-i",
        ",".join(urls),
        "-o",
        f"udp://0.0.0.0:{int(out_port)}",
    ]


def local_srt_args(ffmpeg: str, listen_port: int, local_udp: int) -> list[str]:
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "warning",
        "-i",
        f"srt://0.0.0.0:{int(listen_port)}?mode=listener&latency=200000&pkt_size=1316",
        "-c",
        "copy",
        "-f",
        "mpegts",
        f"udp://127.0.0.1:{int(local_udp)}?pkt_size=1316",
    ]
