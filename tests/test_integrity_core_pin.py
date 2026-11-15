"""deploy/integrity-core.ref is the single integrity-core pin for CI and the deploy images.

An unpinned `git clone` of integrity-core in the Render image was served from Docker's layer
cache and shipped an SDK without `integrity_sdk.billing` for four deploys (2026-11-14). The
image now fetches the pinned commit, and CI checks out the same one, so a deploy runs exactly
the SDK CI tested.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN = ROOT / "deploy" / "integrity-core.ref"
CI = ROOT / ".github" / "workflows" / "ci.yml"
DOCKERFILES = [ROOT / "deploy" / "render" / "Dockerfile", ROOT / "deploy" / "railway" / "Dockerfile"]


def test_pin_is_a_full_commit_sha():
    assert re.fullmatch(r"[0-9a-f]{40}", PIN.read_text().strip())


def test_ci_checks_out_integrity_core_at_the_pin_only():
    ci = CI.read_text()
    checkouts = ci.count("repository: XibalbaTechSol/integrity-core")
    assert checkouts >= 1
    assert ci.count("ref: ${{ steps.core.outputs.ref }}") == checkouts
    assert ci.count("deploy/integrity-core.ref") >= checkouts
    assert not re.search(r"ref:\s*[0-9a-f]{40}", ci), "hard-coded integrity-core ref in ci.yml"


def test_deploy_images_fetch_the_pinned_commit():
    for path in DOCKERFILES:
        text = path.read_text()
        assert "git clone" not in text, f"{path.name}: unpinned clone of integrity-core"
        copy = text.index("COPY deploy/integrity-core.ref")
        fetch = text.index("integrity-core.git")
        assert copy < fetch, f"{path} must COPY the pin before fetching, so the cache keys on it"
        assert 'test "$(git -C /app/integrity-core rev-parse HEAD)" = "$ref"' in text
