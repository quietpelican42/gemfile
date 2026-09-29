"""Real-world Gemfiles, fetched at test time from commit-pinned URLs (never committed)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import oraclelib
import pytest

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / ".corpus"
MANIFEST = Path(__file__).parent / "corpus.tsv"
FILES = sorted(CORPUS.glob("*.Gemfile"))

needs_corpus = pytest.mark.skipif(
    len(FILES) < 400,
    reason="SKIPPED, REAL CORPUS NOT FETCHED: run `python scripts/fetch_corpus.py` "
    "(downloads the Gemfiles pinned in tests/corpus.tsv into .corpus/)",
)
RUBY, WHY = oraclelib.find_oracle()


@needs_corpus
def test_corpus_matches_the_pinned_hashes() -> None:
    rows = [ln.split("\t") for ln in MANIFEST.read_text().splitlines() if ln]
    assert len(rows) == len(FILES)
    for repo, _sha, digest in rows:
        path = CORPUS / (repo.replace("/", "__").lower() + ".Gemfile")
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, repo


@needs_corpus
def test_reader_handles_every_real_file_without_crashing() -> None:
    static = 0
    for f in FILES:
        g = oraclelib.reader_result(f.read_bytes().decode("utf-8", errors="replace"))
        static += not g.diagnostics
    assert static > len(FILES) * 0.4


@needs_corpus
@pytest.mark.skipif(RUBY is None, reason=f"SKIPPED, ORACLE NOT RUN: {WHY}")
def test_static_real_files_equal_bundler(tmp_path: Path) -> None:
    assert RUBY is not None
    # Gemfiles are third-party Ruby that the oracle executes: skip the ones that shell out.
    candidates = []
    for f in FILES:
        text = f.read_bytes().decode("utf-8", errors="replace")
        code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
        if not any(w in code for w in ("system", "`", "exec", "spawn", "FileUtils", "popen", "File.write",
                                       "File.delete", "File.open", "rm_rf", "%x", "IO.")):
            candidates.append(f)
    oracle = oraclelib.run_oracle(RUBY, candidates, tmp_path)
    compared = 0
    for f in candidates:
        text = f.read_bytes().decode("utf-8", errors="replace")
        g = oraclelib.reader_result(text)
        o = oracle[str(f.resolve())]
        if g.diagnostics:
            assert not ({d.kind for d in g.diagnostics} == {"invalid"} and o["ok"]), f.name
            continue
        assert o["ok"], f"{f.name}: reader is static but Bundler raised: {o['error']}"
        assert oraclelib.mismatches(g, o) == [], f.name
        compared += 1
    assert compared > 150
