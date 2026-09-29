"""Parser for the DSL subset: method calls with literal arguments and blocks."""

from __future__ import annotations

from dataclasses import dataclass, field

from ._lexer import Interp, Token, tokenize
from .model import Diagnostic

DSL_METHODS = frozenset(
    "gem group source git_source path git github platforms platform env "
    "install_if ruby gemspec plugin".split()
)
BLOCK_METHODS = frozenset(
    "group source git_source path git github platforms platform env install_if".split()
)
_STATEMENT_START_KW = frozenset(
    "if unless case while until begin def class module for".split()
)
_CONTINUATION_OPS = frozenset(
    [",", ".", "&.", "&&", "||", "=", "+", "-", "*", "/", "%", "**", "=>", "?", ":",
     "==", "!=", "<", ">", "<=", ">=", "=~", "<<", ">>", "+=", "-=", "||=", "&&=", "::"]
)
_ASSIGN_OPS = frozenset(["=", "+=", "-=", "*=", "/=", "||=", "&&=", "%=", "|=", "&="])
_FOLLOW_OK = frozenset([",", ")", "]", "}", "=>"])


@dataclass(frozen=True, slots=True)
class Sym:
    name: str


@dataclass(slots=True)
class HashLit:
    items: list[tuple[object, object]]


@dataclass(slots=True)
class TemplateStep:
    """One statement of a `git_source` block body."""

    target: str | None
    parts: list[str | Interp]
    cond: str | None = None  # "if" | "unless" | None
    cond_var: str = ""
    cond_needle: str = ""


@dataclass(slots=True)
class Template:
    param: str
    steps: list[TemplateStep]


@dataclass(slots=True)
class Block:
    params: list[str]
    body: list[Call]
    template: Template | None = None


@dataclass(slots=True)
class Call:
    name: str
    args: list[object]
    block: Block | None
    line: int
    text: str = field(default="")


class Unsupported(Exception):
    def __init__(self, line: int, message: str) -> None:
        super().__init__(message)
        self.line = line
        self.message = message


def describe(tok: Token) -> str:
    """Short human description of a token, for diagnostics."""
    k, v = tok.kind, tok.value
    if k == "ID":
        return f"`{v}`"
    if k == "CONST":
        return f"constant `{v}`"
    if k in ("KW", "P", "LABEL"):
        return f"`{v}`"
    if k == "ERR":
        return str(v)
    if k == "HEREDOC":
        return "heredoc"
    if k == "REGEX":
        return "regular expression"
    if k == "NL":
        return "end of line"
    if k == "EOF":
        return "end of file"
    return k.lower()


class Parser:
    def __init__(self, src: str) -> None:
        self.lines = src.replace("\r\n", "\n").split("\n")
        self.toks = tokenize(src)
        self.i = 0
        self.diags: list[Diagnostic] = []
        # git_source definitions that could not be read; "*" when even the name is unknown
        self.dead_sources: set[str] = set()

    # -- token access ----------------------------------------------------
    def peek(self, k: int = 0) -> Token:
        j = self.i + k
        return self.toks[j] if j < len(self.toks) else self.toks[-1]

    def is_p(self, value: str, k: int = 0) -> bool:
        t = self.peek(k)
        return t.kind == "P" and t.value == value

    def is_kw(self, value: str, k: int = 0) -> bool:
        t = self.peek(k)
        return t.kind == "KW" and t.value == value

    def skip_nl(self) -> None:
        while self.peek().kind == "NL":
            self.i += 1

    def text_of(self, line: int) -> str:
        if 1 <= line <= len(self.lines):
            t = self.lines[line - 1].strip()
            return t if len(t) <= 120 else t[:117] + "..."
        return ""

    def unsupported(self, tok: Token, message: str) -> Unsupported:
        return Unsupported(tok.line, message)

    # -- program ---------------------------------------------------------
    def parse_program(self) -> list[Call]:
        calls = self.parse_stmts(None)
        return calls

    def parse_stmts(self, closer: str | None) -> list[Call]:
        """Statements up to the closer: None (EOF), "end" or "}"."""
        out: list[Call] = []
        while True:
            self.skip_nl()
            t = self.peek()
            if t.kind == "EOF":
                return out
            if closer == "end" and t.kind == "KW" and t.value == "end":
                return out
            if closer == "}" and t.kind == "P" and t.value == "}":
                return out
            start = self.i
            try:
                if t.kind == "KW" and t.value == "end" or t.kind == "P" and t.value in ("}", ")", "]"):
                    raise Unsupported(t.line, f"unexpected {describe(t)}")
                stmt = self.parse_statement()
                self.end_of_statement()
                out.append(stmt)
            except Unsupported as e:
                self.diags.append(Diagnostic(e.line, "unsupported", e.message, self.text_of(e.line)))
                if t.kind == "ID" and t.value == "git_source":
                    self.dead_sources.add(self.git_source_name(start))
                self.i = max(self.skip_statement(start), start + 1)

    def git_source_name(self, start: int) -> str:
        """Name in `git_source(:name)` at token index `start`, or "*" if it is not a literal."""
        for k in range(start + 1, min(start + 4, len(self.toks))):
            t = self.toks[k]
            if t.kind in ("SYM", "STR") and isinstance(t.value, list) and len(t.value) == 1 \
                    and isinstance(t.value[0], str):
                return t.value[0]
            if not (t.kind == "P" and t.value == "("):
                break
        return "*"

    def end_of_statement(self) -> None:
        t = self.peek()
        if t.kind in ("NL", "EOF"):
            return
        if t.kind == "KW" and t.value == "end":
            return
        if t.kind == "P" and t.value == "}":
            return
        if t.kind == "KW" and t.value in ("if", "unless", "while", "until", "rescue"):
            raise self.unsupported(
                t, f"`{t.value}` modifier: whether the statement runs depends on runtime state"
            )
        raise self.unsupported(t, f"unexpected {describe(t)} after statement")

    def skip_statement(self, start: int) -> int:
        """Index just past the statement beginning at token `start` (block bodies included)."""
        i = start
        depth = 0
        paren = 0
        prev: Token | None = None
        loop_do = False
        toks = self.toks
        while i < len(toks):
            t = toks[i]
            if t.kind == "EOF":
                return i
            if t.kind == "NL":
                loop_do = False
                if depth == 0 and paren == 0 and not (
                    prev is not None and prev.kind == "P" and prev.value in _CONTINUATION_OPS
                ):
                    return i + 1
            elif t.kind == "KW":
                v = t.value
                at_start = (
                    prev is None
                    or prev.kind == "NL"
                    or (prev.kind == "P" and prev.value in ("=", "||", "&&", "(", ",", "||=", "{"))
                    or (prev.kind == "KW" and prev.value in ("then", "do", "else", "begin"))
                )
                if v == "end":
                    if depth == 0:
                        return i
                    depth -= 1
                elif v == "do":
                    if loop_do:
                        loop_do = False
                    else:
                        depth += 1
                elif v in _STATEMENT_START_KW and at_start:
                    depth += 1
                    if v in ("while", "until", "for"):
                        loop_do = True
            elif t.kind == "P":
                v = t.value
                if v in ("(", "[", "{"):
                    paren += 1
                elif v in (")", "]", "}"):
                    if paren == 0 and depth == 0:
                        return i
                    paren = max(0, paren - 1)
            prev = t
            i += 1
        return i

    # -- statements ------------------------------------------------------
    def parse_statement(self) -> Call:
        t = self.peek()
        line = t.line
        if t.kind == "KW":
            v = t.value
            if v in ("if", "unless", "case", "while", "until", "for", "begin"):
                raise self.unsupported(t, f"`{v}` block: what it does depends on runtime state")
            if v in ("def", "class", "module"):
                raise self.unsupported(t, f"`{v}` definition")
            raise self.unsupported(t, f"keyword {describe(t)}")
        if t.kind == "CONST":
            name = str(t.value)
            if name == "ENV":
                raise self.unsupported(t, "ENV access")
            if name in ("File", "Dir", "IO", "Kernel", "Bundler", "Gem", "RbConfig"):
                raise self.unsupported(t, f"call into {name}")
            raise self.unsupported(t, f"constant `{name}`")
        if t.kind != "ID":
            raise self.unsupported(t, f"expression statement starting with {describe(t)}")
        name = str(t.value)
        nxt = self.peek(1)
        if nxt.kind == "P" and nxt.value in _ASSIGN_OPS:
            raise self.unsupported(t, f"assignment to local variable `{name}`")
        if nxt.kind == "P" and nxt.value in (".", "&.", "::"):
            raise self.unsupported(t, f"method call on `{name}`")
        if nxt.kind == "P" and nxt.value == "[" and not nxt.spc:
            raise self.unsupported(t, f"index into `{name}`")
        if name == "eval_gemfile":
            raise self.unsupported(t, "eval_gemfile includes another file, which is not read")
        if name not in DSL_METHODS:
            raise self.unsupported(t, f"call to `{name}`, which is not a Gemfile DSL method")
        self.i += 1
        args: list[object] = []
        paren = False
        if self.is_p("("):
            self.i += 1
            paren = True
            args = self.parse_args(")")
            if not self.is_p(")"):
                raise self.unsupported(self.peek(), f"expected `)`, found {describe(self.peek())}")
            self.i += 1
        elif self.starts_value(self.peek()):
            args = self.parse_args(None)
        block: Block | None = None
        if self.is_kw("do") or (self.is_p("{") and (paren or not args)):
            if name not in BLOCK_METHODS:
                raise self.unsupported(self.peek(), f"block passed to `{name}`")
            block = self.parse_block(name)
        return Call(name, args, block, line, self.text_of(line))

    def starts_value(self, t: Token) -> bool:
        if t.kind in ("STR", "SYM", "LABEL", "WORDS", "INT", "FLOAT", "CONST", "ID", "REGEX",
                      "HEREDOC", "ERR"):
            return True
        if t.kind == "KW":
            return t.value in ("true", "false", "nil", "self", "not", "defined?", "__FILE__",
                               "__dir__", "__method__", "__LINE__")
        if t.kind == "P":
            return t.value in ("[", "->", "-", "*", "**", "&", "!", "::", "(")
        return False

    # -- blocks ----------------------------------------------------------
    def parse_block(self, name: str) -> Block:
        opener = self.peek()
        brace = opener.kind == "P"
        self.i += 1
        params: list[str] = []
        if self.is_p("|"):
            self.i += 1
            while True:
                t = self.peek()
                if t.kind != "ID":
                    raise self.unsupported(t, "unsupported block parameter list")
                params.append(str(t.value))
                self.i += 1
                if self.is_p(","):
                    self.i += 1
                    continue
                break
            if not self.is_p("|"):
                raise self.unsupported(self.peek(), "unsupported block parameter list")
            self.i += 1
        elif self.is_p("||"):
            self.i += 1
        closer = "}" if brace else "end"
        if name == "git_source":
            if len(params) != 1:
                raise self.unsupported(opener, "git_source block must take exactly one parameter")
            template = self.parse_template(params[0], closer)
            return Block(params, [], template)
        if params:
            raise self.unsupported(opener, f"block parameters on `{name}`")
        body = self.parse_stmts(closer)
        self.expect_closer(closer)
        return Block(params, body)

    def expect_closer(self, closer: str) -> None:
        t = self.peek()
        ok = (closer == "}" and t.kind == "P" and t.value == "}") or (
            closer == "end" and t.kind == "KW" and t.value == "end"
        )
        if not ok:
            raise self.unsupported(t, f"missing `{closer}` before {describe(t)}")
        self.i += 1

    def parse_template(self, param: str, closer: str) -> Template:
        """Body of a `git_source` block: optional `x = "..." unless x.include?("/")`, then a string."""
        steps: list[TemplateStep] = []
        env = {param}
        while True:
            self.skip_nl()
            t = self.peek()
            if t.kind == "KW" and t.value == "end" and closer == "end":
                break
            if t.kind == "P" and t.value == "}" and closer == "}":
                break
            if t.kind == "EOF":
                raise self.unsupported(t, f"missing `{closer}`")
            step = self.parse_template_step(env)
            steps.append(step)
            nt = self.peek()
            if not (nt.kind == "NL" or (nt.kind == "KW" and nt.value == "end") or (
                nt.kind == "P" and nt.value == "}"
            )):
                raise self.unsupported(nt, f"unexpected {describe(nt)} in git_source block")
        self.expect_closer(closer)
        if not steps or steps[-1].target is not None or steps[-1].cond is not None:
            raise self.unsupported(self.peek(), "git_source block must end in a string expression")
        return Template(param, steps)

    def parse_template_step(self, env: set[str]) -> TemplateStep:
        t = self.peek()
        target: str | None = None
        if t.kind == "ID" and self.is_p("=", 1):
            target = str(t.value)
            if target not in env:
                raise self.unsupported(t, f"git_source block assigns to `{target}`")
            self.i += 2
            t = self.peek()
        if t.kind != "STR":
            raise self.unsupported(t, f"git_source block contains {describe(t)}, not a string")
        parts = self.string_parts(t)
        self.i += 1
        for p in parts:
            if isinstance(p, Interp) and p.text.strip() not in env:
                raise self.unsupported(
                    t, f"interpolation `#{{{p.text}}}` in git_source is not a block parameter"
                )
        step = TemplateStep(target, parts)
        m = self.peek()
        if m.kind == "KW" and m.value in ("if", "unless"):
            if target is None:
                raise self.unsupported(m, "conditional on the final git_source expression")
            self.i += 1
            v = self.peek()
            if v.kind != "ID" or str(v.value) not in env or not self.is_p(".", 1):
                raise self.unsupported(v, "unsupported git_source condition")
            m2 = self.peek(2)
            if m2.kind != "ID" or m2.value != "include?":
                raise self.unsupported(m2, "unsupported git_source condition")
            self.i += 3
            paren = self.is_p("(")
            if paren:
                self.i += 1
            needle = self.peek()
            if needle.kind != "STR" or any(isinstance(p, Interp) for p in self.string_parts(needle)):
                raise self.unsupported(needle, "unsupported git_source condition")
            self.i += 1
            if paren:
                if not self.is_p(")"):
                    raise self.unsupported(self.peek(), "unsupported git_source condition")
                self.i += 1
            step.cond = str(m.value)
            step.cond_var = str(v.value)
            step.cond_needle = "".join(p for p in self.string_parts(needle) if isinstance(p, str))
        return step

    # -- arguments and values -------------------------------------------
    def string_parts(self, t: Token) -> list[str | Interp]:
        parts = t.value
        assert isinstance(parts, list)
        return parts

    def parse_args(self, closer: str | None) -> list[object]:
        args: list[object] = []
        pairs: list[tuple[object, object]] = []
        while True:
            if closer:
                self.skip_nl()
                if self.is_p(closer):
                    break
            t = self.peek()
            if t.kind == "LABEL":
                self.i += 1
                self.skip_nl()
                pairs.append((Sym(str(t.value)), self.parse_value()))
            else:
                first = self.peek()
                v = self.parse_value()
                if self.is_p("=>"):
                    self.i += 1
                    self.skip_nl()
                    pairs.append((v, self.parse_value()))
                else:
                    if pairs:
                        raise self.unsupported(first, "positional argument after keyword arguments")
                    args.append(v)
            if closer:
                self.skip_nl()
            if self.is_p(","):
                self.i += 1
                self.skip_nl()
                continue
            break
        if pairs:
            args.append(HashLit(pairs))
        return args

    def parse_value(self) -> object:
        t = self.peek()
        k = t.kind
        value: object
        if k == "STR":
            parts = self.string_parts(t)
            self.i += 1
            text = self.plain(t, parts)
            # adjacent literals concatenate: "a" 'b'
            while self.peek().kind == "STR":
                nt = self.peek()
                text += self.plain(nt, self.string_parts(nt))
                self.i += 1
            value = text
        elif k == "SYM":
            parts = self.string_parts(t)
            self.i += 1
            value = Sym(self.plain(t, parts))
        elif k == "WORDS":
            assert isinstance(t.value, tuple)
            words, is_sym = t.value
            self.i += 1
            value = [Sym(w) for w in words] if is_sym else list(words)
        elif k == "INT" or k == "FLOAT":
            self.i += 1
            value = t.value
        elif k == "KW" and t.value in ("true", "false", "nil"):
            self.i += 1
            value = {"true": True, "false": False, "nil": None}[str(t.value)]
        elif k == "P" and t.value == "[":
            self.i += 1
            items: list[object] = []
            while True:
                self.skip_nl()
                if self.is_p("]"):
                    break
                items.append(self.parse_value())
                self.skip_nl()
                if self.is_p(","):
                    self.i += 1
                    continue
                break
            self.skip_nl()
            if not self.is_p("]"):
                raise self.unsupported(self.peek(), f"expected `]`, found {describe(self.peek())}")
            self.i += 1
            value = items
        elif k == "P" and t.value == "{":
            self.i += 1
            pairs: list[tuple[object, object]] = []
            while True:
                self.skip_nl()
                if self.is_p("}"):
                    break
                kt = self.peek()
                if kt.kind == "LABEL":
                    self.i += 1
                    self.skip_nl()
                    pairs.append((Sym(str(kt.value)), self.parse_value()))
                else:
                    key = self.parse_value()
                    self.skip_nl()
                    if not self.is_p("=>"):
                        raise self.unsupported(self.peek(), "expected `=>` in hash literal")
                    self.i += 1
                    self.skip_nl()
                    pairs.append((key, self.parse_value()))
                self.skip_nl()
                if self.is_p(","):
                    self.i += 1
                    continue
                break
            self.skip_nl()
            if not self.is_p("}"):
                raise self.unsupported(self.peek(), f"expected `}}`, found {describe(self.peek())}")
            self.i += 1
            value = HashLit(pairs)
        else:
            raise self.unsupported(t, self.why_not_value(t))
        n = self.peek()
        if n.kind == "P" and n.value not in _FOLLOW_OK:
            raise self.unsupported(n, f"operator {describe(n)} in an expression")
        if n.kind in ("ID", "CONST", "LABEL", "SYM", "WORDS", "INT", "FLOAT", "ERR", "HEREDOC", "REGEX"):
            raise self.unsupported(n, f"unexpected {describe(n)} after value")
        return value

    def plain(self, t: Token, parts: list[str | Interp]) -> str:
        out: list[str] = []
        for p in parts:
            if isinstance(p, Interp):
                if p.text.startswith(("@", "$")):
                    raise self.unsupported(t, f"interpolated variable `#{p.text}`")
                raise self.unsupported(t, f"string interpolation `#{{{p.text.strip()}}}`")
            out.append(p)
        return "".join(out)

    def why_not_value(self, t: Token) -> str:
        if t.kind == "CONST" and t.value == "ENV":
            return "ENV access"
        if t.kind == "CONST":
            return f"constant `{t.value}`"
        if t.kind == "ID":
            return f"method call or variable `{t.value}`"
        if t.kind == "P" and t.value == "->":
            return "lambda"
        if t.kind == "KW":
            return f"keyword {describe(t)}"
        return f"unsupported expression starting at {describe(t)}"


def parse_source(src: str) -> tuple[list[Call], list[Diagnostic], set[str]]:
    p = Parser(src)
    calls = p.parse_program()
    return calls, p.diags, p.dead_sources
