from __future__ import annotations

import difflib
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd


KEYWORDS = {"AND", "OR", "NOT", "IN", "IS", "NULL", "LIKE"}
NULLISH_TEXT_VALUES = frozenset({"", "NULL", "NONE", "NAN", "<NA>", "NAT"})


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    pos: int


@dataclass(frozen=True)
class LiteralValue:
    value: Any
    kind: str


@dataclass(frozen=True)
class ComparisonNode:
    column: str
    operator: str
    value: Optional[LiteralValue] = None
    values: Optional[Tuple[LiteralValue, ...]] = None


@dataclass(frozen=True)
class UnaryNode:
    operator: str
    expr: Any


@dataclass(frozen=True)
class BinaryNode:
    operator: str
    left: Any
    right: Any


@dataclass
class FilterValidationError(Exception):
    message: str
    position: Optional[int] = None
    suggestions: Optional[List[str]] = None

    def __str__(self) -> str:
        if self.position is None:
            return self.message
        return f"{self.message} at position {self.position}"


def _tokenize(expr: str) -> List[Token]:
    tokens: List[Token] = []
    i = 0
    n = len(expr)
    while i < n:
        ch = expr[i]
        if ch.isspace():
            i += 1
            continue
        if expr.startswith(">=", i) or expr.startswith("<=", i) or expr.startswith("!=", i):
            tokens.append(Token("OP", expr[i : i + 2], i))
            i += 2
            continue
        if ch in "=<>":
            tokens.append(Token("OP", ch, i))
            i += 1
            continue
        if ch == "(":
            tokens.append(Token("LPAREN", ch, i))
            i += 1
            continue
        if ch == ")":
            tokens.append(Token("RPAREN", ch, i))
            i += 1
            continue
        if ch == ",":
            tokens.append(Token("COMMA", ch, i))
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            i += 1
            start = i
            buf: List[str] = []
            while i < n:
                cur = expr[i]
                if cur == quote:
                    if i + 1 < n and expr[i + 1] == quote:
                        buf.append(quote)
                        i += 2
                        continue
                    break
                buf.append(cur)
                i += 1
            if i >= n or expr[i] != quote:
                raise FilterValidationError("Unterminated string literal", start - 1)
            tokens.append(Token("STRING", "".join(buf), start - 1))
            i += 1
            continue

        start = i
        while i < n and (not expr[i].isspace()) and expr[i] not in "(),":
            if expr.startswith(">=", i) or expr.startswith("<=", i) or expr.startswith("!=", i):
                break
            if expr[i] in "=<>":
                break
            i += 1
        text = expr[start:i]
        if not text:
            raise FilterValidationError("Unexpected character", start)
        if re.fullmatch(r"-?\d+(?:\.\d+)?", text):
            tokens.append(Token("NUMBER", text, start))
        elif text.upper() in KEYWORDS:
            tokens.append(Token("KEYWORD", text.upper(), start))
        else:
            tokens.append(Token("WORD", text, start))

    return tokens


class FilterParser:
    def __init__(self, expr: str, columns: Sequence[str]):
        self.expr = expr or ""
        self.tokens = _tokenize(self.expr)
        self.pos = 0
        self.columns = [str(c) for c in columns]
        self.column_lookup = {c.upper(): c for c in self.columns}
        self.referenced_columns: List[str] = []

    def parse(self):
        if not self.tokens:
            return None
        node = self._parse_or()
        if self._peek() is not None:
            tok = self._peek()
            raise FilterValidationError(f"Unexpected token '{tok.text}'", tok.pos)
        return node

    def _peek(self) -> Optional[Token]:
        if self.pos >= len(self.tokens):
            return None
        return self.tokens[self.pos]

    def _consume(self) -> Token:
        tok = self._peek()
        if tok is None:
            raise FilterValidationError("Unexpected end of expression")
        self.pos += 1
        return tok

    def _match_keyword(self, *words: str) -> Optional[Token]:
        tok = self._peek()
        if tok and tok.kind == "KEYWORD" and tok.text in words:
            self.pos += 1
            return tok
        return None

    def _match_kind(self, *kinds: str) -> Optional[Token]:
        tok = self._peek()
        if tok and tok.kind in kinds:
            self.pos += 1
            return tok
        return None

    def _expect_kind(self, *kinds: str) -> Token:
        tok = self._peek()
        if tok and tok.kind in kinds:
            self.pos += 1
            return tok
        if tok is None:
            raise FilterValidationError("Unexpected end of expression")
        raise FilterValidationError(f"Expected {'/'.join(kinds)}, got '{tok.text}'", tok.pos)

    def _expect_keyword(self, word: str) -> Token:
        tok = self._peek()
        if tok and tok.kind == "KEYWORD" and tok.text == word:
            self.pos += 1
            return tok
        if tok is None:
            raise FilterValidationError("Unexpected end of expression")
        raise FilterValidationError(f"Expected {word}, got '{tok.text}'", tok.pos)

    def _parse_or(self):
        node = self._parse_and()
        while self._match_keyword("OR"):
            node = BinaryNode("OR", node, self._parse_and())
        return node

    def _parse_and(self):
        node = self._parse_not()
        while self._match_keyword("AND"):
            node = BinaryNode("AND", node, self._parse_not())
        return node

    def _parse_not(self):
        if self._match_keyword("NOT"):
            return UnaryNode("NOT", self._parse_not())
        return self._parse_primary()

    def _parse_primary(self):
        if self._match_kind("LPAREN"):
            node = self._parse_or()
            self._expect_kind("RPAREN")
            return node
        return self._parse_comparison()

    def _parse_comparison(self):
        tok = self._expect_kind("WORD")
        column = self._resolve_column(tok)
        if column not in self.referenced_columns:
            self.referenced_columns.append(column)

        if self._match_keyword("IS"):
            if self._match_keyword("NOT"):
                self._expect_keyword("NULL")
                return ComparisonNode(column, "IS NOT NULL")
            self._expect_keyword("NULL")
            return ComparisonNode(column, "IS NULL")

        if self._match_keyword("NOT"):
            if self._match_keyword("LIKE"):
                return ComparisonNode(column, "NOT LIKE", value=self._parse_value())
            if self._match_keyword("IN"):
                return ComparisonNode(column, "NOT IN", values=self._parse_list())
            raise FilterValidationError("Expected LIKE or IN after NOT", tok.pos)

        if self._match_keyword("LIKE"):
            return ComparisonNode(column, "LIKE", value=self._parse_value())
        if self._match_keyword("IN"):
            return ComparisonNode(column, "IN", values=self._parse_list())

        op = self._match_kind("OP")
        if not op:
            next_tok = self._peek()
            if next_tok is None:
                raise FilterValidationError("Expected operator after column", tok.pos)
            raise FilterValidationError(f"Expected operator after column, got '{next_tok.text}'", next_tok.pos)

        value = self._parse_value()
        if value.kind == "null":
            if op.text == "=":
                return ComparisonNode(column, "IS NULL")
            if op.text == "!=":
                return ComparisonNode(column, "IS NOT NULL")
            raise FilterValidationError("Use IS NULL / IS NOT NULL for NULL comparisons", op.pos)

        return ComparisonNode(column, op.text, value=value)

    def _parse_list(self) -> Tuple[LiteralValue, ...]:
        self._expect_kind("LPAREN")
        values = [self._parse_value()]
        while self._match_kind("COMMA"):
            values.append(self._parse_value())
        self._expect_kind("RPAREN")
        return tuple(values)

    def _parse_value(self) -> LiteralValue:
        tok = self._expect_kind("STRING", "NUMBER", "WORD", "KEYWORD")
        if tok.kind == "STRING":
            return LiteralValue(tok.text, "string")
        if tok.kind == "NUMBER":
            if "." in tok.text:
                return LiteralValue(float(tok.text), "number")
            return LiteralValue(int(tok.text), "number")
        if tok.kind == "KEYWORD" and tok.text == "NULL":
            return LiteralValue(None, "null")
        return LiteralValue(tok.text, "string")

    def _resolve_column(self, tok: Token) -> str:
        actual = self.column_lookup.get(tok.text.upper())
        if actual:
            return actual
        suggestions = difflib.get_close_matches(tok.text.upper(), list(self.column_lookup.keys()), n=3, cutoff=0.6)
        pretty = [self.column_lookup[x] for x in suggestions]
        raise FilterValidationError(f"Unknown column '{tok.text}'", tok.pos, suggestions=pretty)


def normalize_expression(node) -> str:
    if node is None:
        return ""
    if isinstance(node, ComparisonNode):
        if node.operator in ("IS NULL", "IS NOT NULL"):
            return f"{node.column} {node.operator}"
        if node.operator in ("IN", "NOT IN"):
            values = ", ".join(_literal_to_string(v) for v in (node.values or ()))
            return f"{node.column} {node.operator} ({values})"
        return f"{node.column} {node.operator} {_literal_to_string(node.value)}"
    if isinstance(node, UnaryNode):
        inner = normalize_expression(node.expr)
        if isinstance(node.expr, ComparisonNode):
            return f"NOT {inner}"
        return f"NOT ({inner})"
    if isinstance(node, BinaryNode):
        left = normalize_expression(node.left)
        right = normalize_expression(node.right)
        return f"({left} {node.operator} {right})"
    raise TypeError(f"Unsupported node: {type(node)!r}")


def _literal_to_string(literal: Optional[LiteralValue]) -> str:
    if literal is None:
        return "NULL"
    if literal.kind == "null":
        return "NULL"
    if literal.kind == "number":
        return str(literal.value)
    value = str(literal.value).replace("'", "''")
    return f"'{value}'"


def _like_to_regex(pattern: str) -> str:
    out: List[str] = ["^"]
    for ch in str(pattern):
        if ch == "%":
            out.append(".*")
        elif ch == "_":
            out.append(".")
        else:
            out.append(re.escape(ch))
    out.append("$")
    return "".join(out)


def _kind_map(column_info: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    return {name: str(info.get("kind", "text")) for name, info in column_info.items()}


def _is_numeric_literal(literal: Optional[LiteralValue]) -> bool:
    return bool(literal and literal.kind == "number")


def _all_numeric(values: Iterable[LiteralValue]) -> bool:
    seq = list(values)
    return bool(seq) and all(v.kind == "number" for v in seq)


def _nullish_mask(series: pd.Series) -> pd.Series:
    mask = series.isna().fillna(False)
    if pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series):
        normalized = series.astype("string").str.strip().str.upper()
        mask = mask | normalized.isin(NULLISH_TEXT_VALUES).fillna(False)
    return mask.fillna(False)


def compile_sql(node, column_info: Dict[str, Dict[str, Any]]) -> Tuple[str, List[Any]]:
    if node is None:
        return "1 = 1", []

    kind_map = _kind_map(column_info)

    def quote(name: str) -> str:
        return '"' + str(name).replace('"', '""') + '"'

    def column_expr(name: str, want_numeric: bool) -> str:
        kind = kind_map.get(name, "text")
        quoted = quote(name)
        if want_numeric:
            if kind == "number":
                return quoted
            return f"TRY_CAST({quoted} AS DOUBLE)"
        return f"CAST({quoted} AS VARCHAR)"

    def nullish_sql(name: str) -> str:
        quoted = quote(name)
        text_expr = f"UPPER(TRIM(CAST({quoted} AS VARCHAR)))"
        placeholders = ", ".join("'" + value.replace("'", "''") + "'" for value in sorted(NULLISH_TEXT_VALUES))
        return f"(({quoted} IS NULL) OR ({text_expr} IN ({placeholders})))"

    def rec(cur) -> Tuple[str, List[Any]]:
        if isinstance(cur, BinaryNode):
            left_sql, left_params = rec(cur.left)
            right_sql, right_params = rec(cur.right)
            return f"({left_sql} {cur.operator} {right_sql})", [*left_params, *right_params]

        if isinstance(cur, UnaryNode):
            inner_sql, params = rec(cur.expr)
            return f"(NOT ({inner_sql}))", params

        if isinstance(cur, ComparisonNode):
            op = cur.operator
            numeric = _is_numeric_literal(cur.value) or _all_numeric(cur.values or ())
            col_sql = column_expr(cur.column, numeric and op not in ("LIKE", "NOT LIKE"))

            if op == "IS NULL":
                return nullish_sql(cur.column), []
            if op == "IS NOT NULL":
                return f"(NOT {nullish_sql(cur.column)})", []
            if op in ("LIKE", "NOT LIKE"):
                sql = f"({column_expr(cur.column, False)} {op} ?)"
                return sql, [str(cur.value.value if cur.value else "")]
            if op in ("IN", "NOT IN"):
                values = list(cur.values or ())
                if not values:
                    return ("(1 = 0)" if op == "IN" else "(1 = 1)"), []
                placeholders = ", ".join("?" for _ in values)
                params = [_literal_param(v) for v in values]
                return f"({col_sql} {op} ({placeholders}))", params
            return f"({col_sql} {op} ?)", [_literal_param(cur.value)]

        raise TypeError(f"Unsupported node: {type(cur)!r}")

    return rec(node)


def _literal_param(value: Optional[LiteralValue]):
    if value is None or value.kind == "null":
        return None
    return value.value


def apply_to_dataframe(df: pd.DataFrame, node, column_info: Dict[str, Dict[str, Any]]) -> pd.Series:
    if node is None:
        return pd.Series([True] * len(df), index=df.index)

    kind_map = _kind_map(column_info)

    def as_text(series: pd.Series) -> pd.Series:
        return series.astype("string")

    def as_numeric(series: pd.Series) -> pd.Series:
        return pd.to_numeric(series, errors="coerce")

    def rec(cur) -> pd.Series:
        if isinstance(cur, BinaryNode):
            left = rec(cur.left).fillna(False)
            right = rec(cur.right).fillna(False)
            if cur.operator == "AND":
                return left & right
            return left | right

        if isinstance(cur, UnaryNode):
            return ~rec(cur.expr).fillna(False)

        if isinstance(cur, ComparisonNode):
            series = df[cur.column]
            kind = kind_map.get(cur.column, "text")
            op = cur.operator

            if op == "IS NULL":
                return _nullish_mask(series)
            if op == "IS NOT NULL":
                return ~_nullish_mask(series)

            if op in ("LIKE", "NOT LIKE"):
                regex = _like_to_regex(str(cur.value.value if cur.value else ""))
                mask = as_text(series).str.match(regex, na=False)
                return ~mask if op == "NOT LIKE" else mask

            numeric = (_is_numeric_literal(cur.value) or _all_numeric(cur.values or ())) and kind == "number"
            if op in ("IN", "NOT IN"):
                if numeric:
                    series_cmp = as_numeric(series)
                    values = [v.value for v in (cur.values or ())]
                else:
                    series_cmp = as_text(series)
                    values = [None if v.kind == "null" else str(v.value) for v in (cur.values or ())]
                    values = [v for v in values if v is not None]
                mask = series_cmp.isin(values)
                return ~mask if op == "NOT IN" else mask

            if numeric:
                series_cmp = as_numeric(series)
                rhs = cur.value.value if cur.value else math.nan
            else:
                series_cmp = as_text(series)
                rhs = None if not cur.value or cur.value.kind == "null" else str(cur.value.value)

            if op == "=":
                return series_cmp == rhs
            if op == "!=":
                return series_cmp != rhs
            if op == ">":
                return series_cmp > rhs
            if op == ">=":
                return series_cmp >= rhs
            if op == "<":
                return series_cmp < rhs
            if op == "<=":
                return series_cmp <= rhs
            raise TypeError(f"Unsupported operator: {op}")

        raise TypeError(f"Unsupported node: {type(cur)!r}")

    return rec(node).fillna(False)


def validate_expression(expr: str, columns: Sequence[str]) -> Dict[str, Any]:
    text = str(expr or "").strip()
    if not text:
        return {
            "valid": True,
            "normalized_expression": "",
            "referenced_columns": [],
            "errors": [],
            "suggestions": [],
        }

    try:
        parser = FilterParser(text, columns)
        node = parser.parse()
        return {
            "valid": True,
            "normalized_expression": normalize_expression(node),
            "referenced_columns": parser.referenced_columns,
            "errors": [],
            "suggestions": [],
            "ast": node,
        }
    except FilterValidationError as exc:
        return {
            "valid": False,
            "normalized_expression": "",
            "referenced_columns": [],
            "errors": [str(exc)],
            "suggestions": exc.suggestions or [],
        }
