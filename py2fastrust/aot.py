"""Generate direct Rust basic blocks from the compiler's executable IR.

The runtime operation implementation supplies statement templates. It is read
at conversion time: generated static functions contain no Op construction or
opcode dispatch, and continue to share value, GC and exception helpers.
"""
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
import re

from .diagnostics import CompilationError, Diagnostic

RAW_STRING = re.compile(r'(?:br|r)(#*)"')
CHARACTER = re.compile(r"'(?:\\(?:u\{[0-9a-fA-F_]+\}|x[0-9a-fA-F]{2}|.)|[^'\\\n])'")


def rust_mask(source):
    """Mask Rust comments and literals while preserving source offsets."""
    result = list(source)
    index = 0
    while index < len(source):
        end = None
        if source.startswith("//", index):
            end = source.find("\n", index)
            if end < 0:
                end = len(source)
        elif source.startswith("/*", index):
            end = index + 2
            depth = 1
            while depth and end < len(source):
                if source.startswith("/*", end):
                    depth += 1
                    end += 2
                elif source.startswith("*/", end):
                    depth -= 1
                    end += 2
                else:
                    end += 1
            if depth:
                raise ValueError("unterminated Rust comment")
        else:
            raw = RAW_STRING.match(source, index) if source[index] in "rb" else None
            if raw:
                closing = '"' + raw.group(1)
                position = source.find(closing, raw.end())
                if position < 0:
                    raise ValueError("unterminated Rust raw string")
                end = position + len(closing)
            elif source[index] == '"':
                end = index + 1
                while end < len(source):
                    if source[end] == "\\":
                        end += 2
                    elif source[end] == '"':
                        end += 1
                        break
                    else:
                        end += 1
            elif source[index] == "'":
                char = CHARACTER.match(source, index)
                if char:
                    end = char.end()
        if end is not None:
            for position in range(index, min(end, len(source))):
                if result[position] != "\n":
                    result[position] = " "
            index = end
        else:
            index += 1
    return "".join(result)


def closing(masked, start):
    pairs = {"(": ")", "[": "]", "{": "}"}
    stack = [pairs[masked[start]]]
    for index in range(start + 1, len(masked)):
        char = masked[index]
        if char in pairs:
            stack.append(pairs[char])
        elif char in ")]}":
            if not stack or char != stack.pop():
                raise ValueError("unbalanced Rust delimiters")
            if not stack:
                return index
    raise ValueError("unterminated Rust delimiter")


def split_top(source, separator=","):
    masked = rust_mask(source)
    parts = []
    start = 0
    index = 0
    while index < len(source):
        if masked[index] in "([{":
            index = closing(masked, index) + 1
        elif masked.startswith(separator, index):
            parts.append(source[start:index].strip())
            index += len(separator)
            start = index
        else:
            index += 1
    parts.append(source[start:].strip())
    return [part for part in parts if part]


def match_arms(source):
    masked = rust_mask(source)
    index = 0
    while index < len(source):
        while index < len(source) and (masked[index].isspace() or masked[index] == ","):
            index += 1
        if index == len(source):
            break
        start = index
        while not masked.startswith("=>", index):
            if masked[index] in "([{":
                index = closing(masked, index) + 1
            else:
                index += 1
            if index >= len(source):
                raise ValueError("missing Rust match arm arrow")
        pattern = source[start:index].strip()
        index += 2
        while masked[index].isspace():
            index += 1
        start = index
        if masked[index] == "{":
            index = closing(masked, index) + 1
            expression = source[start:index]
        else:
            while index < len(source) and masked[index] != ",":
                if masked[index] in "([{":
                    index = closing(masked, index) + 1
                else:
                    index += 1
            expression = source[start:index].strip()
        yield pattern, expression


@dataclass(frozen=True)
class Template:
    pattern: str
    expression: str
    types: tuple


@lru_cache(maxsize=4)
def templates(runtime_source):
    masked = rust_mask(runtime_source)
    enum_start = masked.index("enum Op {") + len("enum Op ")
    enum_end = closing(masked, enum_start)
    types = {}
    for variant in split_top(runtime_source[enum_start + 1:enum_end]):
        name = re.match(r"\w+", variant).group()
        tail = variant[len(name):].strip()
        if tail.startswith("("):
            types[name] = tuple(split_top(tail[1:-1]))
        elif tail.startswith("{"):
            types[name] = tuple(tuple(field.split(":", 1)) for field in split_top(tail[1:-1]))
        else:
            types[name] = ()
    step_start = masked.index("fn step(")
    match_start = masked.index("match op {", step_start) + len("match op ")
    match_end = closing(masked, match_start)
    result = {}
    for pattern, expression in match_arms(runtime_source[match_start + 1:match_end]):
        for variant in split_top(pattern, "|"):
            name = re.match(r"Op::(\w+)", variant).group(1)
            result[name] = Template(variant, expression, types[name])
    if result.keys() != types.keys():
        raise ValueError("incomplete Rust operation templates")
    return result


def specialize(expression, operation):
    """Resolve variant tests in shared templates before emitting Rust."""
    while True:
        masked = rust_mask(expression)
        found = re.search(r"\bmatch\s+op\s*\{", masked)
        if not found:
            break
        start = masked.index("{", found.start())
        end = closing(masked, start)
        arms = list(match_arms(expression[start + 1:end]))
        if not any("Op::" in pattern for pattern, _ in arms):
            raise ValueError("unrecognized static operation match")
        selected = next(value for pattern, value in arms
                        if pattern == "_" or re.search(rf"\bOp::{operation}\b", pattern))
        expression = expression[:found.start()] + selected + expression[end + 1:]
    while True:
        masked = rust_mask(expression)
        found = re.search(r"\bmatches!\(\s*op\s*,", masked)
        if not found:
            break
        start = masked.index("(", found.start())
        end = closing(masked, start)
        pattern = expression[masked.index(",", start) + 1:end]
        if "Op::" not in pattern:
            raise ValueError("unrecognized static operation predicate")
        selected = str(pattern.strip() == "_" or bool(re.search(rf"\bOp::{operation}\b", pattern))).lower()
        expression = expression[:found.start()] + selected + expression[end + 1:]
    return expression


def statement(instruction, template):
    from .codegen import operation
    rendered = operation(instruction)
    name = instruction.op
    suffix = rendered[len("Op::" + name):].strip()
    pattern = template.pattern[len("Op::" + name):].strip()
    bindings = []
    if pattern.startswith("("):
        names = split_top(pattern[1:-1])
        values = split_top(suffix[1:-1])
        bindings = [(key, field_type, value)
                    for key, field_type, value in zip(names, template.types, values, strict=True)]
    elif pattern.startswith("{"):
        names = split_top(pattern[1:-1])
        values = dict(field.split(":", 1) for field in split_top(suffix[1:-1]))
        field_types = dict((key.strip(), value.strip()) for key, value in template.types)
        bindings = [(key.strip(), field_types[key.strip()], values[key.strip()].strip()) for key in names]
    prefix = "\n".join(f"let {key}: {field_type} = {value};" for key, field_type, value in bindings if key != "_")
    expression = specialize(template.expression, name)
    body = expression[1:-1] if expression.startswith("{") else expression + ";"
    return "{\n" + prefix + "\n" + body + "\n}"


TRANSFER = {"Jump", "JumpTrue", "JumpFalse", "ForIter", "Break", "Continue", "Return", "Yield", "YieldFrom", "Raise", "EndFinally", "EndExceptStar"}
TARGET = {"Jump", "JumpTrue", "JumpFalse", "ForIter", "Break", "Continue", "SetupExcept", "SetupFinally"}


def basic_blocks(code, available):
    leaders = {0, len(code.ops)}
    for index, instruction in enumerate(code.ops):
        # A delegated yield resumes the same statement, rather than its successor.
        if instruction.op == "YieldFrom":
            leaders.add(index)
        if instruction.op in TARGET:
            leaders.add(instruction.args[0])
        body = available[instruction.op].expression
        if instruction.op in TRANSFER or "start_protocol" in body or "next_call" in body:
            leaders.add(index + 1)
    positions = sorted(leaders)
    return [(start, end) for start, end in zip(positions, positions[1:]) if start < end]


def generate(program, runtime_source=None):
    runtime_source = runtime_source or files("py2fastrust").joinpath("runtime", "vm.rs").read_text(encoding="utf-8")
    available = templates(runtime_source)
    parts = ["// Direct Rust execution for every statically compiled Python code body.\nimpl Runtime {"]
    for code_id, code in enumerate(program.codes):
        parts.append(f"fn generated_aot_code_{code_id}(&mut self,f:&mut Frame,root_index:usize)->PyResult<Option<FrameExit>> {{")
        parts.append("if f.pc==0 {f.pc=1;if let Some(value)=self.try_native_leaf(f){return Ok(Some(FrameExit::Return(value)));}f.pc=0;}")
        parts.append("match f.pc {")
        for start, end in basic_blocks(code, available):
            parts.append(f"{start} => {{")
            for position in range(start, end):
                instruction = code.ops[position]
                try:
                    emitted = statement(instruction, available[instruction.op])
                except (KeyError, ValueError, StopIteration) as error:
                    raise CompilationError(Diagnostic(f"cannot generate direct Rust for {instruction.op}: {error}",
                                                      code.filename, instruction.line, instruction.column + 1, "E006")) from error
                parts.append(f"self.compiled_frame_checkpoint(f,root_index);f.pc={position + 1};")
                parts.append(emitted)
            parts.append("Ok(None)\n}")
        parts.append('_ => Err(pyerr("RuntimeError","invalid AOT continuation")),\n}\n}')
    parts.append("}\n")
    result = "\n".join(parts)
    if re.search(r"\bOp::", rust_mask(result)):
        raise ValueError("static Rust generation retained an operation tag")
    return result


def _remove_definition(source, marker):
    masked = rust_mask(source)
    start = masked.index(marker)
    opening = masked.index("{", start)
    end = closing(masked, opening) + 1
    line = source.rfind("\n", 0, start) + 1
    previous = source.rfind("\n", 0, max(0, line - 1)) + 1
    if source[previous:line].lstrip().startswith("#[derive("):
        line = previous
    return source[:line] + source[end:]


def runtime_source(source, include_dynamic=True):
    """A closed program has no instruction interpreter or instruction type."""
    if include_dynamic:
        return source
    fallback = '''                let ins = self.codes[f.code].ops[f.pc].clone();
                f.pc += 1;
                self.step(&mut f, ins.op)'''
    if source.count(fallback) != 1:
        raise ValueError("cannot locate dynamic-only instruction execution")
    source = source.replace(fallback, '                Err(pyerr("RuntimeError","missing compiled code entry"))', 1)
    source = _remove_definition(source, "fn step(")
    source = _remove_definition(source, "enum Op {")
    source = _remove_definition(source, "struct Instr {")
    source, count = re.subn(r"^\s*ops:\s*Vec<Instr>,\n", "", source, count=1, flags=re.MULTILINE)
    if count != 1 or re.search(r"\bOp\b|\bInstr\b|\.ops\b", rust_mask(source)):
        raise ValueError("closed runtime retains an instruction dependency")
    return source
