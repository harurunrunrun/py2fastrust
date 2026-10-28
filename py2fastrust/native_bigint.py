"""Direct Rust lowering for proven arbitrary-precision integer expressions.

Integers are ordinary owned Rust ``Int`` values, not Python object handles.
The fixed-width backend's binding and control-flow proofs are shared; explicit
clones preserve Python's immutable-value semantics without requiring ``Copy``.
Missing direct lowering produces a positioned diagnostic in the public API.
"""

from .native_constraints import ConstraintFailure
from .native_constraint_lowering import result_shapes

import ast
from dataclasses import replace
from .native_types import (TupleType,ListType,MaybeType,TypedListInfo,rust_type,kind_tag,
                           is_maybe,unmaybe,maybe_type,immutable,list_type,default_value,UnionType,NullableType,EmptyType,EMPTY)
from importlib.resources import files
import symtable

from .native import (_Binding, _Expression, _Function, _Generator, _ListInfo, _Specializations,
                     _Unsupported, _OUTPUT_HELPERS, _declarations,
                     _function_plans, _string, _direct_diagnostic)
from .native import _static_reference
from .references import CANONICAL_REBINDABLES
from .native_bigint_lists import BigIntLists, HELPERS as LIST_HELPERS
from .native_bigint_text import BigIntText, HELPERS as BIG_TEXT_HELPERS


_HELPERS = r'''
#[derive(Debug)]
struct NativeError { message: String, line: usize, function: &'static str, frames: Vec<(usize, &'static str)> }
fn native_at<T>(result: Result<T, String>, line: usize, function: &'static str) -> Result<T, NativeError> {
    result.map_err(|message| NativeError { message, line, function, frames: Vec::new() })
}
// Each range owns its cursor. The Python target can be rebound independently.
struct NativeRange { cursor: Int, stop: Int, step: Int, ascending: bool }
impl NativeRange {
    fn new(cursor: Int, stop: Int, step: Int) -> Result<Self,String> {
        if step.is_zero(){return Err("ValueError: range() arg 3 must not be zero".into());}
        let ascending=!step.is_negative();
        Ok(Self {cursor,stop,step,ascending})
    }
}
impl Iterator for NativeRange {
    type Item=Int;
    #[inline(always)]
    fn next(&mut self)->Option<Int> {
        if if self.ascending {self.cursor>=self.stop}else{self.cursor<=self.stop}{return None;}
        let value=self.cursor.clone();
        self.cursor=self.cursor.add(&self.step);
        Some(value)
    }
}
#[derive(Clone)]
enum NativeScalar { Int(Int), Bool(bool) }
impl NativeScalar {
    fn integer(&self)->Int {match self {Self::Int(value)=>value.clone(),Self::Bool(value)=>Int::from_i128(*value as i128)}}
    fn truth(&self)->bool {match self {Self::Int(value)=>!value.is_zero(),Self::Bool(value)=>*value}}
    fn bitand(self,other:Self)->Self {match (&self,&other) {(Self::Bool(a),Self::Bool(b))=>Self::Bool(a&b),_=>Self::Int(self.integer().bitand(&other.integer()))}}
    fn bitor(self,other:Self)->Self {match (&self,&other) {(Self::Bool(a),Self::Bool(b))=>Self::Bool(a|b),_=>Self::Int(self.integer().bitor(&other.integer()))}}
    fn bitxor(self,other:Self)->Self {match (&self,&other) {(Self::Bool(a),Self::Bool(b))=>Self::Bool(a^b),_=>Self::Int(self.integer().bitxor(&other.integer()))}}
}
impl std::fmt::Display for NativeScalar {
    fn fmt(&self,formatter:&mut std::fmt::Formatter<'_>)->std::fmt::Result {
        match self {Self::Int(value)=>std::fmt::Display::fmt(value,formatter),Self::Bool(value)=>formatter.write_str(if *value {"True"}else{"False"})}
    }
}
'''

_INPUT_HELPERS = r'''
struct NativeInput { reader:StandardInput, line:String }
impl NativeInput {
    fn new()->Self {Self {reader:StandardInput::new(),line:String::new()}}
    fn line(&mut self,output:&mut String)->Result<&str,String> {
        if !output.is_empty(){native_flush_output(output)?;}
        self.reader.read_text_into(&mut self.line,None,true).map_err(StandardInputError::native_message)?;
        if self.line.is_empty(){return Err("EOFError: EOF when reading a line".into());}
        if self.line.ends_with('\n'){self.line.pop();}
        Ok(&self.line)
    }
    fn integer(&mut self,output:&mut String)->Result<Int,String> {Int::parse(self.line(output)?,10)}
}
fn native_space(character:char)->bool {character.is_whitespace()||('\u{1c}'..='\u{1f}').contains(&character)}
'''


class BigIntGenerator(BigIntText, BigIntLists, _Generator):
    BUILTINS = _Generator.BUILTINS | {"bool", "reversed", "str"}

    def __init__(self, bits=0, functions=None, function=None, function_input=False, constructors=None, specializations=None):
        super().__init__(0, functions, function, function_input, constructors, specializations)

    def normalize(self, value):
        from .literal_semantics import integer_policy
        return integer_policy(0).normalize(value)

    def literal(self, value):
        from .literal_semantics import integer_policy
        return integer_policy(0).rust_literal(value,_string)

    def slot(self, kind):
        if isinstance(unmaybe(kind),(TupleType,ListType,UnionType,NullableType,EmptyType)) or getattr(unmaybe(kind),"_key_container",False):return super().slot(kind)
        if kind == "str":
            self.has_big_text = True
            slot = f"native_var_{len(self.bindings)}"
            self.bindings[slot] = kind
            return slot
        if unmaybe(kind) not in {"int", "bool", "int_bool", "list_int", "str", "bytes", "none"}:
            raise _Unsupported
        return super().slot(kind)

    @staticmethod
    def number(expression):
        if isinstance(expression.kind,EmptyType):return f"native_empty::<NativeInt>({expression.code})"
        if expression.kind == "int":
            return expression.code
        if expression.kind == "bool":
            return f"Int::from_i128(({expression.code}) as i128)"
        if expression.kind == "int_bool":
            return f"({expression.code}).integer()"
        raise _Unsupported

    @staticmethod
    def coerce(expression, kind):
        if isinstance(expression.kind,EmptyType):return f"native_empty::<{rust_type(kind)}>({expression.code})"
        from .native_tuples import coerce_structural
        from .native_unions import coerce_union
        finite=coerce_union(expression,kind,BigIntGenerator.coerce)
        if finite is not None:return finite
        if is_maybe(kind):
            if expression.kind==kind:return expression.code if not immutable(unmaybe(kind)) and expression.owned else f"({expression.code}).clone()"
            if is_maybe(expression.kind):
                if not immutable(unmaybe(expression.kind)):
                    if not expression.owned:raise _Unsupported
                    item=_Expression("native_optional",unmaybe(expression.kind))
                    return f"({expression.code}).map(|native_optional|{BigIntGenerator.coerce(item,unmaybe(kind))})"
                item=_Expression("native_optional.clone()",unmaybe(expression.kind))
                return f"({expression.code}).as_ref().map(|native_optional|{BigIntGenerator.coerce(item,unmaybe(kind))})"
            return f"Some({BigIntGenerator.coerce(expression,unmaybe(kind))})"
        from .native_constraints import canonical_kind
        source_shape=canonical_kind(expression.kind);target_shape=canonical_kind(kind)
        if isinstance(source_shape,ListType) and isinstance(target_shape,ListType):
            return coerce_structural(replace(expression,kind=source_shape),target_shape,BigIntGenerator.coerce)
        structural=coerce_structural(expression,kind,BigIntGenerator.coerce)
        if structural is not None:return structural
        if expression.kind == kind:
            if kind=="str":return f"({expression.code}).clone()"
            return f"({expression.code}).clone()" if kind in {"int","int_bool","bytes"} else expression.code
        if kind == "int_bool" and expression.kind in {"int", "bool"}:
            variant = "Int" if expression.kind == "int" else "Bool"
            value = f"({expression.code}).clone()" if expression.kind == "int" else expression.code
            return f"NativeScalar::{variant}({value})"
        raise _Unsupported

    @staticmethod
    def truth(expression):
        from .native_characters import truth as character_truth
        character=character_truth(expression)
        if character is not None:return character
        if isinstance(expression.kind,EmptyType):return f"native_empty::<bool>({expression.code})"
        from .native_unions import truth
        finite=truth(expression,BigIntGenerator.truth)
        if finite is not None:return finite
        if isinstance(expression.kind,(TupleType,ListType)) or getattr(expression.kind,"_key_container",False):return _Generator.truth(expression)
        if expression.kind in {"str","bytes"}:
            return f"!({expression.code}).is_empty()"
        if expression.kind == "list_int":
            return f"!({expression.code}).is_empty()"
        if expression.kind == "int":
            return f"!({expression.code}).is_zero()"
        if expression.kind == "int_bool":
            return f"({expression.code}).truth()"
        if expression.kind == "bool":
            return expression.code
        raise _Unsupported

    def scalar_kind(self, values):
        if values and all(value.kind == "str" for value in values):
            return "str"
        return super().scalar_kind(values)

    def integer_bit_query(self, node, environment):
        value = self.expression(node.func.value, environment)
        method = node.func.attr
        code = f"Int::from_i128(({self.number(value)}).{method}() as i128)"
        constant = None if value.constant is None else getattr(int(value.constant), method)()
        return _Expression(code, "int", constant)

    @result_shapes
    def expression(self, node, environment):
        if isinstance(node,(ast.Compare,ast.BoolOp,ast.IfExp)):
            from .native_expression_flow import lower
            return lower(self,node,environment)
        from .native_clear import try_expression as clear_expression
        cleared=clear_expression(self,node,environment)
        if cleared is not None:return cleared
        from .native_characters import read_local
        character=read_local(self,node,environment)
        if character is not None:return character
        from .native_text_predicates import try_expression as predicate_expression
        predicate=predicate_expression(self,node,environment)
        if predicate is not None:return predicate
        from .native_constraint_lowering import allocation_expression
        allocated=allocation_expression(self,node,environment)
        if allocated is not None:return allocated
        from .native_unions import leaf_expression
        leaf=leaf_expression(self,node,environment)
        if leaf is not None:return leaf
        from .native_module_calls import try_expression as module_expression
        module=module_expression(self,node,environment)
        if module is not None:return module
        from .native_stdio import try_expression
        stdio=try_expression(self,node,environment)
        if stdio is not None:
            return stdio
        from .native_key_containers import try_expression as key_expression
        keyed=key_expression(self,node,environment)
        if keyed is not None:return keyed
        from .native_typed_lists import try_expression
        typed=try_expression(self,node,environment)
        if typed is not None:return typed
        from .native_next import try_expression
        following=try_expression(self,node,environment)
        if following is not None:return following
        from .native_tuples import try_expression
        structural=try_expression(self,node,environment)
        if structural is not None:return structural
        text = self.text_expression(node, environment)
        if text is not None:
            return text
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
            from .native_slices import try_slice
            return try_slice(self, node, environment)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "sorted":
            from .native_slices import sorted_list
            return sorted_list(self, node, environment)
        from .native_iterators import try_reduction
        reduction = try_reduction(self, node, environment)
        if reduction is not None:
            return reduction
        result = self.list_expression(node, environment)
        if result is not None:
            return result
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"bit_length", "bit_count"}
                and not node.args and not node.keywords):
            return self.integer_bit_query(node, environment)
        if isinstance(node, ast.Name):
            binding = environment.get(node.id)
            if isinstance(binding, _Binding) and isinstance(binding.info, _ListInfo):
                return _Expression(binding.slot,"list_int",owned=False,length=binding.info.length)
            if isinstance(binding, _Binding) and (is_maybe(binding.kind) or isinstance(binding.kind,EmptyType)):
                return super().expression(node, environment)
            if not isinstance(binding, _Binding) or binding.kind not in {"int", "bool", "int_bool"}:
                raise _Unsupported
            return _Expression(self.coerce(_Expression(binding.slot,binding.kind),binding.kind),binding.kind)
        if isinstance(node, ast.Constant):
            from .literal_semantics import Literal
            literal=Literal.from_ast(node)
            if literal is not None and literal.kind in {"int","bool"}:
                return _Expression(literal.rust_atom(self.literal,_string),literal.kind,literal.value)
            raise _Unsupported("this literal kind has no integrated native value/operation representation on the BigInt scalar path",node=node,types=(("literal",literal.kind if literal is not None else None),),proof="BigInt-path literal value representation")
        if isinstance(node, ast.UnaryOp):
            value = self.expression(node.operand,environment)
            if isinstance(node.op, ast.Not):
                return _Expression(f"!({self.truth(value)})","bool",None if value.constant is None else not value.constant)
            number = self.number(value)
            if isinstance(node.op, ast.UAdd):
                return _Expression(number,"int",value.constant)
            if isinstance(node.op, ast.USub):
                return _Expression(f"({number}).neg()","int",None if value.constant is None else -value.constant)
            if isinstance(node.op, ast.Invert):
                return _Expression(f"({number}).invert()","int",None if value.constant is None else ~value.constant)
            raise _Unsupported
        if isinstance(node, ast.BinOp):
            return self.binary(node.op,self.expression(node.left,environment),self.expression(node.right,environment),node)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            function = environment.get(node.func.id)
            if isinstance(function, _Function):
                return self.user_call(node,function,environment)
            name = node.func.id
            if node.keywords:
                raise _Unsupported
            if name in {"int","bool"} and not node.args:
                return _Expression(self.literal(0),"int",0) if name == "int" else _Expression("false","bool",False)
            if name in {"int","bool"} and len(node.args) == 1:
                argument = node.args[0]
                if name == "int" and isinstance(argument,ast.Call) and isinstance(argument.func,ast.Name) and argument.func.id == "input" and not argument.args and not argument.keywords:
                    self.has_input = True
                    return _Expression(self.at("native_input.integer(&mut native_output)",argument),"int")
                if name == "int" and isinstance(argument,ast.Constant) and type(argument.value) is str:
                    return _Expression(self.at(f"Int::parse({_string(argument.value)},10)",node),"int")
                value = self.expression(argument,environment)
                if name == "bool":
                    return _Expression(self.truth(value),"bool",None if value.constant is None else bool(value.constant))
                return _Expression(self.number(value),"int",value.constant)
            if name == "abs" and len(node.args) == 1:
                value = self.expression(node.args[0],environment)
                return _Expression(f"({self.number(value)}).abs()","int",None if value.constant is None else abs(value.constant))
            if name == "pow" and len(node.args) in {2,3}:
                arguments = [self.expression(value,environment) for value in node.args]
                if len(arguments) == 2:
                    return self.binary(ast.Pow(),*arguments,node)
                names = [self.temporary() for _ in arguments]
                setup = " ".join(f"let {name}={self.number(value)};" for name,value in zip(names,arguments))
                call = self.at(f"{names[0]}.modpow(&{names[1]},&{names[2]})",node)
                return _Expression(f"{{{setup} {call}}}","int")
        raise _Unsupported

    def binary(self, operator, left, right, node):
        text = self.text_binary(operator, left, right, node)
        if text is not None:
            return text
        result = self.list_binary(operator,left,right,node)
        if result is not None:
            return result
        if isinstance(operator,(ast.BitAnd,ast.BitOr,ast.BitXor)) and left.kind == right.kind == "bool":
            return super().binary(operator,left,right,node)
        if (isinstance(operator,(ast.BitAnd,ast.BitOr,ast.BitXor)) and "int_bool" in (left.kind,right.kind)
                and left.kind in {"bool","int_bool"} and right.kind in {"bool","int_bool"}):
            return super().binary(operator,left,right,node)
        first,second = self.temporary(),self.temporary()
        setup = f"let {first}={self.number(left)}; let {second}={self.number(right)};"
        simple = {ast.Add:"add",ast.Sub:"sub",ast.Mult:"mul",ast.BitAnd:"bitand",ast.BitOr:"bitor",ast.BitXor:"bitxor"}
        if type(operator) in simple:
            result = f"{first}.{simple[type(operator)]}(&{second})"
        elif isinstance(operator,(ast.FloorDiv,ast.Mod)):
            result = f"({self.at(f'{first}.divmod(&{second})',node)}).{0 if isinstance(operator,ast.FloorDiv) else 1}"
        elif isinstance(operator,(ast.LShift,ast.RShift)):
            method = "shl" if isinstance(operator,ast.LShift) else "shr"
            result = self.at(f"{first}.{method}(&{second})",node)
        elif isinstance(operator,ast.Pow):
            # Negative exponent results need additional direct float lowering.
            if right.constant is None or right.constant < 0:
                raise _Unsupported
            result = self.at(f"{first}.pow(&{second})",node)
        else:
            raise _Unsupported
        constant = None
        if left.constant is not None and right.constant is not None:
            x,y = int(left.constant),int(right.constant)
            try:
                if isinstance(operator,ast.Add): constant=x+y
                elif isinstance(operator,ast.Sub): constant=x-y
                elif isinstance(operator,ast.Mult) and x.bit_length()+y.bit_length()<=4096: constant=x*y
                elif isinstance(operator,ast.FloorDiv): constant=x//y
                elif isinstance(operator,ast.Mod): constant=x%y
                elif isinstance(operator,ast.BitAnd): constant=x&y
                elif isinstance(operator,ast.BitOr): constant=x|y
                elif isinstance(operator,ast.BitXor): constant=x^y
                elif isinstance(operator,ast.LShift) and 0<=y<=4096: constant=x<<y
                elif isinstance(operator,ast.RShift) and y>=0: constant=x>>y
                elif isinstance(operator,ast.Pow) and 0<=y and max(1,x.bit_length())*y<=4096: constant=x**y
            except (ValueError,ZeroDivisionError):
                pass
        return _Expression(f"{{{setup} {result}}}","int",constant)


    def range_iterator(self, node, environment):
        from .native_stream_lowering import integer_range
        return integer_range(self,node,environment)

    def finish_loop(self, node, entry, header, context, body, remaining, nonempty, may_repeat, zero=False):
        return super().finish_loop(node,entry,header,context,body,remaining,nonempty,may_repeat,zero)

    def statement(self, node, environment):
        from .native_constraint_lowering import reset_statement
        reset=reset_statement(self,node,environment)
        if reset is not None:return reset
        from .native_module_calls import try_statement as module_statement
        module=module_statement(self,node,environment)
        if module is not None:return module
        from .native_stdio import try_statement
        stdio=try_statement(self,node,environment)
        if stdio is not None:
            return stdio
        from .native_key_containers import try_statement as key_statement
        keyed=key_statement(self,node,environment)
        if keyed is not None:return keyed
        from .native_typed_lists import try_statement
        typed=try_statement(self,node,environment)
        if typed is not None:return typed
        from .native_tuples import try_statement
        structural=try_statement(self,node,environment)
        if structural is not None:return structural
        alias = self.function_alias_assignment(node,environment)
        if alias is not None:
            return alias
        if isinstance(node, ast.For):
            from .native_iterators import try_for_loop
            return try_for_loop(self, node, environment)
        result = self.list_statement(node,environment)
        if result is not None:
            return result
        if isinstance(node,ast.Assign):
            if not all(isinstance(target,ast.Name) and target.id not in self.iterating_lists for target in node.targets):
                raise _Unsupported
            value = self.expression(node.value,environment)
            if not immutable(value.kind) and (not value.owned or len(node.targets) != 1):
                raise _Unsupported("these names would share one mutable container, but the selected storage requires a proved unique owner; alias-preserving shared mutable storage is not implemented for this assignment",node=node,types=(("value",value.kind),),proof="mutable alias identity and lifetime")
            name = self.temporary()
            from .native_unions import union_kind
            assigned=self.coerce(value,value.kind) if union_kind(value.kind) and not value.owned else value.code
            lines = [f"let {name}={assigned};"]
            for index,target in enumerate(node.targets):
                # Expressions already produce an owned immutable scalar. The
                # final target can take that temporary; earlier chained targets
                # retain their own values and therefore still need a clone.
                assigned = (name if index == len(node.targets)-1 else
                            self.coerce(_Expression(name,value.kind),value.kind))
                lines.append(f"{self.bind(target.id,value,environment)}={assigned};")
            return "\n".join(lines),environment
        if isinstance(node,ast.For):
            if not isinstance(node.iter,ast.Call) or not isinstance(node.iter.func,ast.Name) or node.iter.func.id != "range":
                raise _Unsupported
        if isinstance(node,ast.ImportFrom)and node.module=="collections"and any(alias.name=="deque"for alias in node.names):
            raise _Unsupported("collections.deque has fixed-width storage adapters, but its arbitrary-precision element storage and deque operations are not implemented on the BigInt path",node=node,operation="import 'collections.deque' in BigInt mode",proof="BigInt deque storage and operations")
        if isinstance(node,(ast.Pass,ast.FunctionDef,ast.Return,ast.AugAssign,ast.If,ast.For,ast.While,ast.Break,ast.Continue,ast.Expr)):
            return super().statement(node,environment)
        raise _Unsupported


def try_generate_bigint(source, filename, *, prune_output=True, diagnostic_out=None,trusted_imports=frozenset(),unit=None,
                        string_mode="ascii"):
    """Return a complete direct-Rust program only after a full scalar proof."""
    from .frontend import build_program, native_namespace_diagnostic
    from .diagnostics import CompilationError
    try:
        if unit is None:
            from dataclasses import replace
            unit = build_program(source, filename).main
            # Internal callers historically opt into standard-module helpers.
            # Restrict that proof to origins verified by the shared resolver.
            unit = replace(unit, native_imports=unit.native_imports.intersection(trusted_imports))
        unit.check_identity(source, filename)
    except CompilationError as error:
        if diagnostic_out is not None:diagnostic_out.append(error.diagnostic)
        return None
    namespace_error = native_namespace_diagnostic(unit)
    if namespace_error is not None:
        if diagnostic_out is not None:diagnostic_out.append(namespace_error)
        return None
    trusted_imports = unit.native_imports
    try:
        tree, table = unit.tree, unit.table
        for node in ast.walk(tree):
            if isinstance(node,ast.Name) and isinstance(node.ctx,ast.Store) and node.id in BigIntGenerator.BUILTINS-{"input"}-CANONICAL_REBINDABLES:
                raise _Unsupported
        functions = _function_plans(tree,table,0,BigIntGenerator,unit=unit)
        function_input = bool(functions) and ("sys" in trusted_imports or any(isinstance(node,ast.Name) and node.id == "input" for node in ast.walk(tree)))
        specializations = _Specializations(0,functions,{},function_input,BigIntGenerator,string_mode=string_mode)
        specializations.trusted_imports=trusted_imports
        specializations.source_unit=unit
        generator = BigIntGenerator(functions=functions,function_input=function_input,specializations=specializations)
        generator.string_mode=string_mode
        generator.trusted_imports=trusted_imports
        generator.source_unit=unit
        from .native_constraints import analyze
        generator.type_analysis=specializations.type_analysis=analyze(unit)
        generator.constraint_facts=generator.type_analysis.scope()
        from .native_range_facts import derive_regions
        generator.range_facts=derive_regions(generator.type_analysis,generator.constraint_facts,0)
        body,_ = generator.statements(tree.body,{})
        for local in specializations.generators:
            generator.union_types.update(local.union_types)
            generator.text_predicates.update(local.text_predicates)
        generator.has_scalar_union |= any(local.has_scalar_union for local in specializations.generators)
        generator.has_empty_type |= any(local.has_empty_type for local in specializations.generators)
        generator.has_input |= function_input or any(local.has_input for local in specializations.generators)
        generator.has_slices |= any(local.has_slices for local in specializations.generators)
        generator.has_big_text |= any(local.has_big_text for local in specializations.generators)
        generator.has_text_methods |= any(local.has_text_methods for local in specializations.generators)
        generator.has_stdio |= any(local.has_stdio for local in specializations.generators)
        generator.has_native_modules |= any(local.has_native_modules for local in specializations.generators)
        generator.has_tuples |= any(local.has_tuples for local in specializations.generators)
        generator.has_key_containers |= any(local.has_key_containers for local in specializations.generators)
        generator.has_typed_lists |= any(local.has_typed_lists for local in specializations.generators)
        generator.has_native_words |= any(local.has_native_words for local in specializations.generators)
    except (SyntaxError,_Unsupported,RecursionError,ConstraintFailure) as error:
        if diagnostic_out is not None:
            diagnostic_out.append(_direct_diagnostic(source,filename,error,unit=unit))
        return None
    runtime = files("py2fastrust").joinpath("runtime")
    notice = runtime.joinpath("NOTICE.txt").read_text(encoding="utf-8")
    unicode_license = files("py2fastrust").joinpath("stdlib","UNICODE_LICENSE.txt").read_text(encoding="utf-8")
    result = ["// Generated by py2fastrust: native BigInt AOT backend.\n"
              "#![allow(dead_code,unused_imports,unused_variables,unused_mut,unused_assignments,unused_parens,unused_labels)]\n"
              "const INT_BITS:u32=0;\ntype NativeInt=Int;\n",
              "/*\n"+notice+"\n*/\n",
              "\n".join("// "+line for line in unicode_license.splitlines())+"\n",
              runtime.joinpath("integer.rs").read_text(encoding="utf-8"),
              _HELPERS,LIST_HELPERS,_OUTPUT_HELPERS]
    if generator.has_slices:
        from .native_slices import SLICE_HELPERS
        result.append(SLICE_HELPERS)
    if generator.has_big_text:
        result.append(BIG_TEXT_HELPERS)
    if generator.has_text_methods:
        from .native_text_methods import HELPERS as TEXT_METHOD_HELPERS
        result.append(TEXT_METHOD_HELPERS)
    if generator.has_input:
        result += [runtime.joinpath("streaming_io.rs").read_text(encoding="utf-8"),_INPUT_HELPERS]
    if generator.has_key_containers:
        from .native_key_containers import HELPERS as KEY_HELPERS,BIG_HASH
        result.extend([KEY_HELPERS,BIG_HASH])
    if generator.has_tuples:
        from .native_tuples import render_helpers
        result.append(render_helpers())
    if generator.has_typed_lists:
        from .native_typed_lists import HELPERS as TYPED_LIST_HELPERS
        result.append(TYPED_LIST_HELPERS)
    if generator.has_native_words:
        from .native_words import HELPERS as WORD_HELPERS
        result.append(WORD_HELPERS)
    if generator.has_stdio:
        from .native_stdio import render_helpers
        result.append(render_helpers(0,input_runtime=generator.has_input))
    if generator.has_native_modules:
        from .native_module_calls import HELPERS as MODULE_HELPERS
        result.append(MODULE_HELPERS)
    if generator.has_empty_type:
        from .native_constraint_lowering import EMPTY_HELPERS
        result.append(EMPTY_HELPERS)
    if generator.union_types:
        from .native_unions import render_types
        result.append(render_types(generator.union_types))
    if generator.text_predicates:
        from .native_text_predicates import render_helpers
        result.append(render_helpers(generator.text_predicates,string_mode))
    result.extend(specializations.sources)
    result.append("fn main(){\nuse std::fmt::Write as _;\nuse std::io::Write as _;\nlet mut native_output=String::new();\nlet native_result=(||->Result<(),NativeError>{")
    if generator.has_input:
        result.append("let mut native_input=NativeInput::new();")
    result.append(_declarations(generator))
    result += [body,"Ok(())\n})();\nstd::io::stdout().write_all(native_output.as_bytes()).unwrap();\n",
               "if let Err(error)=native_result{\n"
               'eprintln!("Traceback (most recent call last):");\n'
               "for &(line,function) in error.frames.iter().rev(){\n"
               f'eprintln!("  File {{:?}}, line {{}}, in {{}}",{_string(filename)},line,function);\n'
               "}\n"
               f'eprintln!("  File {{:?}}, line {{}}, in {{}}\\n{{}}",{_string(filename)},error.line,error.function,error.message);\n'
               "std::process::exit(1);\n}\n}\n"]
    source = "\n".join(result)
    from .native_text_policy import apply_text_policy
    source = apply_text_policy(source,string_mode)
    from .native_cached_text import apply_cached_text
    source = apply_cached_text(source,string_mode)
    if prune_output:
        from .rust_pruning import prune_rust_source
        source = prune_rust_source(source)
    from .native_notices import retain_native_notices
    return retain_native_notices(source)
