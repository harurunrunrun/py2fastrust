"""Non-executable metadata for ahead-of-time Rust functions."""


def comprehension_names(program, code_id):
    owner = program.codes[code_id]
    inline = []
    for instruction in owner.ops:
        if instruction.op == "BeginComprehension":
            for name in program.codes[instruction.args[0]].locals:
                if name != ".0" and not name.startswith(("$", "\0")) and name not in inline:
                    inline.append(name)
    if not inline:
        return owner.locals.copy()
    parameters = owner.params
    arguments = parameters.positional + parameters.kwonly + [parameters.vararg, parameters.kwarg]
    cells = set()
    for instruction in owner.ops:
        if instruction.op == "MakeFunction":
            for name in program.codes[instruction.args[0]].frees:
                if name in owner.locals and name not in inline and name not in arguments:
                    cells.add(name)
    names = []
    for instruction in owner.ops:
        candidates = (program.codes[instruction.args[0]].locals if instruction.op == "BeginComprehension" else
                      [instruction.args[0]] if instruction.op in {"Load", "Store", "Delete"} else [])
        for name in candidates:
            if (name in owner.locals or name in inline) and name not in cells and name not in names:
                names.append(name)
    for name in owner.locals:
        if name not in cells and name not in names:
            names.append(name)
    return names + sorted(cells)


def metadata(program, code_id):
    code = program.codes[code_id]
    finally_ends = []
    for instruction in code.ops:
        if instruction.op != "SetupFinally":
            continue
        start = instruction.args[0]
        depth = 0
        end = None
        for position in range(start, len(code.ops)):
            operation = code.ops[position].op
            if operation == "SetupFinally":
                depth += 1
            elif operation == "EndFinally":
                if depth == 0:
                    end = position
                    break
                depth -= 1
        finally_ends.append((start, end))
    return {
        "locations": [(instruction.line, instruction.column) for instruction in code.ops],
        "children": [instruction.args[1] if instruction.op in {"MakeClass", "MakeClassEx"} else instruction.args[0]
                     for instruction in code.ops if instruction.op in {"MakeFunction", "PrepareClass", "MakeClass", "MakeClassEx"}],
        "functions": [instruction.args[0] for instruction in code.ops if instruction.op == "MakeFunction"],
        "comprehension_names": comprehension_names(program, code_id),
        "class_cell_load": any(instruction.op == "Load" and instruction.args[0] in {"__class__", "super"} for instruction in code.ops),
        "yields": [position for position, instruction in enumerate(code.ops) if instruction.op == "Yield"],
        "yield_from": [position for position, instruction in enumerate(code.ops) if instruction.op == "YieldFrom"],
        "finally_ends": finally_ends,
    }


def metadata_expression(program, code_id):
    from .codegen import string
    data = metadata(program, code_id)
    fields = []
    for name, value in data.items():
        if name == "class_cell_load":
            literal = str(value).lower()
        elif name == "comprehension_names":
            literal = "vec![" + ",".join(string(item) for item in value) + "]"
        elif name in {"locations", "finally_ends"}:
            literal = "vec![" + ",".join(f"({left},{right if right is not None else 'usize::MAX'})" for left, right in value) + "]"
        else:
            literal = "vec![" + ",".join(str(item) for item in value) + "]"
        fields.append(f"{name}:{literal}")
    return "CompiledMetadata{" + ",".join(fields) + "}"


def metadata_runtime_source(include_dynamic=True):
    """Select metadata accessors without retaining an unused instruction type."""
    from importlib.resources import files
    runtime = files("py2fastrust").joinpath("runtime")
    common = runtime.joinpath("code_metadata.rs").read_text(encoding="utf-8")
    if include_dynamic:
        return common
    declarations = common[:common.index("impl Code {")]
    return declarations + runtime.joinpath("code_metadata_static.rs").read_text(encoding="utf-8")
