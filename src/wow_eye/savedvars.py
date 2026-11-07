"""Read and write the Lua data files the game uses, without ever executing Lua.

The client writes SavedVariables as `Name = <value>` assignments. Tables contain
`["key"] = value`, `[1] = value` or bare positional values, sometimes followed by
`-- [n]` comments.
"""

from __future__ import annotations

import re
from typing import Any

_TOKEN = re.compile(
    r"""
    (?P<skip>\s+|--[^\n]*)
  | (?P<string>"(?:[^"\\]|\\.)*")
  | (?P<number>-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)
  | (?P<huge>-?math\.huge)
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<punct>[{}\[\]=,;])
    """,
    re.VERBOSE | re.DOTALL,
)

_ESCAPES = {
    "n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "f": "\f", "v": "\v",
    "\\": "\\", '"': '"', "'": "'", "\n": "\n",
}
_ESCAPE = re.compile(r"\\(\d{1,3}|.)", re.DOTALL)


class ParseError(ValueError):
    pass


def _unescape(body: str) -> str:
    def sub(m: re.Match[str]) -> str:
        esc = m.group(1)
        if esc[0].isdigit():
            return chr(int(esc) & 0xFF)
        return _ESCAPES.get(esc, esc)

    # Text is held as latin-1 during parsing so that each char is one source byte.
    # That keeps \ddd byte escapes and raw UTF-8 correct once decoded together.
    return _ESCAPE.sub(sub, body).encode("latin-1", "replace").decode("utf-8", "replace")


def _tokenize(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            raise ParseError(f"unexpected {text[pos:pos + 20]!r} at offset {pos}")
        kind = m.lastgroup or ""
        if kind != "skip":
            tokens.append((kind, m.group()))
        pos = m.end()
    tokens.append(("eof", ""))
    return tokens


class _Parser:
    def __init__(self, text: str) -> None:
        self.tokens = _tokenize(text)
        self.i = 0

    def peek(self) -> tuple[str, str]:
        return self.tokens[self.i]

    def next(self) -> tuple[str, str]:
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def expect(self, value: str) -> None:
        _, got = self.next()
        if got != value:
            raise ParseError(f"expected {value!r}, got {got!r}")

    def document(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        while self.peek()[0] != "eof":
            kind, name = self.next()
            if kind != "name":
                raise ParseError(f"expected a variable name, got {name!r}")
            self.expect("=")
            out[name] = self.value()
        return out

    def value(self) -> Any:
        kind, tok = self.next()
        if kind == "string":
            return _unescape(tok[1:-1])
        if kind == "number":
            return float(tok) if any(c in tok for c in ".eE") else int(tok)
        if kind == "huge":
            return float("-inf") if tok.startswith("-") else float("inf")
        if kind == "name" and tok in ("true", "false", "nil"):
            return {"true": True, "false": False, "nil": None}[tok]
        if tok == "{":
            return self.table()
        raise ParseError(f"unexpected token {tok!r}")

    def table(self) -> Any:
        items: dict[Any, Any] = {}
        position = 1
        while True:
            kind, tok = self.peek()
            if tok == "}" and kind == "punct":
                self.next()
                break
            if tok == "[" and kind == "punct":
                self.next()
                key = self.value()
                self.expect("]")
                self.expect("=")
                items[key] = self.value()
            elif kind == "name" and self.tokens[self.i + 1][1] == "=":
                self.next()
                self.next()
                items[tok] = self.value()
            else:
                items[position] = self.value()
                position += 1
            if self.peek()[1] in (",", ";") and self.peek()[0] == "punct":
                self.next()
        # A table whose keys are exactly 1..n is a list, whatever order they came in.
        if items and set(items) == set(range(1, len(items) + 1)):
            return [items[k] for k in range(1, len(items) + 1)]
        return items


def loads(text: str) -> dict[str, Any]:
    """Parse the text of a SavedVariables file into {global name: value}."""
    return _Parser(text).document()


def load(path) -> dict[str, Any]:
    with open(path, "rb") as f:
        return loads(f.read().decode("latin-1"))


def _quote(s: str) -> str:
    out = ['"']
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ord(ch) < 32 or ord(ch) == 127:
            out.append(f"\\{ord(ch):03d}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def dumps_value(value: Any, indent: int = 0) -> str:
    """Render a Python value as a Lua literal that is safe to load in the game."""
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError(f"can't represent {value} in a data file")
        return repr(value)
    if isinstance(value, str):
        return _quote(value)
    pad = "  " * (indent + 1)
    end = "  " * indent
    if isinstance(value, (list, tuple)):
        if not value:
            return "{}"
        body = "".join(f"{pad}{dumps_value(v, indent + 1)},\n" for v in value)
        return "{\n" + body + end + "}"
    if isinstance(value, dict):
        if not value:
            return "{}"
        body = "".join(
            f"{pad}[{dumps_value(k, indent + 1)}] = {dumps_value(v, indent + 1)},\n"
            for k, v in value.items()
        )
        return "{\n" + body + end + "}"
    raise TypeError(f"can't write {type(value).__name__} to a data file")
