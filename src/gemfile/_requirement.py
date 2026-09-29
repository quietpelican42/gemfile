"""Gem::Version and Gem::Requirement normalisation, as RubyGems 3.0 does it."""

from __future__ import annotations

import re
from functools import cmp_to_key

_WS = r"[ \t\r\n\f\v]"
_VERSION_PATTERN = r"[0-9]+(?>\.[0-9a-zA-Z]+)*(-[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?"
_OPS = r"=|!=|>=|<=|>|<|~>"
_REQUIREMENT = re.compile(
    rf"\A{_WS}*({_OPS})?{_WS}*({_VERSION_PATTERN}){_WS}*\Z"
)
_SEGMENT = re.compile(r"[0-9]+|[a-z]+", re.IGNORECASE)


class BadRequirementError(ValueError):
    """The string is not a valid Gem::Requirement."""


def _segments(version: str) -> list[int | str]:
    return [int(s) if s.isdigit() else s for s in _SEGMENT.findall(version)]


def _compare_versions(a: str, b: str) -> int:
    """Gem::Version#<=> on normalised version strings."""
    if a == b:
        return 0
    ls, rs = _segments(a), _segments(b)
    if _canonical(ls) == _canonical(rs):
        return 0
    limit = max(len(ls), len(rs))
    for i in range(limit):
        lhs = ls[i] if i < len(ls) else 0
        rhs = rs[i] if i < len(rs) else 0
        if lhs == rhs:
            continue
        if isinstance(lhs, str) and isinstance(rhs, int):
            return -1
        if isinstance(lhs, int) and isinstance(rhs, str):
            return 1
        return -1 if lhs < rhs else 1  # type: ignore[operator]
    return 0


def _canonical(segs: list[int | str]) -> list[int | str]:
    start = next((i for i, s in enumerate(segs) if isinstance(s, str)), len(segs))
    parts = (segs[:start], segs[start:])
    out: list[int | str] = []
    for part in parts:
        trimmed = list(part)
        while trimmed and trimmed[-1] == 0:
            trimmed.pop()
        out.extend(trimmed)
    return out


def normalize_version(version: str) -> str:
    """Gem::Version.new(version).to_s for a string already known to be valid."""
    stripped = version.strip(" \t\r\n\f\v\0")
    return stripped.replace("-", ".pre.")


Requirement = tuple[str, str]


def parse_requirement(text: str) -> Requirement:
    """Gem::Requirement.parse: return (operator, normalised version)."""
    match = _REQUIREMENT.match(text)
    if match is None:
        raise BadRequirementError(f"Illformed requirement [{text!r}]")
    op = match.group(1)
    ver = match.group(2)
    if op == ">=" and ver == "0":
        return (">=", "0")
    return (op or "=", normalize_version(ver))


class AmbiguousOrder(Exception):
    """Sorting has ties between differently spelled requirements."""


def normalize_requirements(inputs: list[str]) -> list[Requirement]:
    """Gem::Requirement.new(*inputs).requirements, in RubyGems' sorted order."""
    unique: list[str] = []
    for item in inputs:
        if item not in unique:
            unique.append(item)
    if not unique:
        return [(">=", "0")]
    parsed = [parse_requirement(item) for item in unique]

    def cmp(l: Requirement, r: Requirement) -> int:
        c = _compare_versions(l[1], r[1])
        if c:
            return c
        return (l[0] > r[0]) - (l[0] < r[0])

    ordered = sorted(parsed, key=cmp_to_key(cmp))
    if len(ordered) > 2:
        for a, b in zip(ordered, ordered[1:]):
            if cmp(a, b) == 0 and a != b:
                raise AmbiguousOrder()
    return ordered


def format_requirements(reqs: list[Requirement]) -> tuple[str, ...]:
    return tuple(f"{op} {ver}" for op, ver in reqs)


def requirements_equal(a: list[Requirement], b: list[Requirement]) -> bool:
    """Gem::Requirement#==, including the stricter check for ~>."""
    if len(a) != len(b):
        return False
    for (aop, aver), (bop, bver) in zip(a, b):
        if aop != bop or _compare_versions(aver, bver) != 0:
            return False
    ta = [r for r in a if r[0] == "~>"]
    tb = [r for r in b if r[0] == "~>"]
    return ta == tb
