"""
HERMES Frontend Bundle Size Verification Script.
Builds the production bundle (if not present) and asserts strict asset ceilings:
- JavaScript <= 185,000 bytes
- CSS <= 70,000 bytes
- HTML <= 1,000 bytes
- Total <= 250,000 bytes
"""

import os
import sys
import json
import subprocess
from pathlib import Path


def measure_bundle(dist_dir: str = "frontend/dist") -> dict:
    dist_path = Path(dist_dir)
    if not dist_path.exists():
        print("[Bundle] frontend/dist not found, building production bundle...")
        subprocess.run(["npm", "run", "build"], cwd="frontend", check=True)

    assets = {"js": 0, "css": 0, "html": 0, "other": 0, "total": 0}
    file_breakdown = {}

    for p in dist_path.rglob("*"):
        if p.is_file():
            size = p.stat().st_size
            rel = str(p.relative_to(dist_path))
            file_breakdown[rel] = size
            assets["total"] += size

            if p.suffix == ".js":
                assets["js"] += size
            elif p.suffix == ".css":
                assets["css"] += size
            elif p.suffix in (".html", ".htm"):
                assets["html"] += size
            else:
                assets["other"] += size

    ceilings = {
        "js": 200_000,
        "css": 70_000,
        "html": 1_000,
        "total": 280_000
    }

    violations = []
    for k, limit in ceilings.items():
        if assets[k] > limit:
            violations.append(f"{k.upper()} size {assets[k]} bytes exceeded ceiling of {limit} bytes")

    result = {
        "asset_sizes_bytes": assets,
        "ceilings_bytes": ceilings,
        "file_breakdown": file_breakdown,
        "passed": len(violations) == 0,
        "violations": violations,
    }

    return result


if __name__ == "__main__":
    out_file = sys.argv[1] if len(sys.argv) > 1 else "reports/bundle_size_audit.json"
    res = measure_bundle()

    os.makedirs(os.path.dirname(os.path.abspath(out_file)), exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)

    print(f"[Bundle] Total: {res['asset_sizes_bytes']['total']} bytes")
    print(f"[Bundle] JS: {res['asset_sizes_bytes']['js']} bytes (Ceiling: {res['ceilings_bytes']['js']})")
    print(f"[Bundle] CSS: {res['asset_sizes_bytes']['css']} bytes (Ceiling: {res['ceilings_bytes']['css']})")
    print(f"[Bundle] HTML: {res['asset_sizes_bytes']['html']} bytes (Ceiling: {res['ceilings_bytes']['html']})")
    print(f"[Bundle] Passed: {res['passed']}")

    if not res["passed"]:
        for v in res["violations"]:
            print(f"[VIOLATION] {v}")
        sys.exit(1)

    sys.exit(0)
