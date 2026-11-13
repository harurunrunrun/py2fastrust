"""Official compiler construction facts for an original set expression context.

Only copied metadata probes are compiled. Original ASTs, scope bindings and
operands remain the authority for native analysis and emission.
"""
import ast,dis,operator,types

from .literal_semantics import integer_policy


def copy_ast(value):
    if isinstance(value,ast.AST):
        result=getattr(ast,type(value).__name__)(**{field:copy_ast(getattr(value,field))for field in value._fields})
        for name in value._attributes:
            if hasattr(value,name):setattr(result,name,getattr(value,name))
        return result
    if isinstance(value,list):return [copy_ast(child)for child in value]
    if isinstance(value,tuple):return tuple(copy_ast(child)for child in value)
    return value


def span(node):return node.lineno,node.end_lineno,node.col_offset,node.end_col_offset


_INTEGER_BINARY={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,
    ast.FloorDiv:operator.floordiv,ast.Mod:operator.mod,ast.Pow:operator.pow,
    ast.LShift:operator.lshift,ast.RShift:operator.rshift,ast.BitAnd:operator.and_,
    ast.BitOr:operator.or_,ast.BitXor:operator.xor}


class PolicyProbe(ast.NodeTransformer):
    """Keep compile-time integer control facts within the declared source policy.

Original CP-folded pure integer operations are folded with width normalization.
Nonfolded pure integer operations stay opaque to the metadata compiler, rather
than acquiring an unbounded-host fold after their operands are normalized.
No user expression or synthesized metadata call is executed.
"""
    def __init__(self,integer):self.policy=integer_policy(0 if integer=='bigint'else int(integer[1:]));self.pure=set()

    def visit_Constant(self,node):
        if type(node.value)is int:node.value=self.policy.normalize(node.value);self.pure.add(id(node))
        elif type(node.value)is bool:self.pure.add(id(node))
        return node

    def visit_UnaryOp(self,node):
        node=self.generic_visit(node)
        operations={ast.UAdd:operator.pos,ast.USub:operator.neg,ast.Invert:operator.invert}
        if type(node.op)in operations and isinstance(node.operand,ast.Constant)and type(node.operand.value)in {int,bool}:
            result=operations[type(node.op)](node.operand.value)
            result=self.policy.normalize(result)if type(result)is int else result
            replacement=ast.copy_location(ast.Constant(result),node);self.pure.add(id(replacement));return replacement
        return node

    def visit_BinOp(self,node):
        original=copy_ast(node)
        node=self.generic_visit(node)
        if type(node.op)not in _INTEGER_BINARY or id(node.left)not in self.pure or id(node.right)not in self.pure:return node
        self.pure.add(id(node))
        instructions=list(dis.get_instructions(compile(ast.Expression(original),'<pytors-set-integer-fact>','eval',optimize=0)))
        instructions=[item for item in instructions if item.opname not in {'RESUME','RETURN_VALUE'}]
        folded=len(instructions)==1 and instructions[0].opname in {'LOAD_CONST','LOAD_SMALL_INT','RETURN_CONST'}
        if folded and isinstance(node.left,ast.Constant)and isinstance(node.right,ast.Constant):
            try:result=_INTEGER_BINARY[type(node.op)](node.left.value,node.right.value)
            except (ArithmeticError,ValueError):pass
            else:
                result=self.policy.normalize(result)if type(result)is int else result
                replacement=ast.copy_location(ast.Constant(result),node)
                if type(result)in {int,bool}:self.pure.add(id(replacement))
                return replacement
        opaque=ast.Call(func=ast.Name(id='_pytors_metadata_integer_operation',ctx=ast.Load()),args=[node.left,node.right],keywords=[])
        ast.copy_location(opaque,node);self.pure.add(id(opaque));return opaque


def _compile(expression,contract,integer):
    expression=copy_ast(expression)
    if integer!='bigint':expression=PolicyProbe(integer).visit(expression)
    if contract=='iteration':
        statement=ast.For(target=ast.Name(id='_pytors_metadata_item',ctx=ast.Store()),iter=expression,body=[ast.Pass()],orelse=[])
    elif contract=='truth':statement=ast.If(test=expression,body=[ast.Pass()],orelse=[])
    else:statement=ast.Expr(value=expression)
    suspension=any(isinstance(item,(ast.Yield,ast.YieldFrom,ast.Await))for item in ast.walk(expression))
    if suspension:
        cls=ast.AsyncFunctionDef if any(isinstance(item,ast.Await)for item in ast.walk(expression))else ast.FunctionDef
        function=cls(name='_pytors_metadata_context',args=ast.arguments(posonlyargs=[],args=[],kwonlyargs=[],kw_defaults=[],defaults=[]),body=[statement],decorator_list=[],type_params=[])
        tree=ast.Module(body=[function],type_ignores=[])
    else:tree=ast.Module(body=[statement],type_ignores=[])
    ast.fix_missing_locations(tree)
    return compile(tree,'<pytors-set-construction>','exec',optimize=0)


def _instructions(code):
    yield from dis.get_instructions(code)
    for constant in code.co_consts:
        if isinstance(constant,types.CodeType):yield from _instructions(constant)


def _classify(code,node):
    wanted=span(node);items=[]
    for item in _instructions(code):
        position=item.positions
        if (position.lineno,position.end_lineno,position.col_offset,position.end_col_offset)==wanted:items.append(item)
    update=any(item.opname=='SET_UPDATE'for item in items)
    add=any(item.opname=='SET_ADD'for item in items)
    build=any(item.opname=='BUILD_SET'and item.arg for item in items)
    frozen=any(item.opname=='LOAD_CONST'and type(item.argval)is frozenset for item in items)
    plans=({'frozen_bulk'}if update else set())|({'incremental'}if add else set())|({'build'}if build else set())
    if frozen and not update:plans.add('frozen_direct')
    if not plans and any(item.opname=='BUILD_SET'for item in items):plans.add('build')
    return plans


def construction_plan(model,node,parents):
    from .native_classes import ClassUnsupported
    if any(isinstance(child,ast.Starred)for child in node.elts):
        raise ClassUnsupported(node,'starred set construction needs the original per-segment BUILD_SET/SET_UPDATE source-consumption plan; this native construction adapter does not implement it yet',proof='CPython set literal expansion history')
    expression=node
    while isinstance(parents.get(id(expression)),ast.expr):expression=parents[id(expression)]
    parent=parents.get(id(expression));contract='value'
    if isinstance(parent,(ast.For,ast.comprehension))and parent.iter is expression:
        if isinstance(parent,ast.comprehension)and parent.is_async:
            raise ClassUnsupported(node,'async comprehension iteration needs its actual GET_AITER construction context',proof='original async set observation context')
        contract='iteration'
    elif (isinstance(parent,(ast.If,ast.While,ast.Assert))and parent.test is expression
          or isinstance(parent,ast.comprehension)and expression in parent.ifs
          or isinstance(parent,ast.match_case)and parent.guard is expression):contract='truth'
    try:
        plans=_classify(_compile(expression,contract,model.integer),node)
        if not plans:
            # With span-preserving BUILD_SET/SET_ADD/SET_UPDATE code generation,
            # an omitted constructor in the policy-normalized context is dead.
            # Its original operands are still emitted only under original lazy
            # control; an isolated value plan supplies well-typed dead code.
            plans=_classify(_compile(node,'value',model.integer),node)
    except (SyntaxError,TypeError,ValueError)as error:
        raise ClassUnsupported(node,'this set literal needs an enclosing compiler context that the metadata probe cannot represent: '+str(error),proof='source-context set construction plan')from None
    if len(plans)!=1:
        raise ClassUnsupported(node,'the official compiler has no single proved construction plan for this original set expression context',proof='original set construction instruction plan')
    return next(iter(plans))
