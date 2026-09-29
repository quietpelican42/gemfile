"""Regenerate tests/fixtures/*.expected.json from the Bundler oracle.

    python scripts/capture_fixtures.py

Each expected file holds the oracle's answer (or its error) for the fixture.
The reader's own expectations (static or not, and the lines it flags) are
written by hand in tests/test_fixtures.py.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

import oraclelib  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


def main() -> None:
    ruby, why = oraclelib.find_oracle()
    if ruby is None:
        sys.exit(f"cannot run the oracle: {why}")
    files = sorted(FIXTURES.glob("*.Gemfile"))
    with tempfile.TemporaryDirectory(prefix="gemfile-fixtures-") as tmp:
        result = oraclelib.run_oracle(ruby, files, Path(tmp))
    for f in files:
        data = result[str(f.resolve())]
        if not data["ok"]:
            # keep absolute paths (and so the machine's username) out of committed files
            err = data["error"].replace(str(f.resolve()), f.name).replace(str(FIXTURES), "fixtures")
            err = err.split(" | #  from")[0]
            data["error"] = re.sub(r"/(?:Users|home|private|var)/\S*", "<path>", err)
        f.with_suffix(".expected.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        print(f"{f.name}: {'ok' if data['ok'] else 'error'}")


if __name__ == "__main__":
    main()
