"""Compare gemfileparser2 and this reader with Bundler's DSL on the fetched real-world corpus.

    python scripts/fetch_corpus.py
    <python with gemfileparser2==0.9.4 installed> bench/compare_incumbent.py --corpus .corpus

Run it from a scratch virtualenv that has gemfileparser2 (it is not a dependency
of this package). The reader is imported from ../src.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))

import oraclelib  # noqa: E402
from differential import UNSAFE  # noqa: E402


def norm_req(reqs: list[str]) -> list[str]:
    return sorted(x.replace(" ", "") for x in reqs if x.strip())


def measure_gemfileparser2(files: list[Path], oracle: dict[str, Any]) -> dict[str, int]:
    from gemfileparser2 import GemfileParser  # type: ignore[import-not-found]

    m = dict(files=0, crash=0, exact_names=0, deps=0, name=0, name_req=0, name_req_group=0,
             phantom_deps=0, files_with_phantoms=0)
    for f in files:
        o = oracle[str(f.resolve())]
        if not o["ok"]:
            continue
        m["files"] += 1
        try:
            res = GemfileParser(str(f), "x").parse()
        except Exception:
            m["crash"] += 1
            continue
        got: dict[str, list[tuple[str, Any]]] = {}
        for grp, lst in res.items():
            for d in lst:
                got.setdefault(d.name, []).append((grp, d))
        exp = o["dependencies"]
        exp_names = {d["name"] for d in exp}
        phantoms = [n for n in got if n not in exp_names]
        m["phantom_deps"] += len(phantoms)
        m["files_with_phantoms"] += bool(phantoms)
        if sorted(d["name"] for d in exp) == sorted(got):
            m["exact_names"] += 1
        for d in exp:
            m["deps"] += 1
            g = got.get(d["name"])
            if not g:
                continue
            m["name"] += 1
            _, gd = g[0]
            req = gd.requirement if isinstance(gd.requirement, list) else (gd.requirement or "").split(",")
            want = [r for r in d["requirements"] if r != ">= 0"]
            ok_req = norm_req(req) == norm_req(want)
            m["name_req"] += ok_req
            eg = set(d["groups"])
            gg = {grp for grp, _ in g}
            ok_grp = eg == gg or (eg == {"default"} and gg == {"runtime"})
            m["name_req_group"] += ok_req and ok_grp
    return m


def measure_reader(files: list[Path], oracle: dict[str, Any]) -> dict[str, int]:
    m = dict(files=0, static=0, static_exact=0, static_wrong=0, declined=0)
    for f in files:
        o = oracle[str(f.resolve())]
        if not o["ok"]:
            continue
        m["files"] += 1
        g = oraclelib.reader_result(f.read_bytes().decode("utf-8", errors="replace"))
        if g.diagnostics:
            m["declined"] += 1
            continue
        m["static"] += 1
        if oraclelib.mismatches(g, o):
            m["static_wrong"] += 1
        else:
            m["static_exact"] += 1
    return m


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", type=Path, default=ROOT / ".corpus")
    args = ap.parse_args()
    ruby, why = oraclelib.find_oracle()
    if ruby is None:
        sys.exit(f"cannot run the oracle: {why}")
    files = []
    for f in sorted(args.corpus.glob("*.Gemfile")):
        code = "\n".join(ln for ln in f.read_bytes().decode("utf-8", errors="replace").splitlines()
                         if not ln.lstrip().startswith("#"))
        if not UNSAFE.search(code):
            files.append(f)
    with tempfile.TemporaryDirectory(prefix="gemfile-bench-") as tmp:
        oracle = oraclelib.run_oracle(ruby, files, Path(tmp))
    import importlib.metadata as md

    print(f"gemfileparser2 {md.version('gemfileparser2')}")
    static = [
        f for f in files
        if oracle[str(f.resolve())]["ok"]
        and not oraclelib.reader_result(f.read_bytes().decode("utf-8", errors="replace")).diagnostics
    ]
    print("gemfileparser2, all oracle-evaluable files:", measure_gemfileparser2(files, oracle))
    print("gemfileparser2, files the reader calls static:", measure_gemfileparser2(static, oracle))
    print("gemfile:", measure_reader(files, oracle))


if __name__ == "__main__":
    main()
