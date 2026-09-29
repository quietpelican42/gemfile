"""Fetch the real-world Gemfile corpus into .corpus/ (gitignored).

    python scripts/fetch_corpus.py                 # download tests/corpus.tsv, verify sha256
    python scripts/fetch_corpus.py --resolve LIST  # rebuild the manifest from a list of owner/repo

The manifest pins every file to a commit SHA and records the sha256 of the bytes
that were measured. Third-party Gemfiles are never committed to this repository.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "tests" / "corpus.tsv"
CORPUS = ROOT / ".corpus"


def raw_url(repo: str, sha: str) -> str:
    return f"https://raw.githubusercontent.com/{repo}/{sha}/Gemfile"


def fetch(url: str) -> bytes | None:
    for _ in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                data: bytes = resp.read()
                return data
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
        except (urllib.error.URLError, TimeoutError):
            continue
    return None


def head_sha(repo: str) -> str | None:
    proc = subprocess.run(
        ["gh", "api", f"repos/{repo}/commits/HEAD", "-q", ".sha"],
        capture_output=True, text=True, check=False, stdin=subprocess.DEVNULL,
    )
    sha = proc.stdout.strip()
    return sha if proc.returncode == 0 and len(sha) == 40 else None


def resolve_one(repo: str) -> tuple[str, str, str] | None:
    sha = head_sha(repo)
    if sha is None:
        return None
    data = fetch(raw_url(repo, sha))
    if data is None:
        return None
    return repo, sha, hashlib.sha256(data).hexdigest()


def resolve(list_path: Path) -> None:
    repos: list[str] = []
    seen: set[str] = set()
    for ln in list_path.read_text().splitlines():
        name = ln.strip()
        if name and name.lower() not in seen:  # GitHub names are case-insensitive
            seen.add(name.lower())
            repos.append(name)
    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = [r for r in pool.map(resolve_one, repos) if r]
    rows.sort()
    MANIFEST.write_text("".join(f"{a}\t{b}\t{c}\n" for a, b, c in rows))
    print(f"{len(rows)} of {len(repos)} repositories have a root Gemfile; wrote {MANIFEST.name}")


def download_one(row: tuple[str, str, str]) -> str:
    repo, sha, digest = row
    dest = CORPUS / (repo.replace("/", "__").lower() + ".Gemfile")
    if dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest() == digest:
        return "cached"
    data = fetch(raw_url(repo, sha))
    if data is None:
        return "missing"
    if hashlib.sha256(data).hexdigest() != digest:
        return "hash-mismatch"
    dest.write_bytes(data)
    return "ok"


def download() -> None:
    rows: list[tuple[str, str, str]] = []
    for ln in MANIFEST.read_text().splitlines():
        if ln.strip():
            repo, sha, digest = ln.split("\t")
            rows.append((repo, sha, digest))
    CORPUS.mkdir(exist_ok=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(download_one, rows))
    counts = {k: results.count(k) for k in sorted(set(results))}
    print(f"corpus: {counts}")
    if any(k in counts for k in ("missing", "hash-mismatch")):
        sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--resolve", type=Path, help="file with one owner/repo per line")
    args = ap.parse_args()
    if args.resolve:
        resolve(args.resolve)
    else:
        download()


if __name__ == "__main__":
    main()
