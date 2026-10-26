// Semantic lowering of the pinned official Python grammar. Source text is used
// only for literal decoding and interpolation metadata, never parsed again.
struct CstLower {
    source: Vec<char>, lines: Vec<usize>, comments: Vec<(usize,usize)>,
    tokens: Vec<PegToken>, tree: PegTree, filename: String, future_flags: u32,
}
impl CstLower {
    fn error(&self,n:usize,message:&str)->String{
        let token=&self.tokens[self.tree.nodes[n].start.min(self.tokens.len()-1)];
        format!("SyntaxError: {message} ({}:{}, column {})",self.filename,token.line,token.column+1)
    }
    fn unsupported(&self,n:usize)->String{self.error(n,&format!("runtime lowering of grammar rule '{}' is not implemented",self.rule(n)))}
    fn rule(&self,n:usize)->&'static str{match self.tree.nodes[n].kind{PegNodeKind::Rule(rule)=>PEG_RULES[rule].name,PegNodeKind::Binding(_)=>"<binding>",PegNodeKind::Token(_)=>"<token>"}}
    fn children(&self,n:usize)->Vec<usize>{self.tree.nodes[n].children.clone()}
    fn binding(&self,n:usize,name:&str)->Option<usize>{self.tree.nodes[n].children.iter().copied().find(|child|matches!(self.tree.nodes[*child].kind,PegNodeKind::Binding(value)if value==name))}
    fn required(&self,n:usize,name:&str)->Result<usize,String>{self.binding(n,name).ok_or_else(||self.error(n,&format!("missing grammar binding '{name}'")))}
    fn present(&self,n:Option<usize>)->Option<usize>{n.filter(|n|self.tree.nodes[*n].start<self.tree.nodes[*n].end)}
    fn optional(&self,n:usize,name:&str)->Option<usize>{self.present(self.binding(n,name))}
    fn unwrap(&self,mut n:usize)->usize{while matches!(self.tree.nodes[n].kind,PegNodeKind::Binding(_))&&self.tree.nodes[n].children.len()==1{n=self.tree.nodes[n].children[0];}n}
    // Bindings retain sequence grouping while rules mark semantic boundaries.
    fn items(&self,n:usize)->Vec<usize>{
        let mut out=Vec::new();let mut pending=self.children(n);pending.reverse();
        while let Some(child)=pending.pop(){match self.tree.nodes[child].kind{PegNodeKind::Rule(_)=>out.push(child),PegNodeKind::Binding(_)=>{let mut children=self.children(child);children.reverse();pending.extend(children);},PegNodeKind::Token(_)=>{}}}out
    }
    fn fields(&self,n:usize,name:&str)->Vec<usize>{
        let mut out=Vec::new();for child in self.children(n){if let PegNodeKind::Binding(key)=self.tree.nodes[child].kind{if key==name{out.push(child)}else{out.extend(self.fields(child,name));}}}out
    }
    fn token(&self,n:usize)->&PegToken{&self.tokens[self.tree.nodes[n].start]}
    fn spelling(&self,n:usize)->String{let node=&self.tree.nodes[n];self.tokens[node.start..node.end].iter().map(|t|t.text.as_str()).collect()}
    fn name(&self,n:usize)->Result<String,String>{d_identifier(&self.token(n).text)}
    fn expr_at(&self,n:usize,kind:DExprKind)->DExpr{let t=self.token(n);DExpr{kind,line:t.line,column:t.column}}
    fn stmt_at(&self,n:usize,kind:DStmtKind)->DStmt{let t=self.token(n);DStmt{kind,line:t.line,column:t.column}}
    fn offset(&self,token:usize)->usize{let t=&self.tokens[token];self.lines[t.line-1]+t.column}
    fn source_text(&self,start:usize,end:usize)->String{self.source[start..end].iter().enumerate().filter_map(|(offset,ch)|if self.comments.iter().any(|(a,b)|*a<=start+offset&&start+offset<*b){None}else{Some(*ch)}).collect()}
    fn scalar_child(&self,n:usize)->Result<usize,String>{let items=self.items(n);if items.len()==1{Ok(items[0])}else{Err(self.unsupported(n))}}
    fn maybe_expr(&mut self,n:Option<usize>)->Result<Option<Box<DExpr>>,String>{n.map(|n|self.expr(n).map(Box::new)).transpose()}
    fn exprs(&mut self,n:usize)->Result<Vec<DExpr>,String>{
        let n=self.unwrap(n);let mut result=Vec::new();
        if matches!(self.tree.nodes[n].kind,PegNodeKind::Binding(_)) {
            for child in self.items(n){result.extend(self.exprs(child)?);}return Ok(result);
        }
        match self.rule(n){
            "star_named_expressions"|"star_targets_list_seq"|"del_targets"=>{let a=self.required(n,"a")?;for child in self.items(a){result.push(self.expr(child)?);}},
            "star_targets_tuple_seq"=>{result.push(self.expr(self.required(n,"a")?)?);if let Some(b)=self.binding(n,"b"){for c in self.fields(b,"c"){result.push(self.expr(c)?);}}},
            _=>result.push(self.expr(n)?),
        }Ok(result)
    }
    fn expr(&mut self,n:usize)->Result<DExpr,String>{
        let n=self.unwrap(n);let rule=self.rule(n);
        if let PegNodeKind::Token(token)=self.tree.nodes[n].kind{return self.atom_token(n,token);}
        if rule=="<binding>"{return self.expr(self.scalar_child(n)?);}
        let kind=match rule{
            "expression" if self.binding(n,"c").is_some()=>DExprKind::Conditional(Box::new(self.expr(self.required(n,"b")?)?),Box::new(self.expr(self.required(n,"a")?)?),Box::new(self.expr(self.required(n,"c")?)?)),
            "assignment_expression"=>{let name=self.name(self.required(n,"a")?)?;self.check_binding(n,&name)?;DExprKind::Named(name,Box::new(self.expr(self.required(n,"b")?)?))},
            "expressions"|"star_expressions"|"star_targets"=>{
                if let Some(a)=self.binding(n,"a"){
                    if rule=="star_targets"&&self.tree.nodes[n].end==self.tree.nodes[a].end{return self.expr(a);}
                    let mut values=vec![self.expr(a)?];if let Some(b)=self.binding(n,"b"){for c in self.fields(b,"c"){values.push(self.expr(c)?);}}
                    DExprKind::Tuple(values)
                }else{return self.expr(self.scalar_child(n)?);}
            },
            "subject_expr" if self.binding(n,"value").is_some()=>{
                let mut values=vec![self.expr(self.required(n,"value")?)?];if let Some(rest)=self.optional(n,"values"){values.extend(self.exprs(rest)?);}DExprKind::Tuple(values)
            },
            "disjunction"|"conjunction" if self.binding(n,"a").is_some()=>{
                let mut values=vec![self.expr(self.required(n,"a")?)?];for c in self.fields(self.required(n,"b")?,"c"){values.push(self.expr(c)?);}
                DExprKind::Bool(if rule=="disjunction"{"or"}else{"and"}.to_owned(),values)
            },
            "inversion" if self.binding(n,"a").is_some()=>DExprKind::Unary("not".to_owned(),Box::new(self.expr(self.required(n,"a")?)?)),
            "bitwise_or"|"bitwise_xor"|"bitwise_and"|"shift_expr"|"sum"|"term"|"power" if self.binding(n,"a").is_some()=>{
                let a=self.required(n,"a")?;let b=self.required(n,"b")?;
                let op=self.tokens[self.tree.nodes[a].end..self.tree.nodes[b].start].iter().map(|t|t.text.as_str()).collect::<String>();
                DExprKind::Binary(op,Box::new(self.expr(a)?),Box::new(self.expr(b)?))
            },
            "factor" if self.binding(n,"a").is_some()=>DExprKind::Unary(self.token(n).text.clone(),Box::new(self.expr(self.required(n,"a")?)?)),
            "comparison" if self.binding(n,"a").is_some()=>{
                let mut pairs=Vec::new();for pair in self.items(self.required(n,"b")?){
                    let mut pair=self.unwrap(pair);while self.binding(pair,"a").is_none(){pair=self.scalar_child(pair)?;}
                    let value=self.required(pair,"a")?;
                    let raw=self.tokens[self.tree.nodes[pair].start..self.tree.nodes[value].start].iter().map(|t|t.text.as_str()).collect::<String>();
                    if (raw=="<>"&&self.future_flags&D_FUTURE_BARRY==0)||(raw=="!="&&self.future_flags&D_FUTURE_BARRY!=0){return Err(self.error(pair,"invalid Barry comparison operator"));}
                    let op=match raw.as_str(){"isnot"=>"is not","notin"=>"not in","<>"=>"!=",other=>other}.to_owned();pairs.push((op,self.expr(value)?));
                }DExprKind::Compare(Box::new(self.expr(self.required(n,"a")?)?),pairs)
            },
            "await_primary" if self.token(n).text=="await"=>return Err(self.error(n,"await expressions are not implemented")),
            "primary"|"t_primary"|"target_with_star_atom"|"single_subscript_attribute_target"|"del_target" if self.binding(n,"a").is_some()&&self.binding(n,"b").is_some()=>{
                let a=self.required(n,"a")?;let b=self.required(n,"b")?;let first=self.tree.nodes[a].end;
                let op=&self.tokens[first].text;
                if op=="."{DExprKind::Attribute(Box::new(self.expr(a)?),self.name(b)?)}
                else if op=="["{DExprKind::Subscript(Box::new(self.expr(a)?),Box::new(self.expr(b)?))}
                else if op=="("{let(args,keywords)=if self.present(Some(b)).is_some(){self.call_arguments(b)?}else{(Vec::new(),Vec::new())};DExprKind::Call(Box::new(self.expr(a)?),args,keywords)}
                else{DExprKind::Call(Box::new(self.expr(a)?),vec![self.expr(b)?],Vec::new())}
            },
            "slices"=>{
                let a=self.required(n,"a")?;let items=self.items(a);
                if items.len()==1&&self.rule(items[0])=="slice"&&self.tree.nodes[n].end==self.tree.nodes[a].end{return self.expr(a);}
                let mut values=Vec::new();for item in items{values.push(self.expr(item)?);}DExprKind::Tuple(values)
            },
            "slice" if self.tokens[self.tree.nodes[n].start..self.tree.nodes[n].end].iter().any(|t|t.kind=="COLON")&&self.binding(n,"b").is_some()=>{
                let lower=self.maybe_expr(self.optional(n,"a"))?;let upper=self.maybe_expr(self.optional(n,"b"))?;
                let step=if let Some(c)=self.optional(n,"c"){self.maybe_expr(self.optional(c,"d"))?}else{None};DExprKind::Slice(lower,upper,step)
            },
            "star_expression"|"star_named_expression"|"starred_expression"|"star_target" if self.token(n).text=="*"=>DExprKind::Star(Box::new(self.expr(self.required(n,"a")?)?)),
            "list"=>DExprKind::List(if let Some(a)=self.optional(n,"a"){self.exprs(a)?}else{Vec::new()}),
            "set"=>DExprKind::Set(self.exprs(self.required(n,"a")?)?),
            "tuple"=>{
                let mut values=Vec::new();if let Some(a)=self.optional(n,"a"){
                    if let Some(y)=self.binding(a,"y"){values.push(self.expr(y)?);}if let Some(z)=self.optional(a,"z"){values.extend(self.exprs(z)?);}
                }DExprKind::Tuple(values)
            },
            "star_atom"|"del_t_atom"=>{
                if self.token(n).text=="("||self.token(n).text=="["{
                    let values=if let Some(a)=self.optional(n,"a"){let inner=self.unwrap(a);if matches!(self.rule(inner),"target_with_star_atom"|"del_target"){return self.expr(inner);}self.exprs(a)?}else{Vec::new()};
                    if self.token(n).text=="["{DExprKind::List(values)}else{DExprKind::Tuple(values)}
                }else{return self.expr(self.required(n,"a")?);}
            },
            "dict"=>{
                let mut entries=Vec::new();if let Some(a)=self.optional(n,"a"){self.dictionary(a,&mut entries)?;}DExprKind::Dict(entries)
            },
            "listcomp"|"setcomp"|"genexp"|"dictcomp"=>{
                let a=self.required(n,"a")?;let(element,value)=if rule=="dictcomp"{let pair=self.unwrap(a);(self.expr(self.required(pair,"a")?)?,Some(Box::new(self.expr(self.required(pair,"b")?)?)))}else{(self.expr(a)?,None)};
                let mut generators=Vec::new();for clause in self.items(self.required(n,"b")?){self.generators(clause,&mut generators)?;}
                DExprKind::Comprehension{kind:match rule{"listcomp"=>"list","setcomp"=>"set","dictcomp"=>"dict",_=>"generator"}.to_owned(),element:Box::new(element),value,generators}
            },
            "lambdef"=>DExprKind::Lambda(if let Some(a)=self.optional(n,"a"){self.parameters(a)?}else{DParams::default()},Box::new(self.expr(self.required(n,"b")?)?)),
            "yield_expr"=>DExprKind::Yield(self.maybe_expr(self.optional(n,"a"))?,self.tokens.get(self.tree.nodes[n].start+1).is_some_and(|t|t.text=="from")),
            "strings"=>return self.strings(n),
            "string"=>return self.plain_string(n),
            "fstring"|"tstring"=>{let mut values=Vec::new();self.formatted(n,rule=="tstring",&mut values,0,false)?;if rule=="tstring"{DExprKind::Template(values)}else{DExprKind::Joined(values)}},
            "signed_number"|"signed_real_number" if self.token(n).text=="-"=>{let a=self.binding(n,"number").or_else(||self.binding(n,"real")).ok_or_else(||self.unsupported(n))?;DExprKind::Unary("-".to_owned(),Box::new(self.expr(a)?))},
            "complex_number"=>{let a=self.required(n,"real")?;let b=self.required(n,"imag")?;let op=self.tokens[self.tree.nodes[a].end].text.clone();DExprKind::Binary(op,Box::new(self.expr(a)?),Box::new(self.expr(b)?))},
            "real_number"|"imaginary_number"=>{let value=self.expr(self.binding(n,"real").or_else(||self.binding(n,"imag")).ok_or_else(||self.unsupported(n))?)?;if (rule=="real_number"&&matches!(value.kind,DExprKind::Imaginary(_)))||(rule=="imaginary_number"&&!matches!(value.kind,DExprKind::Imaginary(_))){return Err(self.error(n,"invalid numeric literal"));}return Ok(value);},
            _=>{
                if matches!(self.tree.nodes[n].kind,PegNodeKind::Rule(_)){
                    let children=self.items(n);if children.len()==1{return self.expr(children[0]);}
                    if children.is_empty()&&self.tree.nodes[n].end==self.tree.nodes[n].start+1{return self.atom_token(n,self.tree.nodes[n].start);}
                }return Err(self.unsupported(n));
            },
        };Ok(self.expr_at(n,kind))
    }
    fn atom_token(&self,n:usize,token:usize)->Result<DExpr,String>{
        let token=&self.tokens[token];let kind=match token.text.as_str(){"True"=>DExprKind::Constant(Const::Bool(true)),"False"=>DExprKind::Constant(Const::Bool(false)),"None"=>DExprKind::Constant(Const::None),"..."=>DExprKind::Ellipsis,_=>match token.kind.as_str(){
            "NAME"=>DExprKind::Name(d_identifier(&token.text)?),"NUMBER"=>if (token.text.ends_with('j')||token.text.ends_with('J')){DExprKind::Imaginary(d_imaginary(&token.text).map_err(|message|self.error(n,&message))?)}else{DExprKind::Constant(d_number(&token.text).map_err(|message|self.error(n,&message))?)},_=>return Err(self.unsupported(n)),
        }};Ok(self.expr_at(n,kind))
    }
    fn dictionary(&mut self,n:usize,result:&mut Vec<(Option<DExpr>,DExpr)>)->Result<(),String>{
        let n=self.unwrap(n);match self.rule(n){
            "kvpair"=>result.push((Some(self.expr(self.required(n,"a")?)?),self.expr(self.required(n,"b")?)?)),
            "double_starred_kvpair" if self.token(n).text=="**"=>result.push((None,self.expr(self.required(n,"a")?)?)),
            _=>for child in self.items(n){self.dictionary(child,result)?;},
        }Ok(())
    }
    fn call_arguments(&mut self,n:usize)->Result<(Vec<DExpr>,Vec<(Option<String>,DExpr)>),String>{let mut args=Vec::new();let mut keywords=Vec::new();self.collect_call(n,&mut args,&mut keywords)?;
        let mut names=Vec::new();for(name,_)in &keywords{if let Some(name)=name{if names.contains(name){return Err(self.error(n,&format!("keyword argument repeated: {name}")));}names.push(name.clone());}}Ok((args,keywords))}
    fn collect_call(&mut self,n:usize,args:&mut Vec<DExpr>,keywords:&mut Vec<(Option<String>,DExpr)>)->Result<(),String>{
        let n=self.unwrap(n);match self.rule(n){
            "arguments"|"args"|"kwargs"=>for child in self.items(n){self.collect_call(child,args,keywords)?;},
            "kwarg_or_starred"|"kwarg_or_double_starred"=>{
                if let Some(b)=self.binding(n,"b"){keywords.push((Some(self.name(self.required(n,"a")?)?),self.expr(b)?));}
                else if self.token(n).text=="**"{keywords.push((None,self.expr(self.required(n,"a")?)?));}
                else{args.push(self.expr(self.required(n,"a")?)?);}
            },
            _=>args.push(self.expr(n)?),
        }Ok(())
    }
    fn generators(&mut self,n:usize,result:&mut Vec<DGenerator>)->Result<(),String>{
        let n=self.unwrap(n);if self.rule(n)=="for_if_clause"{
            if self.token(n).text=="async"{return Err(self.error(n,"asynchronous comprehensions are not implemented"));}
            let mut filters=Vec::new();if let Some(c)=self.binding(n,"c"){for value in self.fields(c,"z"){filters.push(self.expr(value)?);}}
            let target=self.expr(self.required(n,"a")?)?;self.check_target(n,&target)?;
            result.push(DGenerator{target,iter:self.expr(self.required(n,"b")?)?,filters});
        }else{for child in self.items(n){self.generators(child,result)?;}}Ok(())
    }
    fn plain_string(&self,n:usize)->Result<DExpr,String>{
        let token=self.token(n);let chars:Vec<char>=token.text.chars().collect();let start=chars.iter().position(|ch|matches!(ch,'\''|'"')).ok_or_else(||self.error(n,"invalid string literal"))?;
        let original_prefix:String=chars[..start].iter().collect();let prefix=original_prefix.to_ascii_lowercase();let quote=chars[start];let width=if chars.get(start+1)==Some(&quote)&&chars.get(start+2)==Some(&quote){3}else{1};
        let body: String=chars[start+width..chars.len()-width].iter().collect();
        let kind=if prefix.contains('b'){
            if body.chars().any(|ch|!ch.is_ascii()){return Err(self.error(n,"bytes can only contain ASCII literal characters"));}
            let mut chars=body.chars().peekable();let mut bytes=Vec::new();while let Some(ch)=chars.next(){
                if ch!='\\'||prefix.contains('r'){bytes.push(ch as u8);continue;}
                let next=chars.next().ok_or_else(||self.error(n,"unterminated string literal"))?;match next{
                    '\n'=>{},'\\'=>bytes.push(b'\\'),'\''=>bytes.push(b'\''),'"'=>bytes.push(b'"'),'a'=>bytes.push(7),'b'=>bytes.push(8),'f'=>bytes.push(12),'n'=>bytes.push(10),'r'=>bytes.push(13),'t'=>bytes.push(9),'v'=>bytes.push(11),
                    'x'=>{let mut value=0;for _ in 0..2{value=value*16+chars.next().and_then(|ch|ch.to_digit(16)).ok_or_else(||self.error(n,"invalid hexadecimal escape"))?;}bytes.push(value as u8);},
                    '0'..='7'=>{let mut value=next.to_digit(8).unwrap();for _ in 0..2{if let Some(digit)=chars.peek().and_then(|ch|ch.to_digit(8)){chars.next();value=value*8+digit;}else{break;}}bytes.push(value as u8);},
                    other=>{bytes.push(b'\\');bytes.push(other as u8);},
                }
            }DExprKind::Constant(Const::Bytes(bytes))
        }else{let text=d_decode_formatted_text(&body,prefix.contains('r'))?;if original_prefix=="u"{DExprKind::UnicodeString(text)}else{DExprKind::Constant(Const::Str(text))}};
        Ok(self.expr_at(n,kind))
    }
    fn strings(&mut self,n:usize)->Result<DExpr,String>{
        let a=self.required(n,"a")?;let literals=self.items(a);let mut pieces=Vec::new();let mut bytes:Option<Vec<u8>>=None;let mut string_seen=false;let mut formatted=false;let mut templated=false;let mut unicode=false;
        for (index,literal)in literals.iter().enumerate(){let value=self.expr(*literal)?;match value.kind{
            DExprKind::Constant(Const::Bytes(value))=>{if string_seen{return Err(self.error(n,"cannot mix bytes and nonbytes literals"));}bytes.get_or_insert_with(Vec::new).extend(value);},
            DExprKind::Constant(Const::Str(value))|DExprKind::UnicodeString(value)=>{if bytes.is_some(){return Err(self.error(n,"cannot mix bytes and nonbytes literals"));}string_seen=true;if index==0{unicode=self.token(*literal).text.starts_with('u');}pieces.push(self.expr_at(*literal,DExprKind::Constant(Const::Str(value))));},
            DExprKind::Joined(values)=>{if bytes.is_some(){return Err(self.error(n,"cannot mix bytes and nonbytes literals"));}string_seen=true;formatted=true;pieces.extend(values);},
            DExprKind::Template(values)=>{string_seen=true;templated=true;pieces.extend(values);},
            _=>return Err(self.error(n,"invalid string literal")),
        }}
        let kind=if let Some(bytes)=bytes{DExprKind::Constant(Const::Bytes(bytes))}else if templated{DExprKind::Template(pieces)}else if formatted{DExprKind::Joined(pieces)}else{let value=pieces.into_iter().map(|value|match value.kind{DExprKind::Constant(Const::Str(value))=>value,_=>unreachable!()}).collect::<String>();if unicode{DExprKind::UnicodeString(value)}else{DExprKind::Constant(Const::Str(value))}};
        Ok(self.expr_at(n,kind))
    }
    fn formatted(&mut self,n:usize,templated:bool,values:&mut Vec<DExpr>,depth:usize,mut raw:bool)->Result<(),String>{
        let rule=self.rule(n);if matches!(rule,"fstring"|"tstring"){raw=self.token(n).text.to_ascii_lowercase().contains('r');}
        if matches!(rule,"fstring_replacement_field"|"tstring_replacement_field"|"tstring_format_spec_replacement_field"){
            if depth>2{return Err(self.error(n,"formatted-string expressions nested too deeply"));}
            let debug=self.optional(n,"debug_expr");let conversion=self.optional(n,"conversion");let format=self.optional(n,"format");let close=self.required(n,"rbrace")?;
            let start=self.offset(self.tree.nodes[n].start)+1;let end=self.offset(self.tree.nodes[debug.or(conversion).or(format).unwrap_or(close)].start);
            let expression=self.source_text(start,end).trim_end().to_owned();
            if debug.is_some(){let stop=self.offset(self.tree.nodes[conversion.or(format).unwrap_or(close)].start);values.push(self.expr_at(n,DExprKind::Constant(Const::Str(self.source_text(start,stop)))));}
            let value=self.expr(self.required(n,"a")?)?;let value=if templated{self.expr_at(n,DExprKind::RawInterpolation(expression,Box::new(value)))}else{value};
            let conversion=if let Some(conversion)=conversion{
                let node=&self.tree.nodes[conversion];let bang=&self.tokens[node.start];let name=&self.tokens[node.end-1];
                if name.line!=bang.line||name.column!=bang.column+1||!matches!(name.text.as_str(),"s"|"r"|"a"){return Err(self.error(conversion,"invalid formatted-string conversion"));}name.text.chars().next().unwrap() as i32
            }else if debug.is_some()&&format.is_none(){'r' as i32}else{-1};
            let spec=if let Some(format)=format{let mut parts=Vec::new();for child in self.children(format){self.formatted(child,false,&mut parts,depth+1,raw)?;}Some(Box::new(self.expr_at(format,DExprKind::Joined(parts))))}else{None};
            values.push(self.expr_at(n,DExprKind::Formatted(Box::new(value),conversion,spec)));return Ok(());
        }
        if let PegNodeKind::Token(token)=self.tree.nodes[n].kind{if matches!(self.tokens[token].kind.as_str(),"FSTRING_MIDDLE"|"TSTRING_MIDDLE"){
            let value=d_decode_formatted_text(&self.tokens[token].text,raw)?;if !value.is_empty(){values.push(self.expr_at(n,DExprKind::Constant(Const::Str(value))));}return Ok(());
        }}
        for child in self.children(n){self.formatted(child,templated,values,depth,raw)?;}Ok(())
    }
    fn parameters(&mut self,n:usize)->Result<DParams,String>{let mut params=DParams::default();self.parameter_walk(n,&mut params,"positional")?;Ok(params)}
    fn parameter_walk(&mut self,n:usize,params:&mut DParams,category:&str)->Result<(),String>{
        let n=self.unwrap(n);let rule=self.rule(n);
        if matches!(rule,"param_no_default"|"param_no_default_star_annotation"|"param_with_default"|"param_maybe_default"|"lambda_param_no_default"|"lambda_param_with_default"|"lambda_param_maybe_default"){
            let a=self.unwrap(self.required(n,"a")?);let name=self.name(self.required(a,"a")?)?;self.check_binding(n,&name)?;
            if let Some(annotation)=self.optional(a,"b"){params.annotations.push((name.clone(),self.expr(annotation)?));}
            let default=self.optional(n,"c").map(|value|self.expr(value)).transpose()?;
            match category{"vararg"=>params.params.vararg=Some(name),"kwarg"=>params.params.kwarg=Some(name),"kwonly"=>{params.params.kwonly.push(name.clone());if let Some(value)=default{params.kwdefaults.push((name,value));}},_=>{params.params.positional.push(name);if let Some(value)=default{params.defaults.push(value);}}}return Ok(());
        }
        if matches!(rule,"star_etc"|"lambda_star_etc"){
            if self.token(n).text=="*"{
                if let Some(a)=self.optional(n,"a"){self.parameter_walk(a,params,"vararg")?;}
                if let Some(b)=self.optional(n,"b"){for item in self.items(b){self.parameter_walk(item,params,"kwonly")?;}}
                if let Some(c)=self.optional(n,"c"){self.parameter_walk(c,params,"kwarg")?;}
            }else{for child in self.items(n){self.parameter_walk(child,params,"kwarg")?;}}return Ok(());
        }
        if matches!(rule,"kwds"|"lambda_kwds"){self.parameter_walk(self.required(n,"a")?,params,"kwarg")?;return Ok(());}
        for child in self.items(n){self.parameter_walk(child,params,category)?;}
        if matches!(rule,"slash_no_default"|"slash_with_default"|"lambda_slash_no_default"|"lambda_slash_with_default"){params.params.posonly=params.params.positional.len();}Ok(())
    }
    fn check_binding(&self,n:usize,name:&str)->Result<(),String>{if name=="__debug__"{Err(self.error(n,"cannot assign to __debug__"))}else{Ok(())}}
    fn check_target(&self,n:usize,target:&DExpr)->Result<(),String>{match &target.kind{
        DExprKind::Name(name)|DExprKind::Attribute(_,name)=>self.check_binding(n,name)?,
        DExprKind::Tuple(values)|DExprKind::List(values)=>for value in values{self.check_target(n,value)?;},DExprKind::Star(value)=>self.check_target(n,value)?,_=>{},
    }Ok(())}
    fn statements(&mut self,n:usize)->Result<Vec<DStmt>,String>{
        let n=self.unwrap(n);let rule=self.rule(n);let kind=match rule{
            "simple_stmt" if self.binding(n,"e").is_some()=>DStmtKind::Expr(self.expr(self.required(n,"e")?)?),
            "assignment"=>{
                if self.binding(n,"c").is_some()&&self.binding(n,"b").is_some()&&self.rule(self.unwrap(self.required(n,"b")?))=="augassign"{
                    let target=self.expr(self.required(n,"a")?)?;self.check_target(n,&target)?;
                    DStmtKind::AugAssign(target,self.spelling(self.required(n,"b")?).trim_end_matches('=').to_owned(),self.expr(self.required(n,"c")?)?)
                }else if self.binding(n,"c").is_some()&&self.binding(n,"b").is_some(){
                    let a=self.required(n,"a")?;let target=self.expr(a)?;self.check_target(n,&target)?;
                    let simple=self.tree.nodes[a].end==self.tree.nodes[a].start+1&&self.tokens[self.tree.nodes[a].start].kind=="NAME";
                    let value=if let Some(c)=self.optional(n,"c"){if let Some(d)=self.binding(c,"d"){Some(self.expr(d)?)}else{Some(self.expr(c)?)}}else{None};
                    DStmtKind::AnnAssign(target,self.expr(self.required(n,"b")?)?,value,simple)
                }else{
                    let a=self.required(n,"a")?;let mut targets=Vec::new();for target in self.fields(a,"z"){let target=self.expr(target)?;self.check_target(n,&target)?;targets.push(target);}
                    DStmtKind::Assign(targets,self.expr(self.required(n,"b")?)?)
                }
            },
            "return_stmt"=>DStmtKind::Return(self.optional(n,"a").map(|a|self.expr(a)).transpose()?),
            "raise_stmt"=>DStmtKind::Raise(self.optional(n,"a").map(|a|self.expr(a)).transpose()?,self.optional(n,"b").map(|b|if let Some(z)=self.binding(b,"z"){self.expr(z)}else{self.expr(b)}).transpose()?),
            "pass_stmt"=>DStmtKind::Pass,"break_stmt"=>DStmtKind::Break,"continue_stmt"=>DStmtKind::Continue,
            "global_stmt"|"nonlocal_stmt"=>{let a=self.required(n,"a")?;let node=&self.tree.nodes[a];let mut names=Vec::new();for token in &self.tokens[node.start..node.end]{if token.kind=="NAME"{names.push(d_identifier(&token.text)?);}}if rule=="global_stmt"{DStmtKind::Global(names)}else{DStmtKind::Nonlocal(names)}},
            "del_stmt"=>{let targets=self.exprs(self.required(n,"a")?)?;for target in &targets{self.check_target(n,target)?;}DStmtKind::Delete(targets)},
            "yield_stmt"=>DStmtKind::Expr(self.expr(self.required(n,"y")?)?),
            "assert_stmt"=>DStmtKind::Assert(self.expr(self.required(n,"a")?)?,self.optional(n,"b").map(|b|if let Some(z)=self.binding(b,"z"){self.expr(z)}else{self.expr(b)}).transpose()?),
            "import_name"=>{
                let mut aliases=Vec::new();self.import_aliases(self.required(n,"a")?,&mut aliases)?;
                for(name,alias)in &aliases{self.check_binding(n,alias.as_deref().unwrap_or_else(||name.split('.').next().unwrap()))?;}DStmtKind::Import(aliases)
            },
            "import_from"=>{
                let start=self.tree.nodes[n].start;let end=self.tree.nodes[n].end;let import=(start..end).find(|index|self.tokens[*index].text=="import").ok_or_else(||self.error(n,"missing import"))?;
                let mut level=0;let mut path=String::new();for token in &self.tokens[start+1..import]{match token.text.as_str(){"." if path.is_empty()=>level+=1,"..." if path.is_empty()=>level+=3,_=>path.push_str(&if token.kind=="NAME"{d_identifier(&token.text)?}else{token.text.clone()}),}}
                let targets=self.binding(n,"c").or_else(||self.binding(n,"b")).ok_or_else(||self.error(n,"missing imported names"))?;let mut aliases=Vec::new();self.import_aliases(targets,&mut aliases)?;
                if aliases.is_empty()&&self.spelling(targets)=="*"{aliases.push(("*".to_owned(),None));}
                for(name,alias)in &aliases{self.check_binding(n,alias.as_deref().unwrap_or(name))?;}
                if level==0&&path=="__future__"{for(name,_)in &aliases{self.future_flags|=d_future_feature(name).map_err(|message|self.error(n,&message))?;}}
                DStmtKind::ImportFrom(path,aliases,level)
            },
            "if_stmt"|"elif_stmt"=>{
                let condition=self.expr(self.required(n,"a")?)?;let body=self.statements(self.required(n,"b")?)?;
                let tail=if let Some(c)=self.optional(n,"c"){self.statements(c)?}else{Vec::new()};DStmtKind::If(condition,body,tail)
            },
            "while_stmt"=>DStmtKind::While(self.expr(self.required(n,"a")?)?,self.statements(self.required(n,"b")?)?,if let Some(c)=self.optional(n,"c"){self.statements(c)?}else{Vec::new()}),
            "for_stmt"=>{
                if self.token(n).text=="async"{return Err(self.error(n,"asynchronous for statements are not implemented"));}
                let target=self.expr(self.required(n,"t")?)?;self.check_target(n,&target)?;
                DStmtKind::For(target,self.expr(self.required(n,"ex")?)?,self.statements(self.required(n,"b")?)?,if let Some(tail)=self.optional(n,"el"){self.statements(tail)?}else{Vec::new()})
            },
            "with_stmt"=>{
                if self.token(n).text=="async"{return Err(self.error(n,"asynchronous with statements are not implemented"));}
                let mut items=Vec::new();for item in self.items(self.required(n,"a")?){let e=self.required(item,"e")?;let target=self.optional(item,"t").map(|t|self.expr(t)).transpose()?;if let Some(target)=&target{self.check_target(item,target)?;}items.push((self.expr(e)?,target));}
                DStmtKind::With(items,self.statements(self.required(n,"b")?)?)
            },
            "try_stmt"=>{
                let body=self.statements(self.required(n,"b")?)?;let mut handlers=Vec::new();let mut starred=false;
                if let Some(ex)=self.optional(n,"ex"){for handler in self.items(ex){starred=self.rule(handler)=="except_star_block";let kind=self.optional(handler,"e").map(|e|self.expr(e)).transpose()?;let name=self.optional(handler,"t").map(|t|self.name(t)).transpose()?;if let Some(name)=&name{self.check_binding(handler,name)?;}handlers.push((kind,name,self.statements(self.required(handler,"b")?)?));}}
                let tail=if let Some(el)=self.optional(n,"el"){self.statements(el)?}else{Vec::new()};let finally=if let Some(f)=self.optional(n,"f"){self.statements(f)?}else{Vec::new()};
                if starred{DStmtKind::TryStar(body,handlers,tail,finally)}else{DStmtKind::Try(body,handlers,tail,finally)}
            },
            "function_def"|"class_def"=>{
                let(definition,decorators)=if rule=="function_def"{(self.binding(n,"f"),self.binding(n,"d"))}else{(self.binding(n,"b"),self.binding(n,"a"))};
                if let Some(definition)=definition{
                    let mut result=self.statements(definition)?;let mut values=Vec::new();if let Some(decorators)=decorators{for value in self.items(decorators){if self.rule(value)=="decorators"{for f in self.fields(self.required(value,"a")?,"f"){values.push(self.expr(f)?);}}else{values.push(self.expr(value)?);}}}
                    for statement in &mut result{cst_set_decorators(&mut statement.kind,values.clone());statement.line=self.token(n).line;statement.column=self.token(n).column;}return Ok(result);
                }return self.statements(self.scalar_child(n)?);
            },
            "function_def_raw"=>{
                if self.token(n).text=="async"{return Err(self.error(n,"asynchronous functions are not implemented"));}
                let name=self.name(self.required(n,"n")?)?;self.check_binding(n,&name)?;
                let mut params=if let Some(params)=self.optional(n,"params"){self.parameters(params)?}else{DParams::default()};
                if let Some(annotation)=self.optional(n,"a"){let expression=self.binding(annotation,"z").unwrap_or(annotation);params.annotations.push(("return".to_owned(),self.expr(expression)?));}
                let body=self.statements(self.required(n,"b")?)?;let parameters=self.optional(n,"t").map(|t|self.type_parameters(t)).transpose()?.unwrap_or_default();
                let definition=DStmtKind::Function(name,params,body,Vec::new());if parameters.is_empty(){definition}else{DStmtKind::Generic(parameters,Box::new(definition))}
            },
            "class_def_raw"=>{
                let name=self.name(self.required(n,"a")?)?;self.check_binding(n,&name)?;
                let(bases,keywords)=if let Some(b)=self.optional(n,"b"){if let Some(z)=self.optional(b,"z"){self.call_arguments(z)?}else{(Vec::new(),Vec::new())}}else{(Vec::new(),Vec::new())};
                let mut named=Vec::new();for(key,value)in keywords{named.push((key.ok_or_else(||self.error(n,"class keyword unpacking is not implemented"))?,value));}
                let body=self.statements(self.required(n,"c")?)?;let parameters=self.optional(n,"t").map(|t|self.type_parameters(t)).transpose()?.unwrap_or_default();
                let definition=DStmtKind::Class(name,bases,named,body,Vec::new());if parameters.is_empty(){definition}else{DStmtKind::Generic(parameters,Box::new(definition))}
            },
            "type_alias"=>{let name=self.name(self.required(n,"n")?)?;self.check_binding(n,&name)?;let parameters=self.optional(n,"t").map(|t|self.type_parameters(t)).transpose()?.unwrap_or_default();DStmtKind::TypeAlias(name,parameters,self.expr(self.required(n,"b")?)?)},
            "match_stmt"=>{
                let subject=self.expr(self.required(n,"subject")?)?;let mut cases=Vec::new();let mut irrefutable=false;
                for case in self.items(self.required(n,"cases")?){if irrefutable{return Err(self.error(case,"irrefutable pattern is allowed only for the last case"));}
                    let pattern=self.pattern(self.required(case,"pattern")?)?;for name in d_pattern_bindings(&pattern).map_err(|message|self.error(case,&message))?{self.check_binding(case,&name)?;}
                    let guard=self.optional(case,"guard").map(|g|if let Some(value)=self.binding(g,"guard"){self.expr(value)}else{self.expr(g)}).transpose()?;
                    irrefutable=guard.is_none()&&d_pattern_irrefutable(&pattern);cases.push((pattern,guard,self.statements(self.required(case,"body")?)?));}
                DStmtKind::Match(subject,cases)
            },
            _=>{
                let mut out=Vec::new();for child in self.items(n){out.extend(self.statements(child)?);}
                if out.is_empty()&&!matches!(rule,"file"|"interactive"|"statement_newline"|"statements"|"simple_stmts"|"<binding>"){return Err(self.unsupported(n));}return Ok(out);
            },
        };Ok(vec![self.stmt_at(n,kind)])
    }
    fn import_aliases(&self,n:usize,out:&mut Vec<(String,Option<String>)>)->Result<(),String>{
        let n=self.unwrap(n);match self.rule(n){"dotted_as_name"|"import_from_as_name"=>{let a=self.required(n,"a")?;let name=self.spelling(a);let name=name.split('.').map(d_identifier).collect::<Result<Vec<_>,_>>()?.join(".");let alias=if let Some(b)=self.optional(n,"b"){Some(self.name(self.binding(b,"z").unwrap_or(b))?)}else{None};out.push((name,alias));},_=>for child in self.items(n){self.import_aliases(child,out)?;}}Ok(())
    }
    fn type_parameters(&mut self,n:usize)->Result<Vec<DTypeParam>,String>{
        let n=self.unwrap(n);if self.rule(n)=="type_params"{return self.type_parameters(self.required(n,"t")?);}
        let mut result=Vec::new();let mut names=Vec::new();let mut default_seen=false;
        for parameter in self.items(self.required(n,"a")?){let name=self.name(self.required(parameter,"a")?)?;self.check_binding(parameter,&name)?;
            if names.contains(&name){return Err(self.error(parameter,&format!("duplicate type parameter '{name}'")));}names.push(name.clone());
            let kind=match self.token(parameter).text.as_str(){"*"=>"typevartuple","**"=>"paramspec",_=>"typevar"};
            let(bound,default)=if kind=="typevar"{(self.optional(parameter,"b").map(|value|self.expr(value)).transpose()?,self.optional(parameter,"c").map(|value|self.expr(value)).transpose()?)}else{(None,self.optional(parameter,"b").map(|value|self.expr(value)).transpose()?)};
            if default.is_some(){default_seen=true;}else if default_seen{return Err(self.error(parameter,"non-default type parameter follows default type parameter"));}
            let(bound,constraints)=if let Some(value)=bound{if matches!(value.kind,DExprKind::Tuple(_)){(None,Some(value))}else{(Some(value),None)}}else{(None,None)};
            result.push(DTypeParam{name,kind:kind.to_owned(),bound,constraints,default});
        }Ok(result)
    }
    fn path(&self,n:usize)->Result<Vec<String>,String>{let node=&self.tree.nodes[n];self.tokens[node.start..node.end].iter().filter(|token|token.kind=="NAME").map(|token|d_identifier(&token.text)).collect()}
    fn patterns(&mut self,n:usize)->Result<Vec<MatchPattern>,String>{
        let n=self.unwrap(n);let rule=self.rule(n);let mut out=Vec::new();match rule{
            "open_sequence_pattern"=>{out.push(self.pattern(self.required(n,"pattern")?)?);if let Some(rest)=self.optional(n,"patterns"){out.extend(self.patterns(rest)?);}},
            "maybe_sequence_pattern"|"positional_patterns"|"or_pattern"=>{let a=self.binding(n,"patterns").or_else(||self.binding(n,"args")).ok_or_else(||self.unsupported(n))?;for item in self.items(a){out.push(self.pattern(item)?);}},
            _=>{if matches!(self.tree.nodes[n].kind,PegNodeKind::Binding(_)){for item in self.items(n){out.extend(self.patterns(item)?);}}else{out.push(self.pattern(n)?);}},
        }Ok(out)
    }
    fn pattern(&mut self,n:usize)->Result<MatchPattern,String>{
        let n=self.unwrap(n);match self.rule(n){
            "patterns" if self.binding(n,"patterns").is_some()=>Ok(MatchPattern::Sequence(self.patterns(self.required(n,"patterns")?)?)),
            "or_pattern"=>{let mut alternatives=self.patterns(n)?;if alternatives.len()==1{Ok(alternatives.pop().unwrap())}else{Ok(MatchPattern::Or(alternatives))}},
            "as_pattern"=>{let name=self.name(self.required(n,"target")?)?;self.check_binding(n,&name)?;Ok(MatchPattern::As{pattern:Some(Box::new(self.pattern(self.required(n,"pattern")?)?)),name:Some(name)})},
            "capture_pattern"=>{let name=self.name(self.required(n,"target")?)?;self.check_binding(n,&name)?;Ok(MatchPattern::As{pattern:None,name:Some(name)})},
            "wildcard_pattern"=>Ok(MatchPattern::As{pattern:None,name:None}),
            "value_pattern"=>Ok(MatchPattern::ValuePath(self.path(self.required(n,"attr")?)?)),
            "group_pattern"=>self.pattern(self.required(n,"pattern")?),
            "sequence_pattern"=>Ok(MatchPattern::Sequence(if let Some(patterns)=self.optional(n,"patterns"){self.patterns(patterns)?}else{Vec::new()})),
            "star_pattern"=>{let name=self.optional(n,"target").map(|target|self.name(target)).transpose()?;if let Some(name)=&name{self.check_binding(n,name)?;}Ok(MatchPattern::Star(name))},
            "mapping_pattern"=>{
                let mut keys=Vec::new();let mut patterns=Vec::new();if let Some(items)=self.optional(n,"items"){
                    for pair in self.items(self.unwrap(items)){
                        let key=self.required(pair,"key")?;let key=if self.rule(self.unwrap(key))=="attr"{MatchPattern::ValuePath(self.path(key)?)}else{self.literal_pattern(key)?};
                        if keys.iter().any(|prior|d_pattern_literal_equal(prior,&key)){return Err(self.error(n,"mapping pattern checks duplicate key"));}
                        keys.push(key);patterns.push(self.pattern(self.required(pair,"pattern")?)?);
                    }
                }
                let rest=if let Some(rest)=self.optional(n,"rest"){let rest=self.unwrap(rest);let target=self.binding(rest,"target").unwrap_or(rest);let name=self.name(target)?;self.check_binding(n,&name)?;Some(name)}else{None};
                Ok(MatchPattern::Mapping{keys,patterns,rest})
            },
            "class_pattern"=>{
                let path=self.path(self.required(n,"cls")?)?;let positional=if let Some(patterns)=self.optional(n,"patterns"){self.patterns(patterns)?}else{Vec::new()};let mut names=Vec::new();let mut patterns=Vec::new();
                if let Some(keywords)=self.optional(n,"keywords"){for keyword in self.items(self.unwrap(keywords)){
                    let name=self.name(self.required(keyword,"arg")?)?;if names.contains(&name){return Err(self.error(n,"attribute name repeated in class pattern"));}names.push(name);patterns.push(self.pattern(self.required(keyword,"value")?)?);
                }}Ok(MatchPattern::Class{path,positional,keyword_names:names,keyword_patterns:patterns})
            },
            "literal_pattern"=>self.literal_pattern(n),
            _=>self.pattern(self.scalar_child(n)?),
        }
    }
    fn literal_pattern(&mut self,n:usize)->Result<MatchPattern,String>{
        let value=if let Some(value)=self.binding(n,"value"){self.expr(value)?}else{self.expr(n)?};
        let constant=match value.kind{
            DExprKind::Constant(value)=>value,DExprKind::UnicodeString(value)=>Const::Str(value),
            DExprKind::Imaginary(value)=>Const::Complex(0.0,value),
            DExprKind::Unary(op,value)if op=="-"=>match value.kind{DExprKind::Constant(Const::Int(value))=>Const::Int(format!("-{value}")),DExprKind::Constant(Const::Float(value))=>Const::Float(-value),DExprKind::Imaginary(value)=>Const::Complex(-0.0,-value),_=>return Err(self.error(n,"pattern requires a literal"))},
            DExprKind::Binary(op,real,imag)if op=="+"||op=="-"=>{
                let real=cst_real_literal(&real).ok_or_else(||self.error(n,"complex pattern requires a real literal"))?;
                let DExprKind::Imaginary(imag)=imag.kind else{return Err(self.error(n,"complex pattern requires an imaginary literal"));};
                return Ok(MatchPattern::ComplexNumber{real,imag:if op=="-"{-imag}else{imag}});
            },
            _=>return Err(self.error(n,"pattern requires a literal")),
        };Ok(MatchPattern::Literal(constant))
    }
}
fn cst_set_decorators(definition:&mut DStmtKind,decorators:Vec<DExpr>){match definition{DStmtKind::Function(_,_,_,values)|DStmtKind::Class(_,_,_,_,values)=>*values=decorators,DStmtKind::Generic(_,definition)=>cst_set_decorators(definition,decorators),_=>{}}}
fn lower_python_cst(source:&str,filename:&str,mode:&str,inherited_flags:u32)->Result<(Vec<DStmt>,u32),String>{
    let lexer=PegLexer::new(source).with_flags(inherited_flags|D_FUTURE_BARRY);let chars=lexer.source.as_ref().clone();
    let(tokens,comments)=lexer.lex_with_comments(mode).map_err(|error|format!("{}: {} ({}:{}, column {})",error.kind,error.message,filename,error.line,error.column+1))?;
    let tree=PegParser::new(&tokens).parse(mode).map_err(|error|{
        let unexpected_indent=tokens.iter().find(|token|token.line==error.line&&token.column==error.column).is_some_and(|token|token.kind=="INDENT");
        let(kind,message)=if error.expected.contains(&"INDENT"){("IndentationError","expected an indented block")}else if unexpected_indent{("IndentationError","unexpected indent")}else{("SyntaxError","invalid syntax")};
        format!("{kind}: {message} ({}:{}, column {})",filename,error.line,error.column+1)
    })?;
    let mut lines=vec![0];for(index,ch)in chars.iter().enumerate(){if *ch=='\n'{lines.push(index+1);}}
    let root=tree.root;let mut lower=CstLower{source:chars,lines,comments,tokens,tree,filename:filename.to_owned(),future_flags:inherited_flags&!0x10};
    let body=if mode=="eval"{let value=lower.expr(lower.required(root,"a")?)?;vec![DStmt{line:value.line,column:value.column,kind:DStmtKind::Expr(value)}]}else{lower.statements(root)?};
    Ok((body,lower.future_flags))
}

fn cst_real_literal(value:&DExpr)->Option<Const>{match &value.kind{DExprKind::Constant(value @ (Const::Int(_)|Const::Float(_)))=>Some(value.clone()),DExprKind::Unary(op,value)if op=="-"=>match cst_real_literal(value)?{Const::Int(value)=>Some(Const::Int(format!("-{value}"))),Const::Float(value)=>Some(Const::Float(-value)),_=>None},_=>None}}
