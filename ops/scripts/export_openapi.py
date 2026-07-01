"""Emit the canonical OpenAPI schema to contracts/openapi/openapi.json (§10).

The committed schema is the shared API contract: the Slice-4 typed client generates from
it, and CI fails when the app's schema drifts from the committed copy.

Run from backend/ (the uv project):
    uv run python ../ops/scripts/export_openapi.py          # regenerate the committed file
    uv run python ../ops/scripts/export_openapi.py --check  # CI drift guard (exit 1 on drift)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT = REPO_ROOT / "contracts" / "openapi" / "openapi.json"


def build_schema() -> str:
    from yieldfield.api.main import create_app
    from yieldfield.config.settings import Settings

    # Explicit default settings (no .env) so the emitted contract is environment-independent.
    app = create_app(Settings(_env_file=None))
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the OpenAPI contract (§10).")
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail (exit 1) if the committed schema differs from the app's schema",
    )
    args = parser.parse_args()
    schema = build_schema()
    if args.check:
        committed = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if committed != schema:
            print(
                f"OpenAPI drift: {OUTPUT} is stale. Regenerate with: "
                "uv run python ../ops/scripts/export_openapi.py",
                file=sys.stderr,
            )
            return 1
        print("OpenAPI contract is up to date.")
        return 0
    OUTPUT.write_text(schema, encoding="utf-8")
    print(f"Wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
