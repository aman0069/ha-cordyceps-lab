#!/usr/bin/env python3
"""Verify the base image pinned in the Dockerfile actually exists and covers
every architecture declared in config.yaml.

This exists because a plausible-looking but non-existent tag
(ghcr.io/home-assistant/base:2026.08.0 — guessed from the Home Assistant Core
release number) shipped once and failed only at install time on the target
device, with a bare "not found". The real tag format is
<alpine-version>-<base-build-version>, e.g. 3.24-2026.08.0.

Run before pushing a Dockerfile or arch change:
    python tools/check_base_image.py
Exit code 0 = safe to ship.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = ROOT / "cordyceps_lds" / "Dockerfile"
CONFIG = ROOT / "cordyceps_lds" / "config.yaml"

# Home Assistant arch name -> Docker platform architecture (+ variant).
HA_TO_DOCKER = {
    "amd64": ("amd64", None),
    "aarch64": ("arm64", None),
    "armv7": ("arm", "v7"),
    "armhf": ("arm", "v6"),
    "i386": ("386", None),
}
ACCEPT = ",".join([
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
])


def get_json(url: str, headers: dict[str, str]) -> dict:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def registry_token(repo: str) -> str:
    url = f"https://ghcr.io/token?scope=repository:{repo}:pull&service=ghcr.io"
    return get_json(url, {})["token"]


def parse_from() -> tuple[str, str]:
    text = DOCKERFILE.read_text()
    matches = re.findall(r"^\s*FROM\s+(\S+)", text, re.MULTILINE)
    if not matches:
        sys.exit("FAIL: no FROM line found in the Dockerfile.")
    image = matches[-1]
    if "@" in image:
        sys.exit(f"FAIL: digest pins are not supported by this check: {image}")
    if ":" not in image:
        sys.exit(f"FAIL: base image is unpinned (no tag): {image}")
    repo, tag = image.rsplit(":", 1)
    return repo.removeprefix("ghcr.io/"), tag


def parse_arches() -> list[str]:
    """Minimal reader for the top-level `arch:` list. Avoids a PyYAML dep."""
    arches: list[str] = []
    in_block = False
    for line in CONFIG.read_text().splitlines():
        if re.match(r"^arch:\s*$", line):
            in_block = True
            continue
        if in_block:
            m = re.match(r"^\s+-\s*(\S+)", line)
            if m:
                arches.append(m.group(1))
            elif line.strip() and not line.lstrip().startswith("#"):
                break
    return arches


def main() -> int:
    repo, tag = parse_from()
    arches = parse_arches()
    print(f"Dockerfile pins : ghcr.io/{repo}:{tag}")
    print(f"config.yaml arch: {', '.join(arches) or '(none)'}")

    token = registry_token(repo)
    auth = {"Authorization": f"Bearer {token}"}

    tags = get_json(f"https://ghcr.io/v2/{repo}/tags/list", auth).get("tags", [])
    if tag not in tags:
        real = sorted(t for t in tags if not t.startswith("sha256-"))
        print(f"\nFAIL: tag '{tag}' does not exist in ghcr.io/{repo}.")
        print("Available tags:")
        for t in real:
            print(f"  {t}")
        return 1
    print(f"OK   : tag '{tag}' exists.")

    manifest = get_json(
        f"https://ghcr.io/v2/{repo}/manifests/{tag}", {**auth, "Accept": ACCEPT}
    )
    available: set[tuple[str, str | None]] = set()
    for m in manifest.get("manifests", []):
        p = m.get("platform", {})
        if p.get("architecture") and p["architecture"] != "unknown":
            available.add((p["architecture"], p.get("variant")))
    if not available:
        print("WARN : single-platform image; cannot verify multi-arch coverage.")
        return 0
    print(f"OK   : image publishes {', '.join(sorted(a for a, _ in available))}.")

    missing = []
    for ha_arch in arches:
        want = HA_TO_DOCKER.get(ha_arch)
        if want is None:
            print(f"WARN : unrecognized arch '{ha_arch}' in config.yaml.")
            continue
        if want not in available and (want[0], None) not in available:
            missing.append(ha_arch)

    if missing:
        print(
            f"\nFAIL: config.yaml declares {', '.join(missing)}, but the base image "
            "has no such platform. Supervisor would start a build that cannot "
            "resolve a base image. Remove these arches or change the base image."
        )
        return 1

    print("OK   : every declared arch is buildable.")
    print("\nPASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
