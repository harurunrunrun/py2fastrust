// Runtime Python compiler. This module deliberately shares the AOT VM's instruction
// format: dynamically compiled functions have exactly the same calling convention.
#[derive(Clone, Debug)]
struct DExpr { kind: DExprKind, line: usize, column: usize }
#[derive(Clone, Debug)]
enum DExprKind {
    Constant(Const), Imaginary(f64), UnicodeString(String), Ellipsis, Name(String), List(Vec<DExpr>), Tuple(Vec<DExpr>), Set(Vec<DExpr>), Dict(Vec<(Option<DExpr>, DExpr)>),
    Unary(String, Box<DExpr>), Binary(String, Box<DExpr>, Box<DExpr>), Bool(String, Vec<DExpr>),
    Compare(Box<DExpr>, Vec<(String, DExpr)>), Conditional(Box<DExpr>, Box<DExpr>, Box<DExpr>),
    Attribute(Box<DExpr>, String), Subscript(Box<DExpr>, Box<DExpr>), Slice(Option<Box<DExpr>>, Option<Box<DExpr>>, Option<Box<DExpr>>),
    Call(Box<DExpr>, Vec<DExpr>, Vec<(Option<String>, DExpr)>), Star(Box<DExpr>),
    Named(String, Box<DExpr>), Lambda(DParams, Box<DExpr>), Yield(Option<Box<DExpr>>, bool),
    Joined(Vec<DExpr>), Template(Vec<DExpr>), RawInterpolation(String,Box<DExpr>), Formatted(Box<DExpr>, i32, Option<Box<DExpr>>),
    Comprehension { kind: String, element: Box<DExpr>, value: Option<Box<DExpr>>, generators: Vec<DGenerator> },
}
#[derive(Clone, Debug)]
struct DGenerator { target: DExpr, iter: DExpr, filters: Vec<DExpr> }
#[derive(Clone, Debug, Default)]
struct DParams { params: Params, defaults: Vec<DExpr>, kwdefaults: Vec<(String, DExpr)>, annotations: Vec<(String,DExpr)> }
#[derive(Clone, Debug)]
struct DTypeParam { name:String, kind:String, bound:Option<DExpr>, constraints:Option<DExpr>, default:Option<DExpr> }
#[derive(Clone, Debug)]
struct DStmt { kind: DStmtKind, line: usize, column: usize }
#[derive(Clone, Debug)]
enum DStmtKind {
    Generic(Vec<DTypeParam>,Box<DStmtKind>), TypeAlias(String,Vec<DTypeParam>,DExpr),
    // Compiler-only nodes keep generated lexical bindings out of user scopes.
    TypeParameter(DTypeParam), TypeDefinition(Box<DStmtKind>),
    Expr(DExpr), Assign(Vec<DExpr>, DExpr), AnnAssign(DExpr, DExpr, Option<DExpr>, bool), AugAssign(DExpr, String, DExpr), Delete(Vec<DExpr>),
    If(DExpr, Vec<DStmt>, Vec<DStmt>), While(DExpr, Vec<DStmt>, Vec<DStmt>), For(DExpr, DExpr, Vec<DStmt>, Vec<DStmt>),
    Function(String, DParams, Vec<DStmt>, Vec<DExpr>), Class(String, Vec<DExpr>, Vec<(Option<String>, DExpr)>, Vec<DStmt>, Vec<DExpr>),
    Return(Option<DExpr>), Break, Continue, Pass, Raise(Option<DExpr>, Option<DExpr>), Assert(DExpr, Option<DExpr>),
    Global(Vec<String>), Nonlocal(Vec<String>),
    Try(Vec<DStmt>, Vec<(Option<DExpr>, Option<String>, Vec<DStmt>)>, Vec<DStmt>, Vec<DStmt>),
    TryStar(Vec<DStmt>, Vec<(Option<DExpr>, Option<String>, Vec<DStmt>)>, Vec<DStmt>, Vec<DStmt>),
    With(Vec<(DExpr, Option<DExpr>)>, Vec<DStmt>),
    Match(DExpr, Vec<(MatchPattern, Option<DExpr>, Vec<DStmt>)>),
    Import(Vec<(String, Option<String>)>), ImportFrom(String, Vec<(String, Option<String>)>, usize),
}

const D_FUTURE_ANNOTATIONS: u32 = 0x1000000;
const D_FUTURE_BARRY: u32 = 0x400000;

fn d_future_feature(name: &str) -> Result<u32,String> {
    match name {
        "nested_scopes" | "generators" | "division" | "absolute_import" | "with_statement" | "print_function" | "unicode_literals" | "generator_stop" => Ok(0),
        "annotations" => Ok(D_FUTURE_ANNOTATIONS),
        "barry_as_FLUFL" => Ok(D_FUTURE_BARRY),
        "braces" => Err("not a chance".to_owned()),
        _ => Err(format!("future feature {name} is not defined")),
    }
}

fn d_identifier(raw: &str) -> Result<String,String> {
    let name=text_nfkc(raw);
    if ["None","True","False"].contains(&name.as_str()) { return Err(format!("ValueError: identifier field can't represent '{name}' constant")); }
    Ok(name)
}

fn d_pattern_irrefutable(pattern: &MatchPattern) -> bool {
    match pattern { MatchPattern::As { pattern:None,.. }=>true,MatchPattern::As { pattern:Some(pattern),.. }=>d_pattern_irrefutable(pattern),MatchPattern::Or(patterns)=>patterns.iter().any(d_pattern_irrefutable),_=>false }
}
fn d_pattern_bindings(pattern: &MatchPattern) -> Result<Vec<String>,String> {
    let mut names = Vec::new();
    let mut extend = |new_names: Vec<String>| -> Result<(),String> { for name in new_names { if names.contains(&name) { return Err(format!("multiple assignments to name '{name}' in pattern")); } names.push(name); } Ok(()) };
    match pattern {
        MatchPattern::As { pattern,name } => { if let Some(pattern) = pattern { if matches!(**pattern,MatchPattern::Star(_)) { return Err("star pattern requires a sequence".to_owned()); } extend(d_pattern_bindings(pattern)?)?; } if let Some(name) = name { extend(vec![name.clone()])?; } }
        MatchPattern::Star(name) => if let Some(name) = name { extend(vec![name.clone()])?; },
        MatchPattern::Sequence(patterns) => {
            if patterns.iter().filter(|pattern|matches!(pattern,MatchPattern::Star(_))).count() > 1 { return Err("multiple starred names in sequence pattern".to_owned()); }
            for pattern in patterns { extend(d_pattern_bindings(pattern)?)?; }
        }
        MatchPattern::Mapping { patterns,rest,.. } => { for pattern in patterns { if matches!(pattern,MatchPattern::Star(_)) { return Err("star pattern requires a sequence".to_owned()); } extend(d_pattern_bindings(pattern)?)?; } if let Some(name) = rest { extend(vec![name.clone()])?; } }
        MatchPattern::Class { positional,keyword_patterns,.. } => for pattern in positional.iter().chain(keyword_patterns) { if matches!(pattern,MatchPattern::Star(_)) { return Err("star pattern requires a sequence".to_owned()); } extend(d_pattern_bindings(pattern)?)?; },
        MatchPattern::Or(patterns) => {
            for (index,pattern) in patterns.iter().enumerate() {
                if d_pattern_irrefutable(pattern) && index+1 < patterns.len() { return Err("irrefutable alternative makes remaining patterns unreachable".to_owned()); }
                if matches!(pattern,MatchPattern::Star(_)) { return Err("star pattern requires a sequence".to_owned()); }
                let mut bound = d_pattern_bindings(pattern)?; bound.sort();
                if index == 0 { names = bound; } else if names != bound { return Err("alternative patterns bind different names".to_owned()); }
            }
        }
        _ => (),
    }
    Ok(names)
}
fn d_const_numeric_equal(a:&Const,b:&Const)->bool{
    let decimal=|value:&str|if value=="-0"{"0".to_owned()}else{value.to_owned()};
    match(a,b){
        (Const::Int(a),Const::Int(b))=>decimal(a)==decimal(b),
        (Const::Float(a),Const::Float(b))=>a==b,
        (Const::Bool(a),Const::Bool(b))=>a==b,
        (Const::Bool(a),Const::Int(b))|(Const::Int(b),Const::Bool(a))=>decimal(b)==if *a{"1"}else{"0"},
        (Const::Bool(a),Const::Float(b))|(Const::Float(b),Const::Bool(a))=>*b==if *a{1.0}else{0.0},
        (Const::Int(a),Const::Float(b))|(Const::Float(b),Const::Int(a))=>b.is_finite()&&b.fract()==0.0&&decimal(a)==decimal(&format!("{b:.0}")),
        _=>false,
    }
}
fn d_pattern_literal_equal(a:&MatchPattern,b:&MatchPattern)->bool{
    let parts=|value:&MatchPattern|match value{
        MatchPattern::ComplexNumber{real,imag}=>Some((real.clone(),*imag)),
        MatchPattern::Literal(Const::Complex(real,imag))=>Some((Const::Float(*real),*imag)),
        MatchPattern::Literal(value @ (Const::Int(_)|Const::Float(_)|Const::Bool(_)))=>Some((value.clone(),0.0)),_=>None,
    };
    if let(Some((ar,ai)),Some((br,bi)))=(parts(a),parts(b)){return ai==bi&&d_const_numeric_equal(&ar,&br);}
    match(a,b){
        (MatchPattern::Literal(Const::None),MatchPattern::Literal(Const::None))=>true,
        (MatchPattern::Literal(Const::Str(a)),MatchPattern::Literal(Const::Str(b)))=>a==b,
        (MatchPattern::Literal(Const::Bytes(a)),MatchPattern::Literal(Const::Bytes(b)))=>a==b,_=>false,
    }
}

fn d_contains_named(expr: &DExpr) -> bool {
    match &expr.kind {
        DExprKind::Named(..) => true,
        DExprKind::List(values) | DExprKind::Tuple(values) | DExprKind::Set(values) | DExprKind::Joined(values) | DExprKind::Template(values) | DExprKind::Bool(_,values) => values.iter().any(d_contains_named),
        DExprKind::RawInterpolation(_,value)=>d_contains_named(value),
        DExprKind::Dict(items) => items.iter().any(|(key,value)|key.as_ref().is_some_and(d_contains_named) || d_contains_named(value)),
        DExprKind::Unary(_,value) | DExprKind::Star(value) | DExprKind::Attribute(value,_) => d_contains_named(value),
        DExprKind::Binary(_,a,b) | DExprKind::Subscript(a,b) => d_contains_named(a) || d_contains_named(b),
        DExprKind::Compare(a,tail) => d_contains_named(a) || tail.iter().any(|(_,value)|d_contains_named(value)),
        DExprKind::Conditional(a,b,c) => d_contains_named(a) || d_contains_named(b) || d_contains_named(c),
        DExprKind::Slice(a,b,c) => [a,b,c].iter().any(|value|value.as_deref().is_some_and(d_contains_named)),
        DExprKind::Call(fun,args,keywords) => d_contains_named(fun) || args.iter().any(d_contains_named) || keywords.iter().any(|(_,value)|d_contains_named(value)),
        DExprKind::Lambda(params,body) => d_contains_named(body) || params.defaults.iter().any(d_contains_named) || params.kwdefaults.iter().any(|(_,value)|d_contains_named(value)),
        DExprKind::Yield(value,_) => value.as_deref().is_some_and(d_contains_named),
        DExprKind::Formatted(value,_,spec) => d_contains_named(value) || spec.as_deref().is_some_and(d_contains_named),
        DExprKind::Comprehension { element,value,generators,.. } => d_contains_named(element) || value.as_deref().is_some_and(d_contains_named) || generators.iter().any(|generator|d_contains_named(&generator.iter) || d_contains_named(&generator.target) || generator.filters.iter().any(d_contains_named)),
        _ => false,
    }
}

fn d_static_target(target: &DExpr, names: &mut Vec<String>) {
    match &target.kind {
        DExprKind::Attribute(object,name) if matches!(&object.kind,DExprKind::Name(name) if name == "self") => d_push_name(names,name),
        DExprKind::Tuple(items) | DExprKind::List(items) => for item in items { d_static_target(item,names); },
        DExprKind::Star(target) => d_static_target(target,names),
        _ => (),
    }
}
fn d_static_attributes(body: &[DStmt], in_function: bool, names: &mut Vec<String>) {
    for stmt in body {
        match &stmt.kind {
            DStmtKind::Generic(_,definition)=>d_static_attributes(&[DStmt{kind:(**definition).clone(),line:stmt.line,column:stmt.column}],in_function,names),
            DStmtKind::Function(_,_,body,_) => d_static_attributes(body,true,names),
            DStmtKind::Class(..) => (),
            DStmtKind::Assign(targets,value) if in_function && !matches!(&value.kind,DExprKind::Name(name) if name == "$unbound_annotation") => for target in targets { d_static_target(target,names); },
            DStmtKind::AnnAssign(target,_,Some(_),_) if in_function => d_static_target(target,names),
            DStmtKind::If(_,body,tail) | DStmtKind::While(_,body,tail) => { d_static_attributes(body,in_function,names); d_static_attributes(tail,in_function,names); },
            DStmtKind::For(target,_,body,tail) => { if in_function { d_static_target(target,names); } d_static_attributes(body,in_function,names); d_static_attributes(tail,in_function,names); },
            DStmtKind::Try(body,handlers,tail,finally) | DStmtKind::TryStar(body,handlers,tail,finally) => { d_static_attributes(body,in_function,names); for (_,_,body) in handlers { d_static_attributes(body,in_function,names); } d_static_attributes(tail,in_function,names); d_static_attributes(finally,in_function,names); },
            DStmtKind::With(items,body) => { if in_function { for (_,target) in items { if let Some(target) = target { d_static_target(target,names); } } } d_static_attributes(body,in_function,names); },
            DStmtKind::Match(_,cases) => for (_,_,body) in cases { d_static_attributes(body,in_function,names); },
            _ => (),
        }
    }
}

fn d_validate_futures(body: &[DStmt], filename: &str, top_level: bool) -> Result<(),String> {
    let mut allowed = top_level;
    for (index,stmt) in body.iter().enumerate() {
        if let DStmtKind::ImportFrom(module,names,0) = &stmt.kind {
            if module == "__future__" {
                if !allowed { return Err(format!("SyntaxError: from __future__ imports must occur at the beginning of the file ({filename}:{})",stmt.line)); }
                for (name,_) in names { d_future_feature(name).map_err(|message|format!("SyntaxError: {message} ({filename}:{})",stmt.line))?; }
                continue;
            }
        }
        if !(top_level && index == 0 && d_docstring(stmt).is_some()) { allowed = false; }
        match &stmt.kind {
            DStmtKind::Generic(_,definition)=>d_validate_futures(&[DStmt{kind:(**definition).clone(),line:stmt.line,column:stmt.column}],filename,false)?,
            DStmtKind::Function(_,_,body,_) | DStmtKind::Class(_,_,_,body,_) => d_validate_futures(body,filename,false)?,
            DStmtKind::If(_,body,tail) | DStmtKind::While(_,body,tail) | DStmtKind::For(_,_,body,tail) => { d_validate_futures(body,filename,false)?; d_validate_futures(tail,filename,false)?; },
            DStmtKind::Try(body,handlers,tail,finally) | DStmtKind::TryStar(body,handlers,tail,finally) => { d_validate_futures(body,filename,false)?; for (_,_,body) in handlers { d_validate_futures(body,filename,false)?; } d_validate_futures(tail,filename,false)?; d_validate_futures(finally,filename,false)?; },
            DStmtKind::With(_,body) => d_validate_futures(body,filename,false)?,
            DStmtKind::Match(_,cases) => for (_,_,body) in cases { d_validate_futures(body,filename,false)?; },
            _ => (),
        }
    }
    Ok(())
}

// A control transfer may leave an inner loop while remaining in the except*
// handler. It cannot escape any active except* handler in the same code scope.
fn d_validate_except_star(body:&[DStmt],filename:&str,loops:usize,barriers:&[usize])->Result<(),String>{
    for statement in body{
        let invalid=match statement.kind{DStmtKind::Return(_)=>!barriers.is_empty(),DStmtKind::Break|DStmtKind::Continue=>barriers.last().is_some_and(|boundary|loops<=*boundary),_=>false};
        if invalid{return Err(format!("SyntaxError: 'break', 'continue' and 'return' cannot appear in an except* block ({filename}:{})",statement.line));}
        match &statement.kind{
            DStmtKind::Function(_,_,body,_)|DStmtKind::Class(_,_,_,body,_)=>d_validate_except_star(body,filename,0,&[])?,
            DStmtKind::Generic(_,definition)=>d_validate_except_star(&[DStmt{kind:(**definition).clone(),line:statement.line,column:statement.column}],filename,loops,barriers)?,
            DStmtKind::If(_,body,tail)=>{d_validate_except_star(body,filename,loops,barriers)?;d_validate_except_star(tail,filename,loops,barriers)?;},
            DStmtKind::While(_,body,tail)|DStmtKind::For(_,_,body,tail)=>{d_validate_except_star(body,filename,loops+1,barriers)?;d_validate_except_star(tail,filename,loops,barriers)?;},
            DStmtKind::With(_,body)=>d_validate_except_star(body,filename,loops,barriers)?,
            DStmtKind::Match(_,cases)=>for (_,_,body)in cases{d_validate_except_star(body,filename,loops,barriers)?;},
            DStmtKind::Try(body,handlers,tail,finally)|DStmtKind::TryStar(body,handlers,tail,finally)=>{
                d_validate_except_star(body,filename,loops,barriers)?;
                let mut handler_barriers=barriers.to_vec();if matches!(statement.kind,DStmtKind::TryStar(..)){handler_barriers.push(loops);}
                for(_,_,body)in handlers{d_validate_except_star(body,filename,loops,&handler_barriers)?;}
                d_validate_except_star(tail,filename,loops,barriers)?;d_validate_except_star(finally,filename,loops,barriers)?;
            },
            _=>{},
        }
    }Ok(())
}

fn d_docstring(statement: &DStmt) -> Option<&String> {
    match &statement.kind { DStmtKind::Expr(DExpr { kind:DExprKind::Constant(Const::Str(text)) | DExprKind::UnicodeString(text),.. })=>Some(text),_=>None }
}

fn d_has_annotations(body: &[DStmt]) -> bool {
    body.iter().any(|stmt| match &stmt.kind {
        DStmtKind::AnnAssign(..) => true,
        DStmtKind::If(_,body,tail) | DStmtKind::While(_,body,tail) | DStmtKind::For(_,_,body,tail) => d_has_annotations(body) || d_has_annotations(tail),
        DStmtKind::Try(body,handlers,tail,finally) | DStmtKind::TryStar(body,handlers,tail,finally) => d_has_annotations(body) || handlers.iter().any(|(_,_,body)|d_has_annotations(body)) || d_has_annotations(tail) || d_has_annotations(finally),
        DStmtKind::With(_,body) => d_has_annotations(body),
        DStmtKind::Match(_,cases) => cases.iter().any(|(_,_,body)|d_has_annotations(body)),
        _ => false,
    })
}

fn d_annotation_violation(expression: &DExpr) -> Option<&'static str> {
    let scan=|values:&[DExpr]|values.iter().find_map(d_annotation_violation);
    match &expression.kind {
        DExprKind::Named(..)=>Some("named expression cannot be used within an annotation"),
        DExprKind::Yield(..)=>Some("yield expression cannot be used within an annotation"),
        // Lambda defaults run in the enclosing annotation scope. Its body has
        // its own scope and may contain assignment expressions or yields.
        DExprKind::Lambda(params,_)=>scan(&params.defaults).or_else(||params.kwdefaults.iter().find_map(|(_,value)|d_annotation_violation(value))),
        DExprKind::List(values)|DExprKind::Tuple(values)|DExprKind::Set(values)|DExprKind::Joined(values)|DExprKind::Template(values)|DExprKind::Bool(_,values)=>scan(values),
        DExprKind::RawInterpolation(_,value)=>d_annotation_violation(value),
        DExprKind::Dict(items)=>items.iter().find_map(|(key,value)|key.as_ref().and_then(d_annotation_violation).or_else(||d_annotation_violation(value))),
        DExprKind::Unary(_,value)|DExprKind::Star(value)|DExprKind::Attribute(value,_)=>d_annotation_violation(value),
        DExprKind::Binary(_,a,b)|DExprKind::Subscript(a,b)=>d_annotation_violation(a).or_else(||d_annotation_violation(b)),
        DExprKind::Compare(a,tail)=>d_annotation_violation(a).or_else(||tail.iter().find_map(|(_,value)|d_annotation_violation(value))),
        DExprKind::Conditional(a,b,c)=>d_annotation_violation(a).or_else(||d_annotation_violation(b)).or_else(||d_annotation_violation(c)),
        DExprKind::Slice(a,b,c)=>[a,b,c].iter().find_map(|value|value.as_ref().and_then(|value|d_annotation_violation(value))),
        DExprKind::Call(fun,args,keywords)=>d_annotation_violation(fun).or_else(||scan(args)).or_else(||keywords.iter().find_map(|(_,value)|d_annotation_violation(value))),
        DExprKind::Formatted(value,_,spec)=>d_annotation_violation(value).or_else(||spec.as_ref().and_then(|value|d_annotation_violation(value))),
        DExprKind::Comprehension{element,value,generators,..}=>d_annotation_violation(element).or_else(||value.as_ref().and_then(|value|d_annotation_violation(value))).or_else(||generators.iter().find_map(|generator|d_annotation_violation(&generator.iter).or_else(||scan(&generator.filters)))),
        _=>None,
    }
}

// Canonical expression strings used by CO_FUTURE_ANNOTATIONS. Precedence and
// spacing follow CPython's AST expression printer, rather than source slices.
fn d_annotation_string(expression: &DExpr) -> String { d_unparse(expression,0) }
fn d_unparse_tuple(items: &[DExpr], parenthesized: bool) -> String {
    let mut body=items.iter().map(|item|d_unparse(item,2)).collect::<Vec<_>>().join(", ");
    if items.len()==1 { body.push(','); }
    if parenthesized || items.is_empty() { format!("({body})") } else { body }
}
fn d_unparse_params(parameters: &DParams) -> String {
    let p=&parameters.params; let mut values=Vec::new(); let start=p.positional.len()-parameters.defaults.len();
    for (index,name) in p.positional.iter().enumerate() {
        let mut text=name.clone(); if index>=start { text.push('=');text.push_str(&d_unparse(&parameters.defaults[index-start],2)); } values.push(text);
        if index+1==p.posonly { values.push("/".to_owned()); }
    }
    if let Some(name)=&p.vararg { values.push(format!("*{name}")); } else if !p.kwonly.is_empty() { values.push("*".to_owned()); }
    for name in &p.kwonly { let mut text=name.clone();if let Some((_,value))=parameters.kwdefaults.iter().find(|(key,_)|key==name){text.push('=');text.push_str(&d_unparse(value,2));}values.push(text); }
    if let Some(name)=&p.kwarg { values.push(format!("**{name}")); }
    values.join(", ")
}
fn d_unparse_generators(generators: &[DGenerator]) -> String {
    let mut result=String::new();
    for generator in generators {
        result.push_str(" for ");
        result.push_str(&match &generator.target.kind { DExprKind::Tuple(items)=>d_unparse_tuple(items,false),_=>d_unparse(&generator.target,0) });
        result.push_str(" in ");result.push_str(&d_unparse(&generator.iter,5));
        for filter in &generator.filters { result.push_str(" if ");result.push_str(&d_unparse(filter,5)); }
    }
    result
}
fn d_unparse_fstring(values: &[DExpr]) -> String {
    let mut result=String::new();
    for value in values {
        match &value.kind {
            DExprKind::Constant(Const::Str(text))=>result.push_str(&text.replace('{',"{{").replace('}',"}}")),
            DExprKind::Formatted(value,conversion,spec)=>{
                result.push('{');result.push_str(&d_unparse(value,2));
                if *conversion!=-1 { result.push('!');if let Some(ch)=char::from_u32(*conversion as u32){result.push(ch);} }
                if let Some(spec)=spec { result.push(':');if let DExprKind::Joined(values)=&spec.kind {result.push_str(&d_unparse_fstring(values));} }
                result.push('}');
            },
            _=>(),
        }
    }
    result
}
fn d_unparse(expression: &DExpr, required: u8) -> String {
    let (precedence,text)=match &expression.kind {
        DExprKind::Constant(value)=>(18,match value {
            Const::None=>"None".to_owned(),Const::Bool(value)=>if *value{"True"}else{"False"}.to_owned(),Const::Int(value)=>value.clone(),
            Const::Float(value)=>if value.is_infinite(){if value.is_sign_negative(){"-1e309"}else{"1e309"}.to_owned()}else{let text=format!("{value:?}");if let Some((mantissa,exponent))=text.split_once('e'){format!("{mantissa}e{:+03}",exponent.parse::<i32>().unwrap_or(0))}else{text}},
            Const::Complex(real,imag)=>format!("({real:?}{imag:+}j)"),
            Const::Str(value)=>text_repr_str(value),Const::Bytes(value)=>text_repr_bytes(value),
        }),
        DExprKind::UnicodeString(value)=>(18,format!("u{}",text_repr_str(value))),
        DExprKind::Imaginary(value)=>{
            let mut text=if value.is_infinite(){"1e309".to_owned()}else{let text=format!("{value:?}");if let Some((mantissa,exponent))=text.split_once('e'){format!("{mantissa}e{:+03}",exponent.parse::<i32>().unwrap_or(0))}else{text.strip_suffix(".0").unwrap_or(&text).to_owned()}};
            text.push('j');(18,text)
        },
        DExprKind::Ellipsis=>(18,"...".to_owned()),
        DExprKind::Name(name)=>(18,name.clone()),
        DExprKind::List(items)=>(18,format!("[{}]",items.iter().map(|item|d_unparse(item,2)).collect::<Vec<_>>().join(", "))),
        DExprKind::Tuple(items)=>(18,d_unparse_tuple(items,true)),
        DExprKind::Set(items)=>(18,format!("{{{}}}",items.iter().map(|item|d_unparse(item,2)).collect::<Vec<_>>().join(", "))),
        DExprKind::Dict(items)=>(18,format!("{{{}}}",items.iter().map(|(key,value)|match key {Some(key)=>format!("{}: {}",d_unparse(key,2),d_unparse(value,2)),None=>format!("**{}",d_unparse(value,2))}).collect::<Vec<_>>().join(", "))),
        DExprKind::Unary(op,value)=>{let p=if op=="not"{7}else{15};(p,format!("{}{}{}",op,if op=="not"{" "}else{""},d_unparse(value,p)))},
        DExprKind::Binary(op,a,b)=>{let p=match op.as_str(){"|"=>9,"^"=>10,"&"=>11,"<<"|">>"=>12,"+"|"-"=>13,"*"|"@"|"/"|"//"|"%"=>14,_=>16};let power=op=="**";(p,format!("{} {op} {}",d_unparse(a,p+if power{1}else{0}),d_unparse(b,p+if power{0}else{1})))},
        DExprKind::Bool(op,values)=>{let p=if op=="or"{5}else{6};(p,values.iter().map(|value|d_unparse(value,p+1)).collect::<Vec<_>>().join(&format!(" {op} ")))},
        DExprKind::Compare(a,tail)=>{let mut text=d_unparse(a,9);for(op,b)in tail{text.push(' ');text.push_str(op);text.push(' ');text.push_str(&d_unparse(b,9));}(8,text)},
        DExprKind::Conditional(condition,a,b)=>(4,format!("{} if {} else {}",d_unparse(a,5),d_unparse(condition,5),d_unparse(b,4))),
        DExprKind::Attribute(value,name)=>{let mut value_text=d_unparse(value,18);if matches!(&value.kind,DExprKind::Constant(Const::Int(_))){value_text.push(' ');}(18,format!("{value_text}.{name}"))},
        DExprKind::Subscript(value,index)=>{let index=match &index.kind{DExprKind::Tuple(items)=>d_unparse_tuple(items,false),_=>d_unparse(index,0)};(18,format!("{}[{index}]",d_unparse(value,18)))},
        DExprKind::Slice(lower,upper,step)=>{let part=|value:&Option<Box<DExpr>>|value.as_ref().map(|value|d_unparse(value,0)).unwrap_or_default();let mut text=format!("{}:{}",part(lower),part(upper));if step.is_some(){text.push(':');text.push_str(&part(step));}(18,text)},
        DExprKind::Call(value,args,keywords)=>{
            let mut items=Vec::new();
            for arg in args { if args.len()==1 && keywords.is_empty() { if let DExprKind::Comprehension {kind,element,generators,..}=&arg.kind {if kind=="generator"{items.push(format!("{}{}",d_unparse(element,2),d_unparse_generators(generators)));continue;}} }items.push(d_unparse(arg,2)); }
            for(name,value)in keywords{items.push(match name{Some(name)=>format!("{name}={}",d_unparse(value,2)),None=>format!("**{}",d_unparse(value,2))});}
            (18,format!("{}({})",d_unparse(value,18),items.join(", ")))
        },
        DExprKind::Star(value)=>(2,format!("*{}",d_unparse(value,3))),
        DExprKind::Named(name,value)=>(18,format!("({name} := {})",d_unparse(value,0))),
        DExprKind::Lambda(parameters,value)=>{let args=d_unparse_params(parameters);(3,format!("lambda{}: {}",if args.is_empty(){String::new()}else{format!(" {args}")},d_unparse(value,3)))},
        DExprKind::Yield(value,from)=>(2,format!("yield{}{}",if *from{" from"}else{""},value.as_ref().map(|value|format!(" {}",d_unparse(value,0))).unwrap_or_default())),
        DExprKind::Joined(values)=>(18,format!("f{}",text_repr_str(&d_unparse_fstring(values)))),
        DExprKind::Template(values)=>(18,format!("t{}",text_repr_str(&d_unparse_fstring(values)))),
        DExprKind::RawInterpolation(source,_)=>(18,source.clone()),
        DExprKind::Formatted(..)=>(18,String::new()),
        DExprKind::Comprehension{kind,element,value,generators}=>{
            let (open,close)=match kind.as_str(){"list"=>("[","]"),"generator"=>("(",")"),_=>("{","}")};
            let head=if let Some(value)=value{format!("{}: {}",d_unparse(element,2),d_unparse(value,2))}else{d_unparse(element,2)};
            (18,format!("{open}{head}{}{close}",d_unparse_generators(generators)))
        },
    };
    if precedence<required {format!("({text})")}else{text}
}

fn d_number(raw: &str) -> Result<Const,String> {
    if raw.ends_with('j') || raw.ends_with('J') { return Err("complex numbers are not yet supported".to_owned()); }
    if raw.starts_with('_') || raw.ends_with('_') || raw.contains("__") { return Err("invalid numeric literal".to_owned()); }
    let number = raw.replace('_', "");
    let (radix, digits) = if number.starts_with("0x") || number.starts_with("0X") { (16,&number[2..]) }
        else if number.starts_with("0o") || number.starts_with("0O") { (8,&number[2..]) }
        else if number.starts_with("0b") || number.starts_with("0B") { (2,&number[2..]) } else { (10,number.as_str()) };
    let raw_chars: Vec<char> = raw.chars().collect();
    for (index,ch) in raw_chars.iter().enumerate() {
        if *ch == '_' {
            let prefix_separator = radix != 10 && index == 2;
            if (!prefix_separator && raw_chars.get(index.wrapping_sub(1)).and_then(|x|x.to_digit(radix)).is_none()) || raw_chars.get(index+1).and_then(|x|x.to_digit(radix)).is_none() { return Err("invalid numeric literal".to_owned()); }
        }
    }
    if radix == 10 && (number.contains('.') || number.contains('e') || number.contains('E')) {
        return number.parse::<f64>().map(Const::Float).map_err(|_| "invalid floating-point literal".to_owned());
    }
    if digits.is_empty() || !digits.chars().all(|x| x.to_digit(radix).is_some()) { return Err("invalid integer literal".to_owned()); }
    if radix == 10 && digits.len() > 1 && digits.starts_with('0') && digits.chars().any(|x| x != '0') { return Err("leading zeros in decimal integer literals are not permitted".to_owned()); }
    // Decimal conversion uses small limbs, independent of the selected runtime width.
    let mut decimal = vec![0u32];
    for ch in digits.chars() {
        let mut carry = ch.to_digit(radix).unwrap() as u64;
        for limb in &mut decimal { let value = *limb as u64 * radix as u64 + carry; *limb = (value % 1_000_000_000) as u32; carry = value / 1_000_000_000; }
        if carry != 0 { decimal.push(carry as u32); }
    }
    let mut text = decimal.pop().unwrap().to_string(); while let Some(limb) = decimal.pop() { text.push_str(&format!("{limb:09}")); }
    Ok(Const::Int(text))
}

fn d_imaginary(raw: &str) -> Result<f64,String> {
    let body=&raw[..raw.len()-1];
    if body.contains('.') || body.contains('e') || body.contains('E') {
        return match d_number(body)? { Const::Float(value)=>Ok(value),_=>Err("invalid imaginary literal".to_owned()) };
    }
    if body.is_empty() || body.starts_with('_') || body.ends_with('_') || body.contains("__") || !body.chars().all(|ch|ch.is_ascii_digit() || ch=='_') { return Err("invalid imaginary literal".to_owned()); }
    body.replace('_',"").parse::<f64>().map_err(|_|"invalid imaginary literal".to_owned())
}

// Decode only static pieces after the PEG tokenizer has recognized braces.
fn d_decode_formatted_text(text:&str,raw:bool)->Result<String,String>{
    if raw{return Ok(text.to_owned());}
    let mut chars=text.chars().peekable();let mut result=String::new();
    while let Some(ch)=chars.next(){
        if ch!='\\'{result.push(ch);continue;}
        let Some(next)=chars.next()else{result.push(ch);break;};
        match next{
            '\n'=>{},'\\'=>result.push('\\'),'\''=>result.push('\''),'"'=>result.push('"'),
            'n'=>result.push('\n'),'r'=>result.push('\r'),'t'=>result.push('\t'),'a'=>result.push('\x07'),'b'=>result.push('\x08'),'f'=>result.push('\x0c'),'v'=>result.push('\x0b'),
            'x'|'u'|'U'=>{
                let width=if next=='x'{2}else if next=='u'{4}else{8};let mut value=0;
                for _ in 0..width{value=value*16+chars.next().and_then(|ch|ch.to_digit(16)).ok_or_else(||"SyntaxError: truncated hexadecimal escape".to_owned())?;}
                result.push(char::from_u32(value).ok_or_else(||"SyntaxError: invalid Unicode escape".to_owned())?);
            },
            '0'..='7'=>{
                let mut value=next.to_digit(8).unwrap();for _ in 0..2{if let Some(digit)=chars.peek().and_then(|ch|ch.to_digit(8)){chars.next();value=value*8+digit;}else{break;}}
                result.push(char::from_u32(value).unwrap());
            },
            'N'=>{
                if chars.next()!=Some('{'){return Err("SyntaxError: malformed \\N character escape".to_owned());}
                let mut name=String::new();let mut closed=false;
                for ch in chars.by_ref(){if ch=='}'{closed=true;break;}name.push(ch);}
                if !closed || name.is_empty(){return Err("SyntaxError: malformed \\N character escape".to_owned());}
                let value=unicode_character_name(&name).ok_or_else(||"SyntaxError: unknown Unicode character name".to_owned())?;
                result.push(value);
            },
            other=>{result.push('\\');result.push(other);},
        }
    }
    Ok(result)
}

#[derive(Default)]
struct DSymbols { locals: Vec<String>, globals: Vec<String>, nonlocals: Vec<String>, uses: Vec<String>, annotated: Vec<String>, error: Option<String>, generator: bool, private: Option<String> }
fn d_push_name(names: &mut Vec<String>, name: &str) { if !names.iter().any(|x| x == name) { names.push(name.to_owned()); } }

// Mangling belongs to a lexical class context, including its nested functions
// and comprehensions. Runtime strings and call keyword names stay literal.
fn d_mangle(private: &Option<String>, name: &str) -> String {
    if name.starts_with("__") && !name.ends_with("__") && !name.contains('.') {
        if let Some(class) = private {
            let class = class.trim_start_matches('_');
            if !class.is_empty() { return format!("_{class}{name}"); }
        }
    }
    name.to_owned()
}
fn d_mangle_pattern(private: &Option<String>, pattern: MatchPattern) -> MatchPattern {
    let names = |path: Vec<String>| path.into_iter().map(|name| d_mangle(private,&name)).collect();
    match pattern {
        MatchPattern::ValuePath(path) => MatchPattern::ValuePath(names(path)),
        MatchPattern::Sequence(patterns) => MatchPattern::Sequence(patterns.into_iter().map(|pattern| d_mangle_pattern(private,pattern)).collect()),
        MatchPattern::Or(patterns) => MatchPattern::Or(patterns.into_iter().map(|pattern| d_mangle_pattern(private,pattern)).collect()),
        MatchPattern::Mapping { keys,patterns,rest } => MatchPattern::Mapping { keys:keys.into_iter().map(|pattern| d_mangle_pattern(private,pattern)).collect(), patterns:patterns.into_iter().map(|pattern| d_mangle_pattern(private,pattern)).collect(), rest:rest.map(|name|d_mangle(private,&name)) },
        MatchPattern::Class { path,positional,keyword_names,keyword_patterns } => MatchPattern::Class { path:names(path), positional:positional.into_iter().map(|pattern|d_mangle_pattern(private,pattern)).collect(), keyword_names, keyword_patterns:keyword_patterns.into_iter().map(|pattern|d_mangle_pattern(private,pattern)).collect() },
        MatchPattern::As { pattern,name } => MatchPattern::As { pattern:pattern.map(|pattern|Box::new(d_mangle_pattern(private,*pattern))), name:name.map(|name|d_mangle(private,&name)) },
        MatchPattern::Star(name) => MatchPattern::Star(name.map(|name|d_mangle(private,&name))),
        pattern => pattern,
    }
}
impl DSymbols {
    fn target(&mut self, expr: &DExpr) {
        match &expr.kind {
            DExprKind::Name(name) => d_push_name(&mut self.locals,&d_mangle(&self.private,name)),
            DExprKind::Tuple(values) | DExprKind::List(values) => for value in values { self.target(value); },
            DExprKind::Star(value) => self.target(value),
            DExprKind::Subscript(a,b) => { self.expr(a); self.expr(b); },
            DExprKind::Attribute(a,_) => self.expr(a), _ => (),
        }
    }
    fn expr(&mut self, expr: &DExpr) {
        match &expr.kind {
            DExprKind::Name(name) => d_push_name(&mut self.uses,&d_mangle(&self.private,name)),
            DExprKind::Named(name,value) => { d_push_name(&mut self.locals,&d_mangle(&self.private,name)); self.expr(value); },
            DExprKind::Yield(value,_) => { self.generator = true; if let Some(value) = value { self.expr(value); } },
            DExprKind::Lambda(params,_) => { for value in &params.defaults { self.expr(value); } for (_,value) in &params.kwdefaults { self.expr(value); } },
            DExprKind::Comprehension { element,value,generators,.. } => {
                // Iteration variables belong to the implicit comprehension function.
                // Named expressions, however, bind in the containing scope.
                if let Some(first) = generators.first() { self.expr(&first.iter); }
                self.comprehension_named(element); if let Some(value) = value { self.comprehension_named(value); }
                for generator in generators { self.comprehension_named(&generator.iter); for value in &generator.filters { self.comprehension_named(value); } }
            }
            DExprKind::List(values) | DExprKind::Tuple(values) | DExprKind::Set(values) | DExprKind::Joined(values) | DExprKind::Template(values) | DExprKind::Bool(_,values) => for value in values { self.expr(value); },
            DExprKind::RawInterpolation(_,value)=>self.expr(value),
            DExprKind::Dict(items) => for (key,value) in items { if let Some(key) = key { self.expr(key); } self.expr(value); },
            DExprKind::Unary(_,value) | DExprKind::Star(value) | DExprKind::Attribute(value,_) => self.expr(value),
            DExprKind::Binary(_,a,b) | DExprKind::Subscript(a,b) => { self.expr(a); self.expr(b); },
            DExprKind::Compare(a,tail) => { self.expr(a); for (_,b) in tail { self.expr(b); } },
            DExprKind::Conditional(a,b,c) => { self.expr(a); self.expr(b); self.expr(c); },
            DExprKind::Slice(a,b,c) => for value in [a,b,c] { if let Some(value) = value { self.expr(value); } },
            DExprKind::Call(fun,args,keywords) => { self.expr(fun); for arg in args { self.expr(arg); } for (_,value) in keywords { self.expr(value); } },
            DExprKind::Formatted(value,_,spec) => { self.expr(value); if let Some(spec) = spec { self.expr(spec); } },
            _ => (),
        }
    }
    fn comprehension_named(&mut self, expr: &DExpr) {
        let mut nested = Self { private:self.private.clone(),..Self::default() }; nested.expr(expr);
        for name in nested.locals { d_push_name(&mut self.locals,&name); }
    }
    fn pattern_uses(&mut self, pattern: &MatchPattern) {
        match pattern {
            MatchPattern::ValuePath(path) => if let Some(name)=path.first(){d_push_name(&mut self.uses,&d_mangle(&self.private,name));},
            MatchPattern::Class { path,positional,keyword_patterns,.. } => {
                if let Some(name)=path.first(){d_push_name(&mut self.uses,&d_mangle(&self.private,name));}
                for pattern in positional.iter().chain(keyword_patterns){self.pattern_uses(pattern);}
            },
            MatchPattern::Sequence(patterns) | MatchPattern::Or(patterns) => for pattern in patterns{self.pattern_uses(pattern);},
            MatchPattern::Mapping { keys,patterns,.. } => for pattern in keys.iter().chain(patterns){self.pattern_uses(pattern);},
            MatchPattern::As { pattern:Some(pattern),.. } => self.pattern_uses(pattern),
            _ => (),
        }
    }
    fn block(&mut self, body: &[DStmt]) { for stmt in body { self.stmt(stmt); } }
    fn stmt(&mut self, stmt: &DStmt) {
        match &stmt.kind {
            DStmtKind::TypeAlias(name,_,_)=>d_push_name(&mut self.locals,&d_mangle(&self.private,name)),
            DStmtKind::TypeParameter(parameter)=>d_push_name(&mut self.locals,&d_mangle(&self.private,&parameter.name)),
            DStmtKind::Generic(_,definition)=>{
                match &**definition {
                    DStmtKind::Function(name,params,_,decorators)=>{
                        d_push_name(&mut self.locals,&d_mangle(&self.private,name));
                        for value in decorators.iter().chain(&params.defaults).chain(params.kwdefaults.iter().map(|(_,value)|value)){self.expr(value);}
                    },
                    DStmtKind::Class(name,_,_,_,decorators)=>{
                        d_push_name(&mut self.locals,&d_mangle(&self.private,name));for value in decorators{self.expr(value);}
                    },
                    _=>{},
                }
            },
            DStmtKind::TypeDefinition(definition)=>match &**definition {
                DStmtKind::Function(_,params,_,_)=>{for value in params.defaults.iter().chain(params.kwdefaults.iter().map(|(_,value)|value)){self.expr(value);}},
                DStmtKind::Class(_,bases,keywords,_,_)=>{for value in bases.iter().chain(keywords.iter().map(|(_,value)|value)){self.expr(value);}},
                _=>{},
            },
            DStmtKind::Assign(targets,value) => { self.expr(value); for target in targets { self.target(target); } },
            DStmtKind::AnnAssign(target,_,value,_) => {
                if let Some(value) = value { self.expr(value); }
                self.target(target);
                if let DExprKind::Name(name) = &target.kind { d_push_name(&mut self.annotated,&d_mangle(&self.private,name)); }
            },
            DStmtKind::AugAssign(target,_,value) => { self.target(target); self.expr(value); },
            DStmtKind::Delete(targets) => for target in targets { self.target(target); },
            DStmtKind::Expr(value) => self.expr(value),
            DStmtKind::If(test,body,tail) | DStmtKind::While(test,body,tail) => { self.expr(test); self.block(body); self.block(tail); },
            DStmtKind::For(target,iter,body,tail) => { self.expr(iter); self.target(target); self.block(body); self.block(tail); },
            DStmtKind::Function(name,params,_,decorators) => {
                d_push_name(&mut self.locals,&d_mangle(&self.private,name)); for value in decorators { self.expr(value); }
                for value in &params.defaults { self.expr(value); } for (_,value) in &params.kwdefaults { self.expr(value); }
            }
            DStmtKind::Class(name,bases,keywords,_,decorators) => {
                d_push_name(&mut self.locals,&d_mangle(&self.private,name)); for value in decorators { self.expr(value); } for value in bases { self.expr(value); } for (_,value) in keywords { self.expr(value); }
            }
            DStmtKind::Global(names) => for name in names {
                let name=d_mangle(&self.private,name);
                if !self.globals.contains(&name) && (self.locals.contains(&name) || self.uses.contains(&name)) {
                    self.error = Some(format!("SyntaxError: name '{name}' is used prior to global declaration (line {})",stmt.line));
                }
                if self.nonlocals.contains(&name) { self.error = Some(format!("SyntaxError: name '{name}' is both nonlocal and global (line {})",stmt.line)); }
                d_push_name(&mut self.globals,&name);
            },
            DStmtKind::Nonlocal(names) => for name in names {
                let name=d_mangle(&self.private,name);
                if !self.nonlocals.contains(&name) && (self.locals.contains(&name) || self.uses.contains(&name)) {
                    self.error = Some(format!("SyntaxError: name '{name}' is used prior to nonlocal declaration (line {})",stmt.line));
                }
                if self.globals.contains(&name) { self.error = Some(format!("SyntaxError: name '{name}' is both global and nonlocal (line {})",stmt.line)); }
                d_push_name(&mut self.nonlocals,&name);
            },
            DStmtKind::Return(value) => if let Some(value) = value { self.expr(value); },
            DStmtKind::Raise(value,cause) => { if let Some(value) = value { self.expr(value); } if let Some(cause) = cause { self.expr(cause); } },
            DStmtKind::Assert(test,message) => { self.expr(test); if let Some(message) = message { self.expr(message); } },
            DStmtKind::Try(body,handlers,tail,finally) | DStmtKind::TryStar(body,handlers,tail,finally) => {
                self.block(body); for (exception,name,handler) in handlers { if let Some(exception) = exception { self.expr(exception); } if let Some(name) = name { d_push_name(&mut self.locals,&d_mangle(&self.private,name)); } self.block(handler); } self.block(tail); self.block(finally);
            }
            DStmtKind::With(items,body) => { for (value,target) in items { self.expr(value); if let Some(target) = target { self.target(target); } } self.block(body); },
            DStmtKind::Match(subject,cases) => {
                self.expr(subject);
                for (pattern,guard,body) in cases {
                    self.pattern_uses(pattern);
                    if let Ok(names) = d_pattern_bindings(pattern) { for name in names { d_push_name(&mut self.locals,&d_mangle(&self.private,&name)); } }
                    if let Some(guard) = guard { self.expr(guard); } self.block(body);
                }
            }
            DStmtKind::Import(names) => for (name,alias) in names { d_push_name(&mut self.locals,&d_mangle(&self.private,alias.as_ref().map(|x| x.as_str()).unwrap_or_else(|| name.split('.').next().unwrap()))); },
            DStmtKind::ImportFrom(_,names,_) => for (name,alias) in names { if name != "*" { d_push_name(&mut self.locals,&d_mangle(&self.private,alias.as_ref().unwrap_or(name))); } },
            _ => (),
        }
    }
}

struct DLoop { start: usize, breaks: Vec<usize>, continues: Vec<usize> }
struct DCtx { index: usize, loops: Vec<DLoop>, scopes: Vec<(ScopeKind,Vec<String>,Vec<String>)>, private: Option<String> }
fn d_scope_binds(scopes: &[(ScopeKind,Vec<String>,Vec<String>)], name: &str) -> bool {
    for (kind,locals,globals) in scopes.iter().rev() {
        if *kind==ScopeKind::Class { if name=="__class__"{return true;}continue; }
        if *kind==ScopeKind::Module || globals.iter().any(|value|value==name) { return false; }
        if locals.iter().any(|value|value==name) { return true; }
    }
    false
}
fn d_annotation_class_scope(scopes:&[(ScopeKind,Vec<String>,Vec<String>)])->bool {
    for (kind,_,_) in scopes.iter().rev(){match kind{ScopeKind::Class=>return true,ScopeKind::Annotation|ScopeKind::TypeParameters=>{},_=>return false}}
    false
}
#[derive(Clone)]
struct DAnnotation {name:String,value:DExpr,index:Option<usize>,line:usize,column:usize}
fn d_collect_annotations(body:&[DStmt],conditional:bool,records:&mut Vec<DAnnotation>,next:&mut usize){
    for statement in body {match &statement.kind {
        DStmtKind::AnnAssign(DExpr{kind:DExprKind::Name(name),..},value,_,true)=>{
            let index=if conditional{let index=*next;*next+=1;Some(index)}else{None};
            records.push(DAnnotation{name:name.clone(),value:value.clone(),index,line:statement.line,column:statement.column});
        },
        DStmtKind::If(_,body,tail)|DStmtKind::While(_,body,tail)|DStmtKind::For(_,_,body,tail)=>{
            d_collect_annotations(body,true,records,next);d_collect_annotations(tail,true,records,next);
        },
        DStmtKind::With(_,body)=>d_collect_annotations(body,true,records,next),
        DStmtKind::Try(body,handlers,tail,finally) | DStmtKind::TryStar(body,handlers,tail,finally)=>{
            d_collect_annotations(body,true,records,next);for (_,_,body) in handlers{d_collect_annotations(body,true,records,next);}
            d_collect_annotations(tail,true,records,next);d_collect_annotations(finally,true,records,next);
        },
        DStmtKind::Match(_,cases)=>for (_,_,body) in cases{d_collect_annotations(body,true,records,next);},
        _=>{},
    }}
}
struct DCompiler { codes: Vec<Code>, filename: String, offset: usize, temporary: usize, interactive: bool, future_flags: u32, scope_annotations:HashMap<usize,Vec<DAnnotation>>, stringized_annotation:bool, optimize:u8 }
// CPython 3.14 Python/compile.c, _PyCompile_CleanDoc (PSF license).
// Common indentation is removed while blank lines retain their positions.
fn d_clean_doc(value:&str)->String{
    let mut expanded=String::new();let mut column=0usize;
    for ch in value.chars(){match ch{
        '\t'=>{let count=8-column%8;expanded.extend(std::iter::repeat(' ').take(count));column+=count;},
        '\n'|'\r'=>{expanded.push(ch);column=0;},
        _=>{expanded.push(ch);column+=1;},
    }}
    let mut lines:Vec<&str>=expanded.split('\n').collect();
    let margin=lines.iter().skip(1).filter(|line|!line.trim_matches(' ').is_empty()).map(|line|line.len()-line.trim_start_matches(' ').len()).min().unwrap_or(0);
    lines[0]=lines[0].trim_start_matches(' ');
    if margin>0{for line in lines.iter_mut().skip(1){let count=margin.min(line.len()-line.trim_start_matches(' ').len());*line=&line[count..];}}
    lines.join("\n")
}
impl DCompiler {
    fn error(&self, line: usize, message: &str) -> String { format!("SyntaxError: {message} ({}:{line})",self.filename) }
    fn temporary(&mut self, ctx: &DCtx) -> String {
        let name = format!("\0dynamic{}",self.temporary); self.temporary += 1;
        self.codes[ctx.index].locals.push(name.clone()); name
    }
    fn emit(&mut self, ctx: &DCtx, op: Op, line: usize, column: usize) -> usize {
        let op = match op {
            Op::Load(name) => Op::Load(d_mangle(&ctx.private,&name)),
            Op::Store(name) => Op::Store(d_mangle(&ctx.private,&name)),
            Op::Delete(name) => Op::Delete(d_mangle(&ctx.private,&name)),
            Op::GetAttr(name) => Op::GetAttr(d_mangle(&ctx.private,&name)),
            Op::GetSpecialAttr(name) => Op::GetSpecialAttr(d_mangle(&ctx.private,&name)),
            Op::SetAttr(name) => Op::SetAttr(d_mangle(&ctx.private,&name)),
            Op::DelAttr(name) => Op::DelAttr(d_mangle(&ctx.private,&name)),
            Op::Import { module,names,level } => Op::Import { module:d_mangle(&ctx.private,&module),names,level },
            Op::ImportFrom(name) => Op::ImportFrom(d_mangle(&ctx.private,&name)),
            Op::MakeFunction { code,defaults,kwdefaults } => Op::MakeFunction { code,defaults,kwdefaults:kwdefaults.into_iter().map(|name|d_mangle(&ctx.private,&name)).collect() },
            Op::Match(pattern) => Op::Match(d_mangle_pattern(&ctx.private,pattern)),
            op => op,
        };
        let at = self.codes[ctx.index].ops.len(); self.codes[ctx.index].ops.push(Instr { op,line,column }); at
    }
    fn here(&self, ctx: &DCtx) -> usize { self.codes[ctx.index].ops.len() }
    fn propagate_frees(&mut self, child: usize, enclosing: &DCtx) {
        if self.codes[enclosing.index].kind==ScopeKind::Module { return; }
        for name in self.codes[child].frees.clone() {
            let parent=&mut self.codes[enclosing.index];
            if parent.kind==ScopeKind::Class {
                // This class creates its own __class__ cell. Other closures
                // pass through class namespaces even when a class name/global
                // declaration has the same spelling.
                if name!="__class__" { d_push_name(&mut parent.frees,&name); }
            } else if !parent.locals.contains(&name) && !parent.globals.contains(&name) {
                d_push_name(&mut parent.frees,&name);
            }
        }
    }
    fn order_cell_locals(&mut self, index: usize) {
        if !matches!(self.codes[index].kind,ScopeKind::Function | ScopeKind::Comprehension | ScopeKind::TypeParameters) { return; }
        let parameters=&self.codes[index].params;
        let parameters:Vec<String>=parameters.positional.iter().chain(parameters.kwonly.iter()).chain(parameters.vararg.iter()).chain(parameters.kwarg.iter()).cloned().collect();
        let mut cells=Vec::new();
        for instruction in &self.codes[index].ops {
            let child=match &instruction.op { Op::MakeFunction { code,.. } | Op::MakeClass { code,.. } | Op::MakeClassEx { code,.. }=>code.checked_sub(self.offset),_=>None };
            if let Some(child)=child.and_then(|child|self.codes.get(child)) {
                for name in &child.frees { if self.codes[index].locals.contains(name) && !parameters.contains(name) { d_push_name(&mut cells,name); } }
            }
        }
        cells.sort();
        self.codes[index].locals.retain(|name|!cells.contains(name));
        self.codes[index].locals.extend(cells);
    }
    fn patch(&mut self, ctx: &DCtx, at: usize, target: usize) {
        match &mut self.codes[ctx.index].ops[at].op {
            Op::Jump(t) | Op::JumpFalse(t) | Op::JumpTrue(t) | Op::ForIter(t) | Op::SetupExcept(t) | Op::SetupFinally(t) | Op::Break(t) | Op::Continue(t) => *t = target,
            _ => unreachable!("not a branch instruction"),
        }
    }
    fn code(&mut self, name: &str, kind: ScopeKind, params: &DParams, body: &[DStmt], enclosing: &DCtx, definition_line: usize) -> Result<usize,String> {
        let private=if kind == ScopeKind::Class { Some(name.to_owned()) } else { enclosing.private.clone() };
        let mut symbols = DSymbols { private:private.clone(),..DSymbols::default() }; symbols.block(body);
        let generic_class=kind==ScopeKind::Class && self.codes[enclosing.index].kind==ScopeKind::TypeParameters;
        if generic_class {d_push_name(&mut symbols.locals,"__type_params__");d_push_name(&mut symbols.uses,".type_params");}
        if let Some(error) = symbols.error { return Err(error); }
        if kind == ScopeKind::Function {
            for name in &symbols.annotated {
                if symbols.globals.contains(name) { return Err(self.error(definition_line,&format!("annotated name '{name}' can't be global"))); }
                if symbols.nonlocals.contains(name) { return Err(self.error(definition_line,&format!("annotated name '{name}' can't be nonlocal"))); }
            }
        }
        let mut parameters=params.params.clone();
        for name in parameters.positional.iter_mut().chain(parameters.kwonly.iter_mut()).chain(parameters.vararg.iter_mut()).chain(parameters.kwarg.iter_mut()) { *name=d_mangle(&private,name); }
        let mut parameter_names=Vec::new();
        for name in parameters.positional.iter().chain(parameters.kwonly.iter()).chain(parameters.vararg.iter()).chain(parameters.kwarg.iter()) {
            if parameter_names.contains(name) { return Err(self.error(definition_line,&format!("duplicate argument '{name}' in function definition"))); }
            parameter_names.push(name.clone());
            if symbols.globals.contains(name) || symbols.nonlocals.contains(name) { return Err(self.error(body.first().map(|x|x.line).unwrap_or(1),"parameter is declared global or nonlocal")); }
            d_push_name(&mut symbols.locals,name);
        }
        for name in &symbols.nonlocals {
            if symbols.globals.contains(name) { return Err(self.error(1,"name is both global and nonlocal")); }
            for (scope,locals,globals) in enclosing.scopes.iter().rev() {
                if *scope==ScopeKind::Class {continue;}
                if *scope==ScopeKind::Module || globals.contains(name) {break;}
                if locals.contains(name) {
                    if *scope==ScopeKind::TypeParameters{return Err(self.error(definition_line,&format!("nonlocal binding not allowed for type parameter '{name}'")));}
                    break;
                }
            }
            let found = d_scope_binds(&enclosing.scopes,name);
            if !found { return Err(self.error(1,&format!("no binding for nonlocal '{name}' found"))); }
        }
        symbols.locals.retain(|name| !symbols.globals.contains(name) && !symbols.nonlocals.contains(name));
        let mut frees=symbols.nonlocals.clone();
        if matches!(kind,ScopeKind::Annotation|ScopeKind::TypeParameters) && !(kind==ScopeKind::Annotation && self.stringized_annotation) && d_annotation_class_scope(&enclosing.scopes){d_push_name(&mut frees,"__classdict__");}
        for name in &symbols.uses {
            if !symbols.locals.contains(name) && !symbols.globals.contains(name) && d_scope_binds(&enclosing.scopes,name) { d_push_name(&mut frees,name); }
        }
        if !symbols.locals.iter().chain(symbols.globals.iter()).any(|name|name=="__class__")
            && (symbols.uses.iter().any(|name|name=="__class__") || (kind!=ScopeKind::Class && symbols.uses.iter().any(|name|name=="super")))
            && enclosing.scopes.iter().any(|(kind,_,_)|*kind==ScopeKind::Class) { d_push_name(&mut frees,"__class__"); }
        if symbols.generator && kind == ScopeKind::Class { return Err(self.error(1,"yield outside function")); }
        let index = self.codes.len();
        let docstring=if self.optimize<2 && kind==ScopeKind::Function{body.first().and_then(d_docstring).map(|value|d_clean_doc(value))}else{None};
        self.codes.push(Code { name:name.to_owned(),filename:self.filename.clone(),kind:kind.clone(),locals:symbols.locals.clone(),globals:symbols.globals.clone(),nonlocals:symbols.nonlocals,frees,params:parameters,ops:Vec::new(),is_generator:symbols.generator,future_flags:self.future_flags,docstring });
        let is_class = kind == ScopeKind::Class;
        let mut scopes = enclosing.scopes.clone(); scopes.push((kind,symbols.locals,symbols.globals));
        let mut ctx = DCtx { index,loops:Vec::new(),scopes,private };
        let mut body_start = 0;
        if is_class {
            self.emit(&ctx,Op::Const(Const::Int(definition_line.to_string())),definition_line,0); self.emit(&ctx,Op::Store("__firstlineno__".to_owned()),definition_line,0);
            if generic_class {self.emit(&ctx,Op::Load(".type_params".to_owned()),definition_line,0);self.emit(&ctx,Op::Store("__type_params__".to_owned()),definition_line,0);}
            if self.future_flags & D_FUTURE_ANNOTATIONS != 0 && d_has_annotations(body) { self.emit(&ctx,Op::SetupAnnotations,definition_line,0); }
            else if self.future_flags & D_FUTURE_ANNOTATIONS == 0 {self.prepare_scope_annotations(&mut ctx,body,definition_line,0)?;}
            if let Some(first) = body.first() {
                if let Some(doc) = d_docstring(first) { if self.optimize<2{self.emit(&ctx,Op::Const(Const::Str(d_clean_doc(doc))),first.line,first.column); self.emit(&ctx,Op::Store("__doc__".to_owned()),first.line,first.column);} body_start = 1; }
            }
        } else if self.codes[index].kind==ScopeKind::Function && body.first().is_some_and(|stmt|d_docstring(stmt).is_some()) {
            body_start=1;
        }
        self.block(&mut ctx,&body[body_start..])?;
        if is_class {
            if self.future_flags & D_FUTURE_ANNOTATIONS == 0 {
                if let Some(records)=self.scope_annotations.get(&ctx.index).cloned(){if !records.is_empty(){
                    self.scope_annotation_helper(&mut ctx,&records,definition_line,0)?;
                    self.emit(&ctx,Op::Store("__annotate_func__".to_owned()),definition_line,0);
                }}
            }
            let mut attributes = Vec::new(); d_static_attributes(body,false,&mut attributes); attributes.sort();
            for name in &attributes { self.emit(&ctx,Op::Const(Const::Str(name.clone())),definition_line,0); }
            self.emit(&ctx,Op::BuildTuple(attributes.len()),definition_line,0); self.emit(&ctx,Op::Store("__static_attributes__".to_owned()),definition_line,0);
        }
        self.emit(&ctx,Op::Const(Const::None),body.last().map(|x|x.line).unwrap_or(1),0); self.emit(&ctx,Op::Return,body.last().map(|x|x.line).unwrap_or(1),0);
        self.propagate_frees(index,enclosing);
        self.order_cell_locals(index);
        Ok(index)
    }
    fn block(&mut self, ctx: &mut DCtx, body: &[DStmt]) -> Result<(),String> { for stmt in body { self.stmt(ctx,stmt)?; } Ok(()) }
    fn stmt(&mut self, ctx: &mut DCtx, stmt: &DStmt) -> Result<(),String> {
        let line = stmt.line; let col = stmt.column;
        match &stmt.kind {
            DStmtKind::Generic(parameters,definition)=>self.generic_definition(ctx,parameters,definition,line,col)?,
            DStmtKind::TypeAlias(name,parameters,value)=>{
                if parameters.is_empty(){
                    self.emit(ctx,Op::BuildTuple(0),line,col);self.lazy_expression(ctx,name,value,line,col)?;
                    self.emit(ctx,Op::MakeTypeAlias{name:name.clone()},line,col);self.emit(ctx,Op::Store(name.clone()),line,col);
                }else{self.generic_definition(ctx,parameters,&DStmtKind::TypeAlias(name.clone(),Vec::new(),value.clone()),line,col)?;}
            },
            DStmtKind::TypeParameter(parameter)=>{
                for (field,value) in [("__bound__",&parameter.bound),("__constraints__",&parameter.constraints),("__default__",&parameter.default)] {
                    if let Some(value)=value{self.lazy_expression(ctx,field,value,line,col)?;}else{self.emit(ctx,Op::Const(Const::None),line,col);}
                }
                self.emit(ctx,Op::MakeTypeParam{name:parameter.name.clone(),kind:parameter.kind.clone()},line,col);
                self.emit(ctx,Op::Store(parameter.name.clone()),line,col);
            },
            DStmtKind::TypeDefinition(definition)=>{
                match &**definition {
                    DStmtKind::Function(name,params,body,_)=>{
                        for value in params.defaults.iter().chain(params.kwdefaults.iter().map(|(_,value)|value)){self.expr(ctx,value)?;}
                        let code=self.code(name,ScopeKind::Function,params,body,ctx,line)?;
                        self.emit(ctx,Op::MakeFunction{code:self.offset+code,defaults:params.defaults.len(),kwdefaults:params.kwdefaults.iter().map(|(name,_)|name.clone()).collect()},line,col);
                        self.annotations(ctx,params,line,col)?;
                        self.emit(ctx,Op::Dup,line,col);self.emit(ctx,Op::Load(".type_params".to_owned()),line,col);self.emit(ctx,Op::Swap,line,col);self.emit(ctx,Op::SetAttr("__type_params__".to_owned()),line,col);
                    },
                    DStmtKind::Class(name,bases,keywords,body,_)=>{
                        for base in bases.iter().chain(keywords.iter().map(|(_,value)|value)) {
                            if let Some(message)=d_annotation_violation(base){return Err(self.error(line,message));}
                        }
                        let expanded=self.class_arguments(ctx,bases,keywords,true,line,col)?;
                        let code=self.code(name,ScopeKind::Class,&DParams::default(),body,ctx,line)?;
                        let op=if expanded{Op::MakeClassEx{name:name.clone(),code:self.offset+code}}else{Op::MakeClass{name:name.clone(),code:self.offset+code,bases:bases.len()+1,keywords:keywords.iter().map(|(name,_)|name.clone().unwrap()).collect()}};
                        self.emit(ctx,op,line,col);
                    },
                    DStmtKind::TypeAlias(name,_,value)=>{
                        self.emit(ctx,Op::Load(".type_params".to_owned()),line,col);self.lazy_expression(ctx,name,value,line,col)?;
                        self.emit(ctx,Op::MakeTypeAlias{name:name.clone()},line,col);
                    },
                    _=>return Err(self.error(line,"invalid generic declaration")),
                }
                self.emit(ctx,Op::Return,line,col);
            },
            DStmtKind::Pass | DStmtKind::Global(_) | DStmtKind::Nonlocal(_) => { self.emit(ctx,Op::Nop,line,col); }
            DStmtKind::Expr(value) => { self.expr(ctx,value)?; self.emit(ctx,if self.interactive && ctx.index == 0 { Op::PrintExpr } else { Op::Pop },line,col); }
            DStmtKind::Assign(targets,value) => {
                if matches!(&value.kind,DExprKind::Name(name) if name == "$unbound_annotation") { for target in targets { if !matches!(target.kind,DExprKind::Name(_) | DExprKind::Attribute(..) | DExprKind::Subscript(..)) { return Err(self.error(line,"illegal target for annotation")); } } return Ok(()); }
                self.expr(ctx,value)?;
                for (index,target) in targets.iter().enumerate() { if index + 1 < targets.len() { self.emit(ctx,Op::Dup,line,col); } self.store(ctx,target)?; }
            }
            DStmtKind::AnnAssign(target,annotation,value,simple) => {
                if let Some(message)=d_annotation_violation(annotation) { return Err(self.error(line,message)); }
                if let Some(value) = value { self.expr(ctx,value)?; self.store(ctx,target)?; }
                else { match &target.kind {
                    DExprKind::Attribute(value,_)=>{self.expr(ctx,value)?;self.emit(ctx,Op::Pop,line,col);},
                    DExprKind::Subscript(value,index)=>{self.expr(ctx,value)?;self.emit(ctx,Op::Pop,line,col);self.expr(ctx,index)?;self.emit(ctx,Op::Pop,line,col);},
                    _=>(),
                } }
                if self.future_flags & D_FUTURE_ANNOTATIONS == 0 && *simple {
                    let index=self.scope_annotations.get(&ctx.index).and_then(|records|records.iter().find(|record|record.line==line&&record.column==col)).and_then(|record|record.index);
                    if let Some(index)=index{
                        let load=if self.codes[ctx.index].kind==ScopeKind::Class{Op::LoadCell("__conditional_annotations__".to_owned())}else{Op::Load("__conditional_annotations__".to_owned())};
                        self.emit(ctx,load,line,col);self.emit(ctx,Op::Const(Const::Int(index.to_string())),line,col);self.emit(ctx,Op::SetAdd(1),line,col);self.emit(ctx,Op::Pop,line,col);
                    }
                }
                if self.future_flags & D_FUTURE_ANNOTATIONS != 0 && matches!(self.codes[ctx.index].kind,ScopeKind::Module | ScopeKind::Class) && *simple {
                    if let DExprKind::Name(name) = &target.kind {
                        self.emit(ctx,Op::Const(Const::Str(d_annotation_string(annotation))),line,col);
                        self.emit(ctx,Op::Load("__annotations__".to_owned()),line,col);
                        self.emit(ctx,Op::Const(Const::Str(d_mangle(&ctx.private,name))),line,col);
                        self.emit(ctx,Op::SetItem,line,col);
                    }
                }
            }
            DStmtKind::AugAssign(target,op,value) => {
                let op = format!("{op}=");
                match &target.kind {
                    DExprKind::Name(name) => { self.emit(ctx,Op::Load(name.clone()),line,col); self.expr(ctx,value)?; self.emit(ctx,Op::Binary(op),line,col); self.emit(ctx,Op::Store(name.clone()),line,col); }
                    DExprKind::Attribute(object,name) => { self.expr(ctx,object)?; self.emit(ctx,Op::Dup,line,col); self.emit(ctx,Op::GetAttr(name.clone()),line,col); self.expr(ctx,value)?; self.emit(ctx,Op::Binary(op),line,col); self.emit(ctx,Op::Swap,line,col); self.emit(ctx,Op::SetAttr(name.clone()),line,col); }
                    DExprKind::Subscript(object,key) => {
                        let obj = self.temporary(ctx); let idx = self.temporary(ctx);
                        self.expr(ctx,object)?; self.emit(ctx,Op::Store(obj.clone()),line,col); self.expr(ctx,key)?; self.emit(ctx,Op::Store(idx.clone()),line,col);
                        self.emit(ctx,Op::Load(obj.clone()),line,col); self.emit(ctx,Op::Load(idx.clone()),line,col); self.emit(ctx,Op::GetItem,line,col); self.expr(ctx,value)?; self.emit(ctx,Op::Binary(op),line,col);
                        self.emit(ctx,Op::Load(obj),line,col); self.emit(ctx,Op::Load(idx),line,col); self.emit(ctx,Op::SetItem,line,col);
                    }
                    _ => return Err(self.error(line,"illegal expression for augmented assignment")),
                }
            }
            DStmtKind::Delete(targets) => for target in targets { self.delete(ctx,target)?; },
            DStmtKind::If(test,body,tail) => {
                self.expr(ctx,test)?; let otherwise = self.emit(ctx,Op::JumpFalse(0),line,col); self.block(ctx,body)?;
                let end = self.emit(ctx,Op::Jump(0),line,col); self.patch(ctx,otherwise,self.here(ctx)); self.block(ctx,tail)?; self.patch(ctx,end,self.here(ctx));
            }
            DStmtKind::While(test,body,tail) => {
                let start = self.here(ctx); self.expr(ctx,test)?; let exhausted = self.emit(ctx,Op::JumpFalse(0),line,col);
                ctx.loops.push(DLoop { start,breaks:Vec::new(),continues:Vec::new() }); self.block(ctx,body)?; self.emit(ctx,Op::Jump(start),line,col);
                let loop_ = ctx.loops.pop().unwrap(); self.patch(ctx,exhausted,self.here(ctx)); self.block(ctx,tail)?; let end = self.here(ctx);
                for at in loop_.breaks { self.patch(ctx,at,end); } for at in loop_.continues { self.patch(ctx,at,start); }
            }
            DStmtKind::For(target,iter,body,tail) => {
                self.expr(ctx,iter)?; self.emit(ctx,Op::GetIter,line,col); let start = self.here(ctx); let exhausted = self.emit(ctx,Op::ForIter(0),line,col); self.store(ctx,target)?;
                ctx.loops.push(DLoop { start,breaks:Vec::new(),continues:Vec::new() }); self.block(ctx,body)?; self.emit(ctx,Op::Jump(start),line,col);
                let loop_ = ctx.loops.pop().unwrap(); self.patch(ctx,exhausted,self.here(ctx)); self.block(ctx,tail)?; let end_else = self.emit(ctx,Op::Jump(0),line,col);
                let break_cleanup = self.here(ctx); self.emit(ctx,Op::Pop,line,col); let end = self.here(ctx); self.patch(ctx,end_else,end);
                for at in loop_.breaks { self.patch(ctx,at,break_cleanup); } for at in loop_.continues { self.patch(ctx,at,start); }
            }
            DStmtKind::Break => {
                if ctx.loops.is_empty() { return Err(self.error(line,"break outside loop")); }
                let at = self.emit(ctx,Op::Break(0),line,col); ctx.loops.last_mut().unwrap().breaks.push(at);
            }
            DStmtKind::Continue => {
                if ctx.loops.is_empty() { return Err(self.error(line,"continue outside loop")); }
                let at = self.emit(ctx,Op::Continue(0),line,col); ctx.loops.last_mut().unwrap().continues.push(at);
            }
            DStmtKind::Function(name,params,body,decorators) => {
                for decorator in decorators { self.expr(ctx,decorator)?; }
                for default in &params.defaults { self.expr(ctx,default)?; } for (_,default) in &params.kwdefaults { self.expr(ctx,default)?; }
                let code = self.code(name,ScopeKind::Function,params,body,ctx,line)?;
                self.emit(ctx,Op::MakeFunction { code:self.offset+code,defaults:params.defaults.len(),kwdefaults:params.kwdefaults.iter().map(|(name,_)|name.clone()).collect() },line,col);
                self.annotations(ctx,params,line,col)?;
                for _ in decorators { self.emit(ctx,Op::Call { pos:1,keywords:Vec::new() },line,col); }
                self.emit(ctx,Op::Store(name.clone()),line,col);
            }
            DStmtKind::Class(name,bases,keywords,body,decorators) => {
                for decorator in decorators { self.expr(ctx,decorator)?; }
                let expanded=self.class_arguments(ctx,bases,keywords,false,line,col)?;
                let code = self.code(name,ScopeKind::Class,&DParams::default(),body,ctx,line)?;
                let op=if expanded{Op::MakeClassEx{name:name.clone(),code:self.offset+code}}else{Op::MakeClass { name:name.clone(),code:self.offset+code,bases:bases.len(),keywords:keywords.iter().map(|(name,_)|name.clone().unwrap()).collect() }};
                self.emit(ctx,op,line,col);
                for _ in decorators { self.emit(ctx,Op::Call { pos:1,keywords:Vec::new() },line,col); } self.emit(ctx,Op::Store(name.clone()),line,col);
            }
            DStmtKind::Return(value) => {
                if !matches!(self.codes[ctx.index].kind,ScopeKind::Function | ScopeKind::Comprehension | ScopeKind::Annotation | ScopeKind::TypeParameters) { return Err(self.error(line,"return outside function")); }
                if let Some(value) = value { self.expr(ctx,value)?; } else { self.emit(ctx,Op::Const(Const::None),line,col); } self.emit(ctx,Op::Return,line,col);
            }
            DStmtKind::Raise(value,cause) => {
                if let Some(value) = value { self.expr(ctx,value)?; } if let Some(cause) = cause { self.expr(ctx,cause)?; }
                self.emit(ctx,Op::Raise(if cause.is_some() { 2 } else if value.is_some() { 1 } else { 0 }),line,col);
            }
            DStmtKind::Assert(test,message) => {
                if self.optimize>0{return Ok(());}
                self.expr(ctx,test)?; let end = self.emit(ctx,Op::JumpTrue(0),line,col); self.emit(ctx,Op::Load("AssertionError".to_owned()),line,col);
                if let Some(message) = message { self.expr(ctx,message)?; } self.emit(ctx,Op::Call { pos:if message.is_some(){1}else{0},keywords:Vec::new() },line,col); self.emit(ctx,Op::Raise(1),line,col); self.patch(ctx,end,self.here(ctx));
            }
            DStmtKind::Try(body,handlers,tail,finally) => self.try_statement(ctx,body,handlers,tail,finally,line,col)?,
            DStmtKind::TryStar(body,handlers,tail,finally) => self.try_star_statement(ctx,body,handlers,tail,finally,line,col)?,
            DStmtKind::With(items,body) => self.with_statement(ctx,items,body,line,col)?,
            DStmtKind::Match(subject,cases) => {
                let saved = self.temporary(ctx); self.expr(ctx,subject)?; self.emit(ctx,Op::Store(saved.clone()),line,col); let mut ends = Vec::new();
                for (pattern,guard,body) in cases {
                    self.emit(ctx,Op::Load(saved.clone()),line,col); self.emit(ctx,Op::Match(pattern.clone()),line,col); let failed = self.emit(ctx,Op::JumpFalse(0),line,col);
                    let guarded = if let Some(guard) = guard { self.expr(ctx,guard)?; Some(self.emit(ctx,Op::JumpFalse(0),line,col)) } else { None };
                    self.block(ctx,body)?; ends.push(self.emit(ctx,Op::Jump(0),line,col)); let next = self.here(ctx); self.patch(ctx,failed,next); if let Some(guarded) = guarded { self.patch(ctx,guarded,next); }
                }
                let end = self.here(ctx); for at in ends { self.patch(ctx,at,end); }
            }
            DStmtKind::Import(names) => for (name,alias) in names {
                self.emit(ctx,Op::Import { module:name.clone(),names:if alias.is_some(){vec!["*".to_owned()]}else{Vec::new()},level:0 },line,col);
                self.emit(ctx,Op::Store(alias.clone().unwrap_or_else(||name.split('.').next().unwrap().to_owned())),line,col);
            }
            DStmtKind::ImportFrom(module,names,level) => {
                if names.iter().any(|(name,_)|name=="*") && self.codes[ctx.index].kind != ScopeKind::Module { return Err(self.error(line,"import * only allowed at module level")); }
                self.emit(ctx,Op::Import { module:module.clone(),names:names.iter().map(|(name,_)|name.clone()).collect(),level:*level },line,col);
                for (name,alias) in names { self.emit(ctx,Op::ImportFrom(name.clone()),line,col); if name != "*" { self.emit(ctx,Op::Store(alias.clone().unwrap_or_else(||name.clone())),line,col); } }
                self.emit(ctx,Op::Pop,line,col);
            }
        }
        Ok(())
    }
    fn try_star_statement(&mut self,ctx:&mut DCtx,body:&[DStmt],handlers:&[(Option<DExpr>,Option<String>,Vec<DStmt>)],tail:&[DStmt],finally:&[DStmt],line:usize,column:usize)->Result<(),String>{
        let final_setup=if finally.is_empty(){None}else{Some(self.emit(ctx,Op::SetupFinally(0),line,column))};
        let setup=self.emit(ctx,Op::SetupExcept(0),line,column);
        self.block(ctx,body)?;self.emit(ctx,Op::PopHandler,line,column);self.block(ctx,tail)?;
        let normal=self.emit(ctx,Op::Jump(0),line,column);self.patch(ctx,setup,self.here(ctx));
        let state=self.temporary(ctx);self.emit(ctx,Op::BeginExceptStar,line,column);self.emit(ctx,Op::Store(state.clone()),line,column);
        let state_cleanup=self.emit(ctx,Op::SetupFinally(0),line,column);
        for(exception,name,body)in handlers{
            self.emit(ctx,Op::Load(state.clone()),line,column);
            let exception=exception.as_ref().ok_or_else(||self.error(line,"except* requires an exception type"))?;self.expr(ctx,exception)?;
            self.emit(ctx,Op::SplitExceptStar,line,column);let unmatched=self.emit(ctx,Op::JumpFalse(0),line,column);
            if let Some(name)=name{self.emit(ctx,Op::LoadException,line,column);self.emit(ctx,Op::Store(name.clone()),line,column);}
            // Only errors raised by the user handler body join the pending
            // exception group. Binding/clearing its alias can itself call a
            // prepared namespace mapping and must abort dispatch on failure.
            let caught=self.emit(ctx,Op::SetupExcept(0),line,column);
            self.block(ctx,body)?;self.emit(ctx,Op::PopHandler,line,column);
            self.star_alias_cleanup(ctx,name,line,column);
            self.emit(ctx,Op::Load(state.clone()),line,column);self.emit(ctx,Op::RecordExceptStar(false),line,column);
            let next=self.emit(ctx,Op::Jump(0),line,column);self.patch(ctx,caught,self.here(ctx));
            self.emit(ctx,Op::Load(state.clone()),line,column);self.emit(ctx,Op::RecordExceptStar(true),line,column);
            self.star_alias_cleanup(ctx,name,line,column);
            let end=self.here(ctx);self.patch(ctx,next,end);self.patch(ctx,unmatched,end);
        }
        self.emit(ctx,Op::Load(state.clone()),line,column);self.emit(ctx,Op::EndExceptStar,line,column);
        self.emit(ctx,Op::PopHandler,line,column);self.patch(ctx,state_cleanup,self.here(ctx));
        self.emit(ctx,Op::Delete(state),line,column);self.emit(ctx,Op::EndFinally,line,column);
        self.patch(ctx,normal,self.here(ctx));
        if let Some(setup)=final_setup{
            self.emit(ctx,Op::PopHandler,line,column);self.patch(ctx,setup,self.here(ctx));self.block(ctx,finally)?;self.emit(ctx,Op::EndFinally,line,column);
        }Ok(())
    }
    fn star_alias_cleanup(&mut self,ctx:&DCtx,name:&Option<String>,line:usize,column:usize){
        if let Some(name)=name{self.emit(ctx,Op::Const(Const::None),line,column);self.emit(ctx,Op::Store(name.clone()),line,column);self.emit(ctx,Op::Delete(name.clone()),line,column);}
    }
    fn try_statement(&mut self, ctx: &mut DCtx, body: &[DStmt], handlers: &[(Option<DExpr>,Option<String>,Vec<DStmt>)], tail: &[DStmt], finally: &[DStmt], line: usize, col: usize) -> Result<(),String> {
        let final_setup = if finally.is_empty() { None } else { Some(self.emit(ctx,Op::SetupFinally(0),line,col)) };
        if handlers.is_empty() { self.block(ctx,body)?; }
        else {
            let setup = self.emit(ctx,Op::SetupExcept(0),line,col); self.block(ctx,body)?; self.emit(ctx,Op::PopHandler,line,col); self.block(ctx,tail)?;
            let normal_end = self.emit(ctx,Op::Jump(0),line,col); self.patch(ctx,setup,self.here(ctx)); let mut handled = Vec::new();
            for (exception,name,handler) in handlers {
                let next = if let Some(exception) = exception {
                    self.emit(ctx,Op::LoadException,line,col); self.expr(ctx,exception)?; self.emit(ctx,Op::ExceptionMatch,line,col); Some(self.emit(ctx,Op::JumpFalse(0),line,col))
                } else { None };
                if let Some(name) = name { self.emit(ctx,Op::LoadException,line,col); self.emit(ctx,Op::Store(name.clone()),line,col); }
                let cleanup = self.emit(ctx,Op::SetupFinally(0),line,col); self.block(ctx,handler)?; self.emit(ctx,Op::PopHandler,line,col);
                let cleanup_at = self.here(ctx); self.patch(ctx,cleanup,cleanup_at);
                if let Some(name) = name { self.emit(ctx,Op::Const(Const::None),line,col); self.emit(ctx,Op::Store(name.clone()),line,col); self.emit(ctx,Op::Delete(name.clone()),line,col); }
                self.emit(ctx,Op::ClearException,line,col); self.emit(ctx,Op::EndFinally,line,col);
                handled.push(self.emit(ctx,Op::Jump(0),line,col)); if let Some(next) = next { self.patch(ctx,next,self.here(ctx)); }
            }
            self.emit(ctx,Op::Raise(0),line,col); let end = self.here(ctx); self.patch(ctx,normal_end,end); for at in handled { self.patch(ctx,at,end); }
        }
        if let Some(setup) = final_setup { self.emit(ctx,Op::PopHandler,line,col); let start = self.here(ctx); self.patch(ctx,setup,start); self.block(ctx,finally)?; self.emit(ctx,Op::EndFinally,line,col); }
        Ok(())
    }
    fn prepare_scope_annotations(&mut self,ctx:&mut DCtx,body:&[DStmt],line:usize,column:usize)->Result<(),String>{
        let module=self.codes[ctx.index].kind==ScopeKind::Module;
        let mut records=Vec::new();let mut next=0;d_collect_annotations(body,module,&mut records,&mut next);
        for record in &records {if let Some(message)=d_annotation_violation(&record.value){return Err(self.error(record.line,message));}}
        self.scope_annotations.insert(ctx.index,records.clone());
        if module && !records.is_empty(){
            self.scope_annotation_helper(ctx,&records,line,column)?;self.emit(ctx,Op::Store("__annotate__".to_owned()),line,column);
        }
        if module && d_has_annotations(body) || !module && next>0 {
            self.emit(ctx,Op::BuildSet(0),line,column);
            self.emit(ctx,if module{Op::Store("__conditional_annotations__".to_owned())}else{Op::StoreCell("__conditional_annotations__".to_owned())},line,column);
        }
        Ok(())
    }
    fn scope_annotation_helper(&mut self,ctx:&mut DCtx,records:&[DAnnotation],line:usize,column:usize)->Result<(),String>{
        let make=|kind|DExpr{kind,line,column};
        let condition=make(DExprKind::Compare(Box::new(make(DExprKind::Name(".format".to_owned()))),vec![(">".to_owned(),make(DExprKind::Constant(Const::Int("2".to_owned()))))]));
        let error=make(DExprKind::Call(Box::new(make(DExprKind::Name("NotImplementedError".to_owned()))),Vec::new(),Vec::new()));
        let check=DStmt{kind:DStmtKind::If(condition,vec![DStmt{kind:DStmtKind::Raise(Some(error),None),line,column}],Vec::new()),line,column};
        let result_name="$annotations".to_owned();
        let mut statements=vec![check,DStmt{kind:DStmtKind::Assign(vec![make(DExprKind::Name(result_name.clone()))],make(DExprKind::Dict(Vec::new()))),line,column}];
        for record in records{
            let target=make(DExprKind::Subscript(Box::new(make(DExprKind::Name(result_name.clone()))),Box::new(make(DExprKind::Constant(Const::Str(d_mangle(&ctx.private,&record.name)))))));
            let assigned=DStmt{kind:DStmtKind::Assign(vec![target],record.value.clone()),line:record.line,column:record.column};
            if let Some(index)=record.index{
                let condition=make(DExprKind::Compare(Box::new(make(DExprKind::Constant(Const::Int(index.to_string())))),vec![("in".to_owned(),make(DExprKind::Name("__conditional_annotations__".to_owned())))]));
                statements.push(DStmt{kind:DStmtKind::If(condition,vec![assigned],Vec::new()),line:record.line,column:record.column});
            }else{statements.push(assigned);}
        }
        statements.push(DStmt{kind:DStmtKind::Return(Some(make(DExprKind::Name(result_name)))),line,column});
        let mut params=DParams::default();params.params.posonly=1;params.params.positional.push(".format".to_owned());
        let code=self.code("__annotate__",ScopeKind::Annotation,&params,&statements,ctx,line)?;
        if self.codes[ctx.index].kind==ScopeKind::Class && records.iter().any(|record|record.index.is_some()){
            for instruction in &mut self.codes[code].ops{if matches!(&instruction.op,Op::Load(name)if name=="__conditional_annotations__"){instruction.op=Op::LoadCell("__conditional_annotations__".to_owned());}}
            d_push_name(&mut self.codes[code].frees,"__conditional_annotations__");
        }
        self.emit(ctx,Op::MakeFunction{code:self.offset+code,defaults:0,kwdefaults:Vec::new()},line,column);Ok(())
    }
    fn lazy_expression(&mut self,ctx:&mut DCtx,name:&str,value:&DExpr,line:usize,column:usize)->Result<(),String> {
        if let Some(message)=d_annotation_violation(value){return Err(self.error(line,message));}
        let make=|kind|DExpr{kind,line,column};
        let condition=make(DExprKind::Compare(Box::new(make(DExprKind::Name(".format".to_owned()))),vec![(">".to_owned(),make(DExprKind::Constant(Const::Int("2".to_owned()))))]));
        let error=make(DExprKind::Call(Box::new(make(DExprKind::Name("NotImplementedError".to_owned()))),Vec::new(),Vec::new()));
        let check=DStmt{kind:DStmtKind::If(condition,vec![DStmt{kind:DStmtKind::Raise(Some(error),None),line,column}],Vec::new()),line,column};
        let returned_value=if let DExprKind::Star(inner)=&value.kind{(**inner).clone()}else{value.clone()};
        let returned=DStmt{kind:DStmtKind::Return(Some(returned_value)),line,column};
        let mut parameters=DParams::default();parameters.params.posonly=1;parameters.params.positional.push(".format".to_owned());
        let code=self.code(name,ScopeKind::Annotation,&parameters,&[check,returned],ctx,line)?;
        // A leading star in a variadic default means unpack exactly one item.
        if matches!(value.kind,DExprKind::Star(_)) {
            let code_ref=&mut self.codes[code];
            let position=code_ref.ops.iter().position(|instruction|matches!(instruction.op,Op::Return)).unwrap();
            code_ref.ops.insert(position,Instr{op:Op::TypeUnpack,line,column});
        }
        self.emit(ctx,Op::Const(Const::Int("1".to_owned())),line,column);
        self.emit(ctx,Op::MakeFunction{code:self.offset+code,defaults:1,kwdefaults:Vec::new()},line,column);Ok(())
    }
    fn generic_definition(&mut self,ctx:&mut DCtx,parameters:&[DTypeParam],definition:&DStmtKind,line:usize,column:usize)->Result<(),String> {
        let make=|kind|DExpr{kind,line,column};
        let (name,decorators)=match definition{
            DStmtKind::Function(name,_,_,decorators)|DStmtKind::Class(name,_,_,_,decorators)=>(name.clone(),decorators.clone()),
            DStmtKind::TypeAlias(name,_,_)=>(name.clone(),Vec::new()),
            _=>return Err(self.error(line,"invalid generic declaration")),
        };
        let private=if matches!(definition,DStmtKind::Class(..)){Some(name.clone())}else{ctx.private.clone()};
        let mut parameter_names=Vec::new();
        for parameter in parameters {
            let name=d_mangle(&private,&parameter.name);
            if parameter_names.contains(&name){return Err(self.error(line,&format!("duplicate type parameter '{name}'")));}
            parameter_names.push(name);
        }
        for decorator in &decorators{self.expr(ctx,decorator)?;}
        let mut wrapper_params=DParams::default();let mut arguments=Vec::new();let mut inner=definition.clone();
        if let DStmtKind::Function(_,params,_,decorators)=&mut inner {
            decorators.clear();
            for default in &mut params.defaults {
                let parameter=format!(".default{}",arguments.len());arguments.push(default.clone());*default=make(DExprKind::Name(parameter.clone()));wrapper_params.params.positional.push(parameter);
            }
            for (_,default) in &mut params.kwdefaults {
                let parameter=format!(".default{}",arguments.len());arguments.push(default.clone());*default=make(DExprKind::Name(parameter.clone()));wrapper_params.params.positional.push(parameter);
            }
        }
        if let DStmtKind::Class(_,_,_,_,decorators)=&mut inner{decorators.clear();}
        let mut body=parameters.iter().cloned().map(|parameter|DStmt{kind:DStmtKind::TypeParameter(parameter),line,column}).collect::<Vec<_>>();
        let tuple=make(DExprKind::Tuple(parameters.iter().map(|parameter|make(DExprKind::Name(parameter.name.clone()))).collect()));
        body.push(DStmt{kind:DStmtKind::Assign(vec![make(DExprKind::Name(".type_params".to_owned()))],tuple),line,column});
        body.push(DStmt{kind:DStmtKind::TypeDefinition(Box::new(inner)),line,column});
        let enclosing=DCtx{index:ctx.index,loops:Vec::new(),scopes:ctx.scopes.clone(),private};
        let code=self.code(&format!("<generic parameters of {name}>"),ScopeKind::TypeParameters,&wrapper_params,&body,&enclosing,line)?;
        self.emit(ctx,Op::MakeFunction{code:self.offset+code,defaults:0,kwdefaults:Vec::new()},line,column);
        for argument in &arguments{self.expr(ctx,argument)?;}
        self.emit(ctx,Op::Call{pos:arguments.len(),keywords:Vec::new()},line,column);
        for _ in &decorators{self.emit(ctx,Op::Call{pos:1,keywords:Vec::new()},line,column);}
        self.emit(ctx,Op::Store(name),line,column);Ok(())
    }
    fn annotations(&mut self, ctx: &mut DCtx, params: &DParams, line: usize, column: usize) -> Result<(),String> {
        if params.annotations.is_empty() { return Ok(()); }
        let make = |kind| DExpr { kind,line,column };
        let condition=make(DExprKind::Compare(Box::new(make(DExprKind::Name(".format".to_owned()))),vec![(">".to_owned(),make(DExprKind::Constant(Const::Int("2".to_owned()))))]));
        let error=make(DExprKind::Call(Box::new(make(DExprKind::Name("NotImplementedError".to_owned()))),Vec::new(),Vec::new()));
        let check=DStmt { kind:DStmtKind::If(condition,vec![DStmt { kind:DStmtKind::Raise(Some(error),None),line,column }],Vec::new()),line,column };
        let mut items=Vec::new();
        for (name,value) in &params.annotations {
            if let Some(message)=d_annotation_violation(value) { return Err(self.error(line,message)); }
            let value = if self.future_flags & D_FUTURE_ANNOTATIONS != 0 { make(DExprKind::Constant(Const::Str(d_annotation_string(value)))) } else { value.clone() };
            items.push((Some(make(DExprKind::Constant(Const::Str(d_mangle(&ctx.private,name))))),value));
        }
        let annotations=make(DExprKind::Dict(items));
        let returned=DStmt { kind:DStmtKind::Return(Some(annotations)),line,column };
        let mut parameters=DParams::default();parameters.params.posonly=1;parameters.params.positional.push(".format".to_owned());
        // Future function annotations contain strings and never read the class
        // namespace. Lazy alias/bound/default thunks still evaluate expressions.
        let previous=self.stringized_annotation;
        self.stringized_annotation=self.future_flags & D_FUTURE_ANNOTATIONS != 0;
        let compiled=self.code("__annotate__",ScopeKind::Annotation,&parameters,&[check,returned],ctx,line);
        self.stringized_annotation=previous;
        let code=compiled?;
        self.emit(ctx,Op::Dup,line,column); self.emit(ctx,Op::MakeFunction { code:self.offset+code,defaults:0,kwdefaults:Vec::new() },line,column);self.emit(ctx,Op::Swap,line,column);self.emit(ctx,Op::SetAttr("__annotate__".to_owned()),line,column);
        Ok(())
    }
    fn with_statement(&mut self, ctx: &mut DCtx, items: &[(DExpr,Option<DExpr>)], body: &[DStmt], line: usize, col: usize) -> Result<(),String> {
        if items.is_empty() { return self.block(ctx,body); }
        let (manager,target) = &items[0]; let manager_tmp = self.temporary(ctx); let exit_tmp = self.temporary(ctx); let enter_tmp = self.temporary(ctx); let exceptional_tmp = self.temporary(ctx);
        self.expr(ctx,manager)?; self.emit(ctx,Op::Store(manager_tmp.clone()),line,col);
        self.emit(ctx,Op::Load(manager_tmp.clone()),line,col); self.emit(ctx,Op::GetSpecialAttr("__exit__".to_owned()),line,col); self.emit(ctx,Op::Store(exit_tmp.clone()),line,col);
        self.emit(ctx,Op::Load(manager_tmp),line,col); self.emit(ctx,Op::GetSpecialAttr("__enter__".to_owned()),line,col); self.emit(ctx,Op::Call { pos:0,keywords:Vec::new() },line,col); self.emit(ctx,Op::Store(enter_tmp.clone()),line,col);
        self.emit(ctx,Op::Const(Const::Bool(false)),line,col); self.emit(ctx,Op::Store(exceptional_tmp.clone()),line,col);
        let final_setup = self.emit(ctx,Op::SetupFinally(0),line,col); let except_setup = self.emit(ctx,Op::SetupExcept(0),line,col);
        if let Some(target) = target { self.emit(ctx,Op::Load(enter_tmp),line,col); self.store(ctx,target)?; }
        self.with_statement(ctx,&items[1..],body,line,col)?;
        self.emit(ctx,Op::PopHandler,line,col); self.emit(ctx,Op::PopHandler,line,col); let normal_final = self.emit(ctx,Op::Jump(0),line,col);
        self.patch(ctx,except_setup,self.here(ctx)); self.emit(ctx,Op::Const(Const::Bool(true)),line,col); self.emit(ctx,Op::Store(exceptional_tmp.clone()),line,col);
        self.emit(ctx,Op::Load(exit_tmp.clone()),line,col); self.emit(ctx,Op::LoadExceptionType,line,col);
        self.emit(ctx,Op::LoadException,line,col); self.emit(ctx,Op::LoadExceptionTraceback,line,col); self.emit(ctx,Op::Call { pos:3,keywords:Vec::new() },line,col);
        let suppressed = self.emit(ctx,Op::JumpTrue(0),line,col); self.emit(ctx,Op::Raise(0),line,col); self.patch(ctx,suppressed,self.here(ctx));
        self.emit(ctx,Op::ClearException,line,col); self.emit(ctx,Op::PopHandler,line,col); let suppress_final = self.emit(ctx,Op::Jump(0),line,col);
        let final_start = self.here(ctx); self.patch(ctx,normal_final,final_start); self.patch(ctx,suppress_final,final_start); self.patch(ctx,final_setup,final_start);
        self.emit(ctx,Op::Load(exceptional_tmp),line,col); let skip = self.emit(ctx,Op::JumpTrue(0),line,col);
        self.emit(ctx,Op::Load(exit_tmp),line,col); for _ in 0..3 { self.emit(ctx,Op::Const(Const::None),line,col); }
        self.emit(ctx,Op::Call { pos:3,keywords:Vec::new() },line,col); self.emit(ctx,Op::Pop,line,col); self.patch(ctx,skip,self.here(ctx)); self.emit(ctx,Op::EndFinally,line,col); Ok(())
    }
    fn keyword_arguments(&mut self,ctx:&mut DCtx,keywords:&[(Option<String>,DExpr)],line:usize,col:usize)->Result<(),String>{
        self.emit(ctx,Op::BuildDict(0),line,col);let mut index=0;
        while index<keywords.len(){
            let (_,value)=&keywords[index];
            if keywords[index].0.is_none(){self.expr(ctx,value)?;index+=1;}
            else{
                let start=index;
                while index<keywords.len(){
                    let(Some(name),value)=&keywords[index]else{break;};
                    self.emit(ctx,Op::Keyword(name.clone()),value.line,value.column);self.expr(ctx,value)?;index+=1;
                }
                self.emit(ctx,Op::BuildDict(index-start),value.line,value.column);
            }
            self.emit(ctx,Op::Binary("kwargs_merge".to_owned()),value.line,value.column);
        }
        Ok(())
    }
    fn class_arguments(&mut self,ctx:&mut DCtx,bases:&[DExpr],keywords:&[(Option<String>,DExpr)],generic:bool,line:usize,col:usize)->Result<bool,String>{
        let expanded=bases.iter().any(|base|matches!(base.kind,DExprKind::Star(_)))||keywords.iter().any(|(name,_)|name.is_none());
        for base in bases{
            if let DExprKind::Star(value)=&base.kind{
                self.expr(ctx,value)?;self.emit(ctx,Op::BuildTupleUnpack(1),base.line,base.column);
            }else{
                self.expr(ctx,base)?;if expanded{self.emit(ctx,Op::BuildTuple(1),base.line,base.column);}
            }
        }
        if generic{
            self.emit(ctx,Op::Load(".type_params".to_owned()),line,col);self.emit(ctx,Op::GenericBase,line,col);
            if expanded{self.emit(ctx,Op::BuildTuple(1),line,col);}
        }
        if expanded{
            self.emit(ctx,Op::BuildTupleUnpack(bases.len()+usize::from(generic)),line,col);
            self.keyword_arguments(ctx,keywords,line,col)?;
        }else{for(_,value)in keywords{self.expr(ctx,value)?;}}
        Ok(expanded)
    }
    fn store(&mut self, ctx: &mut DCtx, target: &DExpr) -> Result<(),String> {
        let line = target.line; let col = target.column;
        match &target.kind {
            DExprKind::Name(name) => { self.emit(ctx,Op::Store(name.clone()),line,col); }
            DExprKind::Attribute(object,name) => { self.expr(ctx,object)?; self.emit(ctx,Op::SetAttr(name.clone()),line,col); }
            DExprKind::Subscript(object,key) => { self.expr(ctx,object)?; self.expr(ctx,key)?; self.emit(ctx,Op::SetItem,line,col); }
            DExprKind::Tuple(items) | DExprKind::List(items) => {
                let stars: Vec<usize> = items.iter().enumerate().filter_map(|(i,item)|if matches!(item.kind,DExprKind::Star(_)){Some(i)}else{None}).collect();
                if stars.len() > 1 { return Err(self.error(line,"multiple starred expressions in assignment")); }
                if let Some(index) = stars.first() { self.emit(ctx,Op::UnpackEx { before:*index,after:items.len()-index-1 },line,col); }
                else { self.emit(ctx,Op::Unpack(items.len()),line,col); }
                for item in items { if let DExprKind::Star(value) = &item.kind { self.store(ctx,value)?; } else { self.store(ctx,item)?; } }
            }
            _ => return Err(self.error(line,"cannot assign to this expression")),
        }
        Ok(())
    }
    fn delete(&mut self, ctx: &mut DCtx, target: &DExpr) -> Result<(),String> {
        let line = target.line; let col = target.column;
        match &target.kind {
            DExprKind::Name(name) => { self.emit(ctx,Op::Delete(name.clone()),line,col); }
            DExprKind::Attribute(object,name) => { self.expr(ctx,object)?; self.emit(ctx,Op::DelAttr(name.clone()),line,col); }
            DExprKind::Subscript(object,key) => { self.expr(ctx,object)?; self.expr(ctx,key)?; self.emit(ctx,Op::DelItem,line,col); }
            DExprKind::Tuple(items) | DExprKind::List(items) => for item in items { self.delete(ctx,item)?; },
            _ => return Err(self.error(line,"cannot delete this expression")),
        }
        Ok(())
    }
    fn expr(&mut self, ctx: &mut DCtx, expr: &DExpr) -> Result<(),String> {
        let line = expr.line; let col = expr.column;
        match &expr.kind {
            DExprKind::Constant(value) => { self.emit(ctx,Op::Const(value.clone()),line,col); }
            DExprKind::UnicodeString(value) => { self.emit(ctx,Op::Const(Const::Str(value.clone())),line,col); }
            DExprKind::Imaginary(value) => {self.emit(ctx,Op::Const(Const::Complex(0.0,*value)),line,col);}
            DExprKind::Ellipsis => { self.emit(ctx,Op::Load("Ellipsis".to_owned()),line,col); }
            DExprKind::Name(name) => { self.emit(ctx,if name=="__debug__"{Op::Const(Const::Bool(self.optimize==0))}else{Op::Load(name.clone())},line,col); }
            DExprKind::List(items) | DExprKind::Tuple(items) => {
                let tuple = matches!(expr.kind,DExprKind::Tuple(_)); let unpack = items.iter().any(|x|matches!(x.kind,DExprKind::Star(_)));
                for item in items { if let DExprKind::Star(value) = &item.kind { self.expr(ctx,value)?; self.emit(ctx,Op::BuildListUnpack(1),line,col); } else { self.expr(ctx,item)?; if unpack { self.emit(ctx,Op::BuildTuple(1),line,col); } } }
                let op = match (tuple,unpack) { (false,false)=>Op::BuildList(items.len()),(true,false)=>Op::BuildTuple(items.len()),(false,true)=>Op::BuildListUnpack(items.len()),(true,true)=>Op::BuildTupleUnpack(items.len()) };
                self.emit(ctx,op,line,col);
            }
            DExprKind::Set(items) => {
                let unpack = items.iter().any(|x|matches!(x.kind,DExprKind::Star(_)));
                if unpack {
                    self.emit(ctx,Op::BuildSet(0),line,col);
                    for item in items {
                        if let DExprKind::Star(value) = &item.kind {
                            self.expr(ctx,value)?; self.emit(ctx,Op::GetIter,line,col); let start = self.here(ctx); let exhausted = self.emit(ctx,Op::ForIter(0),line,col);
                            self.emit(ctx,Op::SetAdd(2),line,col); self.emit(ctx,Op::Jump(start),line,col); self.patch(ctx,exhausted,self.here(ctx));
                        } else { self.expr(ctx,item)?; self.emit(ctx,Op::SetAdd(1),line,col); }
                    }
                } else { for item in items { self.expr(ctx,item)?; } self.emit(ctx,Op::BuildSet(items.len()),line,col); }
            }
            DExprKind::Dict(items) => {
                if items.iter().all(|(key,_)|key.is_some()) { for (key,value) in items { self.expr(ctx,key.as_ref().unwrap())?; self.expr(ctx,value)?; } self.emit(ctx,Op::BuildDict(items.len()),line,col); }
                else { self.emit(ctx,Op::BuildDict(0),line,col); for (key,value) in items { if let Some(key) = key { self.expr(ctx,key)?; self.expr(ctx,value)?; self.emit(ctx,Op::BuildDict(1),line,col); } else { self.expr(ctx,value)?; } self.emit(ctx,Op::Binary("dict_merge".to_owned()),line,col); } }
            }
            DExprKind::Unary(op,value) => { self.expr(ctx,value)?; self.emit(ctx,Op::Unary(op.clone()),line,col); }
            DExprKind::Binary(op,a,b) => { self.expr(ctx,a)?; self.expr(ctx,b)?; self.emit(ctx,Op::Binary(op.clone()),line,col); }
            DExprKind::Bool(op,values) => {
                let mut ends = Vec::new(); for (index,value) in values.iter().enumerate() { self.expr(ctx,value)?; if index + 1 < values.len() { self.emit(ctx,Op::Dup,line,col); ends.push(self.emit(ctx,if op=="and"{Op::JumpFalse(0)}else{Op::JumpTrue(0)},line,col)); self.emit(ctx,Op::Pop,line,col); } }
                let end = self.here(ctx); for at in ends { self.patch(ctx,at,end); }
            }
            DExprKind::Compare(left,tail) => {
                if tail.len() == 1 { self.expr(ctx,left)?; self.expr(ctx,&tail[0].1)?; self.emit(ctx,Op::Compare(tail[0].0.clone()),line,col); }
                else {
                    let previous = self.temporary(ctx); self.expr(ctx,left)?; self.emit(ctx,Op::Store(previous.clone()),line,col); let mut ends = Vec::new();
                    for (index,(op,value)) in tail.iter().enumerate() {
                        self.emit(ctx,Op::Load(previous.clone()),line,col); self.expr(ctx,value)?;
                        if index + 1 < tail.len() { self.emit(ctx,Op::Dup,line,col); self.emit(ctx,Op::Store(previous.clone()),line,col); }
                        self.emit(ctx,Op::Compare(op.clone()),line,col);
                        if index + 1 < tail.len() { self.emit(ctx,Op::Dup,line,col); ends.push(self.emit(ctx,Op::JumpFalse(0),line,col)); self.emit(ctx,Op::Pop,line,col); }
                    }
                    let end = self.here(ctx); for at in ends { self.patch(ctx,at,end); }
                }
            }
            DExprKind::Conditional(test,yes,no) => { self.expr(ctx,test)?; let otherwise = self.emit(ctx,Op::JumpFalse(0),line,col); self.expr(ctx,yes)?; let end = self.emit(ctx,Op::Jump(0),line,col); self.patch(ctx,otherwise,self.here(ctx)); self.expr(ctx,no)?; self.patch(ctx,end,self.here(ctx)); }
            DExprKind::Attribute(object,name) => { self.expr(ctx,object)?; self.emit(ctx,Op::GetAttr(name.clone()),line,col); }
            DExprKind::Subscript(object,key) => { self.expr(ctx,object)?; self.expr(ctx,key)?; self.emit(ctx,Op::GetItem,line,col); }
            DExprKind::Slice(a,b,c) => { for value in [a,b,c] { if let Some(value) = value { self.expr(ctx,value)?; } else { self.emit(ctx,Op::Const(Const::None),line,col); } } self.emit(ctx,Op::BuildSlice(3),line,col); }
            DExprKind::Call(fun,args,keywords) => {
                self.expr(ctx,fun)?;
                let extended = args.iter().any(|x|matches!(x.kind,DExprKind::Star(_))) || keywords.iter().any(|(name,_)|name.is_none());
                if !extended { for arg in args { self.expr(ctx,arg)?; } for (_,value) in keywords { self.expr(ctx,value)?; } self.emit(ctx,Op::Call { pos:args.len(),keywords:keywords.iter().map(|(name,_)|name.clone().unwrap()).collect() },line,col); }
                else {
                    let sole_star = args.len() == 1 && matches!(args[0].kind,DExprKind::Star(_));
                    for arg in args { if let DExprKind::Star(value) = &arg.kind { self.expr(ctx,value)?; if !sole_star { self.emit(ctx,Op::BuildListUnpack(1),line,col); } } else { self.expr(ctx,arg)?; self.emit(ctx,Op::BuildTuple(1),line,col); } }
                    if !sole_star { self.emit(ctx,Op::BuildTupleUnpack(args.len()),line,col); }
                    if !keywords.is_empty() {self.keyword_arguments(ctx,keywords,line,col)?;}
                    self.emit(ctx,Op::CallEx { kwargs:!keywords.is_empty() },line,col);
                }
            }
            DExprKind::Named(name,value) => { self.expr(ctx,value)?; self.emit(ctx,Op::Dup,line,col); self.emit(ctx,Op::Store(name.clone()),line,col); }
            DExprKind::Lambda(params,body) => {
                for value in &params.defaults { self.expr(ctx,value)?; } for (_,value) in &params.kwdefaults { self.expr(ctx,value)?; }
                let stmt = DStmt { kind:DStmtKind::Return(Some(*body.clone())),line,column:col };
                let code = self.code("<lambda>",ScopeKind::Function,params,&[stmt],ctx,line)?;
                self.emit(ctx,Op::MakeFunction { code:self.offset+code,defaults:params.defaults.len(),kwdefaults:params.kwdefaults.iter().map(|(name,_)|name.clone()).collect() },line,col);
            }
            DExprKind::Yield(value,from) => {
                if !matches!(self.codes[ctx.index].kind,ScopeKind::Function | ScopeKind::Comprehension) { return Err(self.error(line,"yield outside function")); }
                self.codes[ctx.index].is_generator = true;
                if let Some(value) = value { self.expr(ctx,value)?; } else { self.emit(ctx,Op::Const(Const::None),line,col); }
                if *from { self.emit(ctx,Op::GetYieldFromIter,line,col); self.emit(ctx,Op::YieldFrom,line,col); } else { self.emit(ctx,Op::Yield,line,col); }
            }
            DExprKind::Joined(values) => { for value in values { self.expr(ctx,value)?; } self.emit(ctx,Op::BuildString(values.len()),line,col); }
            DExprKind::Template(values) => {
                for value in values{if let DExprKind::Formatted(inner,conversion,spec)=&value.kind{
                    let(expression,inner)=if let DExprKind::RawInterpolation(source,inner)=&inner.kind{(Some(source.clone()),&**inner)}else{(None,&**inner)};
                    self.expr(ctx,inner)?;if let Some(spec)=spec{self.expr(ctx,spec)?;}
                    self.emit(ctx,Op::MakeInterpolation{expression,conversion:*conversion,spec:spec.is_some()},value.line,value.column);
                }else{self.expr(ctx,value)?;}}
                self.emit(ctx,Op::BuildTemplate(values.len()),line,col);
            },
            DExprKind::RawInterpolation(_,value)=>self.expr(ctx,value)?,
            DExprKind::Formatted(value,conversion,spec) => { self.expr(ctx,value)?; if let Some(spec) = spec { self.expr(ctx,spec)?; } self.emit(ctx,Op::FormatValue { conversion:*conversion,spec:spec.is_some() },line,col); }
            DExprKind::Comprehension { kind,element,value,generators } => self.comprehension(ctx,kind,element,value.as_deref(),generators,line,col)?,
            DExprKind::Star(value) => {
                if self.codes[ctx.index].kind!=ScopeKind::Annotation{return Err(self.error(line,"starred expression is not allowed here"));}
                self.expr(ctx,value)?;self.emit(ctx,Op::TypeUnpack,line,col);
            },
        }
        Ok(())
    }
    fn comprehension(&mut self, outer: &mut DCtx, kind: &str, element: &DExpr, value: Option<&DExpr>, generators: &[DGenerator], line: usize, col: usize) -> Result<(),String> {
        if generators.is_empty() { return Err(self.error(line,"comprehension requires a generator")); }
        for generator in generators { if d_contains_named(&generator.iter) { return Err(self.error(line,"assignment expression cannot be used in a comprehension iterable expression")); } }
        let mut symbols = DSymbols { private:outer.private.clone(),..DSymbols::default() };
        for generator in generators { symbols.target(&generator.target); }
        let mut named = DSymbols { private:outer.private.clone(),..DSymbols::default() }; named.expr(element); if let Some(value) = value { named.expr(value); } for generator in generators { for value in &generator.filters { named.expr(value); } }
        for generator in generators.iter().skip(1) { named.expr(&generator.iter); }
        for name in &named.locals {
            if symbols.locals.contains(name) { return Err(self.error(line,"assignment expression cannot rebind a comprehension iteration variable")); }
            for (kind,names,_) in outer.scopes.iter().rev() {
                if *kind != ScopeKind::Comprehension { break; }
                if names.contains(name) { return Err(self.error(line,"assignment expression cannot rebind an enclosing comprehension iteration variable")); }
            }
        }
        if !named.locals.is_empty() && outer.scopes.iter().rev().find(|(kind,_,_)|*kind != ScopeKind::Comprehension).is_some_and(|(kind,_,_)|*kind == ScopeKind::Class) { return Err(self.error(line,"assignment expression within a comprehension cannot be used in a class body")); }
        symbols.locals.push(".0".to_owned());
        let mut globals = Vec::new(); let mut nonlocals = Vec::new();
        for name in named.locals { if self.codes[outer.index].kind == ScopeKind::Module || self.codes[outer.index].globals.contains(&name) { globals.push(name); } else { nonlocals.push(name); } }
        let mut frees=nonlocals.clone();
        for name in &named.uses { if !symbols.locals.contains(name) && !globals.contains(name) && d_scope_binds(&outer.scopes,name) { d_push_name(&mut frees,name); } }
        if named.uses.iter().any(|name|name=="__class__" || name=="super") && outer.scopes.iter().any(|(kind,_,_)|*kind==ScopeKind::Class) { d_push_name(&mut frees,"__class__"); }
        let index = self.codes.len(); let mut params = Params::default(); params.positional.push(".0".to_owned());
        self.codes.push(Code { name:format!("<{kind}comp>"),filename:self.filename.clone(),kind:ScopeKind::Comprehension,locals:symbols.locals.clone(),globals:globals.clone(),nonlocals,frees,params,ops:Vec::new(),is_generator:kind=="generator",future_flags:self.future_flags,docstring:None });
        let mut scopes = outer.scopes.clone(); scopes.push((ScopeKind::Comprehension,symbols.locals,globals)); let mut ctx = DCtx { index,loops:Vec::new(),scopes,private:outer.private.clone() };
        let result = if kind == "generator" { None } else { let tmp = self.temporary(&ctx); self.emit(&ctx,match kind { "list"=>Op::BuildList(0),"set"=>Op::BuildSet(0),_=>Op::BuildDict(0) },line,col); self.emit(&ctx,Op::Store(tmp.clone()),line,col); Some(tmp) };
        self.comprehension_loop(&mut ctx,kind,element,value,generators,0,result.as_deref(),line,col)?;
        if let Some(result) = result { self.emit(&ctx,Op::Load(result),line,col); } else { self.emit(&ctx,Op::Const(Const::None),line,col); } self.emit(&ctx,Op::Return,line,col);
        self.propagate_frees(index,outer);
        self.order_cell_locals(index);
        self.emit(outer,Op::MakeFunction { code:self.offset+index,defaults:0,kwdefaults:Vec::new() },line,col); self.expr(outer,&generators[0].iter)?; self.emit(outer,Op::GetIter,line,col); self.emit(outer,Op::Call { pos:1,keywords:Vec::new() },line,col); Ok(())
    }
    fn comprehension_loop(&mut self, ctx: &mut DCtx, kind: &str, element: &DExpr, value: Option<&DExpr>, generators: &[DGenerator], index: usize, result: Option<&str>, line: usize, col: usize) -> Result<(),String> {
        let generator = &generators[index];
        if index == 0 { self.emit(ctx,Op::Load(".0".to_owned()),line,col); } else { self.expr(ctx,&generator.iter)?; self.emit(ctx,Op::GetIter,line,col); }
        let start = self.here(ctx); let exhausted = self.emit(ctx,Op::ForIter(0),line,col); self.store(ctx,&generator.target)?;
        for filter in &generator.filters { self.expr(ctx,filter)?; self.emit(ctx,Op::JumpFalse(start),line,col); }
        if index + 1 < generators.len() { self.comprehension_loop(ctx,kind,element,value,generators,index+1,result,line,col)?; }
        else if kind == "generator" { self.expr(ctx,element)?; self.emit(ctx,Op::Yield,line,col); self.emit(ctx,Op::Pop,line,col); }
        else if kind == "dict" {
            let key = self.temporary(ctx); self.expr(ctx,element)?; self.emit(ctx,Op::Store(key.clone()),line,col); self.expr(ctx,value.ok_or_else(||self.error(line,"missing dictionary comprehension value"))?)?;
            self.emit(ctx,Op::Load(result.unwrap().to_owned()),line,col); self.emit(ctx,Op::Load(key),line,col); self.emit(ctx,Op::SetItem,line,col);
        } else {
            self.emit(ctx,Op::Load(result.unwrap().to_owned()),line,col); self.emit(ctx,Op::GetAttr(if kind=="list"{"append"}else{"add"}.to_owned()),line,col); self.expr(ctx,element)?; self.emit(ctx,Op::Call { pos:1,keywords:Vec::new() },line,col); self.emit(ctx,Op::Pop,line,col);
        }
        self.emit(ctx,Op::Jump(start),line,col); self.patch(ctx,exhausted,self.here(ctx)); Ok(())
    }
}

fn compile_dynamic(source: &str, filename: &str, mode: &str, code_offset: usize, future_flags: u32) -> Result<Vec<Code>,String> {
    compile_dynamic_optimized(source,filename,mode,code_offset,future_flags,0)
}
fn compile_dynamic_optimized(source: &str, filename: &str, mode: &str, code_offset: usize, future_flags: u32, optimize:u8) -> Result<Vec<Code>,String> {
    if !["exec","eval","single"].contains(&mode) { return Err("ValueError: compile() mode must be 'exec', 'eval' or 'single'".to_owned()); }
    let (body,future_flags)=lower_python_cst(source,filename,mode,future_flags&!0x10)?;
    d_validate_futures(&body,filename,true)?;
    d_validate_except_star(&body,filename,0,&[])?;
    if mode == "single" && (body.is_empty() || body.iter().any(|stmt| stmt.line != body[0].line)) { return Err(format!("SyntaxError: multiple statements found while compiling a single statement ({filename}:1)")); }
    let mut symbols = DSymbols::default(); symbols.block(&body);
    if let Some(error) = symbols.error { return Err(error); }
    if !symbols.nonlocals.is_empty() { return Err(format!("SyntaxError: nonlocal declaration not allowed at module level ({filename}:1)")); }
    let code = Code { name:"<module>".to_owned(),filename:filename.to_owned(),kind:ScopeKind::Module,locals:symbols.locals.clone(),globals:symbols.globals.clone(),nonlocals:Vec::new(),frees:Vec::new(),params:Params::default(),ops:Vec::new(),is_generator:false,future_flags,docstring:None };
    let mut compiler = DCompiler { codes:vec![code],filename:filename.to_owned(),offset:code_offset,temporary:0,interactive:mode=="single",future_flags,scope_annotations:HashMap::new(),stringized_annotation:false,optimize };
    let mut ctx = DCtx { index:0,loops:Vec::new(),scopes:vec![(ScopeKind::Module,symbols.locals,symbols.globals)],private:None };
    if mode == "eval" {
        if let DStmtKind::Expr(value) = &body[0].kind { compiler.expr(&mut ctx,value)?; }
    } else {
        if future_flags & D_FUTURE_ANNOTATIONS != 0 && d_has_annotations(&body) {
            compiler.emit(&ctx,Op::BuildSet(0),1,0);
            compiler.emit(&ctx,Op::Store("__conditional_annotations__".to_owned()),1,0);
            compiler.emit(&ctx,Op::SetupAnnotations,1,0);
        }
        if future_flags & D_FUTURE_ANNOTATIONS == 0 {compiler.prepare_scope_annotations(&mut ctx,&body,1,0)?;}
        let mut body_start=0;
        if mode=="exec"{if let Some(first)=body.first(){if let Some(doc)=d_docstring(first){
            if optimize<2{compiler.emit(&ctx,Op::Const(Const::Str(d_clean_doc(doc))),first.line,first.column);compiler.emit(&ctx,Op::Store("__doc__".to_owned()),first.line,first.column);}body_start=1;
        }}}
        compiler.block(&mut ctx,&body[body_start..])?;
        compiler.emit(&ctx,Op::Const(Const::None),body.last().map(|x|x.line).unwrap_or(1),0);
    }
    compiler.emit(&ctx,Op::Return,body.last().map(|x|x.line).unwrap_or(1),0); Ok(compiler.codes)
}
