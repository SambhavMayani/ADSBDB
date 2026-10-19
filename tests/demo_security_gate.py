"""Demonstrate a harmless executable-header masquerade without storing malware.

Run from repository root: python tests/demo_security_gate.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "landing_zone" / "temporal_landing"))

from security_gate import inspect_file, read_config  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ecosentinel_security_demo_") as folder:
        path = Path(folder) / "lynx.jpg"
        path.write_bytes(b"MZ" + b"\x00" * 96)
        verdict = inspect_file(path, "images", read_config())
        print("EcoSentinel Security Gate demonstration")
        print("Input: harmless synthetic bytes with a .jpg extension")
        print(f"Verdict: {'ALLOWED' if verdict.allowed else 'BLOCKED'}")
        print(f"Reason:  {verdict.reason}")
        print("Note: no executable program was created or run")
        return 1 if verdict.allowed else 0


if __name__ == "__main__":
    raise SystemExit(main())
