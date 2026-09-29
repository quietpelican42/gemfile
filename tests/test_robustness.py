"""The reader must never crash or hang on damaged input."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Literal

import gemgen

import gemfile

FIXTURES = Path(__file__).parent / "fixtures"
SNIPPETS = ["do", "end", "{", "}", "'", '"', "#{", "(", ")", "[", "]", ",", ":", "=>", "\\", "%w[", "<<~X",
            "if ", "\n", "|", "->", "/", "?", "gem ", "group ", "\x00", "é"]


def mutate(rng: random.Random, text: str) -> str:
    for _ in range(rng.randint(1, 6)):
        pos = rng.randint(0, len(text))
        op = rng.random()
        if op < 0.4:
            text = text[:pos] + rng.choice(SNIPPETS) + text[pos:]
        elif op < 0.7:
            text = text[:pos] + text[pos + rng.randint(1, 8):]
        else:
            text = text[: rng.randint(0, len(text))]
    return text


def test_mutated_files_never_raise_in_lenient_mode() -> None:
    rng = random.Random(4242)
    seeds = [p.read_bytes().decode() for p in sorted(FIXTURES.glob("*.Gemfile"))]
    seeds += gemgen.generate(99, 150)
    for text in seeds:
        for _ in range(12):
            broken = mutate(rng, text)
            modes: tuple[Literal["1.17", "2"], ...] = ("1.17", "2")
            for mode in modes:
                result = gemfile.parse(broken, strict=False, bundler=mode)
                assert all(d.line >= 1 for d in result.diagnostics)


def test_every_prefix_of_a_file_is_handled() -> None:
    text = (FIXTURES / "rails_app.Gemfile").read_text()
    for n in range(0, len(text), 7):
        gemfile.parse(text[:n], strict=False)


def test_strict_never_returns_a_result_with_diagnostics() -> None:
    rng = random.Random(7)
    for text in gemgen.generate(5, 200):
        broken = mutate(rng, text)
        try:
            result = gemfile.parse(broken)
        except gemfile.GemfileError as e:
            assert e.diagnostics
        else:
            assert result.diagnostics == ()
