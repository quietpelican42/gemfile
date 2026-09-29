"""Tokenizer for the Ruby subset that Gemfiles use.

The lexer never raises. Anything it cannot read becomes an ``ERR`` token that
the parser turns into an ``unsupported`` diagnostic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

KEYWORDS = frozenset(
    "alias and begin BEGIN break case class def defined? do else elsif end END "
    "ensure false for if in module next nil not or redo rescue retry return self "
    "super then true undef unless until when while yield __FILE__ __LINE__ "
    "__method__ __dir__".split()
)
# Keywords that end a value, so a following "%" or "/" is an operator.
_VALUE_END_KW = frozenset(["end", "true", "false", "nil", "self", "__FILE__", "__LINE__"])


@dataclass(slots=True)
class Interp:
    """A ``#{...}`` (or ``#@x``) hole in a double-quoted string, as source text."""

    text: str


Part = str | Interp


@dataclass(slots=True)
class Token:
    kind: str
    value: object
    line: int
    spc: bool = False


_IDENT = re.compile(r"[A-Za-z_\u0080-\U0010ffff][A-Za-z0-9_\u0080-\U0010ffff]*")
_NUMBER = re.compile(
    r"0[xX][0-9a-fA-F_]+|0[bB][01_]+|\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d+)?"
)
_OPERATOR = re.compile(
    r"\*\*=|<=>|===|\.\.\.|\|\|=|&&=|<<=|>>=|\*\*|=>|==|!=|>=|<=|&&|\|\||<<|>>|"
    r"\+=|-=|\*=|/=|%=|\|=|&=|\^=|=~|!~|::|->|\.\.|&\.|[-+*/%=<>!&|^~?:,.()\[\]{}]"
)
_HEREDOC = re.compile(r"<<([~-]?)([\"'`]?)([A-Za-z_][A-Za-z0-9_]*)\2")
_CLOSERS = {"(": ")", "[": "]", "{": "}", "<": ">"}
_SIMPLE_ESCAPES = {
    "n": "\n", "t": "\t", "r": "\r", "0": "\0", "s": " ", "e": "\x1b",
    "a": "\a", "b": "\b", "f": "\f", "v": "\v",
}
_SPACE = " \t\r\f\v"


class _Lexer:
    def __init__(self, src: str) -> None:
        self.s = src.replace("\r\n", "\n")
        if self.s.startswith("﻿"):
            self.s = self.s[1:]
        self.i = 0
        self.line = 1
        self.tokens: list[Token] = []
        self.spc = False
        self.pending_heredocs: list[tuple[str, bool]] = []

    # -- helpers ---------------------------------------------------------
    def emit(self, kind: str, value: object, line: int | None = None) -> None:
        self.tokens.append(Token(kind, value, self.line if line is None else line, self.spc))
        self.spc = False

    def last(self) -> Token | None:
        return self.tokens[-1] if self.tokens else None

    def value_expected(self, next_char: str) -> bool:
        """Whether a `%`, `/` or `<<` here starts a literal rather than an operator."""
        p = self.last()
        if p is None or p.kind == "NL":
            return True
        if p.kind == "ID":
            return self.spc and next_char not in " \t\n=" and next_char != ""
        if p.kind in ("CONST", "STR", "SYM", "INT", "FLOAT", "WORDS", "REGEX", "HEREDOC"):
            return False
        if p.kind == "KW":
            return p.value not in _VALUE_END_KW
        if p.kind == "P":
            return p.value not in (")", "]", "}")
        return True

    # -- string bodies ---------------------------------------------------
    def skip_interp(self, k: int) -> int:
        """Index of the `}` closing a `#{` whose body starts at k, or -1."""
        s = self.s
        depth = 1
        n = len(s)
        while k < n:
            c = s[k]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return k
            elif c in "\"'`":
                k = self.skip_quoted(k)
                if k < 0:
                    return -1
                continue
            elif c == "\\":
                k += 1
            k += 1
        return -1

    def skip_quoted(self, k: int) -> int:
        """Index just past the quoted string starting at k, or -1."""
        s = self.s
        q = s[k]
        k += 1
        n = len(s)
        while k < n:
            c = s[k]
            if c == "\\":
                k += 2
                continue
            if c == q:
                return k + 1
            if q != "'" and c == "#" and k + 1 < n and s[k + 1] == "{":
                k = self.skip_interp(k + 2)
                if k < 0:
                    return -1
            k += 1
        return -1

    def read_single(self, k: int, close: str, opener: str | None) -> tuple[str, int] | None:
        """Body of a single-quoted style literal starting at k. Returns (text, index past close)."""
        s = self.s
        out: list[str] = []
        depth = 1
        n = len(s)
        while k < n:
            c = s[k]
            if c == "\\" and k + 1 < n and s[k + 1] in (close, "\\") + ((opener,) if opener else ()):
                out.append(s[k + 1])
                k += 2
                continue
            if opener and c == opener:
                depth += 1
            elif c == close:
                depth -= 1
                if depth == 0:
                    return "".join(out), k + 1
            out.append(c)
            k += 1
        return None

    def read_double(
        self, k: int, close: str, opener: str | None
    ) -> tuple[list[Part], int] | str:
        """Body of a double-quoted style literal. Returns (parts, index) or an error message."""
        s = self.s
        parts: list[Part] = []
        buf: list[str] = []
        depth = 1
        n = len(s)

        def flush() -> None:
            if buf:
                parts.append("".join(buf))
                buf.clear()

        while k < n:
            c = s[k]
            if c == "\\":
                if k + 1 >= n:
                    return "unterminated string"
                e = s[k + 1]
                if e in _SIMPLE_ESCAPES:
                    if e == "0" and k + 2 < n and s[k + 2] in "01234567":
                        return "octal escape sequence"
                    buf.append(_SIMPLE_ESCAPES[e])
                    k += 2
                elif e == "\n":
                    k += 2
                elif e in "1234567":
                    m = re.compile(r"[0-7]{1,3}").match(s, k + 1)
                    assert m is not None
                    buf.append(chr(int(m.group(), 8) & 0xFF))
                    k = m.end()
                elif e == "x":
                    m = re.compile(r"[0-9a-fA-F]{1,2}").match(s, k + 2)
                    if m is None:
                        return "invalid hex escape"
                    if int(m.group(), 16) > 0x7F:
                        return "non-ASCII byte escape"
                    buf.append(chr(int(m.group(), 16)))
                    k = m.end()
                elif e == "u":
                    if k + 2 < n and s[k + 2] == "{":
                        end = s.find("}", k + 3)
                        if end < 0:
                            return "invalid unicode escape"
                        try:
                            for h in s[k + 3 : end].split():
                                buf.append(chr(int(h, 16)))
                        except (ValueError, OverflowError):
                            return "invalid unicode escape"
                        k = end + 1
                    else:
                        m = re.compile(r"[0-9a-fA-F]{4}").match(s, k + 2)
                        if m is None:
                            return "invalid unicode escape"
                        buf.append(chr(int(m.group(), 16)))
                        k = m.end()
                elif e in "MC" or e == "c":
                    return "meta/control escape sequence"
                else:
                    buf.append(e)
                    k += 2
                continue
            if c == "#" and k + 1 < n:
                nx = s[k + 1]
                if nx == "{":
                    end = self.skip_interp(k + 2)
                    if end < 0:
                        return "unterminated interpolation"
                    flush()
                    parts.append(Interp(s[k + 2 : end]))
                    k = end + 1
                    continue
                if nx in "@$" and k + 2 < n and (s[k + 2].isalpha() or s[k + 2] in "_@"):
                    m = _IDENT.match(s, k + 2 + (1 if nx == "@" and s[k + 2] == "@" else 0))
                    flush()
                    parts.append(Interp(nx + (m.group() if m else "")))
                    k = m.end() if m else k + 2
                    continue
            if opener and c == opener:
                depth += 1
            elif c == close:
                depth -= 1
                if depth == 0:
                    flush()
                    return parts, k + 1
            buf.append(c)
            k += 1
        return "unterminated string"

    def read_words(
        self, k: int, close: str, opener: str | None
    ) -> tuple[list[str], int] | None:
        s = self.s
        words: list[str] = []
        cur: list[str] = []
        in_word = False
        depth = 1
        n = len(s)
        while k < n:
            c = s[k]
            if c == "\\" and k + 1 < n:
                e = s[k + 1]
                if e in " \t\n" or e in (close, "\\") or (opener and e == opener):
                    cur.append(e)
                    in_word = True
                    k += 2
                    continue
            if c in " \t\r\n\f\v":
                if in_word:
                    words.append("".join(cur))
                    cur.clear()
                    in_word = False
                k += 1
                continue
            if opener and c == opener:
                depth += 1
            elif c == close:
                depth -= 1
                if depth == 0:
                    if in_word:
                        words.append("".join(cur))
                    return words, k + 1
            cur.append(c)
            in_word = True
            k += 1
        return None

    # -- main loop -------------------------------------------------------
    def run(self) -> list[Token]:
        s = self.s
        n = len(s)
        while self.i < n:
            c = s[self.i]
            at_line_start = self.i == 0 or s[self.i - 1] == "\n"
            if c in _SPACE:
                self.spc = True
                self.i += 1
                continue
            if c == "\\" and self.i + 1 < n and s[self.i + 1] == "\n":
                self.i += 2
                self.line += 1
                self.spc = True
                continue
            if c == "\n":
                self.emit("NL", "\n")
                self.i += 1
                self.line += 1
                self.consume_heredocs()
                continue
            if c == ";":
                self.emit("NL", ";")
                self.i += 1
                continue
            if c == "#":
                end = s.find("\n", self.i)
                self.i = n if end < 0 else end
                continue
            if at_line_start and s.startswith("=begin", self.i) and (
                self.i + 6 >= n or s[self.i + 6] in " \t\n"
            ):
                m = re.compile(r"^=end(?=[ \t]|$)", re.MULTILINE).search(s, self.i + 6)
                end = n if m is None else m.end()
                self.line += s.count("\n", self.i, end)
                self.i = end
                nl = s.find("\n", self.i)
                self.i = n if nl < 0 else nl
                continue
            if at_line_start and s.startswith("__END__", self.i) and (
                self.i + 7 >= n or s[self.i + 7] == "\n"
            ):
                break
            self.token(c)
        self.emit("NL", "\n")
        self.emit("EOF", None)
        return self.tokens

    def consume_heredocs(self) -> None:
        s = self.s
        for ident, indented in self.pending_heredocs:
            while self.i < len(s):
                end = s.find("\n", self.i)
                line_text = s[self.i : len(s) if end < 0 else end]
                self.i = len(s) if end < 0 else end + 1
                self.line += 1
                if (line_text.strip() if indented else line_text) == ident:
                    break
        self.pending_heredocs.clear()

    def token(self, c: str) -> None:
        s = self.s
        i = self.i
        n = len(s)
        line = self.line

        # identifiers, labels, keywords, constants
        if c.isalpha() or c == "_" or ord(c) > 0x7F:
            m = _IDENT.match(s, i)
            assert m is not None
            j = m.end()
            if j < n and s[j] in "?!" and not (j + 1 < n and s[j + 1] == "=" and s[j + 2 : j + 3] != "="):
                # `foo?` / `foo!` but not `foo!=`; a following ':' is a label handled below
                j += 1
            word = s[i:j]
            prev = self.last()
            after_dot = prev is not None and prev.kind == "P" and prev.value in (".", "&.")
            if j < n and s[j] == ":" and s[j + 1 : j + 2] != ":" and not after_dot:
                self.emit("LABEL", word)
                self.i = j + 1
                return
            self.i = j
            if word in KEYWORDS and not after_dot:
                self.emit("KW", word)
            elif word[0].isupper() and not after_dot:
                self.emit("CONST", word)
            else:
                self.emit("ID", word)
            return

        # numbers
        if c.isdigit():
            m = _NUMBER.match(s, i)
            assert m is not None
            j = m.end()
            text = m.group().replace("_", "")
            self.i = j
            if j < n and (s[j].isalpha() or s[j] == "_"):
                while self.i < n and (s[self.i].isalnum() or s[self.i] == "_"):
                    self.i += 1
                self.emit("ERR", "numeric literal with suffix")
                return
            try:
                if "." in text or (("e" in text or "E" in text) and not text.startswith(("0x", "0X"))):
                    self.emit("FLOAT", float(text))
                elif len(text) > 1 and text[0] == "0" and text[1] not in "xXbB":
                    self.emit("INT", int(text, 8))
                else:
                    self.emit("INT", int(text, 0))
            except ValueError:
                self.emit("ERR", "numeric literal")
            return

        # single-quoted string
        if c == "'":
            r = self.read_single(i + 1, "'", None)
            if r is None:
                self.error_line("unterminated string")
                return
            text, j = r
            self.finish_string([text], j, line)
            return

        # double-quoted string
        if c == '"':
            r2 = self.read_double(i + 1, '"', None)
            if isinstance(r2, str):
                self.error_line(r2)
                return
            parts, j = r2
            self.finish_string(parts, j, line)
            return

        if c == "`":
            j = self.skip_quoted(i)
            if j < 0:
                self.error_line("unterminated command string")
                return
            self.line += s.count("\n", i, j)
            self.i = j
            self.emit("ERR", "backtick command", line)
            return

        # symbols
        if c == ":" and i + 1 < n:
            nx = s[i + 1]
            if nx == '"':
                r3 = self.read_double(i + 2, '"', None)
                if isinstance(r3, str):
                    self.error_line(r3)
                    return
                parts, j = r3
                self.line += s.count("\n", i, j)
                self.i = j
                self.emit("SYM", parts or [""], line)
                return
            if nx == "'":
                r4 = self.read_single(i + 2, "'", None)
                if r4 is None:
                    self.error_line("unterminated symbol")
                    return
                text, j = r4
                self.line += s.count("\n", i, j)
                self.i = j
                self.emit("SYM", [text], line)
                return
            if nx.isalpha() or nx == "_" or ord(nx) > 0x7F:
                m = _IDENT.match(s, i + 1)
                assert m is not None
                j = m.end()
                if j < n and s[j] in "?!" and s[j + 1 : j + 2] != "=":
                    j += 1
                self.i = j
                self.emit("SYM", [s[i + 1 : j]])
                return

        # variables
        if c in "@$":
            m = re.compile(r"[@$]{1,2}[A-Za-z_0-9]*").match(s, i)
            assert m is not None
            self.i = m.end() if m.end() > i + 1 else i + 1
            self.emit("ERR", "variable")
            return

        # percent literals
        if c == "%" and i + 1 < n and self.value_expected(s[i + 1]):
            if self.percent(i):
                return

        # heredoc
        if c == "<" and s.startswith("<<", i) and i + 2 < n and self.value_expected(s[i + 2]):
            hm = _HEREDOC.match(s, i)
            if hm is not None:
                self.i = hm.end()
                self.pending_heredocs.append((hm.group(3), hm.group(1) != ""))
                self.emit("HEREDOC", hm.group(3))
                return

        # regex literal
        if c == "/" and i + 1 < n and self.value_expected(s[i + 1]):
            k = i + 1
            while k < n and s[k] != "/":
                if s[k] == "\\":
                    k += 1
                elif s[k] == "#" and k + 1 < n and s[k + 1] == "{":
                    e = self.skip_interp(k + 2)
                    if e < 0:
                        k = n
                        break
                    k = e
                elif s[k] == "\n":
                    break
                k += 1
            if k < n and s[k] == "/":
                k += 1
                while k < n and s[k] in "imxounse":
                    k += 1
                self.i = k
                self.emit("REGEX", None)
                return

        m = _OPERATOR.match(s, i)
        if m is not None:
            self.i = m.end()
            self.emit("P", m.group())
            return
        self.i += 1
        self.emit("ERR", f"unexpected character {c!r}")

    def finish_string(self, parts: list[Part], j: int, line: int) -> None:
        s = self.s
        self.line += s.count("\n", self.i, j)
        self.i = j
        # "key": value
        if j < len(s) and s[j] == ":" and s[j + 1 : j + 2] != ":" and s[j + 1 : j + 2] in " \t\n":
            prev = self.last()
            if prev is not None and (
                prev.kind == "NL" or (prev.kind == "P" and prev.value in ("{", ",", "("))
            ):
                if all(isinstance(p, str) for p in parts):
                    self.i = j + 1
                    self.emit("LABEL", "".join(p for p in parts if isinstance(p, str)), line)
                    return
        self.emit("STR", parts or [""], line)

    def error_line(self, message: str) -> None:
        """Emit an ERR token and resume at the next line, so one bad literal cannot swallow the file."""
        s = self.s
        end = s.find("\n", self.i)
        self.i = len(s) if end < 0 else end
        self.emit("ERR", message)

    def percent(self, i: int) -> bool:
        s = self.s
        n = len(s)
        kind = ""
        k = i + 1
        if s[k].isalpha():
            kind = s[k]
            k += 1
            if k >= n:
                return False
        d = s[k]
        if kind not in ("", "w", "W", "i", "I", "q", "Q", "r", "x", "s"):
            return False
        if d.isalnum() or d in " \t\n=" or ord(d) > 0x7F:
            return False
        if kind == "" and d in "=)]}>,;":
            return False
        opener = d if d in _CLOSERS else None
        close = _CLOSERS.get(d, d)
        line = self.line
        start = k + 1
        if kind in ("w", "i", "W", "I"):
            r = self.read_words(start, close, opener)
            if r is None:
                self.error_line("unterminated word list")
                return True
            words, j = r
            body = s[start : j - 1]
            if kind in ("W", "I") and ("\\" in body or "#{" in body):
                self.i = j
                self.line += s.count("\n", i, j)
                self.emit("ERR", "%W/%I literal with escapes or interpolation", line)
                return True
            self.line += s.count("\n", i, j)
            self.i = j
            self.emit("WORDS", (words, kind in ("i", "I")), line)
            return True
        if kind in ("q", ""):
            if kind == "":
                r3 = self.read_double(start, close, opener)
                if isinstance(r3, str):
                    self.error_line(r3)
                    return True
                parts, j = r3
                self.line += s.count("\n", i, j)
                self.i = j
                self.emit("STR", parts or [""], line)
                return True
            r2 = self.read_single(start, close, opener)
            if r2 is None:
                self.error_line("unterminated string")
                return True
            text, j = r2
            self.line += s.count("\n", i, j)
            self.i = j
            self.emit("STR", [text], line)
            return True
        if kind == "Q":
            r3 = self.read_double(start, close, opener)
            if isinstance(r3, str):
                self.error_line(r3)
                return True
            parts, j = r3
            self.line += s.count("\n", i, j)
            self.i = j
            self.emit("STR", parts or [""], line)
            return True
        # %r %x %s: consume the literal, report as unsupported
        r5 = self.read_single(start, close, opener)
        if r5 is None:
            self.error_line("unterminated literal")
            return True
        self.line += s.count("\n", i, r5[1])
        self.i = r5[1]
        self.emit("REGEX" if kind == "r" else "ERR", None if kind == "r" else f"%{kind} literal", line)
        return True


def tokenize(src: str) -> list[Token]:
    return _Lexer(src).run()
