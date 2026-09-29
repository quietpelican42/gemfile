"""Differential run: the reader against Bundler 1.17's DSL on Gemfile corpora.

    python scripts/differential.py --generated 6000 [--seed 1]
    python scripts/differential.py --corpus .corpus

Prints exact agreement per field on the files the reader classifies as static,
and how many files it classifies as dynamic or invalid.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

import gemgen  # noqa: E402
import oraclelib  # noqa: E402


def classify_reason(message: str) -> str:
    """Bucket a diagnostic message for the residual table."""
    for key, label in (
        ("ENV access", "ENV access"),
        ("eval_gemfile", "eval_gemfile"),
        ("`if` block", "if/unless/case block"),
        ("`unless` block", "if/unless/case block"),
        ("`case` block", "if/unless/case block"),
        ("modifier", "if/unless modifier"),
        ("interpolation", "string interpolation"),
        ("install_if", "install_if lambda"),
        ("lambda", "lambda"),
        ("not a Gemfile DSL method", "other method call"),
        ("assignment to local variable", "variable assignment"),
        ("method call on", "method call on receiver"),
        ("constant", "constant / File / Dir access"),
        ("call into", "constant / File / Dir access"),
        ("definition", "def/class/module"),
        ("heredoc", "heredoc"),
        ("method call or variable", "variable or method as argument"),
        ("git_source", "git_source block shape"),
        ("ruby directive", "ruby directive without a version"),
        ("source URI", "source URI form"),
    ):
        if key in message:
            return label
    return "other: " + message[:60]


# Real Gemfiles are third-party Ruby that the oracle would execute. Files that
# shell out or touch the filesystem are not evaluated.
UNSAFE = re.compile(
    r"\b(system|exec|spawn|fork|popen|open3|Open3|FileUtils|rm_rf|rm_r)\b|`|%x|"
    r"File\.(delete|write|unlink|rename|open|chmod|symlink)|Dir\.(mkdir|rmdir)|IO\."
)


def run(files: list[Path], work: Path, show: int) -> dict[str, Any]:
    ruby, why = oraclelib.find_oracle()
    if ruby is None:
        sys.exit(f"cannot run the oracle: {why}")
    def code_of(f: Path) -> str:
        lines = f.read_bytes().decode("utf-8", errors="replace").splitlines()
        return "\n".join(ln for ln in lines if not ln.lstrip().startswith("#"))

    safe = [f for f in files if not UNSAFE.search(code_of(f))]
    print(f"not evaluated by the oracle (shell/filesystem calls): {len(files) - len(safe)}")
    files = safe
    oracle = oraclelib.run_oracle(ruby, files, work)
    stats: collections.Counter[str] = collections.Counter()
    field_ok: collections.Counter[str] = collections.Counter()
    field_all: collections.Counter[str] = collections.Counter()
    dep_field_ok: collections.Counter[str] = collections.Counter()
    dep_total = 0
    partial_got, partial_hit, partial_want, partial_found = [0], [0], [0], [0]
    reasons: collections.Counter[str] = collections.Counter()
    wrong: list[tuple[str, str]] = []
    for f in files:
        text = f.read_bytes().decode("utf-8", errors="replace")
        o = oracle[str(f.resolve())]
        try:
            g = oraclelib.reader_result(text)
        except Exception as e:  # a crash is a bug, count it as wrong
            wrong.append((f.name, f"crash {e!r}"))
            stats["crash"] += 1
            continue
        stats["files"] += 1
        stats["oracle ok" if o["ok"] else "oracle error"] += 1
        kinds = {d.kind for d in g.diagnostics}
        if not g.diagnostics:
            stats["reader static"] += 1
            if not o["ok"]:
                stats["WRONG: static but oracle error"] += 1
                wrong.append((f.name, "static but oracle error: " + o["error"][:100]))
                continue
            stats["static and oracle ok"] += 1
            bad = oraclelib.mismatches(g, o)
            for fld in oraclelib.FILE_FIELDS:
                field_all[fld] += 1
                field_ok[fld] += fld not in bad
            field_all["dependency-list"] += 1
            field_ok["dependency-list"] += "dependency-list" not in bad
            if "dependency-list" not in bad:
                dep_total += len(g.dependencies)
                gdeps = [oraclelib.dep_dict(d) for d in g.dependencies]
                for got, want in zip(gdeps, o["dependencies"]):
                    for fld in oraclelib.DEP_FIELDS:
                        dep_field_ok[fld] += got[fld] == want[fld]
                for fld in oraclelib.DEP_FIELDS:
                    field_all[f"dep.{fld}"] += 1
                    field_ok[f"dep.{fld}"] += f"dep.{fld}" not in bad
            if bad:
                stats["static file with a mismatch"] += 1
                wrong.append((f.name, "mismatch " + ",".join(bad)))
        else:
            for d in g.diagnostics:
                reasons[classify_reason(d.message) if d.kind == "unsupported" else "invalid: Bundler rejects"] += 1
            if "invalid" in kinds:
                stats["reader invalid"] += 1
                if o["ok"]:
                    stats["WRONG: invalid but oracle ok"] += 1
                    wrong.append((f.name, "invalid but oracle ok: " + "; ".join(d.message for d in g.diagnostics)[:100]))
            else:
                stats["reader dynamic"] += 1
            if o["ok"] and "invalid" not in kinds:
                stats["dynamic but oracle evaluates it"] += 1
                want = {json.dumps(d, sort_keys=True) for d in o["dependencies"]}
                mine = [json.dumps(oraclelib.dep_dict(d), sort_keys=True) for d in g.dependencies]
                partial_got[0] += len(mine)
                partial_hit[0] += sum(x in want for x in mine)
                partial_want[0] += len(want)
                partial_found[0] += len(want & set(mine))
                if o.get("env_access"):
                    stats["  of which read ENV"] += 1
            elif not o["ok"]:
                stats["dynamic/invalid and oracle also errors"] += 1
    for k in ("WRONG: static but oracle error", "WRONG: invalid but oracle ok",
              "static file with a mismatch", "crash"):
        stats.setdefault(k, 0)
    print(f"files: {stats['files']}")
    for k in sorted(stats):
        if k != "files":
            print(f"  {k}: {stats[k]}")
    print("agreement on static files that the oracle also evaluates (files):")
    for k in sorted(field_all):
        print(f"  {k}: {field_ok[k]}/{field_all[k]}")
    print(f"dependencies compared: {dep_total}")
    print("dependencies with an identical field:")
    for k in oraclelib.DEP_FIELDS:
        print(f"  {k}: {dep_field_ok[k]}/{dep_total}")
    print(
        "lenient mode on dynamic files that the oracle evaluates: "
        f"{partial_hit[0]}/{partial_got[0]} returned dependencies are exact oracle dependencies; "
        f"{partial_found[0]}/{partial_want[0]} oracle dependencies are returned"
    )
    print("diagnostic buckets (per statement):")
    for k, n in reasons.most_common():
        print(f"  {n:5d}  {k}")
    if wrong:
        print(f"WRONG or crashing files: {len(wrong)}")
        for name, why in wrong[:show]:
            print(f"  {name}: {why}")
    return {"stats": dict(stats), "wrong": wrong}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--generated", type=int, default=0, help="number of generated Gemfiles")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--corpus", type=Path, help="directory of fetched real Gemfiles")
    ap.add_argument("--show", type=int, default=15)
    ap.add_argument("--work", type=Path, default=None)
    args = ap.parse_args()
    work = args.work or Path(tempfile.mkdtemp(prefix="gemfile-diff-"))
    files: list[Path] = []
    if args.generated:
        gdir = work / "generated"
        gdir.mkdir(parents=True, exist_ok=True)
        for i, text in enumerate(gemgen.generate(args.seed, args.generated)):
            p = gdir / f"g{i:05d}.Gemfile"
            p.write_bytes(text.encode())
            files.append(p)
    if args.corpus:
        files += sorted(args.corpus.glob("*.Gemfile"))
    if not files:
        ap.error("give --generated N and/or --corpus DIR")
    res = run(files, work / "oracle", args.show)
    (work / "result.json").write_text(json.dumps(res, default=str))
    print(f"work dir: {work}")


if __name__ == "__main__":
    main()
