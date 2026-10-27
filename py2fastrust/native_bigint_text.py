"""Ordinary Rust String values alongside owned arbitrary-precision integers."""
import ast

from .native import _Binding, _Expression, _Unsupported, _string


HELPERS = r'''
fn native_big_text_add(mut left:String,right:&str)->Result<String,String> {
    left.try_reserve(right.len()).map_err(|_|"MemoryError: string is too large".to_owned())?;
    left.push_str(right);Ok(left)
}
fn native_big_text_repeat(text:&str,count:&Int)->Result<String,String> {
    let count=count.to_i128().and_then(|value|isize::try_from(value).ok())
        .ok_or_else(||"OverflowError: cannot fit 'int' into an index-sized integer".to_owned())?;
    if count<=0||text.is_empty(){return Ok(String::new());}
    let length=text.len().checked_mul(count as usize).filter(|n|*n<=isize::MAX as usize)
        .ok_or_else(||"OverflowError: repeated string is too long".to_owned())?;
    let mut result=String::new();
    result.try_reserve_exact(length).map_err(|_|"MemoryError: string is too large".to_owned())?;
    for _ in 0..count {result.push_str(text);}
    Ok(result)
}
fn native_big_text_item(text:&str,index:&Int)->Result<String,String> {
    let error=||"IndexError: string index out of range".to_owned();
    let length=if text.is_ascii(){text.len()}else{text.chars().count()};
    let index=index.to_i128().ok_or_else(error)?;
    let index=if index<0 {index.checked_add(length as i128).ok_or_else(error)?}else{index};
    let index=usize::try_from(index).ok().filter(|index|*index<length).ok_or_else(error)?;
    Ok(if text.is_ascii(){(text.as_bytes()[index] as char).to_string()}
        else{text.chars().nth(index).unwrap().to_string()})
}
'''


class BigIntText:
    def read_expression(self, node, environment):
        if isinstance(node, ast.Name):
            binding = environment.get(node.id)
            if isinstance(binding, _Binding) and binding.kind == "str":
                self.has_big_text = True
                return _Expression(f"&{binding.slot}", "str", owned=False, stable_borrow=True)
        if isinstance(node, ast.Constant) and type(node.value) is str:
            from .literal_semantics import Literal
            literal=Literal.from_ast(node)
            if literal is None:raise _Unsupported
            self.has_big_text = True
            from .native_regions import literal_char
            return _Expression(_string(literal.value),literal.kind,owned=False,stable_borrow=True,char_code=literal_char(literal.value))
        if (self.string_mode == "ascii" and isinstance(node,ast.Subscript)
                and not isinstance(node.slice,ast.Slice)):
            from .native_regions import owner_view,char_projection
            view=owner_view(self,node)
            owner=_Expression(view,"str",owned=False,stable_borrow=True)if view else self.read_expression(node.value,environment)
            if owner.kind=="str" and owner.stable_borrow:
                index=self.expression(node.slice,environment)
                first,second=self.temporary(),self.temporary()
                self.has_big_text=True
                call=self.at(f"native_big_text_item_ref({first},&{second})",node)
                prefix=f"{{ let {first}:&str={owner.code}; let {second}={self.number(index)}; "
                code=prefix+call+" }"
                projected=prefix+self.at(f"native_big_ascii_codepoint({first},&{second})",node)+" }"
                return _Expression(code,"str",owned=False,stable_borrow=True,char_code=char_projection(self,node,code,projected))
        value = self.expression(node, environment)
        return (_Expression(f"&({value.code})", "str", owned=False,char_code=value.char_code) if value.kind == "str" else value)

    def text_expression(self, node, environment):
        if isinstance(node, ast.Constant) and type(node.value) is str:
            from .literal_semantics import Literal
            literal=Literal.from_ast(node)
            if literal is None:raise _Unsupported
            self.has_big_text = True
            from .native_regions import literal_char
            return _Expression(literal.rust_atom(self.literal,_string),literal.kind,char_code=literal_char(literal.value))
        if isinstance(node, ast.Name):
            value = environment.get(node.id)
            if isinstance(value, _Binding) and value.kind == "str":
                return _Expression(f"{value.slot}.clone()", "str")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            from .native_text_methods import try_text_method
            return try_text_method(self,node,environment)
        if isinstance(node, ast.Subscript) and not isinstance(node.slice, ast.Slice):
            text = self.read_expression(node.value, environment)
            if text.kind == "str":
                index = self.expression(node.slice, environment)
                owner, offset = self.temporary(), self.temporary()
                result = self.at(f"native_big_text_item({owner},&{offset})", node)
                prefix=f"{{let {owner}:&str={text.code};let {offset}={self.number(index)};"
                code=prefix+result+"}"
                from .native_regions import char_projection
                projected=None
                if self.string_mode=="ascii":
                    projected=prefix+self.at(f"native_big_ascii_codepoint({owner},&{offset})",node)+"}"
                return _Expression(code,"str",char_code=char_projection(self,node,code,projected))
        if isinstance(node, ast.Compare):
            values = [self.read_expression(value, environment) for value in [node.left,*node.comparators]]
            if any(value.kind == "str" for value in values):
                return self.text_compare(node, values)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            name = node.func.id
            if name == "input" and not node.args:
                self.has_input = self.has_big_text = True
                return _Expression(f"({self.at('native_input.line(&mut native_output)', node)}).to_owned()", "str")
            if name == "str" and not node.args:
                self.has_big_text = True
                return _Expression("String::new()", "str")
            if name in {"len", "int", "bool", "str"} and len(node.args) == 1 and not isinstance(node.args[0], ast.Starred):
                # Preserve the existing buffered decimal-input lowering.
                arg = node.args[0]
                if (name == "int" and isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name)
                        and arg.func.id == "input" and not arg.args and not arg.keywords):
                    return None
                value = self.read_expression(arg, environment)
                if value.kind == "str":
                    self.has_big_text = True
                    if name == "len":
                        length = "len()" if self.string_mode == "ascii" else "chars().count()"
                        return _Expression(f"Int::from_i128(({value.code}).{length} as i128)", "int")
                    if name == "bool":
                        return _Expression(f"!({value.code}).is_empty()", "bool")
                    if name == "int":
                        return _Expression(self.at(f"Int::parse({value.code},10)",node), "int")
                    return _Expression(f"({value.code}).to_owned()", "str")
                if name == "str" and value.kind in {"int", "bool", "int_bool"}:
                    self.has_big_text = True
                    result = (f'(if {value.code} {{"True"}}else{{"False"}}).to_owned()'
                              if value.kind == "bool" else f"({value.code}).to_string()")
                    return _Expression(result, "str")
        return None

    def text_binary(self, operator, left, right, node):
        if left.kind == right.kind == "str" and isinstance(operator, ast.Add):
            a,b = self.temporary(),self.temporary()
            result = self.at(f"native_big_text_add({a},&{b})",node)
            return _Expression(f"{{let {a}={left.code};let {b}={right.code};{result}}}", "str")
        if "str" in (left.kind,right.kind) and isinstance(operator, ast.Mult):
            first,second = self.temporary(),self.temporary()
            text,count = (first,second) if left.kind == "str" else (second,first)
            left_code = left.code if left.kind == "str" else self.number(left)
            right_code = right.code if right.kind == "str" else self.number(right)
            result = self.at(f"native_big_text_repeat(&{text},&{count})",node)
            return _Expression(f"{{let {first}={left_code};let {second}={right_code};{result}}}", "str")
        return None

    def text_compare(self, node, values):
        from .native_regions import compare_characters
        projected=compare_characters(self,node,values)
        if projected is not None:return projected
        from .native_unions import compare
        finite=compare(self,node,values)
        if finite is not None:return finite
        operators = {ast.Eq:"==",ast.NotEq:"!=",ast.Lt:"<",ast.LtE:"<=",ast.Gt:">",ast.GtE:">="}
        names = [self.temporary() for _ in values]
        tail = "true"
        def bind(name,value):
            return f"let {name}" + (":&str" if value.kind == "str" else "") + f"={value.code};"
        for i in reversed(range(len(node.ops))):
            a,b,op = values[i],values[i+1],node.ops[i]
            x,y = names[i],names[i+1]
            if a.kind == b.kind == "str":
                if isinstance(op,(ast.In,ast.NotIn)):
                    result = f"{y}.contains({x})"
                    if isinstance(op,ast.NotIn):result="!"+result
                elif type(op) in operators:result=f"{x}{operators[type(op)]}{y}"
                else:raise _Unsupported
            elif "str" in (a.kind,b.kind):
                if not isinstance(op,(ast.Eq,ast.NotEq)) or not {a.kind,b.kind}<={"str","int","bool","int_bool"}:
                    raise _Unsupported
                result = str(isinstance(op,ast.NotEq)).lower()
            elif type(op) in operators:
                result = f"{self.number(_Expression(x,a.kind))}{operators[type(op)]}{self.number(_Expression(y,b.kind))}"
            else:raise _Unsupported
            tail=f"{{{bind(y,b)}({result})&&({tail})}}"
        return _Expression(f"{{{bind(names[0],values[0])}{tail}}}","bool")
