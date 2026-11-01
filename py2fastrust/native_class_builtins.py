"""Canonical builtin operations shared by direct and captured typed calls.

Explicit arguments arrive already evaluated; no source spelling is substituted
and the adapter never traverses/evaluates argument ASTs a second time.
"""
import ast
from .references import BuiltinIdentity

SUPPORTED=frozenset({"classmethod","ord","bin","oct","hex","format","repr","ascii","divmod","input","print","int","str","bytes","bool","float","len","abs","id","globals","isinstance",
                     "range","list","tuple","sum","min","max","map","zip","enumerate","filter","iter","reversed","next","any","all","pow","sorted","dict","set"})


def analyze(model,plan,node,identity,arguments,keywords,environment,*,factory=None,call_arguments=None):
    from .native_classes import Cell,ClassUnsupported,merge
    self=model
    cell=(lambda tag=None,args=():model.cell(plan,node,tag,args))if factory is None else factory
    name = identity.name
    if name=='int':
        from .native_integer_base import analyze as analyze_integer_base
        explicit=analyze_integer_base(model,plan,node,arguments,keywords,factory=cell)
        if explicit is not None:return explicit
    if name in {"format","repr","ascii"}:return cell("str")
    if name in {'ord','bin','oct','hex'}:
        from .native_character_builtins import analyze as analyze_character
        return analyze_character(model,plan,node,name,arguments,keywords,factory=cell)
    if name=='divmod':
        from .native_class_divmod import analyze as analyze_divmod
        return analyze_divmod(model,plan,node,arguments,keywords,factory=cell)
    if name=='tuple':
        from .native_class_materialization import analyze_tuple
        return analyze_tuple(model,plan,node,arguments,keywords,environment,cell)
    if name in {'dict','set'}:
        return model.mappings.analyze_builtin(plan,node,name,arguments,keywords,environment,cell)
    if name == 'isinstance' and len(arguments) == 2 and not keywords:
        return cell('bool')
    if name=='sorted':
        from .native_class_sorting import analyze_builtin
        return analyze_builtin(model,plan,node,arguments,keywords,environment,factory=cell)
    if name in {'min','max'}:
        from .native_class_extrema import analyze as analyze_extrema
        return analyze_extrema(model,plan,node,name,arguments,keywords,environment,factory=cell)
    if name=='pow':
        from .native_class_numeric_calls import analyze as analyze_numeric
        return analyze_numeric(model,plan,node,identity,arguments,keywords,environment,factory=cell,call_arguments=call_arguments)
    if name=="globals"and not arguments and not keywords:
        if model.unit is None:
            raise ClassUnsupported(node,"the live module namespace view requires canonical SourceUnit binding ownership metadata",proof="official lexical module bindings")
        model.namespace.globals_observed=True
        return cell("globals_dict")
    if name == "print":
        if any(key not in {"sep","end","file","flush"} for key,_ in keywords):
            raise ClassUnsupported(node)
        return cell("none")
    if name == "input" and not arguments and not keywords:
        return cell("str")
    if name in {"int","str","bool","float"} and len(arguments) <= 1 and not keywords:
        return cell({"int":"int","str":"str","bool":"bool","float":"float"}[name])
    if name == "len" and len(arguments) == 1 and not keywords:
        return cell("int")
    if name in {"abs","id"} and len(arguments) == 1 and not keywords:
        if name=="abs":
            from .native_classes import shape
            from .native_types import alternatives
            if "float"in alternatives(shape(arguments[0])):
                kinds=[Cell("float")]
                if any(value in {"int","bool","int_bool"}for value in alternatives(shape(arguments[0]))):kinds.append(Cell("int"))
                return cell(kinds[0].tag)if len(kinds)==1 else cell("union",tuple(kinds))
        return cell("int")
    if name == "range" and 1 <= len(arguments) <= 3 and not keywords:
        return cell("range")
    if name=="enumerate":
        from .native_enumerate import analyze as analyze_enumerate
        return analyze_enumerate(model,plan,node,arguments,keywords,environment,factory=cell)
    if name == "filter" and len(arguments)==2 and not keywords:
        result=model.iterators.filter(plan,node,arguments[0],arguments[1])
        return cell(result.root().tag)
    if name == "map" and len(arguments)>=2 and all(key=="strict"for key,_ in keywords):
        result=model.iterators.map(plan,node,arguments[0],arguments[1:])
        return cell(result.root().tag)
    if name == "zip" and all(key=="strict"for key,_ in keywords):
        result=model.iterators.zip(plan,node,arguments)
        return cell(result.root().tag)
    if name in {"iter","reversed"} and len(arguments)==1 and not keywords:
        return cell(model.iterators.source(plan,node,arguments[0],operation="reverse"if name=="reversed"else"source"))
    if name == "next" and 1<=len(arguments)<=2 and not keywords:
        from .native_class_iterators import iterator_kind
        from .native_types import alternatives
        from .native_classes import shape,Environment
        result=cell()
        kinds=alternatives(shape(arguments[0]))
        valid=[kind for kind in kinds if iterator_kind(kind)or getattr(kind,'_native_class_generator',False)]
        if len(valid)==len(kinds):
            model.contribute(result,model.iterators.demand(plan,node,arguments[0],environment),node)
        elif valid:
            branches=[Environment(environment)]
            for kind in valid:
                inside=Environment(environment)
                model.contribute(result,model.iterators.demand(plan,node,model.cell_for_kind(kind),inside),node)
                branches.append(inside)
            joined=branches[0]
            for branch in branches[1:]:joined=model.join(joined,branch,node,'next_iterator_union')
            model.replace_environment(environment,joined)
        elif shape(arguments[0])is not None:model.contribute(result,Cell("none"),node)
        if len(arguments)==2:model.contribute(result,arguments[1],node)
        return result
    if name in {"any","all"}and len(arguments)==1 and not keywords:
        from .native_classes import shape
        from .native_class_iterators import iterator_kind
        source=arguments[0]
        if not iterator_kind(shape(source))and not getattr(shape(source),'_native_class_generator',False):
            source=Cell(model.iterators.source(plan,node,source))
        model.iterators.demand(plan,node,source,environment)
        return cell("bool")
    if name == "list" and len(arguments) <= 1 and not keywords:
        result = cell("list",(Cell(),))
        if arguments:
            from .native_class_materialization import list_source
            arguments=[list_source(model,plan,node,arguments[0])]
            self.contribute(result.root().args[0],self.iterators.demand(plan,node,arguments[0],environment),node)
        return result
    if name == "sum" and 1 <= len(arguments) <= 2 and not keywords:
        from .native_types import EmptyType
        source=arguments[0]
        from .native_classes import shape
        if self.iterators.needs_source_cursor(shape(source)):source=Cell(self.iterators.source(plan,node,source))
        item = self.iterators.demand(plan,node,source,environment).root()
        if not isinstance(item.tag,EmptyType)and item.tag not in {None,"int","bool","int_bool"}:
            raise ClassUnsupported(node)
        start=arguments[1]if len(arguments)==2 else Cell("int")
        if start.root().tag not in {None,"int","bool","int_bool"}:
            raise ClassUnsupported(node,"this sum start needs its numeric/container addition and initial-value identity protocol; only builtin integer and boolean starts are currently represented",proof="sum start and addition result representation")
        result=cell()
        self.contribute(result,start,node)
        if not isinstance(item.tag,EmptyType):self.contribute(result,Cell("int"),node)
        return result
    if name in {"min","max"} and arguments and not keywords:
        result = cell()
        for value in arguments if len(arguments)>1 else [self.iterators.demand(plan,node,arguments[0],environment)]:
            merge(result,value,node)
        return result
    return None


def emit(emitter,node,identity,arguments,keywords,wanted,raw_kind):
    from .native_classes import Expression
    from .native_unions import project,union_kind
    from .native_builtin_singletons import has_singleton
    if identity.name=="print"and "flush"in keywords and has_singleton(keywords["flush"].kind):
        checked=emitter.fresh()
        converted=emitter.truth(keywords["flush"],node)
        result=emit(emitter,node,identity,arguments,{**keywords,"flush":Expression(checked,"bool")},wanted,raw_kind)
        return Expression("{let "+checked+"="+converted+";"+result.code+"}",result.kind)
    if identity.name=='int':
        from .native_integer_base import emit as emit_integer_base
        explicit=emit_integer_base(emitter,node,arguments,keywords,wanted)
        if explicit is not None:return explicit
    if identity.name in {'ord','bin','oct','hex'}:
        from .native_character_builtins import emit as emit_character
        return emit_character(emitter,node,identity.name,arguments,keywords,wanted)
    if identity.name in {"format","repr","ascii"}:
        from .native_formatting import emit_builtin
        return emit_builtin(emitter,node,identity.name,arguments,keywords,wanted)
    if identity.name in {'min','max'}:
        from .native_class_extrema import emit as emit_extrema
        return emit_extrema(emitter,node,identity.name,arguments,keywords,wanted)
    if identity.name=='tuple':
        from .native_class_materialization import emit_tuple
        return emit_tuple(emitter,node,arguments,wanted)
    if identity.name in {'dict','set'}:
        return emitter.model.mappings.emit_builtin(emitter,node,identity.name,arguments,keywords,wanted)
    if identity.name=='sorted':
        from .native_class_sorting import emit_builtin
        return emit_builtin(emitter,node,arguments,keywords,wanted)
    if arguments and getattr(arguments[0].kind,'_native_class_generator',False):
        from .native_immediate_generators import CONSUMERS
        if identity.name in CONSUMERS:return emitter.model.generators.consume(emitter,node,identity.name,arguments[0],arguments,keywords,wanted)
    if identity.name == 'isinstance':
        from .native_type_checks import emit as emit_type_check
        return emit_type_check(emitter,node,arguments)
    if identity.name=='divmod':
        from .native_class_divmod import emit as emit_divmod
        return emit_divmod(emitter,node,arguments,keywords,wanted)
    if identity.name=='pow':
        from .native_class_numeric_calls import emit as emit_numeric
        return emit_numeric(emitter,node,identity,arguments,keywords,wanted)
    # Inspect finite tagged alternatives over captured values. Arguments and
    # keyword expressions have already run; these matches never replay them.
    if identity.name in {"len","abs","int","bool","float","list","sum","next"}and arguments and union_kind(arguments[0].kind):
        value=arguments[0]
        code=project(value.kind,value.code,lambda kind,code:emit(emitter,node,identity,
            [Expression(f"({code}).clone()",kind)]+arguments[1:],keywords,wanted,raw_kind).code)
        return Expression(code,wanted)
    if identity.name=="print":
        for key in ("sep","end","file"):
            value=keywords.get(key)
            if value is not None and union_kind(value.kind):
                code=project(value.kind,value.code,lambda kind,code:emit(emitter,node,identity,arguments,
                    {**keywords,key:Expression(f"({code}).clone()",kind)},wanted,raw_kind).code)
                return Expression(code,wanted)
    return _emit(emitter,node,identity,arguments,keywords,wanted,raw_kind)


def _type_name(emitter,value,node):
    from .native_classes import domain
    from .native import _string
    if hasattr(value.kind,'_native_python_type_name'):return _string(value.kind._native_python_type_name)
    tag=domain(value.kind)
    if tag=='cmp_key':return '"functools.KeyWrapper"'
    if tag=="int_bool":return f'match {value.code}{{NativeScalar::Int(_)=>"int",NativeScalar::Bool(_)=>"bool"}}'
    if tag=="object":return _string(emitter.model.classes[value.kind.name].node.name)
    if tag=="globals_dict":return '"dict"'
    if getattr(value.kind,'_native_class_mapping',False)and value.kind.record.flavor in {'Counter','defaultdict'}:return _string(value.kind.record.flavor)
    if tag=="iterator"and value.kind.record.operation in {"filter","map","zip","enumerate"}:
        return _string(value.kind.record.operation)
    if tag=="iterator"and hasattr(value.kind.record,"tool"):return _string("itertools."+value.kind.record.tool)
    if tag=="tuple_sequence":return '"tuple"'
    if tag=='dict_view':return _string('dict_'+value.kind.record.mode)
    if tag=="function":
        from .native_aot_callables import variant
        arms=[f'{emitter.model.callable_cells.reference_pattern(definition)}=>"function"'for definition in value.kind.definitions]
        arms.extend(f'{emitter.model.callable_cells.bound_methods.reference_pattern(target)}=>"method"'for target in value.kind.methods)
        for identity in value.kind.builtins:
            from .native_type_checks import TYPE_NAMES
            name="type"if identity.name in TYPE_NAMES else"builtin_function_or_method"
            arms.append(f'{variant(identity)}=>{_string(name)}')
        for identity in value.kind.members:
            adapter=emitter.model.callable_cells.member_adapters.get(identity.module)
            name="type"if adapter is not None and identity.name in getattr(adapter,"TYPES",())else"builtin_function_or_method"
            arms.append(f'{variant(identity)}=>{_string(name)}')
        arms.append('_=>unreachable!("callable type contradicts finite family")')
        return f'match {value.code}{{'+','.join(arms)+'}'
    return _string({"none":"NoneType"}.get(tag,tag))


def _error(emitter,node,kind,message):
    from .native_classes import Expression
    return Expression(emitter.at(f'Err::<{emitter.rust_type(kind)},String>({message})',node),kind)


def _emit(emitter,node,identity,arguments,keywords,wanted,raw_kind):
    from .native import _Expression
    from .native_classes import Expression,ClassUnsupported,domain
    from .native_types import ListType
    self=emitter
    name=identity.name
    if name=="enumerate":
        from .native_enumerate import emit as emit_enumerate
        return emit_enumerate(emitter,node,arguments,keywords,wanted)
    code=None
    if name=="globals":code="ClassGlobalsView(class_scope.globals.clone())"
    elif name in {"input","reader_text","reader_bytes","read_text","read_bytes"}:
        if name in {"reader_bytes","read_bytes"}:
            code = self.at(f"class_read_bytes(&class_scope,{str(name=='reader_bytes').lower()})",node)
        else:
            code = self.at(f"class_read_text(&class_scope,{str(name!='read_text').lower()},{str(name=='input').lower()})",node)
    elif name == "print":
        sep = keywords.get("sep",Expression('" ".to_owned()','str'))
        end = keywords.get("end",Expression('"\\n".to_owned()','str'))
        if sep.kind == 'none':
            sep = Expression('" ".to_owned()','str')
        if end.kind == 'none':
            end = Expression('"\\n".to_owned()','str')
        for key,value in (("sep",sep),("end",end)):
            if value.kind!='str':
                name=_type_name(emitter,value,node)
                return _error(emitter,node,wanted,f'format!("TypeError: {key} must be None or a string, not {{}}",{name})')
        if "file"in keywords and keywords["file"].kind!="none":
            raise ClassUnsupported(node,"this print file needs the supplied writer object's write/flush protocol; typed arbitrary output writers are not implemented",proof="print file writer protocol")
        pieces=[]
        for i,value in enumerate(arguments):
            if i:
                pieces.append(f"class_scope.io.borrow_mut().output.push_str(&{sep.code});")
            pieces.append(f"class_scope.io.borrow_mut().output.push_str(&({self.show(value,node)}));")
        pieces.append(f"class_scope.io.borrow_mut().output.push_str(&{end.code});")
        if "flush"in keywords:
            flush = self.truth(keywords["flush"])
            call = self.at("native_flush_output(&mut class_scope.io.borrow_mut().output)",node)
            pieces.append(f"if {flush}{{{call};}}")
        code = "{"+"".join(pieces)+"()}"
    elif name == "len":
        value=arguments[0]
        if domain(value.kind)=='dict_view':length=self.model.mappings.views.length(self,value)
        elif domain(value.kind)in {"list","dict","set","deque"}:length=f"{value.code}.borrow().len()"
        elif domain(value.kind)=="str":
            length=f"{value.code}."+("len()"if self.model.string_mode=="ascii"else"codepoint_len()")
        elif domain(value.kind)in {"bytes","tuple_sequence"}:length=f"{value.code}.len()"
        elif domain(value.kind)=="tuple":length=str(len(value.kind.fields))
        elif domain(value.kind)=="globals_dict":length=f"class_globals_length(&{value.code})"
        elif domain(value.kind)=="range":
            raise ClassUnsupported(node,"len(range) needs a checked structural range-length calculation; that length helper is not implemented on this typed frame path",proof="range structural length and OverflowError")
        else:
            name=_type_name(emitter,value,node)
            return _error(emitter,node,wanted,f'format!("TypeError: object of type \'{{}}\' has no len()",{name})')
        code=f"class_from_usize({length})"
        raw_kind='int'
    elif name == "int":
        raw_kind='int'
        if not arguments:code=self.literal(0)
        elif domain(arguments[0].kind) in {"int","bool","int_bool"}:code=self.number(arguments[0])
        elif arguments[0].kind=='str':code=self.at(f"class_parse_text(&{arguments[0].code})",node)
        elif arguments[0].kind=='bytes':code=self.at(f"class_parse_bytes(&{arguments[0].code})",node)
        elif arguments[0].kind=='float':
            operation="Int::from_f64"if self.model.integer=="bigint"else"native_float_integer"
            code=self.at(f"{operation}({arguments[0].code})",node)
        else:
            name=_type_name(emitter,arguments[0],node)
            return _error(emitter,node,wanted,f'format!("TypeError: int() argument must be a string, a bytes-like object or a real number, not \'{{}}\'",{name})')
    elif name == "str":
        code=('NativeText::new()'if not arguments else arguments[0].code+'.clone()'
              if arguments[0].kind=="str"else self.show(arguments[0],node))
    elif name == "bool":
        code='false'if not arguments else self.truth(arguments[0],node)
        raw_kind='bool'
    elif name == "float":
        from .native_float_constructor import frame_value
        code="0.0_f64"if not arguments else frame_value(self,arguments[0],node)
    elif name == "abs":
        value=arguments[0]
        if domain(value.kind)in{"int","bool","int_bool"}:
            number=self.number(value)
            code=f"({number}).abs()"if self.model.integer=="bigint"else f"({number}).wrapping_abs()"
            raw_kind='int'
        elif value.kind=="float":code=f"({value.code}).abs()";raw_kind="float"
        else:
            name=_type_name(emitter,value,node)
            return _error(emitter,node,wanted,f'format!("TypeError: bad operand type for abs(): \'{{}}\'",{name})')
    elif name == "id":
        if domain(arguments[0].kind)not in{"object","list","iterator","dict","set","dict_view"}:raise ClassUnsupported(node)
        code=f"class_from_usize(Rc::as_ptr(&{arguments[0].code}) as usize)"
        raw_kind='int'
    elif name == "range":
        values=[self.number(value)for value in arguments]
        if len(values)==1:values.insert(0,self.literal(0))
        if len(values)==2:values.append(self.literal(1))
        code=self.at("class_range("+",".join(values)+")",node)
    elif name == "filter":
        return self.model.iterators.emit_filter(self,node,arguments[0],arguments[1],wanted)
    elif name == "map":
        return self.model.iterators.emit_map(self,node,arguments[0],arguments[1:],keywords.get("strict",Expression("false","bool",False)),wanted)
    elif name == "zip":
        return self.model.iterators.emit_multiple(self,node,arguments,keywords.get("strict",Expression("false","bool",False)),wanted)
    elif name in {"iter","reversed"}:
        return self.model.iterators.construct(self,node,arguments[0],kind=wanted)
    elif name == "next":
        from .native_class_iterators import iterator_kind
        if not iterator_kind(arguments[0].kind):
            actual=_type_name(self,arguments[0],node)
            return _error(self,node,wanted,f'format!("TypeError: \'{{}}\' object is not an iterator",{actual})')
        pulled=self.model.iterators.pull(self,node,arguments[0]);current=self.fresh()
        present=self.coerce(Expression(current,pulled.kind),wanted,node)
        absent=self.coerce(arguments[1],wanted,node)if len(arguments)==2 else self.at(f'Err::<{self.rust_type(wanted)},String>("StopIteration".to_owned())',node)
        return Expression(f"match {pulled.code}{{Some({current})=>{present},None=>{absent}}}",wanted)
    elif name in {"any","all"}:
        from .native_class_iterators import iterator_kind
        source=arguments[0];setup=""
        if not iterator_kind(source.kind):
            setup,source=self.capture(self.model.iterators.construct(self,node,source))
        pulled=self.model.iterators.pull(self,node,source);current=self.fresh();test=self.truth(Expression(current,pulled.kind),node)
        if name=="all":test="!("+test+")"
        return Expression("{"+setup+"loop{"+f"let Some({current})=({pulled.code}) else{{break {str(name=='all').lower()};}};if {test}{{break {str(name=='any').lower()};}}"+"}}","bool")
    elif name == "list":
        if not arguments:code=f"class_list(Vec::<{self.rust_type(wanted.element)}>::new())"
        elif self.model.mappings.views.element(arguments[0].kind)is not None:
            before,source=self.capture(self.model.iterators.construct(self,node,arguments[0]))
            pulled=self.model.iterators.pull(self,node,source);current=self.fresh();values=self.fresh()
            item=self.coerce(Expression(current,pulled.kind),wanted.element,node)
            code="{"+before+f"let mut {values}=Vec::<{self.rust_type(wanted.element)}>::new();loop{{let Some({current})=({pulled.code}) else{{break;}};{values}.push({item});}}class_list({values})"+"}"
        elif domain(arguments[0].kind)=="iterator":
            pulled=self.model.iterators.pull(self,node,arguments[0]);current=self.fresh();values=self.fresh()
            item=self.coerce(Expression(current,pulled.kind),wanted.element,node)
            code="{"+f"let mut {values}=Vec::<{self.rust_type(wanted.element)}>::new();loop{{let Some({current})=({pulled.code}) else{{break;}};{values}.push({item});}}class_list({values})"+"}"
        elif domain(arguments[0].kind)=="list":
            source=arguments[0]
            if source.kind.element==wanted.element:code=f"class_list({source.code}.borrow().clone())"
            else:
                item=self.fresh()
                converted=self.coerce(Expression(item+".clone()",source.kind.element),wanted.element,node)
                code=f"class_list({source.code}.borrow().iter().map(|{item}|{converted}).collect::<Vec<{self.rust_type(wanted.element)}>>())"
        elif domain(arguments[0].kind)=="tuple_sequence":
            source=arguments[0];item=self.fresh()
            converted=self.coerce(Expression(item+".clone()",source.kind.element),wanted.element,node)
            code=f"class_list({source.code}.iter().map(|{item}|{converted}).collect::<Vec<{self.rust_type(wanted.element)}>>())"
        elif domain(arguments[0].kind)=="range":
            values=f"{arguments[0].code}.iter()"
            if wanted.element!='int':
                item=self.fresh()
                converted=self.coerce(Expression(item,'int'),wanted.element,node)
                values+=f".map(|{item}|{converted})"
            code=f"class_list(({values}).collect::<Vec<_>>())"
        elif domain(arguments[0].kind)=="tuple":
            value=arguments[0]
            elements=[self.coerce(Expression(f"{value.code}.{i}.clone()",kind),wanted.element,node)for i,kind in enumerate(value.kind.fields)]
            code="class_list(vec!["+",".join(elements)+"])"
        elif domain(arguments[0].kind)in {"none","int","bool","int_bool","float","function"}:
            name=_type_name(self,arguments[0],node)
            return _error(self,node,wanted,f'format!("TypeError: \'{{}}\' object is not iterable",{name})')
        else:
            before,source=self.capture(self.model.iterators.construct(self,node,arguments[0]))
            pulled=self.model.iterators.pull(self,node,source);current=self.fresh();values=self.fresh()
            item=self.coerce(Expression(current,pulled.kind),wanted.element,node)
            code="{"+before+f"let mut {values}=Vec::<{self.rust_type(wanted.element)}>::new();loop{{let Some({current})=({pulled.code}) else{{break;}};{values}.push({item});}}class_list({values})"+"}"
    elif name in {"min","max","sum"}:
        accumulator=self.fresh();member=self.fresh()
        if name=="sum":
            start=arguments[1]if len(arguments)==2 else Expression(self.literal(0),'int',0)
            code=f"{{let mut {accumulator}={self.coerce(start,wanted,node)};"
            stream=arguments[0]
        elif len(arguments)>1:
            code=f"{{let mut {accumulator}={self.coerce(arguments[0],wanted,node)};"
            stream=None
            for candidate in arguments[1:]:
                value=Expression(self.coerce(candidate,wanted,node),wanted)
                comparison=self.comparison(ast.Lt()if name=="min"else ast.Gt(),value,Expression(accumulator,wanted),node)
                code+=f"if {comparison}{{{accumulator}={value.code};}}"
            code+=accumulator+"}"
        else:
            code=f"{{let mut {accumulator}:Option<{self.rust_type(wanted)}>=None;"
            stream=arguments[0]
        if stream is not None:
            pull=None
            if self.model.iterators.needs_source_cursor(stream.kind):
                before,stream=self.capture(self.model.iterators.construct(self,node,stream));code+=before
            if domain(stream.kind)=="iterator":
                pull=self.model.iterators.pull(self,node,stream);kind=pull.kind
            elif domain(stream.kind)=="list":
                iterator=f"{stream.code}.borrow().iter().cloned()";kind=stream.kind.element
            elif domain(stream.kind)=="tuple_sequence":
                iterator=f"{stream.code}.iter().cloned()";kind=stream.kind.element
            elif domain(stream.kind)=="range":
                iterator=f"{stream.code}.iter()";kind='int'
            elif domain(stream.kind)=="tuple" and bool(stream.kind.fields):
                kind=wanted if name!="sum"else'int'
                values=[self.coerce(Expression(f"{stream.code}.{i}.clone()",old),kind,node)for i,old in enumerate(stream.kind.fields)]
                iterator="["+",".join(values)+"].into_iter()"
            else:raise ClassUnsupported(node)
            from .native_types import EmptyType
            if name=="sum":
                if isinstance(kind,EmptyType):action=f"match {member}{{}};"
                else:
                    value=self.numeric.binary(ast.Add(),self.scalar(Expression(accumulator+".clone()",wanted)),self.scalar(Expression(member,kind)),node)
                    action=f"{accumulator}={self.coerce(value,wanted,node)};"
                ending=accumulator
            else:
                if isinstance(kind,EmptyType):action=f"match {member}{{}};"
                else:
                    value=self.coerce(Expression(member,kind),wanted,node)
                    candidate=self.fresh();old=self.fresh()
                    comparison=self.comparison(ast.Lt()if name=="min"else ast.Gt(),Expression(candidate+".clone()",wanted),Expression(old+".clone()",wanted),node)
                    action=f"let {candidate}={value};let replace=match &{accumulator}{{Some({old})=>{comparison},None=>true}};if replace{{{accumulator}=Some({candidate});}}"
                ending=self.at(f'{accumulator}.ok_or_else(||"ValueError: {name}() iterable argument is empty".to_owned())',node)
            if pull is not None:code+=f"loop{{let Some({member})=({pull.code}) else{{break;}};{action}}}{ending}}}"
            else:code+=f"for {member} in {iterator}{{{action}}}{ending}}}"
    if code is None:
        raise ClassUnsupported(node,f"captured builtin {name!r} needs an iterator/object protocol not implemented by this typed builtin adapter",proof="builtin result/iterator representation")
    if raw_kind=="str":code=f"NativeText::from({code})"
    return self.encoded(code,raw_kind,wanted,node)
