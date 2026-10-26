"""Generate Rust PEG tables from the unmodified CPython 3.14.4 grammar.

Bindings and rule boundaries are retained in the concrete syntax tree. CPython's
C semantic actions are not executed by this generator: AST construction and
context-sensitive validation belong to the runtime compiler's lowering pass.
"""

import argparse
import ast
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
GRAMMAR = ROOT / "py2fastrust/grammar/python3.14.4.gram"
TOKENS = ROOT / "py2fastrust/grammar/Tokens"
OUTPUT = ROOT / "py2fastrust/runtime/peg_tables.rs"
UPSTREAM = {
    GRAMMAR: "7b27b04bf7989ef64349e651aaccde6e114d1d0b",
    TOKENS: "0547e6ed08f79ae397836c1b426af7760f7199ce",
}


def verify_upstream():
    for path, expected in UPSTREAM.items():
        content = path.read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
        if actual != expected:
            raise ValueError(f"modified upstream source: {path}: {actual}")


def quoted_end(source, start):
    quote = source[start]
    at = start + 1
    while at < len(source):
        if source[at] == "\\":
            at += 2
        elif source[at] == quote:
            return at + 1
        else:
            at += 1
    raise ValueError(f"unterminated grammar/action string at {start}")


def grammar_without_actions(source):
    source = source[source.index("\nfile[") + 1:]
    result = []
    at = 0
    while at < len(source):
        char = source[at]
        if char in "'\"":
            end = quoted_end(source, at)
            result.append(source[at:end])
            at = end
        elif char == "#":
            end = source.find("\n", at)
            at = len(source) if end == -1 else end
        elif char == "{":
            begin = at
            depth = 1
            at += 1
            while depth:
                if at == len(source):
                    raise ValueError("unterminated C action")
                if source[at] in "'\"":
                    at = quoted_end(source, at)
                elif source.startswith("//", at):
                    end = source.find("\n", at)
                    at = len(source) if end == -1 else end
                elif source.startswith("/*", at):
                    end = source.find("*/", at + 2)
                    if end == -1:
                        raise ValueError("unterminated C comment")
                    at = end + 2
                else:
                    depth += (source[at] == "{") - (source[at] == "}")
                    at += 1
            result.append("".join("\n" if c == "\n" else " " for c in source[begin:at]))
        else:
            result.append(char)
            at += 1
    return "".join(result)


@dataclass(frozen=True)
class Expr:
    kind: str
    args: tuple = ()


LEX = re.compile(r"\s+|(?:'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\")|[A-Za-z_]\w*|&&|.", re.S)
HEADER = re.compile(r"^([a-z_]\w*)(?:\[[^\]\n]*\])?\s*(?:\(memo\)\s*)?:", re.M)


class GrammarParser:
    def __init__(self, source):
        self.tokens = [m.group() for m in LEX.finditer(source) if not m.group().isspace()]
        self.at = 0

    def peek(self, offset=0):
        return self.tokens[self.at + offset] if self.at + offset < len(self.tokens) else None

    def eat(self, token):
        if self.peek() == token:
            self.at += 1
            return True
        return False

    def expect(self, token):
        if not self.eat(token):
            raise ValueError(f"expected {token!r}, got {self.tokens[self.at:self.at+8]}")

    def parse(self):
        result = self.choice()
        if self.peek() is not None:
            raise ValueError(f"unexpected grammar tokens: {self.tokens[self.at:]}")
        return result

    def choice(self):
        self.eat("|")
        alternatives = [self.sequence()]
        while self.eat("|"):
            alternatives.append(self.sequence())
        return alternatives[0] if len(alternatives) == 1 else Expr("Choice", tuple(alternatives))

    def sequence(self):
        items = []
        while self.peek() not in (None, "|", ")", "]"):
            items.append(self.item())
        return items[0] if len(items) == 1 else Expr("Sequence", tuple(items))

    def item(self):
        label = None
        # Typed bindings have the same [] spelling as optional groups.
        if self.peek() and re.fullmatch(r"[A-Za-z_]\w*", self.peek()):
            if self.peek(1) == "=":
                label = self.peek()
                self.at += 2
            elif self.peek(1) == "[":
                end = self.at + 2
                while end < len(self.tokens) and self.tokens[end] != "]":
                    end += 1
                if end + 1 < len(self.tokens) and self.tokens[end + 1] == "=":
                    label = self.peek()
                    self.at = end + 2
        if self.eat("~"):
            result = Expr("Cut")
        elif self.eat("&&"):
            result = Expr("Force", (self.atom(),))
        elif self.eat("&"):
            result = Expr("Look", (self.atom(), True))
        elif self.eat("!"):
            result = Expr("Look", (self.atom(), False))
        else:
            result = self.atom()
            if self.eat("."):
                separator = result
                result = Expr("Gather", (separator, self.atom()))
                self.expect("+")
            elif self.eat("?"):
                result = Expr("Optional", (result,))
            elif self.eat("*"):
                result = Expr("Repeat", (result, 0))
            elif self.eat("+"):
                result = Expr("Repeat", (result, 1))
        return Expr("Bind", (label, result)) if label else result

    def atom(self):
        if self.eat("("):
            result = self.choice()
            self.expect(")")
            return result
        if self.eat("["):
            result = self.choice()
            self.expect("]")
            return Expr("Optional", (result,))
        token = self.peek()
        if token is None:
            raise ValueError("expected grammar atom")
        self.at += 1
        if token[0] in "'\"":
            return Expr("Literal", (ast.literal_eval(token), token[0] == '"'))
        if re.fullmatch(r"[A-Za-z_]\w*", token):
            return Expr("Token" if token.isupper() else "Rule", (token,))
        raise ValueError(f"unexpected grammar atom {token!r}")


def walk(expression):
    yield expression
    for item in expression.args:
        if isinstance(item, Expr):
            yield from walk(item)


def left_recursion_components(rules):
    nullable = {name: False for name in rules}

    def empty(expr):
        if expr.kind == "Rule":
            return nullable[expr.args[0]]
        if expr.kind in {"Optional", "Look", "Cut"}:
            return True
        if expr.kind == "Repeat":
            return not expr.args[1] or empty(expr.args[0])
        if expr.kind == "Bind":
            return empty(expr.args[1])
        if expr.kind in {"Force", "Gather"}:
            return empty(expr.args[-1])
        if expr.kind == "Choice":
            return any(map(empty, expr.args))
        if expr.kind == "Sequence":
            return all(map(empty, expr.args))
        return False

    while True:
        new = {name: empty(expr) for name, expr in rules.items()}
        if new == nullable:
            break
        nullable = new

    def first(expr):
        if expr.kind == "Rule":
            return {expr.args[0]}
        if expr.kind == "Bind":
            return first(expr.args[1])
        if expr.kind in {"Optional", "Repeat", "Look", "Force"}:
            return first(expr.args[0])
        if expr.kind == "Gather":
            return first(expr.args[1])
        if expr.kind in {"Sequence", "Choice"}:
            result = set()
            for child in expr.args:
                result.update(first(child))
                if expr.kind == "Sequence" and not empty(child):
                    break
            return result
        return set()

    edges = {name: first(expr) for name, expr in rules.items()}
    stack, on_stack, indexes, low, components = [], set(), {}, {}, []

    def visit(name):
        indexes[name] = low[name] = len(indexes)
        stack.append(name)
        on_stack.add(name)
        for child in sorted(edges[name]):
            if child not in indexes:
                visit(child)
                low[name] = min(low[name], low[child])
            elif child in on_stack:
                low[name] = min(low[name], indexes[child])
        if low[name] == indexes[name]:
            component = []
            while True:
                child = stack.pop()
                on_stack.remove(child)
                component.append(child)
                if child == name:
                    break
            components.append(component)

    for name in rules:
        if name not in indexes:
            visit(name)
    return components, {name for group in components for name in group
                        if len(group) > 1 or name in edges[name]}


def generate():
    verify_upstream()
    source = grammar_without_actions(GRAMMAR.read_text())
    headers = list(HEADER.finditer(source))
    rules = {}
    for index, match in enumerate(headers):
        body = source[match.end():headers[index + 1].start() if index + 1 < len(headers) else len(source)]
        name = match[1]
        try:
            rules[name] = Expr("Fail") if name.startswith("invalid_") else GrammarParser(body).parse()
        except ValueError as error:
            raise ValueError(f"rule {name}: {error}") from error
    numbers = {name: index for index, name in enumerate(rules)}
    token_names = {line.split()[0] for line in TOKENS.read_text().splitlines()
                   if line.strip() and not line.startswith("#")}
    for expression in rules.values():
        for node in walk(expression):
            if node.kind == "Rule" and node.args[0] not in rules:
                raise ValueError(f"unknown rule {node.args[0]}")
            if node.kind == "Token" and node.args[0] not in token_names:
                raise ValueError(f"unknown token {node.args[0]}")
    components, recursive = left_recursion_components(rules)
    component_ids = {name: index for index, group in enumerate(components) for name in group}
    expressions, seen = [], {}

    def intern(expr):
        if expr in seen:
            return seen[expr]
        args = expr.args
        if expr.kind in {"Choice", "Sequence"}:
            rendered = "&[" + ",".join(str(intern(child)) for child in args) + "]"
        elif expr.kind == "Rule":
            rendered = str(numbers[args[0]])
        elif expr.kind == "Token":
            rendered = json.dumps(args[0])
        elif expr.kind == "Literal":
            rendered = json.dumps(args[0], ensure_ascii=False) + "," + str(args[1]).lower()
        elif expr.kind == "Bind":
            rendered = json.dumps(args[0]) + "," + str(intern(args[1]))
        elif expr.kind == "Gather":
            rendered = ",".join(str(intern(child)) for child in args)
        elif expr.kind in {"Optional", "Force"}:
            rendered = str(intern(args[0]))
        elif expr.kind in {"Repeat", "Look"}:
            rendered = str(intern(args[0])) + "," + str(args[1]).lower()
        else:
            rendered = ""
        number = len(expressions)
        expressions.append("PegExpr::" + expr.kind + (f"({rendered})" if args else ""))
        seen[expr] = number
        return number

    rule_rows = []
    for name, expression in rules.items():
        rule_rows.append(f'PegRule {{ name:{json.dumps(name)},expression:{intern(expression)},'
                         f'component:{component_ids[name]},recursive:{str(name in recursive).lower()} }}')
    keywords = sorted({node.args[0] for expr in rules.values() for node in walk(expr)
                       if node.kind == "Literal" and not node.args[1] and node.args[0].isidentifier()})
    operators = []
    for line in TOKENS.read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                operators.append((ast.literal_eval(parts[1]), parts[0]))
    operators.sort(key=lambda item: (-len(item[0]), item[0]))
    lines = ["// Generated by tools/generate_peg.py; do not edit.",
             "// Grammar: CPython v3.14.4, PSF License 2; see grammar/NOTICE.txt.",
             "const PEG_EXPRESSIONS: &[PegExpr] = &[", *[line + "," for line in expressions], "];",
             "const PEG_RULES: &[PegRule] = &[", *[line + "," for line in rule_rows], "];",
             "const PEG_COMPONENTS: &[&[usize]] = &[",
             *["&[" + ",".join(str(numbers[name]) for name in group) + "]," for group in components], "];",
             "const PEG_HARD_KEYWORDS: &[&str] = &[" + ",".join(map(json.dumps, keywords)) + "];",
             "const PEG_OPERATORS: &[(&str,&str)] = &[" +
             ",".join(f"({json.dumps(text)},{json.dumps(kind)})" for text, kind in operators) + "];", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    generated = generate()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text() != generated:
            parser.exit(1, f"stale generated PEG tables: {OUTPUT}\n")
    else:
        OUTPUT.write_text(generated)


if __name__ == "__main__":
    main()
