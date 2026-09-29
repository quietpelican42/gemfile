from __future__ import annotations

import json
from pathlib import Path

import pytest

from gemfile.cli import main


def test_prints_json_and_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = tmp_path / "Gemfile"
    p.write_text("gem 'a', '~> 1.0'\n")
    assert main([str(p)]) == 0
    out = capsys.readouterr()
    assert json.loads(out.out)["dependencies"][0]["requirement"] == "~> 1.0"
    assert out.err == ""


def test_exits_one_and_lists_diagnostics_on_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    p = tmp_path / "Gemfile"
    p.write_text("gem 'a'\ngem 'b' if ENV['X']\n")
    assert main([str(p)]) == 1
    out = capsys.readouterr()
    assert [d["name"] for d in json.loads(out.out)["dependencies"]] == ["a"]
    assert "unsupported construct at line 2" in out.err


def test_exits_two_when_unreadable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(tmp_path / "missing")]) == 2
    assert "cannot read" in capsys.readouterr().err


def test_bundler_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = tmp_path / "Gemfile"
    p.write_text("gem 'a', github: 'x/y'\n")
    assert main(["--bundler", "1.17", str(p)]) == 0
    assert "git://github.com/x/y.git" in capsys.readouterr().out
    assert main([str(p)]) == 0
    assert "https://github.com/x/y.git" in capsys.readouterr().out
