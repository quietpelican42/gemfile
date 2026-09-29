"""Run the Bundler oracle and compare its output with the reader's, field by field."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import gemfile
from gemfile import Gemfile

ROOT = Path(__file__).resolve().parent.parent
ORACLE_RB = ROOT / "scripts" / "oracle.rb"
ORACLE_BUNDLER = "1.17"

DEP_FIELDS = ("name", "requirement", "requirements", "groups", "platforms", "source", "autorequire",
              "type", "env", "install_if")
FILE_FIELDS = ("sources", "ruby", "optional_groups")


def find_oracle() -> tuple[str | None, str]:
    """Return (ruby path, reason). The path is None when the oracle cannot run."""
    ruby = shutil.which("ruby")
    if ruby is None:
        return None, "ruby is not on PATH; install Ruby with Bundler 1.17.x to run the oracle tests"
    proc = subprocess.run(
        [ruby, "-e", 'require "bundler"; print Bundler::VERSION'],
        capture_output=True, text=True, check=False,
    )
    version = proc.stdout.strip()
    if proc.returncode != 0 or not version.startswith(ORACLE_BUNDLER + "."):
        return None, (
            f"the oracle needs Bundler {ORACLE_BUNDLER}.x, found {version or 'none'}; "
            "the reader's default results are only compared against that version"
        )
    return ruby, version


def run_oracle(ruby: str, files: list[Path], work: Path) -> dict[str, dict[str, Any]]:
    """Evaluate `files` with Bundler's DSL in one Ruby process."""
    work = work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    listing = work / "list.txt"
    out = work / "oracle.json"
    listing.write_text("\n".join(str(f.resolve()) for f in files) + "\n")
    if out.exists():
        out.unlink()
    proc = subprocess.run(
        [ruby, str(ORACLE_RB), str(out), str(listing)],
        cwd=work, capture_output=True, text=True, check=False, stdin=subprocess.DEVNULL,
    )
    if not out.exists():
        raise RuntimeError(f"oracle failed: {proc.stderr[-500:]}")
    data: dict[str, dict[str, Any]] = json.loads(out.read_text())
    return data


def reader_result(text: str) -> Gemfile:
    return gemfile.parse(text, strict=False, bundler="1.17")


def dep_dict(d: gemfile.Dependency) -> dict[str, Any]:
    full = d.to_dict()
    return {k: full[k] for k in DEP_FIELDS}


def file_level(g: Gemfile) -> dict[str, Any]:
    return {
        "sources": list(g.sources),
        "ruby": None if g.ruby is None else {
            "versions": list(g.ruby.versions),
            "engine": g.ruby.engine,
            "engine_versions": list(g.ruby.engine_versions),
            "patchlevel": g.ruby.patchlevel,
        },
        "optional_groups": list(g.optional_groups),
    }


def mismatches(g: Gemfile, oracle: dict[str, Any]) -> list[str]:
    """Names of the fields where the reader and the oracle disagree ([] when they agree)."""
    bad: list[str] = []
    mine = file_level(g)
    for f in FILE_FIELDS:
        if mine[f] != oracle[f]:
            bad.append(f)
    deps = oracle["dependencies"]
    if [d.name for d in g.dependencies] != [d["name"] for d in deps]:
        bad.append("dependency-list")
        return bad
    for got, want in zip(g.dependencies, deps):
        gd = dep_dict(got)
        for f in DEP_FIELDS:
            if gd[f] != want[f] and f"dep.{f}" not in bad:
                bad.append(f"dep.{f}")
    return bad
