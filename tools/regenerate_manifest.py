#!/usr/bin/env python3
"""Regenerates MANIFEST.sha256 for sovereign-sheets-crm."""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main():
    lines = []
    for p in sorted(ROOT.rglob('*')):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT)
        if any(part.startswith('.') for part in rel.parts):
            continue
        if '__pycache__' in rel.parts or rel.name == 'MANIFEST.sha256':
            continue
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        lines.append(f"{digest}  {rel.as_posix()}\n")

    lines.sort(key=lambda x: x.split("  ")[1])
    manifest_path = ROOT / "MANIFEST.sha256"
    manifest_path.write_text("".join(lines), encoding="utf-8")
    print(f"Wrote {len(lines)} file hashes to {manifest_path}")

if __name__ == "__main__":
    main()
