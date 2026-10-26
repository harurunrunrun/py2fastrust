// Python source tokenization for the generated PEG. Literal escape decoding,
// identifier normalization and AST semantic checks belong to the lowering pass.
// Unicode identifier membership reuses the runtime's Unicode 16 tables.
#[derive(Debug)]
struct PegLexError { kind: &'static str, message: String, line: usize, column: usize }
struct PegLexer {
    source: std::rc::Rc<Vec<char>>, at: usize, line: usize, column: usize, line_start: bool,
    comments:Vec<(usize,usize)>, indents: Vec<(usize,usize)>, brackets: Vec<char>, fields: usize, tokens: Vec<PegToken>, future_flags: u32,
}
impl PegLexer {
    fn new(source: &str) -> Self {
        Self { source: source.replace("\r\n","\n").replace('\r',"\n").chars().collect::<Vec<_>>().into(),
            at:0,line:1,column:0,line_start:true,comments:Vec::new(),indents:vec![(0,0)],brackets:Vec::new(),fields:0,tokens:Vec::new(),future_flags:0 }
    }
    fn with_flags(mut self, flags: u32) -> Self { self.future_flags=flags;self }
    fn peek(&self, offset: usize) -> Option<char> { self.source.get(self.at+offset).copied() }
    fn bump(&mut self) -> Option<char> {
        let value=self.peek(0)?;self.at+=1;
        if value=='\n' { self.line+=1;self.column=0; }else{self.column+=1;}Some(value)
    }
    fn text(&self, start: usize) -> String { self.source[start..self.at].iter().collect() }
    fn error(&self, kind: &'static str, message: &str) -> PegLexError {
        PegLexError {kind,message:message.to_owned(),line:self.line,column:self.column}
    }
    fn emit(&mut self, kind: &str, text: String, line: usize, column: usize) {
        self.tokens.push(PegToken {kind:kind.to_owned(),text,line,column});
    }
    fn matches(&self, text: &str) -> bool { text.chars().enumerate().all(|(index,ch)|self.peek(index)==Some(ch)) }
    fn identifier_start(ch: char) -> bool {
        if ch.is_ascii(){ch.is_ascii_alphabetic()||ch=='_'}else{text_property(ch,TEXT_IDENTIFIER_START)}
    }
    fn identifier_continue(ch: char) -> bool {
        if ch.is_ascii(){ch.is_ascii_alphanumeric()||ch=='_'}else{text_property(ch,TEXT_IDENTIFIER_CONTINUE)}
    }
    fn indent(&mut self) -> Result<bool,PegLexError> {
        let start=self.at;
        let mut width=0;let mut alternate=0;
        while let Some(ch)=self.peek(0) {
            match ch {' '=>{self.bump();width+=1;alternate+=1;},'\t'=>{self.bump();width=(width/8+1)*8;alternate+=1;},'\x0c'=>{self.bump();width=0;alternate=0;},_=>break}
        }
        if matches!(self.peek(0),None|Some('\n')|Some('#')) {
            if self.peek(0)==Some('#'){while !matches!(self.peek(0),None|Some('\n')){self.bump();}}
            if self.peek(0)==Some('\n'){self.bump();}return Ok(false);
        }
        let (previous,alt)=*self.indents.last().unwrap();
        if width==previous {
            if alternate!=alt{return Err(self.error("TabError","inconsistent use of tabs and spaces in indentation"));}
        }else if width>previous {
            if alternate<=alt{return Err(self.error("TabError","inconsistent use of tabs and spaces in indentation"));}
            if self.indents.len()>=100{return Err(self.error("IndentationError","too many levels of indentation"));}
            self.indents.push((width,alternate));self.emit("INDENT",self.text(start),self.line,0);
        }else {
            while self.indents.last().unwrap().0>width {self.indents.pop();self.emit("DEDENT",String::new(),self.line,self.column);}
            if self.indents.last().unwrap().0!=width{return Err(self.error("IndentationError","unindent does not match any outer indentation level"));}
            if self.indents.last().unwrap().1!=alternate{return Err(self.error("TabError","inconsistent use of tabs and spaces in indentation"));}
        }
        self.line_start=false;Ok(true)
    }
    fn digits(&mut self, base: u32, required: bool, prefix_underscore: bool) -> Result<(),PegLexError> {
        if prefix_underscore&&self.peek(0)==Some('_'){self.bump();}
        if !self.peek(0).is_some_and(|ch|ch.is_ascii()&&ch.is_digit(base)) {
            if required{return Err(self.error("SyntaxError","invalid numeric literal"));}return Ok(());
        }
        loop {
            self.bump();
            if self.peek(0)==Some('_') {
                if !self.peek(1).is_some_and(|ch|ch.is_ascii()&&ch.is_digit(base)){return Err(self.error("SyntaxError","invalid numeric literal"));}self.bump();
            }
            if !self.peek(0).is_some_and(|ch|ch.is_ascii()&&ch.is_digit(base)){break;}
        }
        Ok(())
    }
    fn number(&mut self) -> Result<(),PegLexError> {
        let (start,line,column)=(self.at,self.line,self.column);
        let mut floating=false;let mut imaginary=false;
        if self.peek(0)==Some('0')&&matches!(self.peek(1),Some('x'|'X'|'o'|'O'|'b'|'B')) {
            let base=match self.peek(1).unwrap(){'x'|'X'=>16,'o'|'O'=>8,_=>2};self.bump();self.bump();self.digits(base,true,true)?;
        }else {
            if self.peek(0)!=Some('.') {self.digits(10,true,false)?;}
            if self.peek(0)==Some('.') {floating=true;self.bump();self.digits(10,false,false)?;}
            if matches!(self.peek(0),Some('e'|'E')) {
                floating=true;self.bump();if matches!(self.peek(0),Some('+'|'-')){self.bump();}self.digits(10,true,false)?;
            }
            if matches!(self.peek(0),Some('j'|'J')){imaginary=true;self.bump();}
            if !floating&&!imaginary&&self.source[start]=='0'&&self.source[start..self.at].iter().any(|ch|matches!(ch,'1'..='9')) {
                return Err(self.error("SyntaxError","leading zeros in decimal integer literals are not permitted"));
            }
        }
        if self.peek(0).is_some_and(Self::identifier_continue) {
            let follows_keyword=["and","else","for","if","in","is","not","or"].iter().any(|word|
                self.matches(word)&&!self.peek(word.len()).is_some_and(Self::identifier_continue));
            if !follows_keyword{return Err(self.error("SyntaxError","invalid numeric literal"));}
        }
        self.emit("NUMBER",self.text(start),line,column);Ok(())
    }
    fn operator(&mut self) -> Result<(),PegLexError> {
        let (line,column)=(self.line,self.column);
        if self.future_flags&0x400000!=0&&self.matches("<>") {
            self.bump();self.bump();self.emit("NOTEQUAL","<>".into(),line,column);return Ok(());
        }
        let (text,kind)=PEG_OPERATORS.iter().copied().find(|(text,_)|self.matches(text))
            .ok_or_else(||self.error("SyntaxError","invalid character in source"))?;
        let first=text.chars().next().unwrap();
        if ["(","[","{"].contains(&text) {
            if self.brackets.len()+self.fields>=200{return Err(self.error("SyntaxError","too many nested parentheses"));}self.brackets.push(first);
        }else if [")","]","}"].contains(&text) {
            let expected=match first{')'=>'(',']'=>'[',_=>'{'};
            if self.brackets.pop()!=Some(expected){return Err(self.error("SyntaxError","unmatched or mismatched closing bracket"));}
        }
        for _ in text.chars(){self.bump();}self.emit(kind,text.to_owned(),line,column);Ok(())
    }
    fn string(&mut self, prefix: &str, start: usize, line: usize, column: usize) -> Result<(),PegLexError> {
        let quote=self.bump().unwrap();let triple=self.peek(0)==Some(quote)&&self.peek(1)==Some(quote);
        if triple{self.bump();self.bump();}
        let lower=prefix.to_ascii_lowercase();let formatted=lower.contains('f')||lower.contains('t');
        if formatted {
            let family=if lower.contains('t'){"TSTRING"}else{"FSTRING"};
            self.emit(&format!("{}_START",family),self.text(start),line,column);
            self.formatted_text(quote,triple,family,false,lower.contains('r'))?;
            let (end,line,column)=(self.at,self.line,self.column);self.bump();if triple{self.bump();self.bump();}
            self.emit(&format!("{}_END",family),self.text(end),line,column);
        }else {
            loop {
                if self.peek(0)==Some(quote)&&(!triple||(self.peek(1)==Some(quote)&&self.peek(2)==Some(quote))) {
                    self.bump();if triple{self.bump();self.bump();}break;
                }
                match self.bump() {
                    None=>return Err(self.error("SyntaxError","unterminated string literal")),
                    Some('\n') if !triple=>return Err(self.error("SyntaxError","unterminated string literal")),
                    Some('\\')=>{if self.bump().is_none(){return Err(self.error("SyntaxError","unterminated string literal"));}},
                    _=>(),
                }
            }
            self.emit("STRING",self.text(start),line,column);
        }Ok(())
    }
    fn formatted_text(&mut self, quote: char, triple: bool, family: &str, format: bool, raw: bool) -> Result<(),PegLexError> {
        let (mut line,mut column)=(self.line,self.column);let mut text=String::new();
        loop {
            let ch=self.peek(0).ok_or_else(||self.error("SyntaxError","unterminated formatted string"))?;
            let closing=ch==quote&&(!triple||(self.peek(1)==Some(quote)&&self.peek(2)==Some(quote)));
            if (!format&&closing)||(format&&ch=='}') {
                if !text.is_empty(){self.emit(&format!("{}_MIDDLE",family),text,line,column);}return Ok(());
            }
            if (format&&closing)||(ch=='\n'&&!triple){return Err(self.error("SyntaxError","unterminated formatted string"));}
            if ch=='{' {
                if !format&&self.peek(1)==Some('{'){text.push('{');self.bump();self.bump();continue;}
                if !text.is_empty(){self.emit(&format!("{}_MIDDLE",family),std::mem::take(&mut text),line,column);}
                let (field_line,field_column)=(self.line,self.column);self.bump();self.emit("LBRACE","{".into(),field_line,field_column);
                self.field(quote,triple,family,raw)?;line=self.line;column=self.column;continue;
            }
            if ch=='}' {
                if !format&&self.peek(1)==Some('}'){text.push('}');self.bump();self.bump();continue;}
                return Err(self.error("SyntaxError","single '}' is not allowed in a formatted string"));
            }
            text.push(self.bump().unwrap());
            if ch=='\\' {
                if !raw&&self.peek(0)==Some('N')&&self.peek(1)==Some('{') {
                    text.push(self.bump().unwrap());text.push(self.bump().unwrap());
                    while let Some(next)=self.bump(){text.push(next);if next=='}'{break;}}
                }else if !matches!(self.peek(0),None|Some('{'|'}')) {text.push(self.bump().unwrap());}
            }
        }
    }
    fn field(&mut self, quote: char, triple: bool, family: &str, raw: bool) -> Result<(),PegLexError> {
        if self.fields+self.brackets.len()>=200{return Err(self.error("SyntaxError","too many nested formatted strings"));}
        self.fields+=1;let base=self.brackets.len();
        loop {
            let next=self.peek(0).ok_or_else(||self.error("SyntaxError","unterminated formatted-string expression"))?;
            if self.brackets.len()==base {
                if next=='}' {let (line,column)=(self.line,self.column);self.bump();self.emit("RBRACE","}".into(),line,column);self.fields-=1;return Ok(());}
                if next==':' {let (line,column)=(self.line,self.column);self.bump();self.emit("COLON",":".into(),line,column);self.formatted_text(quote,triple,family,true,raw)?;continue;}
                if next==')'||next==']'{return Err(self.error("SyntaxError","unmatched closing bracket in formatted string"));}
            }
            self.one(true)?;
        }
    }
    fn one(&mut self, in_field: bool) -> Result<(),PegLexError> {
        let (line,column)=(self.line,self.column);let ch=self.peek(0).unwrap();
        if ch==' '||ch=='\t'||ch=='\x0c'{self.bump();return Ok(());}
        if ch=='#'{let start=self.at;while !matches!(self.peek(0),None|Some('\n')){self.bump();}self.comments.push((start,self.at));return Ok(());}
        if ch=='\n' {
            self.bump();if self.brackets.is_empty()&&!in_field {self.emit("NEWLINE","\n".into(),line,column);self.line_start=true;}return Ok(());
        }
        if ch=='\\' {
            if self.peek(1)!=Some('\n'){return Err(self.error("SyntaxError","unexpected character after line continuation character"));}
            self.bump();self.bump();if self.peek(0).is_none(){return Err(self.error("SyntaxError","unexpected EOF after line continuation"));}return Ok(());
        }
        if ch=='\''||ch=='"'{return self.string("",self.at,line,column);}
        if Self::identifier_start(ch) {
            let start=self.at;self.bump();while self.peek(0).is_some_and(Self::identifier_continue){self.bump();}
            let name=self.text(start);
            if matches!(self.peek(0),Some('\''|'"'))&&["r","b","u","f","t","br","rb","fr","rf","tr","rt"].contains(&name.to_ascii_lowercase().as_str()) {
                return self.string(&name,start,line,column);
            }self.emit("NAME",name,line,column);return Ok(());
        }
        if ch.is_ascii_digit()||(ch=='.'&&self.peek(1).is_some_and(|next|next.is_ascii_digit())){return self.number();}
        self.operator()
    }
    fn lex(self,mode:&str)->Result<Vec<PegToken>,PegLexError>{self.lex_with_comments(mode).map(|(tokens,_)|tokens)}
    fn lex_with_comments(mut self, mode: &str) -> Result<(Vec<PegToken>,Vec<(usize,usize)>),PegLexError> {
        if self.source.contains(&'\0'){return Err(self.error("SyntaxError","source code string cannot contain null bytes"));}
        while self.at<self.source.len() {
            if self.line_start&&self.brackets.is_empty()&&!self.indent()?{continue;}
            self.one(false)?;
        }
        if !self.brackets.is_empty(){return Err(self.error("SyntaxError","unclosed bracket"));}
        if self.tokens.last().is_some_and(|token|token.kind!="NEWLINE"&&token.kind!="DEDENT") {
            self.emit("NEWLINE",String::new(),self.line,self.column);self.line+=1;self.column=0;
        }else if self.column!=0 {
            self.line+=1;self.column=0;
        }
        while self.indents.len()>1{self.indents.pop();self.emit("DEDENT",String::new(),self.line,self.column);}
        if mode=="single"&&self.tokens.last().is_some_and(|token|token.kind=="DEDENT"){self.emit("NEWLINE",String::new(),self.line,self.column);}
        self.emit("ENDMARKER",String::new(),self.line,self.column);Ok((self.tokens,self.comments))
    }
}

fn validate_python_peg(source: &str, mode: &str, future_flags: u32) -> Result<PegTree,String> {
    let tokens=PegLexer::new(source).with_flags(future_flags).lex(mode).map_err(|error|
        format!("{}: {} (line {}, column {})",error.kind,error.message,error.line,error.column+1))?;
    PegParser::new(&tokens).parse(mode).map_err(|error|
        format!("SyntaxError: invalid syntax (line {}, column {})",error.line,error.column+1))
}
