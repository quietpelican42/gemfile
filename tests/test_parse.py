from __future__ import annotations

import json
from pathlib import Path

import pytest

import gemfile
from gemfile import Dependency, GemfileError, GitSource, PathSource, RubygemsSource


def deps(text: str, **kw: str) -> tuple[Dependency, ...]:
    return gemfile.parse(text, **kw).dependencies  # type: ignore[arg-type]


def test_readme_example() -> None:
    result = gemfile.parse(
        "source 'https://rubygems.org'\n"
        "gem 'rails', '~> 7.0'\n"
        "gem 'tzinfo-data', platforms: [:mingw, :mswin, :x64_mingw, :jruby]\n"
        "gem 'foo', github: 'a/foo', ref: 'abc123'\n"
        "group :development, :test do\n  gem 'rspec'\nend\n",
        bundler="1.17",
    )
    assert result.sources == ("https://rubygems.org/",)
    got = [(d.name, d.requirement, d.groups, d.platforms) for d in result.dependencies]
    assert got == [
        ("rails", "~> 7.0", ("default",), ()),
        ("tzinfo-data", ">= 0", ("default",), ("mingw", "mswin", "x64_mingw", "jruby")),
        ("foo", ">= 0", ("default",), ()),
        ("rspec", ">= 0", ("development", "test"), ()),
    ]
    assert result.dependencies[2].source == GitSource("git://github.com/a/foo.git", ref="abc123")
    assert [d.line for d in result.dependencies] == [2, 3, 4, 6]


def test_strict_is_the_default_and_raises_with_the_line() -> None:
    with pytest.raises(GemfileError) as info:
        gemfile.parse("gem 'a'\ngem 'b', ENV['V']\n")
    err = info.value
    assert len(err.diagnostics) == 1
    d = err.diagnostics[0]
    assert (d.line, d.kind, d.text) == (2, "unsupported", "gem 'b', ENV['V']")
    assert str(d) == "unsupported construct at line 2: ENV access"
    assert isinstance(err, ValueError)


def test_lenient_mode_skips_and_records() -> None:
    result = gemfile.parse("gem 'a'\ngem 'b' if ENV['X']\ngem 'c'\n", strict=False)
    assert [d.name for d in result.dependencies] == ["a", "c"]
    assert [(d.line, d.kind) for d in result.diagnostics] == [(2, "unsupported")]


def test_skipped_block_statements_do_not_hide_the_rest_of_the_block() -> None:
    text = "group :test do\n  gem 'a'\n  if ENV['X']\n    gem 'b'\n  end\n  gem 'c'\nend\ngem 'd'\n"
    result = gemfile.parse(text, strict=False)
    assert [(d.name, d.groups) for d in result.dependencies] == [
        ("a", ("test",)), ("c", ("test",)), ("d", ("default",)),
    ]
    assert [d.line for d in result.diagnostics] == [3]


def test_block_with_dynamic_arguments_is_skipped_whole() -> None:
    result = gemfile.parse("group ENV['G'].to_sym do\n  gem 'a'\nend\ngem 'b'\n", strict=False)
    assert [d.name for d in result.dependencies] == ["b"]
    assert len(result.diagnostics) == 1


def test_invalid_is_reported_as_invalid_not_unsupported() -> None:
    result = gemfile.parse("gem 'a', platforms: :nope\n", strict=False, bundler="1.17")
    assert [(d.kind, d.line) for d in result.diagnostics] == [("invalid", 1)]
    assert str(result.diagnostics[0]).startswith("invalid Gemfile at line 1: `nope` is not a valid")


def test_symbol_keys_win_over_string_keys() -> None:
    a = deps("gem 'a', 'require' => true, require: false\n")[0]
    b = deps("gem 'a', require: false, 'require' => true\n")[0]
    assert a.autorequire == b.autorequire == ()


def test_platform_option_is_preferred_over_platforms() -> None:
    d = deps("gem 'a', platforms: :jruby, platform: :mri\n")[0]
    assert d.platforms == ("mri",)


def test_group_option_is_appended_to_block_groups_and_groups_beats_group() -> None:
    d = deps("group :a do\n  gem 'x', group: :b, groups: [:c]\nend\n")[0]
    assert d.groups == ("a", "c")


def test_nested_blocks_restore_state() -> None:
    result = gemfile.parse(
        "source 'https://one.example/' do\n  gem 'a'\n  source 'https://two.example/' do\n"
        "    gem 'b'\n  end\n  gem 'c'\nend\ngem 'd'\n"
    )
    assert [(d.name, d.source) for d in result.dependencies] == [
        ("a", RubygemsSource(("https://one.example/",))),
        ("b", RubygemsSource(("https://two.example/",))),
        ("c", RubygemsSource(("https://one.example/",))),
        ("d", None),
    ]


def test_path_and_git_options() -> None:
    a, b, c = deps(
        "gem 'a', path: '../a', glob: '*.gemspec'\n"
        "gem 'b', git: 'https://x/b.git', branch: :dev, submodules: true\n"
        "gem 'c', git: 'https://x/c.git', path: '../c'\n"
    )
    assert a.source == PathSource("../a", "*.gemspec")
    assert b.source == GitSource("https://x/b.git", branch="dev", submodules=True)
    assert c.source == PathSource("../c")


def test_custom_git_source_template() -> None:
    d = deps(
        "git_source(:gl) do |repo|\n"
        "  repo = \"#{repo}/#{repo}\" unless repo.include?(\"/\")\n"
        "  \"https://gitlab.com/#{repo}.git\"\n"
        "end\n"
        "gem 'a', gl: 'solo'\ngem 'b', gl: 'org/b'\n"
    )
    assert [x.source for x in d] == [
        GitSource("https://gitlab.com/solo/solo.git"),
        GitSource("https://gitlab.com/org/b.git"),
    ]


def test_git_source_using_a_variable_it_cannot_resolve_is_declined() -> None:
    result = gemfile.parse(
        "git_source(:gl) { |repo| \"https://#{ENV['HOST']}/#{repo}.git\" }\ngem 'a', gl: 'x/y'\n",
        strict=False,
    )
    assert result.diagnostics[0].line == 1
    # the shorthand is not defined, so the use is also reported
    assert [d.line for d in result.diagnostics] == [1, 2]


def test_gemspec_is_reported_not_evaluated() -> None:
    result = gemfile.parse("gemspec path: 'sub', name: 'x', development_group: :dev\ngemspec\n")
    assert [(g.path, g.name, g.development_group, g.line) for g in result.gemspecs] == [
        ("sub", "x", "dev", 1), (".", None, "development", 2),
    ]
    assert result.dependencies == ()


def test_ruby_directive() -> None:
    r = gemfile.parse("ruby '2.5.1'\n").ruby
    assert r is not None
    assert (r.versions, r.engine, r.patchlevel, r.line) == (("2.5.1",), "ruby", None, 1)
    r2 = gemfile.parse("ruby '>= 2.3', engine: 'jruby', engine_version: '9.2', patchlevel: '3'\n").ruby
    assert r2 is not None
    assert (r2.versions, r2.engine, r2.engine_versions, r2.patchlevel) == ((">= 2.3",), "jruby", ("9.2",), "3")


def test_optional_groups_are_listed() -> None:
    result = gemfile.parse("group :docs, optional: true do\n  gem 'yard'\nend\n")
    assert result.optional_groups == ("docs",)


def test_top_level_sources_are_normalised_and_deduplicated() -> None:
    result = gemfile.parse("source 'https://rubygems.org'\nsource 'https://rubygems.org/'\n")
    assert result.sources == ("https://rubygems.org/",)


def test_mode_2_accepts_newer_platform_names_and_options() -> None:
    d = deps("gem 'a', platforms: %i[windows jruby], force_ruby_platform: true\n", bundler="2")[0]
    assert d.platforms == ("windows", "jruby")
    assert d.force_ruby_platform is True
    result = gemfile.parse("gem 'a', platforms: :windows\n", strict=False, bundler="1.17")
    assert [d.kind for d in result.diagnostics] == ["invalid"]


def test_mode_2_declines_what_it_cannot_judge() -> None:
    result = gemfile.parse("gem 'a', mystery: 1\ngem 'b', platforms: :nonesuch\n", strict=False)
    assert [d.kind for d in result.diagnostics] == ["unsupported", "unsupported"]


def test_unknown_bundler_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown bundler mode"):
        gemfile.parse("", bundler="3")  # type: ignore[arg-type]


def test_parse_file_and_encoding(tmp_path: Path) -> None:
    p = tmp_path / "Gemfile"
    p.write_bytes(b"\xef\xbb\xbfgem 'caf\xc3\xa9'\n")
    assert gemfile.parse_file(p).dependencies[0].name == "café"
    p.write_bytes(b"gem '\xff'\n")
    with pytest.raises(UnicodeDecodeError):
        gemfile.parse_file(p)


def test_result_is_json_serialisable() -> None:
    result = gemfile.parse("gem 'a', git: 'https://x/a.git'\nruby '3.0'\ngemspec\n")
    data = json.loads(json.dumps(result.to_dict()))
    assert data["dependencies"][0]["source"]["type"] == "git"
    assert data["ruby"]["versions"] == ["3.0"]


def test_dependencies_are_immutable() -> None:
    d = deps("gem 'a'\n")[0]
    with pytest.raises(AttributeError):
        d.name = "b"  # type: ignore[misc]


@pytest.mark.parametrize(
    "text",
    [
        "gem 'a' 'b'\n",           # adjacent literals concatenate: 'ab'
        "gem('a'\n)\n",
        "gem 'a', {\n  require: false,\n}\n",
        "gem 'a'; gem 'b'\n",
        "group :x do gem 'a' end\n",
        "group(:x) { gem 'a' }\n",
        "gem 'a',\\\n  '1.0'\n",
    ],
)
def test_layout_variants_parse(text: str) -> None:
    assert gemfile.parse(text).dependencies


def test_adjacent_string_literals_concatenate() -> None:
    assert deps("gem 'a' 'b'\n")[0].name == "ab"


@pytest.mark.parametrize(
    "text",
    [
        "gem 'a'\n  , '1.0'\n",       # a leading comma is a syntax error in Ruby
        "gem 'a' do\nend\n",           # gem does not take a block
        "gem 'a', 1.0\n",              # a number is not a requirement
        "gem 'a', *versions\n",
        "gem 'a', require: !x\n",
        "gem 'a', x ? 1 : 2\n",
        "gem 'a', '1' + '.0'\n",
        "gem 'a').foo\n",
        "gem 'a'.freeze\n",
        "x = 1\n",
        "puts 'hi'\n",
        "gem 'a' \\\n if true\n",
        "end\n",
        "gem 'a', [\n",
        "group :a do\n  gem 'b'\n",
        "gem 'a', 'unterminated\n",
        "gem \"#{x}\"\n",
        "gem 'a', <<~X\n  1\nX\n",
        "gem 'a', /re/\n",
        "gem 'a', ->{}\n",
        "gem 'a', @v\n",
        "gem 'a', :\"#{x}\"\n",
        "install_if -> { true } do\n  gem 'a'\nend\n",
    ],
)
def test_constructs_outside_the_subset_are_declined(text: str) -> None:
    with pytest.raises(GemfileError):
        gemfile.parse(text)


def test_pathological_nesting_is_a_diagnostic_not_a_crash() -> None:
    result = gemfile.parse("gem " + "[" * 5000 + "]" * 5000, strict=False)
    assert result.diagnostics
    result = gemfile.parse("group :a do\n" * 600 + "end\n" * 600, strict=False)
    assert result.diagnostics


def test_gist_and_bitbucket_shorthands_are_only_expanded_for_bundler_1_17() -> None:
    text = "gem 'a', gist: '123'\ngem 'b', bitbucket: 'u/r'\n"
    old = gemfile.parse(text, bundler="1.17")
    assert [d.source for d in old.dependencies] == [
        GitSource("https://gist.github.com/123.git"),
        GitSource("https://u@bitbucket.org/u/r.git"),
    ]
    new = gemfile.parse(text, strict=False, bundler="2")
    assert new.dependencies == ()
    assert [d.kind for d in new.diagnostics] == ["unsupported", "unsupported"]
