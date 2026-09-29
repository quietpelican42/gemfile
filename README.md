# gemfile

Reads a Ruby `Gemfile` without running Ruby and returns what Bundler's DSL would produce: each dependency's name, requirement, groups, platforms, source and `require:` setting.

```python
import gemfile

gf = gemfile.parse("""
source 'https://rubygems.org'
gem 'rails', '~> 7.0'
gem 'foo', github: 'a/foo', ref: 'abc123'
group :development, :test do
  gem 'rspec', require: false
end
""")
for d in gf.dependencies:
    print(d.name, d.requirement, d.groups, d.source, d.autorequire)
```

```
rails ~> 7.0 ('default',) None None
foo >= 0 ('default',) GitSource(uri='https://github.com/a/foo.git', branch=None, tag=None, ref='abc123', submodules=None, glob=None) None
rspec >= 0 ('development', 'test') None ()
```

Anything that depends on runtime state (`ENV`, `File`, `if`, interpolation, variables, `eval_gemfile`) is never guessed. Strict mode (the default) raises `GemfileError` with the line number. Lenient mode skips that statement and records it in `Gemfile.diagnostics`.

## Why

A `Gemfile` is Ruby, and Bundler's own reader executes it. Tools written in other languages have three options: run Ruby, parse `Gemfile.lock` (which needs a resolved project), or read the Gemfile with regular expressions. In earlier measurements gemfileparser2 treated keyword arguments as gems and did not split `group :a, :b do`, and it does not implement Bundler's option rules (`github:` expansion, `platform` versus `platforms`, block-scoped sources, duplicate handling).

This package covers the static subset of the DSL with Bundler's semantics and says so when a file leaves that subset.

Incumbents checked: gemfileparser2 0.9.4 (Python), gemfileparser 0.8.0 (Python, same lineage, not measured), `@faissaloux/gemfile` (Node, measured in earlier research only). gemfileparser2 was re-measured for this table.

Measured: `python bench/compare_incumbent.py --corpus .corpus` (Ruby 2.6.10, Bundler 1.17.2 as oracle; 392 real Gemfiles that Bundler evaluated without error, 5,155 dependencies; repeated twice, identical):

```
gemfileparser2 0.9.4
gemfileparser2, all oracle-evaluable files: {'files': 392, 'crash': 0, 'exact_names': 259, 'deps': 5155, 'name': 4938, 'name_req': 4692, 'name_req_group': 4134, 'phantom_deps': 190, 'files_with_phantoms': 132}
gemfileparser2, files the reader calls static: {'files': 238, 'crash': 0, 'exact_names': 140, 'deps': 3669, 'name': 3502, 'name_req': 3305, 'name_req_group': 2863, 'phantom_deps': 107, 'files_with_phantoms': 97}
gemfile: {'files': 392, 'static': 238, 'static_exact': 238, 'static_wrong': 0, 'declined': 154}
```

| | files with exactly the right dependency names | dependencies with name, requirement and group right | phantom dependencies |
|---|---|---|---|
| gemfileparser2, 392 files | 259 (66.1%) | 4,134 of 5,155 (80.2%) | 190 in 132 files |
| gemfileparser2, the 238 files `gemfile` calls static | 140 (58.8%) | 2,863 of 3,669 (78.0%) | 107 in 97 files |
| gemfile, the same 238 files | 238 (100%) | 3,669 of 3,669 (100%) | 0 |
| gemfile, the other 154 files | declined with a diagnostic | | |

The comparison is not symmetric: gemfileparser2 answers for every file and `gemfile` declines the files it cannot evaluate statically. gemfileparser2 is also scored against what Bundler produced on the machine that ran the oracle, so a file with `if RUBY_VERSION` counts as a miss for it.

## Installation

```sh
pip install gemfile
```

Python 3.11 or newer. No runtime dependencies.

## Usage

### Read a file

```python
gf = gemfile.parse_file("Gemfile")          # strict: raises GemfileError on anything dynamic
gf = gemfile.parse_file("Gemfile", strict=False)
for d in gf.diagnostics:
    print(d)    # unsupported construct at line 12: ENV access
```

### Tell whether the answer is complete

```python
gf = gemfile.parse(text, strict=False)
if gf.is_static:
    ...   # nothing was skipped; the result equals what Bundler builds
```

### Choose the Bundler flavor for `github:`

```python
gemfile.parse("gem 'a', github: 'x/y'\n", bundler="1.17").dependencies[0].source.uri
# 'git://github.com/x/y.git'
gemfile.parse("gem 'a', github: 'x/y'\n").dependencies[0].source.uri
# 'https://github.com/x/y.git'
```

### Custom git sources

```python
gf = gemfile.parse('''
git_source(:gitlab) do |repo|
  repo = "#{repo}/#{repo}" unless repo.include?("/")
  "https://gitlab.com/#{repo}.git"
end
gem 'a', gitlab: 'acme'
''')
gf.dependencies[0].source.uri   # 'https://gitlab.com/acme/acme.git'
```

Only two `git_source` block shapes are read: a single interpolated string, optionally preceded by the `x = "..." unless x.include?("...")` idiom. Any other block is reported as unsupported.

### Command line

```sh
gemfile path/to/Gemfile        # JSON on stdout, diagnostics on stderr
```

## Reference

### `gemfile.parse(text, *, strict=True, bundler="2") -> Gemfile`

### `gemfile.parse_file(path, *, strict=True, bundler="2") -> Gemfile`

| Name | Type | Default | Description |
|---|---|---|---|
| `strict` | `bool` | `True` | Raise `GemfileError` if any diagnostic exists. When `False`, skip the statement and record it. |
| `bundler` | `"1.17"` or `"2"` | `"2"` | `"1.17"` reproduces the oracle: `github:` gives `git://`, unknown platform names and options are invalid. `"2"` gives `https://` and declines what it cannot judge (see Limitations). |

`parse_file` reads UTF-8 and raises `UnicodeDecodeError` otherwise.

### `Gemfile`

| Field | Type | Description |
|---|---|---|
| `sources` | `tuple[str, ...]` | Top-level `source` calls without a block, normalized with a trailing slash, in order, without duplicates. |
| `ruby` | `RubyDirective \| None` | The `ruby` directive (last one wins). |
| `gemspecs` | `tuple[Gemspec, ...]` | `gemspec` calls. Reported, never evaluated. |
| `plugins` | `tuple[str, ...]` | First argument of each `plugin` call. Not evaluated. |
| `optional_groups` | `tuple[str, ...]` | Groups declared with `optional: true`. |
| `dependencies` | `tuple[Dependency, ...]` | One entry per `gem` call, in file order, after Bundler's duplicate handling. |
| `diagnostics` | `tuple[Diagnostic, ...]` | Skipped statements (lenient mode). |
| `is_static` | `bool` | `True` when `diagnostics` is empty. |
| `to_dict()` | `dict` | JSON-ready form. |

### `Dependency`

| Field | Type | Description |
|---|---|---|
| `name` | `str` | Gem name. |
| `requirements` | `tuple[str, ...]` | Normalized requirements in RubyGems' order, for example `('>= 0.5', '< 2')`. `('>= 0',)` when none is given. |
| `requirement` | `str` | `", ".join(requirements)`, the string `Gem::Requirement#to_s` returns. |
| `groups` | `tuple[str, ...]` | Enclosing `group` blocks first, then `group:`/`groups:`. `('default',)` when there are none. |
| `platforms` | `tuple[str, ...]` | Enclosing `platforms` blocks first, then `platform:`/`platforms:`. |
| `source` | `RubygemsSource \| GitSource \| PathSource \| None` | Explicit `source:`, `git:`, `path:`, shorthand, or the enclosing block's source. |
| `autorequire` | `tuple[str \| bool, ...] \| None` | `None` when `require:` is absent, `()` for `require: false`. |
| `type` | `str` | `"runtime"` or `"development"`. |
| `env` | `str \| None` | Name from an enclosing `env` block. |
| `install_if` | `bool` | Result of literal `install_if` conditions. |
| `force_ruby_platform` | `bool \| None` | Only accepted with `bundler="2"`. |
| `line` | `int` | Line of the `gem` call. |

Sources: `RubygemsSource(remotes)`, `GitSource(uri, branch, tag, ref, submodules, glob)` and `PathSource(path, glob)`. Options are reported as written; `None` means absent. `github:`, `gist:`, `bitbucket:` and custom `git_source` names are expanded into `GitSource.uri`.

### Diagnostics

| `kind` | Meaning |
|---|---|
| `unsupported` | The statement is outside the supported subset, or is inside it but its value cannot be known statically. |
| `invalid` | Bundler itself raises here (bad option, invalid platform in 1.17 mode, malformed requirement, conflicting duplicate, missing block). |

`str(diagnostic)` gives `unsupported construct at line N: ...` or `invalid Gemfile at line N: ...`. `GemfileError.diagnostics` holds all of them.

### Command line

```
gemfile [--bundler {1.17,2}] FILE
```

Prints the `Gemfile` as JSON. Always lenient.

| Exit code | Meaning |
|---|---|
| 0 | Clean, no diagnostics. |
| 1 | JSON printed; one or more diagnostics on stderr. |
| 2 | The file could not be read or decoded. |

## How it works

1. A tokenizer reads the Ruby subset: single and double quoted strings (with escapes), `%q %Q %w %i %()` literals, symbols, labels, numbers, comments, `=begin` blocks, `__END__`. It never raises. Interpolation, heredocs, regular expressions and unknown characters become tokens that the parser rejects.
2. A parser accepts method calls (with or without parentheses), literal arguments, hashes in both styles, and `do`/`{}` blocks for the DSL methods. On an unsupported statement it records a diagnostic and resynchronizes at the end of that statement, including its block.
3. An evaluator mirrors `Bundler::Dsl` 1.17: option normalization (symbol keys win over string keys), the `group`/`groups` and `platform`/`platforms` precedence rules, git-source shorthand resolution, the source stack, and the duplicate-gem checks. Requirements are normalized as RubyGems 3.0 does, including sorting by version and then operator.
4. Any statement the evaluator cannot judge is skipped and reported. Any error Bundler would raise is reported as `invalid`, only where the check is certain.

### How it was checked

The oracle is `Bundler::Dsl#eval_gemfile` from Bundler 1.17.2 on Ruby 2.6.10 (`scripts/oracle.rb`), with `gemspec` stubbed. It emits each dependency's name, requirement, groups, platforms, source and autorequire, plus the file's sources, `ruby` directive and optional groups.

Measured: `python scripts/differential.py --generated 10000 --seed 11`. The generator (`tests/gemgen.py`) mixes every supported construct and injects invalid and dynamic statements into about 8% and 10% of files.

```
files: 10000
  WRONG: invalid but oracle ok: 0
  WRONG: static but oracle error: 0
  crash: 0
  reader static: 7923
  reader invalid: 1065
  reader dynamic: 1012
  static and oracle ok: 7923
  static file with a mismatch: 0
dependencies compared: 83905
  name, requirement, requirements, groups, platforms, source, autorequire, type, env, install_if: each 83905/83905
  sources, ruby, optional_groups, dependency-list (per file): each 7923/7923
```

Measured: `python scripts/differential.py --corpus .corpus` on 459 real Gemfiles from 459 GitHub repositories, each pinned to a commit SHA with a recorded sha256 (`tests/corpus.tsv`; fetched by `python scripts/fetch_corpus.py`, never committed). Six files that shell out or write files were not passed to the oracle.

```
files: 453
  reader static: 238        reader dynamic: 211        reader invalid: 4
  oracle ok: 392            oracle error: 61
  static and oracle ok: 238
  static file with a mismatch: 0
  WRONG: static but oracle error: 0
  WRONG: invalid but oracle ok: 0
dependencies compared: 3669
  every field: 3669/3669
```

Across all 459 real files (including the six not run through the oracle) the reader returned a complete answer for 239 files in `bundler="1.17"` mode and 242 in the default mode, and declined the rest.

The diagnostics on the 211 dynamic real files break down as follows (statements, not files; one file can have several): 96 `eval_gemfile`, 93 `File`/`Dir`/`Gem`/constant access, 81 lambdas (mostly `install_if -> { ... }`), 59 `if`/`unless`/`case` blocks, 56 local-variable assignments, 17 `if`/`unless` modifiers, 16 `ENV` reads. Of the 154 dynamic files that Bundler evaluated here, 26 read `ENV` directly.

The 4 real files (of the 453 run through the oracle) flagged `invalid` use `platforms: :windows` or the `force_ruby_platform:` gem option. Bundler 1.17.2 rejects both and newer Bundler accepts them, so they are `invalid` only in `bundler="1.17"` mode (in the default mode they are read as valid).

Lenient mode on dynamic files: on the 154 real dynamic files that Bundler evaluated, 1,195 of 1,195 dependencies the reader returned are exactly Bundler's, and 1,194 of Bundler's 1,485 dependencies were returned (the rest sit inside skipped statements).

Residuals, all on the declined side:

- 192 statements in the 10,000 generated files (and none in the real corpus) declined because three or more requirements compare equal but are spelled differently (for example `'5', '5.0', '5.0.0'`). RubyGems' sort leaves their order to the platform's `qsort`.
- Files where Bundler itself raised on the machine that ran the oracle (61 real files, most with "No such file or directory" for a file the Gemfile reads, such as a Pluginfile or `.ruby-version`) are compared only in the sense that the reader must not answer them as static. It never did.

Tests in the repository: `pytest` runs the fixtures (with oracle-captured expected output in `tests/fixtures/*.expected.json`), 800 generated files, 373 adversarial snippets (`tests/adversarial.py`), and the real corpus when it has been fetched. Tests that need Ruby or the corpus skip with a message that names what is missing.

## Limitations

- Only the static subset is read. `ENV`, `File`, `Dir`, `Gem::Version`, local variables, constants, `if`/`unless`/`case`/`while`, modifiers, `def`, heredocs, regular expressions, string interpolation (outside the two `git_source` shapes), `eval_gemfile`, method chains, splats and lambdas (including `install_if -> { ... }`) are reported as unsupported.
- `gemspec` is reported, not evaluated. The gem's own dependency and its development dependencies are not in `dependencies`.
- `eval_gemfile` files are not read.
- `plugin` calls are listed, not run. `source ... type:` (plugin sources) is unsupported.
- The order of three or more requirements that compare equal but are spelled differently is not defined by RubyGems, so those statements are declined.
- Source URIs are checked against a conservative pattern. Anything outside it (IPv6 hosts, query strings with unusual characters, non-ASCII) is declined, not judged.
- Two gem servers that differ only in embedded credentials are declined when the same gem is listed with both, because Bundler's comparison then depends on `bundle config`.
- `path:` values starting with `~` or `//` are declined (they depend on the home directory or the filesystem).
- Bundler 1.17.2 is the only oracle that was run. The default `bundler="2"` mode differs from it in these ways, all taken from what I know of newer Bundler and none tested: `github:` expands to `https://`; platform names `windows` and `ruby_26` and later are accepted; the `force_ruby_platform` gem option is accepted; unknown platform names and unknown gem options are declined instead of being called invalid; the `gist:` and `bitbucket:` shorthands and `path` without a block are declined; the `source :rubygems` symbol form is declined. Other changes in newer Bundler (multiple-source handling, `ruby file:`, `bundle config` settings such as `github.https`, and anything added after 1.17) are not modeled.
- Evaluating a Gemfile with the oracle runs its Ruby code. Run `scripts/oracle.rb` only on files you trust.

## Compatibility

Run: Python 3.14.7 on macOS (arm64), with Ruby 2.6.10 and Bundler 1.17.2 (RubyGems 3.0.3) as the oracle. `pytest` and `mypy --strict` over `src`, `tests`, `scripts` and `bench` were run on 3.14.7 only.

Not run: Python 3.11, 3.12 and 3.13 (the CI workflow covers them), Linux, Windows, any Bundler other than 1.17.2, and the `bundler="2"` mode against a real Bundler 2.

## Development

```sh
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q
.venv/bin/python -m mypy --strict
python scripts/fetch_corpus.py                      # real corpus, needs network
python scripts/differential.py --generated 10000    # needs Ruby with Bundler 1.17.x
python scripts/differential.py --corpus .corpus
python scripts/capture_fixtures.py                  # regenerate fixture expectations from the oracle
```

`bench/compare_incumbent.py` needs `gemfileparser2==0.9.4` in a scratch virtual environment.

## License

MIT. See [LICENSE](LICENSE).
