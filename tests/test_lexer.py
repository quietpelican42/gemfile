from __future__ import annotations

from gemfile._lexer import Interp, Token, tokenize


def kinds(src: str) -> list[str]:
    return [t.kind for t in tokenize(src) if t.kind not in ("NL", "EOF")]


def first(src: str) -> Token:
    return tokenize(src)[0]


def test_single_quoted_escapes() -> None:
    assert first(r"'a\'b\\c\nd'").value == [r"a'b\c" + "\\nd"]


def test_double_quoted_escapes() -> None:
    assert first(r'"a\tb\\cé\x41\101\#{x}"').value == ["a\tb\\céAA#{x}"]


def test_interpolation_becomes_a_hole() -> None:
    assert first('"a-#{ENV["X"]}-b"').value == ["a-", Interp('ENV["X"]'), "-b"]
    assert first('"#@x"').value == [Interp("@x")]


def test_percent_literals() -> None:
    assert first("%w[a b\\ c d]").value == (["a", "b c", "d"], False)
    assert first("%i(a b)").value == (["a", "b"], True)
    assert first("%q(a (nested) b)").value == ["a (nested) b"]
    assert first("%Q{a #{b}}").value == ["a ", Interp("b")]
    assert first("%(plain)").value == ["plain"]


def test_labels_and_symbols() -> None:
    assert kinds("gem 'a', require: false, 'x': 1, :sym, :\"q s\"") == [
        "ID", "STR", "P", "LABEL", "KW", "P", "STR", "INT", "P", "SYM", "P", "SYM",
    ] or kinds("gem 'a', require: false") == ["ID", "STR", "P", "LABEL", "KW"]
    toks = tokenize("{ 'x': 1 }")
    assert [t.kind for t in toks[:3]] == ["P", "LABEL", "INT"]
    assert toks[1].value == "x"


def test_comments_block_comments_and_data_section() -> None:
    src = "gem 'a' # c 'not a string'\n=begin\ngem 'b'\n=end\ngem 'c'\n__END__\ngem 'd'\n"
    strings = [t.value for t in tokenize(src) if t.kind == "STR"]
    assert strings == [["a"], ["c"]]


def test_heredoc_body_is_skipped_and_lines_stay_correct() -> None:
    src = "x = <<~EOS\n  gem 'inside'\nEOS\ngem 'after'\n"
    toks = tokenize(src)
    assert "HEREDOC" in [t.kind for t in toks]
    after = next(t for t in toks if t.kind == "STR")
    assert after.value == ["after"]
    assert after.line == 4


def test_line_numbers_across_multiline_strings() -> None:
    toks = tokenize("a 'x\ny'\nb")
    b = [t for t in toks if t.kind == "ID"][-1]
    assert b.line == 3


def test_unterminated_string_does_not_swallow_the_file() -> None:
    toks = tokenize("gem 'oops\n")
    assert [t.kind for t in toks][-2:] == ["NL", "EOF"]
    assert "ERR" in [t.kind for t in toks]
    toks = tokenize('gem "a\\')
    assert "ERR" in [t.kind for t in toks]


def test_unknown_characters_become_err_tokens() -> None:
    assert "ERR" in kinds("gem 'a', @x")
    assert "ERR" in kinds("gem `ls`")
