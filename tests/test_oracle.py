"""Differential tests against Bundler 1.17's own DSL. Skipped, loudly, when Ruby or Bundler is missing."""

from __future__ import annotations

from pathlib import Path

import adversarial
import gemgen
import oraclelib
import pytest

RUBY, WHY = oraclelib.find_oracle()
pytestmark = pytest.mark.skipif(
    RUBY is None, reason=f"SKIPPED, ORACLE NOT RUN: {WHY}"
)


def test_generated_gemfiles_agree_with_bundler(tmp_path: Path) -> None:
    assert RUBY is not None
    texts = gemgen.generate(2026, 800)
    files = []
    for i, text in enumerate(texts):
        p = tmp_path / f"g{i:04d}.Gemfile"
        p.write_bytes(text.encode())
        files.append(p)
    oracle = oraclelib.run_oracle(RUBY, files, tmp_path / "oracle")
    static = wrong = 0
    for p, text in zip(files, texts):
        o = oracle[str(p.resolve())]
        g = oraclelib.reader_result(text)
        kinds = {d.kind for d in g.diagnostics}
        if not g.diagnostics:
            static += 1
            assert o["ok"], f"{p.name}: reader is static but Bundler raised: {o['error']}"
            bad = oraclelib.mismatches(g, o)
            assert bad == [], f"{p.name}: fields differ: {bad}"
        elif "invalid" in kinds:
            assert not o["ok"], f"{p.name}: reader says invalid but Bundler accepts it"
    assert static > 500, "the generator or the reader has degenerated: too few static files"
    assert wrong == 0


def test_bundler_rejects_what_the_reader_calls_invalid(tmp_path: Path) -> None:
    assert RUBY is not None
    cases = {
        "platform": "gem 'a', platforms: :nope\n",
        "option": "gem 'a', bogus: 1\n",
        "symbol": "gem :a\n",
        "space": "gem 'a b'\n",
        "empty": "gem ''\n",
        "branch": "gem 'a', branch: 'x'\n",
        "req": "gem 'a', '~~ 1'\n",
        "dup": "gem 'a', '1'\ngem 'a', '2'\n",
        "dupsrc": "gem 'a'\ngem 'a', path: '../a'\n",
        "group": "group :a\n",
        "git": "git 'https://x/y.git'\n",
        "ruby": "ruby '2.5', engine: 'jruby'\n",
        "type": "gem 'a', type: :nope\n",
    }
    files = []
    for name, text in cases.items():
        p = tmp_path / f"{name}.Gemfile"
        p.write_text(text)
        files.append(p)
    oracle = oraclelib.run_oracle(RUBY, files, tmp_path / "oracle")
    for p in files:
        assert not oracle[str(p.resolve())]["ok"], p.name
        g = oraclelib.reader_result(p.read_text())
        assert [d.kind for d in g.diagnostics] == ["invalid"], p.name


def test_bundler_accepts_what_the_reader_calls_static(tmp_path: Path) -> None:
    assert RUBY is not None
    cases = {
        "sym_and_str_keys": "gem 'a', 'require' => true, require: false\n",
        "platform_wins": "gem 'a', platforms: :jruby, platform: :mri\n",
        "github_bare": "gem 'a', github: 'solo'\n",
        "bitbucket": "gem 'a', bitbucket: 'user/repo'\n",
        "path_beats_git": "gem 'a', git: 'https://x/y.git', path: '../y'\n",
        "dev_then_run": "gem 'a', type: :development\ngem 'a', '~> 2.0'\n",
        "same_twice": "gem 'a', '~> 1.0'\ngem 'a', '~> 1.0'\n",
        "optional": "group :a, :a, optional: true do\nend\n",
        "install_if_false": "gem 'a', install_if: false\n",
        "empty_require": "gem 'a', require: []\ngem 'b', require: nil\n",
    }
    files = []
    for name, text in cases.items():
        p = tmp_path / f"{name}.Gemfile"
        p.write_text(text)
        files.append(p)
    oracle = oraclelib.run_oracle(RUBY, files, tmp_path / "oracle")
    for p in files:
        o = oracle[str(p.resolve())]
        assert o["ok"], f"{p.name}: {o.get('error')}"
        g = oraclelib.reader_result(p.read_text())
        assert g.diagnostics == (), p.name
        assert oraclelib.mismatches(g, o) == [], p.name


def test_adversarial_snippets(tmp_path: Path) -> None:
    """Every tricky snippet: static means equal to Bundler, invalid means Bundler raises."""
    assert RUBY is not None
    files = []
    for i, text in enumerate(adversarial.CASES):
        p = tmp_path / f"c{i:04d}.Gemfile"
        p.write_bytes(text.encode() + b"\n")
        files.append(p)
    oracle = oraclelib.run_oracle(RUBY, files, tmp_path / "oracle")
    static = 0
    for p, text in zip(files, adversarial.CASES):
        o = oracle[str(p.resolve())]
        g = oraclelib.reader_result(text + "\n")
        kinds = {d.kind for d in g.diagnostics}
        if not g.diagnostics:
            static += 1
            assert o["ok"], f"{text!r}: reader is static but Bundler raised: {o['error']}"
            assert oraclelib.mismatches(g, o) == [], text
        elif "invalid" in kinds:
            assert not o["ok"], f"{text!r}: reader says invalid but Bundler accepts it"
    assert static > 150
