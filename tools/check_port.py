#!/usr/bin/env python3
"""Check whether the host port this app wants to publish is already taken.

Run this ON THE HOME ASSISTANT HOST (Terminal & SSH app) before installing or
after changing the Network settings:

    python3 tools/check_port.py            # reads the port from config.yaml
    python3 tools/check_port.py 8189       # or check a specific port

Background: port 8099 is the default `ingress_port` for Home Assistant apps, so
it is heavily used inside other app containers and frequently published on the
host too (Zigbee2MQTT frontend, SSH/Terminal web UI, File Editor). That is why
this app publishes 8189 on the host instead, while still listening on 8099
inside its own container.
"""
from __future__ import annotations

import re
import socket
import subprocess
import sys
from pathlib import Path

CONFIG = Path(__file__).resolve().parent.parent / "cordyceps_lds" / "config.yaml"

# Host ports commonly published by Home Assistant apps, so we can name a likely
# culprit instead of just reporting "in use".
KNOWN = {
    8099: "HA app ingress convention — Zigbee2MQTT frontend, SSH/Terminal, File Editor",
    8123: "Home Assistant web interface",
    1883: "Mosquitto MQTT",
    8883: "Mosquitto MQTT over TLS",
    6052: "ESPHome dashboard",
    1880: "Node-RED",
    4357: "HA Supervisor observer",
    8080: "generic app web UI",
    3000: "AdGuard Home / Grafana",
    5000: "Frigate",
    445: "Samba",
    22: "SSH",
}


def wanted_port() -> int:
    text = CONFIG.read_text()
    m = re.search(r"^\s*(\d+)/tcp:\s*(\d+)\s*$", text, re.MULTILINE)
    if not m:
        sys.exit("Could not read a host port from config.yaml ports: block.")
    container, host = int(m.group(1)), int(m.group(2))
    print(f"config.yaml maps container {container}/tcp -> host {host}")
    return host


def in_use(port: int) -> bool:
    """True if something is already listening on this port on any interface."""
    for family, addr in ((socket.AF_INET, "0.0.0.0"), (socket.AF_INET6, "::")):
        try:
            s = socket.socket(family, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((addr, port))
            s.close()
        except OSError:
            return True
        except Exception:
            continue
    return False


def identify(port: int) -> None:
    """Best-effort: name the process or container holding the port."""
    for cmd in (["ss", "-ltnp"], ["netstat", "-ltnp"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout
        except (FileNotFoundError, subprocess.SubprocessError):
            continue
        hits = [ln for ln in out.splitlines() if f":{port} " in ln or ln.rstrip().endswith(f":{port}")]
        if hits:
            print("\nListener detail:")
            for h in hits:
                print("  " + h.strip())
            return
    try:
        out = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"],
            capture_output=True, text=True, timeout=15,
        ).stdout
        hits = [ln for ln in out.splitlines() if f":{port}->" in ln]
        if hits:
            print("\nHolding container:")
            for h in hits:
                print("  " + h.strip())
            return
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    print("\n(Could not identify the listener — ss/netstat/docker unavailable here.)")
    print("Run this on the host via the Terminal & SSH app for a useful answer.")


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else wanted_port()

    if not in_use(port):
        print(f"OK: host port {port} is free.\n\nPASS")
        return 0

    print(f"\nFAIL: host port {port} is already in use.")
    if port in KNOWN:
        print(f"Commonly this is: {KNOWN[port]}")
    identify(port)
    print(
        "\nFix: open the app's Configuration tab, scroll to Network, and set a\n"
        "different host port. Then reprint labels ONLY if you had already printed\n"
        "any — the host port is encoded in every QR code. Nothing else needs to\n"
        "change: Home Assistant talks to the app over the Docker network on the\n"
        "container port, which never conflicts."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
