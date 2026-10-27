"""Direct Rust lowering for proven arbitrary-precision integer expressions.

Integers are ordinary owned Rust ``Int`` values, not Python object handles.
The fixed-width backend's binding and control-flow proofs are shared; explicit
clones preserve Python's immutable-value semantics without requiring ``Copy``.
Missing direct lowering produces a positioned diagnostic in the public API.
"""

import ast
from .native_types import (TupleType,ListType,MaybeType,TypedListInfo,rust_type,kind_tag,
                           is_maybe,unmaybe,maybe_type,immutable,list_type,default_value)
from importlib.resources import files
import symtable

from .native import (_Binding, _Expression, _Function, _Generator, _ListInfo, _Specializations,
                     _Unsupported, _OUTPUT_HELPERS, _declarations,
                     _function_plans, _string, _direct_diagnostic)
from .native import _static_reference
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
    fn integers(&mut self,output:&mut String)->Result<Vec<Int>,String> {
        let mut result=Vec::new();
        for word in self.line(output)?.split(native_space).filter(|word|!word.is_empty()) {
            let value=Int::parse(word,10)?;
            native_big_list_push(&mut result,value)?;
        }
        Ok(result)
    }
    fn unpack_integers(&mut self,count:usize,output:&mut String)->Result<Vec<Int>,String> {
        let mut words=self.line(output)?.split(native_space).filter(|word|!word.is_empty());
        let mut result=Vec::with_capacity(count);
        for index in 0..count {
            let word=words.next().ok_or_else(||format!("ValueError: not enough values to unpack (expected {}, got {})",count,index))?;
            result.push(Int::parse(word,10)?);
        }
        if let Some(word)=words.next(){
            // A lazy map converts exactly one excess item before unpack fails.
            Int::parse(word,10)?;
            return Err(format!("ValueError: too many values to unpack (expected {})",count));
        }
        Ok(result)
    }
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
        if isinstance(unmaybe(kind),(TupleType,ListType)):return super().slot(kind)
        if kind == "str":
            self.has_big_text = True
            slot = f"native_var_{len(self.bindings)}"
            self.bindings[slot] = kind
            return slot
        if unmaybe(kind) not in {"int", "bool", "int_bool", "list_int", "str", "bytes"}:
            raise _Unsupported
        return super().slot(kind)

    @staticmethod
    def number(expression):
        if expression.kind == "int":
            return expression.code
        if expression.kind == "bool":
            return f"Int::from_i128(({expression.code}) as i128)"
        if expression.kind == "int_bool":
            return f"({expression.code}).integer()"
        raise _Unsupported

    @staticmethod
    def coerce(expression, kind):
        from .native_tuples import coerce_structural
        if is_maybe(kind):
            if expression.kind==kind:return f"({expression.code}).clone()"
            if is_maybe(expression.kind):
                item=_Expression("native_optional.clone()",unmaybe(expression.kind))
                return f"({expression.code}).as_ref().map(|native_optional|{BigIntGenerator.coerce(item,unmaybe(kind))})"
            return f"Some({BigIntGenerator.coerce(expression,unmaybe(kind))})"
        structural=coerce_structural(expression,kind,BigIntGenerator.coerce)
        if structural is not None:return structural
        if expression.kind == kind:
            return f"({expression.code}).clone()" if kind in {"int","int_bool","str","bytes"} else expression.code
        if kind == "int_bool" and expression.kind in {"int", "bool"}:
            variant = "Int" if expression.kind == "int" else "Bool"
            value = f"({expression.code}).clone()" if expression.kind == "int" else expression.code
            return f"NativeScalar::{variant}({value})"
        raise _Unsupported

    @staticmethod
    def truth(expression):
        if isinstance(expression.kind,(TupleType,ListType)):return _Generator.truth(expression)
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

    def expression(self, node, environment):
        from .native_module_calls import try_expression as module_expression
        module=module_expression(self,node,environment)
        if module is not None:return module
        from .native_stdio import try_expression
        stdio=try_expression(self,node,environment)
        if stdio is not None:
            return stdio
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
            if isinstance(binding, _Binding) and is_maybe(binding.kind):
                return super().expression(node, environment)
            if not isinstance(binding, _Binding) or binding.kind not in {"int", "bool", "int_bool"}:
                raise _Unsupported
            return _Expression(self.coerce(_Expression(binding.slot,binding.kind),binding.kind),binding.kind)
        if isinstance(node, ast.Constant):
            from .literal_semantics import Literal
            literal=Literal.from_ast(node)
            if literal is not None and literal.kind in {"int","bool"}:
                return _Expression(literal.rust_atom(self.literal,_string),literal.kind,literal.value)
            raise _Unsupported
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
        if isinstance(node, (ast.BoolOp, ast.Compare, ast.IfExp)):
            return super().expression(node,environment)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            function = environment.get(node.func.id)
            if isinstance(function, _Function):
                return self.user_call(node,function,environment)
            name = node.func.id
            if name in {"min","max"}:
                return self.extremum(node,environment)
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

    def extremum(self, node, environment):
        if any(isinstance(argument,ast.Starred) for argument in node.args) or not node.args:
            raise _Unsupported
        default = None
        for keyword in node.keywords:
            if keyword.arg == "key" and isinstance(keyword.value,ast.Constant) and keyword.value.value is None:
                continue
            if keyword.arg == "default" and len(node.args) == 1 and default is None:
                default = self.expression(keyword.value,environment)
            else:
                raise _Unsupported
        compare = ">" if node.func.id == "max" else "<"
        if len(node.args)>=2:
            values = [self.expression(value,environment) for value in node.args]
            kind = self.scalar_kind(values)
            names = [self.temporary() for _ in values]
            setup = " ".join(f"let {name}={self.coerce(value,kind)};" for name,value in zip(names,values))
            best = self.temporary()
            current = self.number(_Expression(best,kind))
            updates = " ".join(f"if {self.number(_Expression(name,kind))} {compare} {current} {{{best}={name};}}" for name in names[1:])
            return _Expression(f"{{{setup} let mut {best}={names[0]}; {updates} {best}}}",kind)
        iterable = node.args[0]
        if not isinstance(iterable,(ast.List,ast.Tuple)):
            return self.list_extremum(node,environment)
        values = [self.expression(value,environment) for value in iterable.elts]
        kind = self.scalar_kind(values+([default] if default else [])) if values or default else "int"
        names = [self.temporary() for _ in values]
        # Evaluate iterable elements first, then the default, then comparisons.
        setup = " ".join(f"let {name}={self.coerce(value,kind)};" for name,value in zip(names,values))
        if default is not None:
            default_name = self.temporary()
            setup += f"let {default_name}={self.coerce(default,kind)};"
        if not values:
            if default is not None:
                return _Expression(f"{{{setup} {default_name}}}",kind)
            error = self.at(f'Err::<Int,String>("ValueError: {node.func.id}() iterable argument is empty".into())',node)
            return _Expression(error,"int")
        best = self.temporary()
        current = self.number(_Expression(best,kind))
        updates = " ".join(f"if {self.number(_Expression(name,kind))} {compare} {current} {{{best}={name};}}" for name in names[1:])
        return _Expression(f"{{{setup} let mut {best}={names[0]}; {updates} {best}}}",kind)

    def range_iterator(self, node, environment):
        if not (isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id == "range" and not node.keywords and 1<=len(node.args)<=3):
            raise _Unsupported
        arguments = [self.expression(value,environment) for value in node.args]
        if len(arguments)==1:
            arguments.insert(0,_Expression(self.literal(0),"int",0))
        if len(arguments)==2:
            arguments.append(_Expression(self.literal(1),"int",1))
        names = [self.temporary() for _ in arguments]
        setup = "\n".join(f"let {name}={self.number(value)};" for name,value in zip(names,arguments))
        return setup,self.at(f"NativeRange::new({','.join(names)})",node),arguments

    def finish_loop(self, node, entry, header, context, body, remaining, nonempty, may_repeat, zero=False):
        # The shared CFG proof uses moves for fixed-width Copy values. BigInt
        # edges instead copy immutable values explicitly, and construct typed
        # zero placeholders only for bindings proved definite after the loop.
        if remaining is not None:
            marker = "// "+self.temporary()+"_edge"
            context["edges"].append((marker,"normal",remaining))
            body += "\n"+marker
        edges = context["edges"]
        environments = ([entry] if not nonempty else [])+[environment for _,_,environment in edges]
        if zero:
            environments = [entry]
        joined,post_moves = self.join(environments,preferred=entry)
        if joined is None:
            joined = self.after_loop(entry)
        initializers = []
        entry_slots = {binding.slot for binding in entry.values() if isinstance(binding,_Binding)}
        for name,binding in joined.items():
            if isinstance(binding,_Binding) and binding.slot not in entry_slots:
                default = None if is_maybe(binding.kind) else default_value(binding.kind,self.literal(0))
                old = entry.get(name)
                if default is None:
                    default = self.coerce(_Expression(old.slot,old.kind),binding.kind) if isinstance(old,_Binding) else "None"
                elif isinstance(old,_Binding) and binding.kind == "int_bool":
                    default = self.coerce(_Expression(old.slot,old.kind),binding.kind)
                initializers.append(f"{binding.slot}={default};")
        live = self.read_before_write(node.body)
        if isinstance(node,ast.While):
            live |= {value.id for value in ast.walk(node.test) if isinstance(value,ast.Name) and isinstance(value.ctx,ast.Load)}
        else:
            live -= {value.id for value in ast.walk(node.target) if isinstance(value,ast.Name)}
        replacements = {}
        offset = 0 if nonempty else 1
        for index,(marker,kind,environment) in enumerate(edges):
            copies = []
            if kind != "break" and may_repeat and not zero:
                for name,previous in header.items():
                    if _static_reference(previous):
                        if name in live and environment.get(name) is not previous:
                            raise _Unsupported
                        continue
                    if not isinstance(previous,_Binding):
                        continue
                    current = environment.get(name)
                    previous_inner = unmaybe(previous.kind)
                    current_inner = unmaybe(current.kind) if isinstance(current,_Binding) else None
                    compatible = isinstance(current,_Binding) and (current.kind==previous.kind or previous.kind=="int_bool" and current.kind in {"int","bool"}
                                 or is_maybe(previous.kind) and (current_inner==previous_inner or previous_inner=="int_bool" and current_inner in {"int","bool"}))
                    if not compatible:
                        if name in live:
                            raise _Unsupported
                    elif current.slot != previous.slot:
                        copies.append(f"{previous.slot}={self.coerce(_Expression(current.slot,current.kind),previous.kind)};")
            if not zero:
                copies += post_moves[index+offset]
            replacements[marker] = "\n".join(dict.fromkeys(copies))
        body = "\n".join(replacements.get(line,line) for line in body.split("\n"))
        return "\n".join(initializers),body,self.after_loop(joined)

    def statement(self, node, environment):
        from .native_module_calls import try_statement as module_statement
        module=module_statement(self,node,environment)
        if module is not None:return module
        from .native_stdio import try_statement
        stdio=try_statement(self,node,environment)
        if stdio is not None:
            return stdio
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
            if len(node.targets)==1 and isinstance(node.targets[0],(ast.Tuple,ast.List)):
                targets = node.targets[0].elts
                if not all(isinstance(target,ast.Name) and target.id not in self.iterating_lists for target in targets):
                    raise _Unsupported
                name = self.temporary()
                if self.input_map(node.value,environment):
                    self.has_input = True
                    value = self.at(f"native_input.unpack_integers({len(targets)},&mut native_output)",node)
                    lines = [f"let {name}={value};"]
                    for index,target in enumerate(targets):
                        lines.append(f"{self.bind(target.id,'int',environment)}={name}[{index}].clone();")
                    return "\n".join(lines),environment
                if isinstance(node.value,(ast.Tuple,ast.List)) and len(node.value.elts)==len(targets):
                    values = [self.expression(value,environment) for value in node.value.elts]
                    if any(list_type(value.kind) for value in values):
                        raise _Unsupported
                    names = [self.temporary() for _ in values]
                    lines = [f"let {name}={value.code};" for name,value in zip(names,values)]
                    for target,name,value in zip(targets,names,values):
                        lines.append(f"{self.bind(target.id,value,environment)}={name};")
                    return "\n".join(lines),environment
                value = self.expression(node.value,environment)
                if value.kind != "list_int":
                    raise _Unsupported
                lines = [f"let {name}={value.code if value.owned else '&'+value.code};"]
                check = f'native_big_unpack_length({name}.len(),{len(targets)})'
                lines.append(self.at(check,node)+";")
                for index,target in enumerate(targets):
                    lines.append(f"{self.bind(target.id,'int',environment)}={name}[{index}].clone();")
                return "\n".join(lines),environment
            if not all(isinstance(target,ast.Name) and target.id not in self.iterating_lists for target in node.targets):
                raise _Unsupported
            value = self.expression(node.value,environment)
            if list_type(value.kind) and (not value.owned or len(node.targets) != 1):
                raise _Unsupported
            name = self.temporary()
            lines = [f"let {name}={value.code};"]
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
        if isinstance(node,(ast.Pass,ast.FunctionDef,ast.Return,ast.AugAssign,ast.If,ast.For,ast.While,ast.Break,ast.Continue,ast.Expr)):
            return super().statement(node,environment)
        raise _Unsupported


def try_generate_bigint(source, filename, *, prune_output=True, diagnostic_out=None,trusted_imports=frozenset(),unit=None):
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
            if isinstance(node,ast.Name) and isinstance(node.ctx,ast.Store) and node.id in BigIntGenerator.BUILTINS-{"input"}:
                raise _Unsupported
        functions = _function_plans(tree,table,0,BigIntGenerator)
        function_input = bool(functions) and ("sys" in trusted_imports or any(isinstance(node,ast.Name) and node.id == "input" for node in ast.walk(tree)))
        specializations = _Specializations(0,functions,{},function_input,BigIntGenerator)
        specializations.trusted_imports=trusted_imports
        specializations.source_unit=unit
        generator = BigIntGenerator(functions=functions,function_input=function_input,specializations=specializations)
        generator.trusted_imports=trusted_imports
        generator.source_unit=unit
        body,_ = generator.statements(tree.body,{})
        generator.has_input |= function_input or any(local.has_input for local in specializations.generators)
        generator.has_slices |= any(local.has_slices for local in specializations.generators)
        generator.has_big_text |= any(local.has_big_text for local in specializations.generators)
        generator.has_text_methods |= any(local.has_text_methods for local in specializations.generators)
        generator.has_stdio |= any(local.has_stdio for local in specializations.generators)
        generator.has_native_modules |= any(local.has_native_modules for local in specializations.generators)
        generator.has_tuples |= any(local.has_tuples for local in specializations.generators)
        generator.has_typed_lists |= any(local.has_typed_lists for local in specializations.generators)
    except (SyntaxError,_Unsupported,RecursionError) as error:
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
    if generator.has_tuples:
        from .native_tuples import render_helpers
        result.append(render_helpers())
    if generator.has_typed_lists:
        from .native_typed_lists import HELPERS as TYPED_LIST_HELPERS
        result.append(TYPED_LIST_HELPERS)
    if generator.has_stdio:
        from .native_stdio import render_helpers
        result.append(render_helpers(0))
    if generator.has_native_modules:
        from .native_module_calls import HELPERS as MODULE_HELPERS
        result.append(MODULE_HELPERS)
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
    if prune_output:
        from .rust_pruning import prune_rust_source
        source = prune_rust_source(source)
    return source
