"""Owned, exact-integer Vec lowering for the arbitrary precision backend.

Lists keep the same unique-owner proof as fixed-width code. Integer reads clone
immutable values; copying a mutable Python list binding is never inferred.
"""

import ast

from .native import _Binding, _Expression, _ListInfo, _Unsupported


HELPERS = r'''
fn native_big_unpack_length(length:usize, expected:usize)->Result<(),String> {
    if length<expected{return Err(format!("ValueError: not enough values to unpack (expected {}, got {})",expected,length));}
    if length>expected{return Err(format!("ValueError: too many values to unpack (expected {})",expected));}
    Ok(())
}
fn native_big_list_reserve(values:&mut Vec<Int>, additional:usize)->Result<(),String> {
    let length=values.len().checked_add(additional).ok_or("MemoryError")?;
    if length>isize::MAX as usize{return Err("MemoryError".into());}
    values.try_reserve(additional).map_err(|_|"MemoryError".to_string())
}
fn native_big_list_push(values:&mut Vec<Int>, value:Int)->Result<(),String> {
    native_big_list_reserve(values,1)?;
    values.push(value);
    Ok(())
}
fn native_big_list_extend(values:&mut Vec<Int>, items:Vec<Int>)->Result<(),String> {
    native_big_list_reserve(values,items.len())?;
    values.extend(items);
    Ok(())
}
fn native_big_list_index(index:&Int, length:usize)->Result<usize,String> {
    let bound=Int::from_i128(length as i128);
    let offset=if index.is_negative(){index.add(&bound)}else{index.clone()};
    if offset.is_negative()||offset>=bound{return Err("IndexError: list index out of range".into());}
    offset.to_usize().ok_or_else(||"IndexError: list index out of range".into())
}
fn native_big_list_get(values:&[Int], index:&Int)->Result<Int,String> {
    Ok(values[native_big_list_index(index,values.len())?].clone())
}
fn native_big_list_set(values:&mut [Int], index:&Int, value:Int)->Result<(),String> {
    let offset=native_big_list_index(index,values.len()).map_err(|_|"IndexError: list assignment index out of range".to_string())?;
    values[offset]=value;
    Ok(())
}
fn native_big_list_repeat(values:&[Int], count:&Int)->Result<Vec<Int>,String> {
    // Python converts the repetition count to Py_ssize_t even for [] and
    // negative counts. No truncating BigInt -> machine-size casts are used.
    let count=count.to_i128().and_then(|n|isize::try_from(n).ok())
        .ok_or_else(||"OverflowError: cannot fit 'int' into an index-sized integer".to_string())?;
    let length=values.len().checked_mul(count.max(0) as usize).ok_or("MemoryError")?;
    let mut result=Vec::new();
    native_big_list_reserve(&mut result,length)?;
    if values.is_empty(){return Ok(result);}
    for _ in 0..count.max(0){result.extend(values.iter().cloned());}
    Ok(result)
}
fn native_big_list_copy(values:&[Int])->Result<Vec<Int>,String> {
    let mut result=Vec::new();
    native_big_list_reserve(&mut result,values.len())?;
    result.extend(values.iter().cloned());
    Ok(result)
}
'''


class BigIntLists:
    def integer_input_list(self, node):
        self.has_input = self.has_lists = True
        return _Expression(self.at("native_input.integers(&mut native_output)", node), "list_int")

    def list_copy(self, value, node):
        if value.kind != "list_int":
            raise _Unsupported
        self.has_lists = True
        if value.owned:
            return value.code
        return self.at(f"native_big_list_copy(&({value.code}))", node)

    def list_expression(self, node, environment):
        if isinstance(node, ast.ListComp):
            if len(node.generators) != 1 or node.generators[0].is_async or not isinstance(node.generators[0].target, ast.Name):
                raise _Unsupported
            generator = node.generators[0]
            target = generator.target.id
            if (not generator.ifs and self.input_words(generator.iter) and isinstance(node.elt, ast.Call)
                    and isinstance(node.elt.func, ast.Name) and node.elt.func.id == "int"
                    and len(node.elt.args) == 1 and not node.elt.keywords
                    and isinstance(node.elt.args[0],ast.Name) and node.elt.args[0].id == target):
                return self.integer_input_list(node)
            setup, iterator, arguments = self.range_iterator(generator.iter, environment)
            item, result = self.temporary(), self.temporary()
            inside = environment.copy()
            inside[target] = _Binding(item, "int")
            filters = [self.expression(condition, inside) for condition in generator.ifs]
            element = self.expression(node.elt, inside)
            if element.kind != "int":
                raise _Unsupported
            insertion = self.at(f"native_big_list_push(&mut {result},{element.code})",node) + ";"
            for condition in reversed(filters):
                insertion = f"if {self.truth(condition)} {{{insertion}}}"
            self.has_lists = True
            return _Expression(f"{{{setup} let mut {result}=Vec::<Int>::new(); for {item} in {iterator} {{{insertion}}} {result}}}", "list_int")
        if isinstance(node, ast.List):
            values = [self.expression(value, environment) for value in node.elts]
            if any(value.kind != "int" for value in values):
                raise _Unsupported
            self.has_lists = True
            return _Expression("vec![" + ",".join(value.code for value in values) + "]", "list_int", length=len(values))
        if isinstance(node, ast.Subscript):
            if isinstance(node.slice, ast.Slice):
                raise _Unsupported
            values = self.expression(node.value, environment)
            if values.kind != "list_int":
                raise _Unsupported
            index = self.expression(node.slice, environment)
            owner, offset = self.temporary(), self.temporary()
            setup = f"let {owner}={values.code};" if values.owned else ""
            receiver = owner if values.owned else values.code
            lookup = self.at(f"native_big_list_get(&({receiver}),&{offset})", node)
            # A named owner's lookup is delayed until after its index runs.
            # Functions can only borrow lists read-only, so no list rebinding
            # can escape from index evaluation in the accepted subset.
            return _Expression(f"{{{setup} let {offset}={self.number(index)}; {lookup}}}", "int")
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "copy" and not node.args and not node.keywords):
            value = self.expression(node.func.value, environment)
            return _Expression(self.list_copy(value, node), "list_int", length=value.length)
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords):
            return None
        name = node.func.id
        if name == "list":
            if not node.args:
                self.has_lists = True
                return _Expression("Vec::<Int>::new()", "list_int", length=0)
            if len(node.args) != 1:
                raise _Unsupported
            source = node.args[0]
            if self.input_map(source):
                return self.integer_input_list(node)
            if (isinstance(source,ast.Call) and isinstance(source.func,ast.Name) and source.func.id == "range"):
                setup, iterator, _ = self.range_iterator(source, environment)
                item, result = self.temporary(), self.temporary()
                insertion = self.at(f"native_big_list_push(&mut {result},{item})",node)
                self.has_lists = True
                return _Expression(f"{{{setup} let mut {result}=Vec::<Int>::new(); for {item} in {iterator} {{{insertion};}} {result}}}", "list_int")
            reverse = (isinstance(source, ast.Call) and isinstance(source.func, ast.Name)
                       and source.func.id == "reversed" and len(source.args) == 1 and not source.keywords)
            value = self.expression(source.args[0] if reverse else source, environment)
            code = self.list_copy(value, node)
            if reverse:
                owner = self.temporary()
                code = f"{{let mut {owner}={code}; {owner}.reverse(); {owner}}}"
            return _Expression(code, "list_int", length=value.length)
        if name == "len" and len(node.args) == 1:
            value = self.expression(node.args[0], environment)
            if value.kind != "list_int":
                raise _Unsupported
            return _Expression(f"Int::from_i128(({value.code}).len() as i128)", "int", value.length)
        if name == "sum" and 1 <= len(node.args) <= 2:
            # Generic generator/reversed stream reductions are handled by the
            # iterator backend. This path handles an ordinary typed list.
            value = self.expression(node.args[0], environment)
            if value.kind != "list_int":
                raise _Unsupported
            start = self.expression(node.args[1], environment) if len(node.args) == 2 else _Expression(self.literal(0), "int", 0)
            if start.kind != "int":
                raise _Unsupported
            owner, initial = self.temporary(), self.temporary()
            setup = f"let {owner}={value.code};" if value.owned else ""
            receiver = owner if value.owned else value.code
            code = f"{{{setup} let {initial}={self.number(start)}; ({receiver}).iter().fold({initial},|total,item|total.add(item))}}"
            return _Expression(code, "int")
        return None

    def list_binary(self, operator, left, right, node):
        if "list_int" not in {left.kind, right.kind}:
            return None
        self.has_lists = True
        first, second = self.temporary(), self.temporary()
        # Borrowing an exact list cannot invoke user code. The other operand's
        # accepted scalar calls have no access to mutate this unique owner.
        if isinstance(operator, ast.Mult):
            if left.kind == "list_int" and right.kind in {"int", "bool", "int_bool"}:
                setup = f"let {first}={'(' + left.code + ')' if left.owned else '&(' + left.code + ')'}; let {second}={self.number(right)};"
                call = f"native_big_list_repeat(&{first},&{second})"
                count = right.constant
                length = left.length
            elif right.kind == "list_int" and left.kind in {"int", "bool", "int_bool"}:
                setup = f"let {first}={self.number(left)}; let {second}={'(' + right.code + ')' if right.owned else '&(' + right.code + ')'};"
                call = f"native_big_list_repeat(&{second},&{first})"
                count = left.constant
                length = right.length
            else:
                raise _Unsupported
            size = None if length is None or count is None else length * max(0, count)
            return _Expression(f"{{{setup} {self.at(call,node)}}}", "list_int", length=size)
        if isinstance(operator, ast.Add) and left.kind == right.kind == "list_int":
            setup = f"let mut {first}={self.list_copy(left,node)}; let {second}={self.list_copy(right,node)};"
            action = self.at(f"native_big_list_extend(&mut {first},{second})", node)
            length = None if left.length is None or right.length is None else left.length + right.length
            return _Expression(f"{{{setup} {action}; {first}}}", "list_int", length=length)
        raise _Unsupported

    def list_extremum(self, node, environment):
        value = self.expression(node.args[0], environment)
        if value.kind != "list_int":
            raise _Unsupported
        default = None
        for keyword in node.keywords:
            if keyword.arg == "key" and isinstance(keyword.value, ast.Constant) and keyword.value.value is None:
                continue
            if keyword.arg != "default" or default is not None:
                raise _Unsupported
            default = self.expression(keyword.value, environment)
            if default.kind != "int":
                raise _Unsupported
        owner, initial = self.temporary(), self.temporary()
        setup = f"let {owner}={value.code};" if value.owned else ""
        receiver = owner if value.owned else value.code
        if default:
            setup += f"let {initial}={self.number(default)};"
        reduction = f"({receiver}).iter().{node.func.id}().cloned()"
        result = f"{reduction}.unwrap_or({initial})" if default else self.at(f'{reduction}.ok_or_else(||"ValueError: {node.func.id}() iterable argument is empty".to_string())',node)
        return _Expression(f"{{{setup} {result}}}", "int")

    def list_for(self, node, environment):
        if node.orelse or not isinstance(node.target, ast.Name):
            raise _Unsupported
        source = node.iter
        reverse = (isinstance(source, ast.Call) and isinstance(source.func, ast.Name)
                   and source.func.id == "reversed" and len(source.args) == 1 and not source.keywords)
        if reverse:
            source = source.args[0]
        values = self.expression(source, environment)
        if values.kind != "list_int":
            raise _Unsupported
        list_name = source.id if isinstance(source, ast.Name) else None
        if list_name is None and not values.owned:
            raise _Unsupported
        if node.target.id in self.iterating_lists or node.target.id == list_name:
            raise _Unsupported
        owner = self.temporary() if values.owned else values.code
        setup = f"let {owner}={values.code};" if values.owned else ""
        iterator = f"{owner}.into_iter()" if values.owned else f"{owner}.iter().cloned()"
        if reverse:
            iterator += ".rev()"
        label = self.temporary()
        context = {"label": label, "edges": []}
        header_initializers, widened = self.loop_header(node, environment)
        inside = widened.copy()
        target = self.bind(node.target.id, "int", inside)
        self.loops.append(context)
        if list_name is not None:
            self.iterating_lists.append(list_name)
        body, remaining = self.statements(node.body, inside)
        if list_name is not None:
            self.iterating_lists.pop()
        self.loops.pop()
        count = values.length
        initialization, body, joined = self.finish_loop(node, environment, inside, context, body, remaining,
                                                       count is not None and count > 0, count is None or count > 1, count == 0)
        item = self.temporary()
        code = f"{setup}\n{header_initializers}\n{initialization}\n'{label}: for {item} in {iterator} {{\n{target}={item};\n{body}\n}}"
        return code, joined

    def list_statement(self, node, environment):
        if isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if len(targets) == 1 and isinstance(targets[0], ast.Subscript):
                target = targets[0]
                if not isinstance(target.value, ast.Name) or target.value.id in self.iterating_lists or isinstance(target.slice, ast.Slice):
                    raise _Unsupported
                values = self.expression(target.value, environment)
                if values.kind != "list_int":
                    raise _Unsupported
                offset, result = self.temporary(), self.temporary()
                if isinstance(node, ast.Assign):
                    value = self.expression(node.value, environment)
                    index = self.expression(target.slice, environment)
                    setup = f"let {result}={self.number(value)}; let {offset}={self.number(index)};"
                else:
                    index = self.expression(target.slice, environment)
                    old = self.temporary()
                    getter = self.at(f"native_big_list_get(&{values.code},&{offset})", target)
                    right = self.expression(node.value, environment)
                    value = self.binary(node.op, _Expression(old, "int"), right, node)
                    setup = f"let {offset}={self.number(index)}; let {old}={getter}; let {result}={self.number(value)};"
                setter = self.at(f"native_big_list_set(&mut {values.code},&{offset},{result})",node)
                return setup + setter + ";", environment
        if isinstance(node, ast.For):
            if not (isinstance(node.iter, ast.Call) and isinstance(node.iter.func, ast.Name) and node.iter.func.id == "range"):
                return self.list_for(node, environment)
        if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute) and isinstance(node.value.func.value, ast.Name)):
            return None
        call = node.value
        target = call.func.value
        values = self.expression(target, environment)
        if values.kind != "list_int":
            return None
        if target.id in self.iterating_lists:
            raise _Unsupported
        method = call.func.attr
        if method in {"clear", "reverse"} and not call.args and not call.keywords:
            if method == "clear":
                self.update_info(environment,target.id,_ListInfo(0))
            return f"{values.code}.{method}();", environment
        if method in {"append", "extend"} and len(call.args) == 1 and not call.keywords:
            argument = self.expression(call.args[0], environment)
            item = self.temporary()
            if method == "append" and argument.kind == "int":
                code = argument.code
                length = None if values.length is None else values.length + 1
                action = f"native_big_list_push(&mut {values.code},{item})"
            elif method == "extend" and argument.kind == "list_int":
                code = self.list_copy(argument, node)
                length = None if values.length is None or argument.length is None else values.length + argument.length
                action = f"native_big_list_extend(&mut {values.code},{item})"
            else:
                raise _Unsupported
            self.update_info(environment,target.id,_ListInfo(length))
            return f"let {item}={code}; {self.at(action,node)};", environment
        if method == "sort" and not call.args:
            reverse = False
            for keyword in call.keywords:
                if keyword.arg == "key" and isinstance(keyword.value,ast.Constant) and keyword.value.value is None:
                    continue
                if keyword.arg != "reverse" or not isinstance(keyword.value,ast.Constant) or type(keyword.value.value) is not bool:
                    raise _Unsupported
                reverse = keyword.value.value
            code = f"{values.code}.sort_unstable();"
            if reverse:
                code += f"{values.code}.reverse();"
            return code, environment
        return None
