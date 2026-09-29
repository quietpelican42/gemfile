"""Command line entry point: ``gemfile [--bundler 1.17|2] FILE``."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, cast

from . import parse_file


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="gemfile",
        description="Print what Bundler's DSL would produce for a Gemfile, as JSON, without running Ruby.",
    )
    ap.add_argument("file", type=Path, help="path to a Gemfile")
    ap.add_argument(
        "--bundler",
        choices=["1.17", "2"],
        default="2",
        help="how the built-in github: shorthand expands (default: 2, https)",
    )
    args = ap.parse_args(argv)
    try:
        gem = parse_file(args.file, strict=False, bundler=cast(Literal["1.17", "2"], args.bundler))
    except (OSError, UnicodeDecodeError) as e:
        print(f"gemfile: cannot read {args.file}: {e}", file=sys.stderr)
        return 2
    json.dump(gem.to_dict(), sys.stdout, indent=2)
    sys.stdout.write("\n")
    for d in gem.diagnostics:
        print(f"{args.file}: {d}", file=sys.stderr)
    return 1 if gem.diagnostics else 0
