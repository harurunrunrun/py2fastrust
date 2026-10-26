// Runtime Python compiler. This module deliberately shares the AOT VM's instruction
// format: dynamically compiled functions have exactly the same calling convention.
#[derive(Clone, Debug, PartialEq)]
enum DTokenKind {
    Name(String), Number(String), String(String), Bytes(Vec<u8>), FString(String),
    Symbol(String), Newline, Indent, Dedent, Eof,
}
#[derive(Clone, Debug)]
struct DToken { kind: DTokenKind, line: usize, column: usize }

struct DLexer {
    source: Vec<char>, at: usize, line: usize, column: usize,
    nesting: usize, line_start: bool, indents: Vec<usize>, tokens: Vec<DToken>,
}
impl DLexer {
    fn new(source: &str) -> Self {
        Self { source: source.replace("\r\n", "\n").replace('\r', "\n").chars().collect(), at: 0,
            line: 1, column: 0, nesting: 0, line_start: true, indents: vec![0], tokens: Vec::new() }
    }
    fn peek(&self, offset: usize) -> Option<char> { self.source.get(self.at + offset).copied() }
    fn bump(&mut self) -> Option<char> {
        let ch = self.peek(0)?; self.at += 1;
        if ch == '\n' { self.line += 1; self.column = 0; } else { self.column += 1; }
        Some(ch)
    }
    fn error(&self, message: &str) -> String { format!("SyntaxError: {message} (line {}, column {})", self.line, self.column + 1) }
    fn emit(&mut self, kind: DTokenKind, line: usize, column: usize) { self.tokens.push(DToken { kind, line, column }); }
    fn string(&mut self, prefix: &str, line: usize, column: usize) -> Result<DTokenKind, String> {
        let quote = self.bump().unwrap();
        let triple = self.peek(0) == Some(quote) && self.peek(1) == Some(quote);
        if triple { self.bump(); self.bump(); }
        let raw = prefix.contains('r') || prefix.contains('R');
        let bytes = prefix.contains('b') || prefix.contains('B');
        let formatted = prefix.contains('f') || prefix.contains('F');
        if prefix.contains('t') || prefix.contains('T') { return Err(self.error("template strings are not yet supported")); }
        let mut text = String::new();
        let mut field_depth = 0usize;
        let mut field_quote = None;
        loop {
            let ch = self.bump().ok_or_else(|| format!("SyntaxError: unterminated string literal (line {line}, column {})", column + 1))?;
            if formatted && field_depth > 0 {
                // PEP 701 permits the surrounding quote inside replacement fields.
                // Preserve expression escapes for the nested expression lexer.
                text.push(ch);
                if let Some(inner_quote) = field_quote {
                    if ch == '\\' { let next = self.bump().ok_or_else(|| self.error("unterminated f-string"))?; text.push(next); }
                    else if ch == inner_quote { field_quote = None; }
                } else if ch == '\'' || ch == '"' { field_quote = Some(ch); }
                else if ch == '{' { field_depth += 1; }
                else if ch == '}' { field_depth -= 1; }
                continue;
            }
            if ch == quote && (!triple || (self.peek(0) == Some(quote) && self.peek(1) == Some(quote))) {
                if triple { self.bump(); self.bump(); } break;
            }
            if ch == '\n' && !triple { return Err(self.error("unterminated string literal")); }
            if formatted && ch == '{' {
                text.push(ch);
                if self.peek(0) == Some('{') { text.push(self.bump().unwrap()); } else { field_depth = 1; }
                continue;
            }
            if ch != '\\' { if bytes && !ch.is_ascii() { return Err(self.error("bytes can only contain ASCII literal characters")); } text.push(ch); continue; }
            let escaped = self.bump().ok_or_else(|| self.error("unterminated string literal"))?;
            if raw { text.push('\\'); text.push(escaped); continue; }
            match escaped {
                '\n' => (), '\\' => text.push('\\'), '\'' => text.push('\''), '"' => text.push('"'),
                'n' => text.push('\n'), 'r' => text.push('\r'), 't' => text.push('\t'),
                'a' => text.push('\x07'), 'b' => text.push('\x08'), 'f' => text.push('\x0c'), 'v' => text.push('\x0b'),
                'x' | 'u' | 'U' if escaped == 'x' || !bytes => {
                    let count = match escaped { 'x' => 2, 'u' => 4, _ => 8 };
                    let mut value = 0u32;
                    for _ in 0..count {
                        let digit = self.bump().and_then(|x| x.to_digit(16)).ok_or_else(|| self.error("truncated hexadecimal escape"))?;
                        value = value * 16 + digit;
                    }
                    text.push(char::from_u32(value).ok_or_else(|| self.error("invalid Unicode escape"))?);
                }
                '0'..='7' => {
                    let mut value = escaped.to_digit(8).unwrap();
                    for _ in 0..2 {
                        if let Some(digit) = self.peek(0).and_then(|x| x.to_digit(8)) { self.bump(); value = value * 8 + digit; } else { break; }
                    }
                    text.push(char::from_u32(if bytes { value & 255 } else { value }).unwrap());
                }
                'N' if !bytes => return Err(self.error("named Unicode escapes are not yet supported by dynamic compilation")),
                other => { text.push('\\'); text.push(other); }
            }
        }
        if bytes {
            let mut result = Vec::new();
            for ch in text.chars() { if ch as u32 > 255 { return Err(self.error("bytes literals only contain byte characters")); } result.push(ch as u8); }
            Ok(DTokenKind::Bytes(result))
        } else if formatted { Ok(DTokenKind::FString(text)) } else { Ok(DTokenKind::String(text)) }
    }
    fn lex(mut self) -> Result<Vec<DToken>, String> {
        while self.at < self.source.len() {
            if self.line_start && self.nesting == 0 {
                let mut width = 0;
                while let Some(ch) = self.peek(0) {
                    match ch { ' ' => { self.bump(); width += 1; }, '\t' => { self.bump(); width = (width / 8 + 1) * 8; }, '\x0c' => { self.bump(); width = 0; }, _ => break }
                }
                if matches!(self.peek(0), Some('#') | Some('\n') | None) {
                    if self.peek(0) == Some('#') { while !matches!(self.peek(0), Some('\n') | None) { self.bump(); } }
                    if self.peek(0) == Some('\n') { self.bump(); } continue;
                }
                let previous = *self.indents.last().unwrap();
                if width > previous { self.indents.push(width); self.emit(DTokenKind::Indent, self.line, self.column); }
                else if width < previous {
                    while width < *self.indents.last().unwrap() { self.indents.pop(); self.emit(DTokenKind::Dedent, self.line, self.column); }
                    if width != *self.indents.last().unwrap() { return Err(self.error("inconsistent indentation")); }
                }
                self.line_start = false;
            }
            let line = self.line; let column = self.column;
            let ch = self.peek(0).unwrap();
            if ch == ' ' || ch == '\t' || ch == '\x0c' { self.bump(); continue; }
            if ch == '#' { while !matches!(self.peek(0), Some('\n') | None) { self.bump(); } continue; }
            if ch == '\n' { self.bump(); if self.nesting == 0 { self.emit(DTokenKind::Newline, line, column); self.line_start = true; } continue; }
            if ch == '\\' && self.peek(1) == Some('\n') { self.bump(); self.bump(); continue; }
            if ch == '\'' || ch == '"' { let token = self.string("", line, column)?; self.emit(token, line, column); continue; }
            if ch == '_' || ch.is_alphabetic() {
                let start = self.at; self.bump();
                while self.peek(0).is_some_and(|x| x == '_' || x.is_alphanumeric()) { self.bump(); }
                let name: String = self.source[start..self.at].iter().collect();
                if matches!(self.peek(0), Some('\'') | Some('"')) && name.len() <= 2 && name.chars().all(|x| "rRbBuUfFtT".contains(x)) {
                    let lower = name.to_ascii_lowercase();
                    if !["r", "b", "u", "f", "t", "br", "rb", "fr", "rf", "tr", "rt"].contains(&lower.as_str()) { return Err(self.error("invalid string prefix")); }
                    let token = self.string(&name, line, column)?; self.emit(token, line, column);
                } else { self.emit(DTokenKind::Name(name), line, column); }
                continue;
            }
            if ch.is_ascii_digit() || (ch == '.' && self.peek(1).is_some_and(|x| x.is_ascii_digit())) {
                let start = self.at; self.bump();
                while let Some(next) = self.peek(0) {
                    if next.is_ascii_alphanumeric() || next == '_' || next == '.' { self.bump(); }
                    else if (next == '+' || next == '-') && self.at > start && matches!(self.source[self.at - 1], 'e' | 'E') { self.bump(); }
                    else { break; }
                }
                let number: String = self.source[start..self.at].iter().collect();
                self.emit(DTokenKind::Number(number), line, column); continue;
            }
            let mut symbol = None;
            for candidate in ["**=", "//=", "<<=", ">>=", "...", ":=", "==", "!=", "<=", ">=", "**", "//", "<<", ">>", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "@=", "->"] {
                if candidate.chars().enumerate().all(|(offset, c)| self.peek(offset) == Some(c)) { symbol = Some(candidate.to_owned()); break; }
            }
            let symbol = symbol.unwrap_or_else(|| ch.to_string());
            if !"+-*/%@&|^~<>=:;,.()[]{}!".contains(ch) { return Err(self.error(&format!("invalid character {ch:?}"))); }
            if matches!(ch, '(' | '[' | '{') { self.nesting += 1; }
            else if matches!(ch, ')' | ']' | '}') { if self.nesting == 0 { return Err(self.error("unmatched closing bracket")); } self.nesting -= 1; }
            for _ in symbol.chars() { self.bump(); }
            self.emit(DTokenKind::Symbol(symbol), line, column);
        }
        if self.nesting != 0 { return Err(self.error("unclosed bracket")); }
        if !matches!(self.tokens.last().map(|x| &x.kind), Some(DTokenKind::Newline)) { self.emit(DTokenKind::Newline, self.line, self.column); }
        while self.indents.len() > 1 { self.indents.pop(); self.emit(DTokenKind::Dedent, self.line, self.column); }
        self.emit(DTokenKind::Eof, self.line, self.column); Ok(self.tokens)
    }
}

#[derive(Clone, Debug)]
struct DExpr { kind: DExprKind, line: usize, column: usize }
#[derive(Clone, Debug)]
enum DExprKind {
    Constant(Const), Name(String), List(Vec<DExpr>), Tuple(Vec<DExpr>), Set(Vec<DExpr>), Dict(Vec<(Option<DExpr>, DExpr)>),
    Unary(String, Box<DExpr>), Binary(String, Box<DExpr>, Box<DExpr>), Bool(String, Vec<DExpr>),
    Compare(Box<DExpr>, Vec<(String, DExpr)>), Conditional(Box<DExpr>, Box<DExpr>, Box<DExpr>),
    Attribute(Box<DExpr>, String), Subscript(Box<DExpr>, Box<DExpr>), Slice(Option<Box<DExpr>>, Option<Box<DExpr>>, Option<Box<DExpr>>),
    Call(Box<DExpr>, Vec<DExpr>, Vec<(Option<String>, DExpr)>), Star(Box<DExpr>),
    Named(String, Box<DExpr>), Lambda(DParams, Box<DExpr>), Yield(Option<Box<DExpr>>, bool),
    Joined(Vec<DExpr>), Formatted(Box<DExpr>, i32, Option<Box<DExpr>>),
    Comprehension { kind: String, element: Box<DExpr>, value: Option<Box<DExpr>>, generators: Vec<DGenerator> },
}
#[derive(Clone, Debug)]
struct DGenerator { target: DExpr, iter: DExpr, filters: Vec<DExpr> }
#[derive(Clone, Debug, Default)]
struct DParams { params: Params, defaults: Vec<DExpr>, kwdefaults: Vec<(String, DExpr)> }
#[derive(Clone, Debug)]
struct DStmt { kind: DStmtKind, line: usize, column: usize }
#[derive(Clone, Debug)]
enum DStmtKind {
    Expr(DExpr), Assign(Vec<DExpr>, DExpr), AugAssign(DExpr, String, DExpr), Delete(Vec<DExpr>),
    If(DExpr, Vec<DStmt>, Vec<DStmt>), While(DExpr, Vec<DStmt>, Vec<DStmt>), For(DExpr, DExpr, Vec<DStmt>, Vec<DStmt>),
    Function(String, DParams, Vec<DStmt>, Vec<DExpr>), Class(String, Vec<DExpr>, Vec<(String, DExpr)>, Vec<DStmt>, Vec<DExpr>),
    Return(Option<DExpr>), Break, Continue, Pass, Raise(Option<DExpr>, Option<DExpr>), Assert(DExpr, Option<DExpr>),
    Global(Vec<String>), Nonlocal(Vec<String>),
    Try(Vec<DStmt>, Vec<(Option<DExpr>, Option<String>, Vec<DStmt>)>, Vec<DStmt>, Vec<DStmt>),
    With(Vec<(DExpr, Option<DExpr>)>, Vec<DStmt>),
    Import(Vec<(String, Option<String>)>), ImportFrom(String, Vec<(String, Option<String>)>, usize),
}

struct DParser { tokens: Vec<DToken>, at: usize }
impl DParser {
    fn new(source: &str) -> Result<Self, String> { Ok(Self { tokens: DLexer::new(source).lex()?, at: 0 }) }
    fn token(&self) -> &DToken { &self.tokens[self.at.min(self.tokens.len() - 1)] }
    fn error(&self, message: &str) -> String { format!("SyntaxError: {message} (line {}, column {})", self.token().line, self.token().column + 1) }
    fn is(&self, word: &str) -> bool { matches!(&self.token().kind, DTokenKind::Name(x) | DTokenKind::Symbol(x) if x == word) }
    fn next_is(&self, word: &str) -> bool { self.tokens.get(self.at + 1).is_some_and(|t| matches!(&t.kind, DTokenKind::Name(x) | DTokenKind::Symbol(x) if x == word)) }
    fn eat(&mut self, word: &str) -> bool { if self.is(word) { self.at += 1; true } else { false } }
    fn expect(&mut self, word: &str) -> Result<(), String> { if self.eat(word) { Ok(()) } else { Err(self.error(&format!("expected {word:?}"))) } }
    fn name(&mut self) -> Result<String, String> {
        match self.token().kind.clone() { DTokenKind::Name(name) if !d_reserved(&name) => { self.at += 1; Ok(name) }, _ => Err(self.error("expected an identifier")) }
    }
    fn expr_at(&self, kind: DExprKind, token: &DToken) -> DExpr { DExpr { kind, line: token.line, column: token.column } }
    fn end_simple(&self) -> bool { matches!(self.token().kind, DTokenKind::Newline | DTokenKind::Dedent | DTokenKind::Eof) || self.is(";") }
    fn expression_end(&self) -> bool { self.end_simple() || [")", "]", "}", ":", "="].iter().any(|x| self.is(x)) }
    fn parse(mut self) -> Result<Vec<DStmt>, String> {
        let mut statements = Vec::new();
        while !matches!(self.token().kind, DTokenKind::Eof) {
            if matches!(self.token().kind, DTokenKind::Newline) { self.at += 1; continue; }
            statements.extend(self.statement()?);
        }
        Ok(statements)
    }
    fn suite(&mut self) -> Result<Vec<DStmt>, String> {
        self.expect(":")?;
        if !matches!(self.token().kind, DTokenKind::Newline) { return self.simple_line(); }
        self.at += 1;
        if !matches!(self.token().kind, DTokenKind::Indent) { return Err(self.error("expected an indented block")); }
        self.at += 1; let mut body = Vec::new();
        while !matches!(self.token().kind, DTokenKind::Dedent | DTokenKind::Eof) {
            if matches!(self.token().kind, DTokenKind::Newline) { self.at += 1; continue; }
            body.extend(self.statement()?);
        }
        if !matches!(self.token().kind, DTokenKind::Dedent) { return Err(self.error("expected end of indented block")); }
        self.at += 1; Ok(body)
    }
    fn statement(&mut self) -> Result<Vec<DStmt>, String> {
        let token = self.token().clone();
        let mut decorators = Vec::new();
        while self.eat("@") {
            decorators.push(self.expression()?);
            if !matches!(self.token().kind, DTokenKind::Newline) { return Err(self.error("expected newline after decorator")); }
            self.at += 1;
        }
        let kind = if self.eat("if") { let condition = self.expression()?; let body = self.suite()?; let tail = self.if_tail()?; DStmtKind::If(condition, body, tail) }
        else if self.eat("while") {
            let condition = self.expression()?; let body = self.suite()?;
            let tail = if self.eat("else") { self.suite()? } else { Vec::new() };
            DStmtKind::While(condition, body, tail)
        } else if self.eat("for") {
            let target = self.target_list()?; self.expect("in")?; let iter = self.expression_list()?;
            let body = self.suite()?; let tail = if self.eat("else") { self.suite()? } else { Vec::new() };
            DStmtKind::For(target, iter, body, tail)
        } else if self.eat("def") {
            let name = self.name()?; self.expect("(")?; let params = self.parameters(")")?; self.expect(")")?;
            if self.eat("->") { self.expression()?; }
            DStmtKind::Function(name, params, self.suite()?, decorators.clone())
        } else if self.eat("class") {
            let name = self.name()?; let mut bases = Vec::new(); let mut keywords = Vec::new();
            if self.eat("(") {
                while !self.is(")") {
                    if matches!(self.token().kind, DTokenKind::Name(_)) && self.next_is("=") { let key = self.name()?; self.expect("=")?; keywords.push((key, self.expression()?)); }
                    else { bases.push(self.expression()?); }
                    if !self.eat(",") { break; }
                }
                self.expect(")")?;
            }
            DStmtKind::Class(name, bases, keywords, self.suite()?, decorators.clone())
        } else if self.eat("try") {
            let body = self.suite()?; let mut handlers = Vec::new();
            while self.eat("except") {
                if self.eat("*") { return Err(self.error("except* is not yet supported")); }
                let exception = if self.is(":") { None } else { Some(self.expression()?) };
                let name = if self.eat("as") { Some(self.name()?) } else { None };
                let handler = self.suite()?; handlers.push((exception, name, handler));
            }
            let tail = if self.eat("else") { self.suite()? } else { Vec::new() };
            let finally = if self.eat("finally") { self.suite()? } else { Vec::new() };
            if handlers.is_empty() && finally.is_empty() { return Err(self.error("try requires except or finally")); }
            if handlers.is_empty() && !tail.is_empty() { return Err(self.error("try/else requires except")); }
            for (index, (exception, _, _)) in handlers.iter().enumerate() { if exception.is_none() && index + 1 < handlers.len() { return Err(self.error("default except must be last")); } }
            DStmtKind::Try(body, handlers, tail, finally)
        } else if self.eat("with") {
            let parenthesized = self.eat("("); let mut items = Vec::new();
            loop {
                let value = self.expression()?; let target = if self.eat("as") { Some(self.bit_or()?) } else { None };
                items.push((value, target)); if !self.eat(",") { break; } if parenthesized && self.is(")") { break; }
            }
            if parenthesized { self.expect(")")?; }
            DStmtKind::With(items, self.suite()?)
        } else {
            if !decorators.is_empty() { return Err(self.error("decorator must precede a function or class")); }
            if self.is("async") { return Err(self.error("async statements are not supported by dynamic compilation")); }
            return self.simple_line();
        };
        if !decorators.is_empty() && !matches!(kind, DStmtKind::Function(..) | DStmtKind::Class(..)) { return Err(self.error("decorator must precede a function or class")); }
        Ok(vec![DStmt { kind, line: token.line, column: token.column }])
    }
    fn if_tail(&mut self) -> Result<Vec<DStmt>, String> {
        if self.eat("elif") {
            let token = self.tokens[self.at - 1].clone(); let condition = self.expression()?; let body = self.suite()?; let tail = self.if_tail()?;
            Ok(vec![DStmt { kind: DStmtKind::If(condition, body, tail), line: token.line, column: token.column }])
        } else if self.eat("else") { self.suite() } else { Ok(Vec::new()) }
    }
    fn simple_line(&mut self) -> Result<Vec<DStmt>, String> {
        let mut result = Vec::new();
        loop {
            result.push(self.simple_statement()?);
            if !self.eat(";") || self.end_simple() { break; }
        }
        if matches!(self.token().kind, DTokenKind::Newline) { self.at += 1; }
        else if !matches!(self.token().kind, DTokenKind::Eof | DTokenKind::Dedent) { return Err(self.error("expected newline or semicolon")); }
        Ok(result)
    }
    fn simple_statement(&mut self) -> Result<DStmt, String> {
        let token = self.token().clone();
        let kind = if self.eat("pass") { DStmtKind::Pass }
        else if self.eat("break") { DStmtKind::Break }
        else if self.eat("continue") { DStmtKind::Continue }
        else if self.eat("return") { DStmtKind::Return(if self.end_simple() { None } else { Some(self.expression_list()?) }) }
        else if self.eat("raise") {
            let exception = if self.end_simple() { None } else { Some(self.expression()?) };
            let cause = if self.eat("from") { Some(self.expression()?) } else { None };
            DStmtKind::Raise(exception, cause)
        } else if self.eat("assert") {
            let test = self.expression()?; let message = if self.eat(",") { Some(self.expression()?) } else { None }; DStmtKind::Assert(test, message)
        } else if self.eat("global") || self.eat("nonlocal") {
            let global = matches!(&self.tokens[self.at - 1].kind, DTokenKind::Name(x) if x == "global");
            let mut names = vec![self.name()?]; while self.eat(",") { names.push(self.name()?); }
            if global { DStmtKind::Global(names) } else { DStmtKind::Nonlocal(names) }
        } else if self.eat("del") {
            let target = self.expression_list()?; DStmtKind::Delete(match target.kind { DExprKind::Tuple(items) => items, _ => vec![target] })
        } else if self.eat("import") {
            let mut names = Vec::new();
            loop { let module = self.dotted_name()?; let alias = if self.eat("as") { Some(self.name()?) } else { None }; names.push((module, alias)); if !self.eat(",") { break; } }
            DStmtKind::Import(names)
        } else if self.eat("from") {
            let mut level = 0; while self.eat(".") || self.eat("...") { level += if self.tokens[self.at - 1].kind == DTokenKind::Symbol("...".to_owned()) { 3 } else { 1 }; }
            let module = if self.is("import") { String::new() } else { self.dotted_name()? }; self.expect("import")?;
            let parenthesized = self.eat("("); let mut names = Vec::new();
            if self.eat("*") { names.push(("*".to_owned(), None)); }
            else { loop { let name = self.name()?; let alias = if self.eat("as") { Some(self.name()?) } else { None }; names.push((name, alias)); if !self.eat(",") { break; } if parenthesized && self.is(")") { break; } } }
            if parenthesized { self.expect(")")?; }
            DStmtKind::ImportFrom(module, names, level)
        } else {
            let first = self.expression_list()?;
            if self.eat("=") {
                let mut targets = vec![first]; let mut value = self.expression_list()?;
                while self.eat("=") { targets.push(value); value = self.expression_list()?; }
                DStmtKind::Assign(targets, value)
            } else if self.eat(":") {
                self.expression()?;
                if self.eat("=") { DStmtKind::Assign(vec![first], self.expression_list()?) } else {
                    // Local annotations create a binding for scope analysis even without a value.
                    DStmtKind::Assign(vec![first], DExpr { kind: DExprKind::Name("$unbound_annotation".to_owned()), line: token.line, column: token.column })
                }
            } else if let DTokenKind::Symbol(op) = self.token().kind.clone() {
                if op.ends_with('=') && ["+=", "-=", "*=", "/=", "//=", "%=", "**=", "&=", "|=", "^=", "<<=", ">>=", "@="].contains(&op.as_str()) {
                    self.at += 1; DStmtKind::AugAssign(first, op[..op.len() - 1].to_owned(), self.expression_list()?)
                } else { DStmtKind::Expr(first) }
            } else { DStmtKind::Expr(first) }
        };
        Ok(DStmt { kind, line: token.line, column: token.column })
    }
    fn dotted_name(&mut self) -> Result<String, String> { let mut name = self.name()?; while self.eat(".") { name.push('.'); name.push_str(&self.name()?); } Ok(name) }
    fn expression_list(&mut self) -> Result<DExpr, String> {
        let first = self.star_expression()?;
        if !self.eat(",") { return Ok(first); }
        let token = DToken { kind: DTokenKind::Eof, line: first.line, column: first.column }; let mut values = vec![first];
        while !self.expression_end() && !self.is("in") { values.push(self.star_expression()?); if !self.eat(",") { break; } }
        Ok(self.expr_at(DExprKind::Tuple(values), &token))
    }
    fn target_list(&mut self) -> Result<DExpr, String> {
        let token = self.token().clone(); let first = self.target_atom()?;
        if !self.eat(",") { return Ok(first); } let mut values = vec![first];
        while !self.is("in") { values.push(self.target_atom()?); if !self.eat(",") { break; } }
        Ok(self.expr_at(DExprKind::Tuple(values), &token))
    }
    fn target_atom(&mut self) -> Result<DExpr, String> {
        let token = self.token().clone(); if self.eat("*") { let value = self.target_atom()?; return Ok(self.expr_at(DExprKind::Star(Box::new(value)), &token)); }
        if self.eat("(") || self.eat("[") {
            let close = if matches!(&self.tokens[self.at - 1].kind,DTokenKind::Symbol(s) if s == "(") { ")" } else { "]" };
            let mut items = Vec::new(); while !self.is(close) { items.push(self.target_atom()?); if !self.eat(",") { break; } } self.expect(close)?;
            return Ok(self.expr_at(DExprKind::Tuple(items), &token));
        }
        self.postfix()
    }
    fn star_expression(&mut self) -> Result<DExpr, String> {
        let token = self.token().clone(); if self.eat("*") { let value = self.bit_or()?; Ok(self.expr_at(DExprKind::Star(Box::new(value)), &token)) } else { self.expression() }
    }
    fn expression(&mut self) -> Result<DExpr, String> {
        let token = self.token().clone();
        if self.eat("lambda") { let params = self.parameters(":")?; self.expect(":")?; let body = self.expression()?; return Ok(self.expr_at(DExprKind::Lambda(params, Box::new(body)), &token)); }
        if self.eat("yield") {
            let from = self.eat("from"); let value = if self.expression_end() { None } else { Some(Box::new(self.expression_list()?)) };
            if from && value.is_none() { return Err(self.error("yield from requires an expression")); }
            return Ok(self.expr_at(DExprKind::Yield(value, from), &token));
        }
        let value = self.or_expr()?;
        if self.eat(":=") {
            let name = match value.kind { DExprKind::Name(name) => name, _ => return Err(self.error("assignment expression requires an identifier")) };
            let value = self.expression()?;
            return Ok(self.expr_at(DExprKind::Named(name, Box::new(value)), &token));
        }
        if self.eat("if") { let condition = self.or_expr()?; self.expect("else")?; let otherwise = self.expression()?; return Ok(self.expr_at(DExprKind::Conditional(Box::new(condition), Box::new(value), Box::new(otherwise)), &token)); }
        Ok(value)
    }
    fn or_expr(&mut self) -> Result<DExpr, String> { self.bool_expr("or", Self::and_expr) }
    fn and_expr(&mut self) -> Result<DExpr, String> { self.bool_expr("and", Self::not_expr) }
    fn bool_expr(&mut self, op: &str, next: fn(&mut Self) -> Result<DExpr,String>) -> Result<DExpr,String> {
        let token = self.token().clone(); let first = next(self)?; if !self.eat(op) { return Ok(first); } let mut values = vec![first, next(self)?]; while self.eat(op) { values.push(next(self)?); }
        Ok(self.expr_at(DExprKind::Bool(op.to_owned(), values), &token))
    }
    fn not_expr(&mut self) -> Result<DExpr,String> {
        let token = self.token().clone(); if self.eat("not") { let value = self.not_expr()?; Ok(self.expr_at(DExprKind::Unary("not".to_owned(), Box::new(value)), &token)) } else { self.comparison() }
    }
    fn comparison(&mut self) -> Result<DExpr, String> {
        let token = self.token().clone(); let left = self.bit_or()?; let mut tail = Vec::new();
        loop {
            let op = if self.eat("not") { self.expect("in")?; Some("not in".to_owned()) }
            else if self.eat("is") { Some(if self.eat("not") { "is not" } else { "is" }.to_owned()) }
            else if ["<", ">", "<=", ">=", "==", "!=", "in"].iter().any(|x| self.is(x)) { let op = match self.token().kind.clone() { DTokenKind::Name(x) | DTokenKind::Symbol(x) => x, _ => unreachable!() }; self.at += 1; Some(op) }
            else { None };
            if let Some(op) = op { tail.push((op, self.bit_or()?)); } else { break; }
        }
        if tail.is_empty() { Ok(left) } else { Ok(self.expr_at(DExprKind::Compare(Box::new(left), tail), &token)) }
    }
    fn binary_level(&mut self, ops: &[&str], next: fn(&mut Self) -> Result<DExpr,String>) -> Result<DExpr,String> {
        let token = self.token().clone(); let mut left = next(self)?;
        while ops.iter().any(|x| self.is(x)) { let op = match self.token().kind.clone() { DTokenKind::Symbol(x) => x, _ => unreachable!() }; self.at += 1; let right = next(self)?; left = self.expr_at(DExprKind::Binary(op, Box::new(left), Box::new(right)), &token); }
        Ok(left)
    }
    fn bit_or(&mut self) -> Result<DExpr,String> { self.binary_level(&["|"], Self::bit_xor) }
    fn bit_xor(&mut self) -> Result<DExpr,String> { self.binary_level(&["^"], Self::bit_and) }
    fn bit_and(&mut self) -> Result<DExpr,String> { self.binary_level(&["&"], Self::shift) }
    fn shift(&mut self) -> Result<DExpr,String> { self.binary_level(&["<<", ">>"], Self::sum) }
    fn sum(&mut self) -> Result<DExpr,String> { self.binary_level(&["+", "-"], Self::term) }
    fn term(&mut self) -> Result<DExpr,String> { self.binary_level(&["*", "/", "//", "%", "@"], Self::factor) }
    fn factor(&mut self) -> Result<DExpr,String> {
        let token = self.token().clone(); for op in ["+", "-", "~"] { if self.eat(op) { let value = self.factor()?; return Ok(self.expr_at(DExprKind::Unary(op.to_owned(), Box::new(value)), &token)); } } self.power()
    }
    fn power(&mut self) -> Result<DExpr,String> {
        let token = self.token().clone(); let left = self.postfix()?; if self.eat("**") { let right = self.factor()?; Ok(self.expr_at(DExprKind::Binary("**".to_owned(), Box::new(left), Box::new(right)), &token)) } else { Ok(left) }
    }
    fn postfix(&mut self) -> Result<DExpr,String> {
        let token = self.token().clone(); let mut value = self.atom()?;
        loop {
            if self.eat(".") { let name = self.name()?; value = self.expr_at(DExprKind::Attribute(Box::new(value), name), &token); }
            else if self.eat("(") {
                let mut args = Vec::new(); let mut keywords = Vec::new(); let mut seen_keyword = false;
                while !self.is(")") {
                    if self.eat("**") { keywords.push((None, self.expression()?)); seen_keyword = true; }
                    else if matches!(self.token().kind, DTokenKind::Name(_)) && self.next_is("=") {
                        let name = self.name()?; self.expect("=")?; if keywords.iter().any(|(key,_)| key.as_ref() == Some(&name)) { return Err(self.error("keyword argument repeated")); }
                        keywords.push((Some(name), self.expression()?)); seen_keyword = true;
                    } else {
                        let arg = self.star_expression()?;
                        if seen_keyword && !matches!(arg.kind, DExprKind::Star(_)) { return Err(self.error("positional argument follows keyword argument")); }
                        if self.is("for") { if !args.is_empty() || !keywords.is_empty() { return Err(self.error("generator expression must be parenthesized")); } let generators = self.generators()?; args.push(self.expr_at(DExprKind::Comprehension { kind: "generator".to_owned(), element: Box::new(arg), value: None, generators }, &token)); }
                        else { args.push(arg); }
                    }
                    if !self.eat(",") { break; }
                }
                self.expect(")")?; value = self.expr_at(DExprKind::Call(Box::new(value), args, keywords), &token);
            } else if self.eat("[") {
                let first = self.subscript()?; let mut values = vec![first]; let mut tuple = false;
                while self.eat(",") { tuple = true; if self.is("]") { break; } values.push(self.subscript()?); }
                self.expect("]")?; let subscript = if tuple { self.expr_at(DExprKind::Tuple(values), &token) } else { values.pop().unwrap() };
                value = self.expr_at(DExprKind::Subscript(Box::new(value), Box::new(subscript)), &token);
            } else { break; }
        }
        Ok(value)
    }
    fn subscript(&mut self) -> Result<DExpr,String> {
        let token = self.token().clone(); let lower = if self.is(":") { None } else { Some(Box::new(self.expression()?)) };
        if !self.eat(":") { return lower.map(|x| *x).ok_or_else(|| self.error("expected subscript")); }
        let upper = if self.is(":") || self.is(",") || self.is("]") { None } else { Some(Box::new(self.expression()?)) };
        let step = if self.eat(":") && !self.is(",") && !self.is("]") { Some(Box::new(self.expression()?)) } else { None };
        Ok(self.expr_at(DExprKind::Slice(lower, upper, step), &token))
    }
    fn atom(&mut self) -> Result<DExpr,String> {
        let token = self.token().clone();
        let kind = match token.kind.clone() {
            DTokenKind::Number(number) => { self.at += 1; DExprKind::Constant(d_number(&number).map_err(|m| self.error(&m))?) }
            DTokenKind::String(_) | DTokenKind::Bytes(_) | DTokenKind::FString(_) => {
                let mut values = Vec::new(); let mut plain = String::new(); let mut bytes: Option<Vec<u8>> = None;
                loop {
                    match self.token().kind.clone() {
                        DTokenKind::String(text) => { if bytes.is_some() { return Err(self.error("cannot mix bytes and nonbytes literals")); } plain.push_str(&text); self.at += 1; }
                        DTokenKind::Bytes(text) => { if !plain.is_empty() || !values.is_empty() { return Err(self.error("cannot mix bytes and nonbytes literals")); } bytes.get_or_insert_with(Vec::new).extend(text); self.at += 1; }
                        DTokenKind::FString(text) => {
                            if bytes.is_some() { return Err(self.error("cannot mix bytes and nonbytes literals")); }
                            if !plain.is_empty() { values.push(self.expr_at(DExprKind::Constant(Const::Str(std::mem::take(&mut plain))), &token)); }
                            values.extend(d_fstring(&text, token.line, token.column)?); self.at += 1;
                        }
                        _ => break,
                    }
                }
                if let Some(bytes) = bytes { DExprKind::Constant(Const::Bytes(bytes)) }
                else if values.is_empty() { DExprKind::Constant(Const::Str(plain)) }
                else { if !plain.is_empty() { values.push(self.expr_at(DExprKind::Constant(Const::Str(plain)), &token)); } DExprKind::Joined(values) }
            }
            DTokenKind::Name(name) if name == "None" || name == "True" || name == "False" => { self.at += 1; DExprKind::Constant(match name.as_str() { "None" => Const::None, "True" => Const::Bool(true), _ => Const::Bool(false) }) }
            DTokenKind::Name(name) if !d_reserved(&name) => { self.at += 1; DExprKind::Name(name) }
            DTokenKind::Symbol(symbol) if symbol == "(" => {
                self.at += 1; if self.eat(")") { DExprKind::Tuple(Vec::new()) }
                else {
                    let first = self.star_expression()?;
                    if self.is("for") { let generators = self.generators()?; self.expect(")")?; DExprKind::Comprehension { kind: "generator".to_owned(), element: Box::new(first), value: None, generators } }
                    else if self.eat(",") { let mut values = vec![first]; while !self.is(")") { values.push(self.star_expression()?); if !self.eat(",") { break; } } self.expect(")")?; DExprKind::Tuple(values) }
                    else { self.expect(")")?; return Ok(first); }
                }
            }
            DTokenKind::Symbol(symbol) if symbol == "[" => {
                self.at += 1; if self.eat("]") { DExprKind::List(Vec::new()) }
                else { let first = self.star_expression()?;
                    if self.is("for") { let generators = self.generators()?; self.expect("]")?; DExprKind::Comprehension { kind: "list".to_owned(), element: Box::new(first), value: None, generators } }
                    else { let mut values = vec![first]; while self.eat(",") { if self.is("]") { break; } values.push(self.star_expression()?); } self.expect("]")?; DExprKind::List(values) }
                }
            }
            DTokenKind::Symbol(symbol) if symbol == "{" => {
                self.at += 1; if self.eat("}") { DExprKind::Dict(Vec::new()) }
                else if self.eat("**") {
                    let mut items = vec![(None, self.expression()?)];
                    while self.eat(",") { if self.is("}") { break; } if self.eat("**") { items.push((None,self.expression()?)); } else { let key = self.expression()?; self.expect(":")?; items.push((Some(key), self.expression()?)); } }
                    self.expect("}")?; DExprKind::Dict(items)
                } else { let first = self.star_expression()?;
                    if self.eat(":") { let value = self.expression()?;
                        if self.is("for") { let generators = self.generators()?; self.expect("}")?; DExprKind::Comprehension { kind: "dict".to_owned(), element: Box::new(first), value: Some(Box::new(value)), generators } }
                        else { let mut items = vec![(Some(first), value)]; while self.eat(",") { if self.is("}") { break; } if self.eat("**") { items.push((None,self.expression()?)); } else { let key = self.expression()?; self.expect(":")?; items.push((Some(key),self.expression()?)); } } self.expect("}")?; DExprKind::Dict(items) }
                    } else if self.is("for") { let generators = self.generators()?; self.expect("}")?; DExprKind::Comprehension { kind: "set".to_owned(), element: Box::new(first), value: None, generators } }
                    else { let mut items = vec![first]; while self.eat(",") { if self.is("}") { break; } items.push(self.star_expression()?); } self.expect("}")?; DExprKind::Set(items) }
                }
            }
            DTokenKind::Symbol(symbol) if symbol == "..." => return Err(self.error("Ellipsis is not yet supported by dynamic compilation")),
            _ => return Err(self.error("expected expression")),
        };
        Ok(self.expr_at(kind, &token))
    }
    fn generators(&mut self) -> Result<Vec<DGenerator>,String> {
        let mut generators = Vec::new();
        while self.eat("for") {
            let target = self.target_list()?; self.expect("in")?; let iter = self.or_expr()?; let mut filters = Vec::new();
            while self.eat("if") { filters.push(self.or_expr()?); }
            generators.push(DGenerator { target, iter, filters });
        }
        Ok(generators)
    }
    fn parameters(&mut self, closing: &str) -> Result<DParams,String> {
        let mut params = DParams::default(); let mut keyword_only = false; let mut seen_default = false; let mut seen_slash = false;
        while !self.is(closing) {
            if self.eat("/") {
                if seen_slash || keyword_only || params.params.positional.is_empty() { return Err(self.error("invalid positional-only separator")); }
                params.params.posonly = params.params.positional.len(); seen_slash = true;
            } else if self.eat("**") {
                params.params.kwarg = Some(self.name()?); if closing == ")" && self.eat(":") { self.expression()?; }
                if self.eat(",") && !self.is(closing) { return Err(self.error("arguments cannot follow **kwargs")); }
                break;
            } else if self.eat("*") {
                if keyword_only { return Err(self.error("duplicate * parameter")); } keyword_only = true;
                if !self.is(",") && !self.is(closing) { params.params.vararg = Some(self.name()?); if closing == ")" && self.eat(":") { self.expression()?; } }
            } else {
                let name = self.name()?;
                if params.params.positional.contains(&name) || params.params.kwonly.contains(&name) || params.params.vararg.as_ref() == Some(&name) || params.params.kwarg.as_ref() == Some(&name) { return Err(self.error("duplicate parameter")); }
                if closing == ")" && self.eat(":") { self.expression()?; }
                let default = if self.eat("=") { Some(self.expression()?) } else { None };
                if keyword_only { params.params.kwonly.push(name.clone()); if let Some(default) = default { params.kwdefaults.push((name,default)); } }
                else { params.params.positional.push(name); if let Some(default) = default { seen_default = true; params.defaults.push(default); } else if seen_default { return Err(self.error("nondefault argument follows default argument")); } }
            }
            if !self.eat(",") { break; }
        }
        if keyword_only && params.params.vararg.is_none() && params.params.kwonly.is_empty() { return Err(self.error("named arguments must follow bare *")); }
        Ok(params)
    }
}

fn d_reserved(name: &str) -> bool {
    ["False","None","True","and","as","assert","async","await","break","class","continue","def","del","elif","else","except","finally","for","from","global","if","import","in","is","lambda","nonlocal","not","or","pass","raise","return","try","while","with","yield"].contains(&name)
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

fn d_fstring(text: &str, line: usize, column: usize) -> Result<Vec<DExpr>,String> {
    let chars: Vec<char> = text.chars().collect(); let mut at = 0; let mut literal = String::new(); let mut values = Vec::new();
    let expr = |kind| DExpr { kind, line, column };
    while at < chars.len() {
        if chars[at] == '{' && chars.get(at+1) == Some(&'{') { literal.push('{'); at += 2; continue; }
        if chars[at] == '}' && chars.get(at+1) == Some(&'}') { literal.push('}'); at += 2; continue; }
        if chars[at] == '}' { return Err(format!("SyntaxError: single '}}' in f-string (line {line})")); }
        if chars[at] != '{' { literal.push(chars[at]); at += 1; continue; }
        if !literal.is_empty() { values.push(expr(DExprKind::Constant(Const::Str(std::mem::take(&mut literal))))); }
        at += 1; let start = at; let mut nesting = 0isize; let mut quote = None; let mut escaped = false;
        while at < chars.len() {
            let ch = chars[at];
            if let Some(q) = quote { if escaped { escaped = false; } else if ch == '\\' { escaped = true; } else if ch == q { quote = None; } at += 1; continue; }
            if ch == '\'' || ch == '"' { quote = Some(ch); at += 1; continue; }
            if nesting == 0 && (ch == '}' || ch == ':' || (ch == '!' && chars.get(at+1) != Some(&'='))) { break; }
            if "([{".contains(ch) { nesting += 1; } if ")]}".contains(ch) { nesting -= 1; }
            at += 1;
        }
        let mut source: String = chars[start..at].iter().collect(); let debug = source.trim_end().ends_with('=') && !source.trim_end().ends_with("==");
        if debug { values.push(expr(DExprKind::Constant(Const::Str(source.clone())))); source = source.trim_end().trim_end_matches('=').to_owned(); }
        let mut parser = DParser::new(&source)?; let value = parser.expression_list()?;
        if !matches!(parser.token().kind,DTokenKind::Newline | DTokenKind::Eof) { return Err(parser.error("invalid f-string expression")); }
        let mut conversion = if debug { 'r' as i32 } else { -1 };
        if chars.get(at) == Some(&'!') { at += 1; let ch = *chars.get(at).ok_or_else(|| "SyntaxError: invalid f-string conversion".to_owned())?; if !"sra".contains(ch) { return Err("SyntaxError: invalid f-string conversion".to_owned()); } conversion = ch as i32; at += 1; }
        let spec = if chars.get(at) == Some(&':') {
            at += 1; let start = at; let mut nesting = 0;
            while at < chars.len() { if chars[at] == '}' && nesting == 0 { break; } if chars[at] == '{' { nesting += 1; } else if chars[at] == '}' { nesting -= 1; } at += 1; }
            let raw: String = chars[start..at].iter().collect(); Some(Box::new(expr(DExprKind::Joined(d_fstring(&raw,line,column)?))))
        } else { None };
        if chars.get(at) != Some(&'}') { return Err(format!("SyntaxError: expecting '}}' in f-string (line {line})")); } at += 1;
        values.push(expr(DExprKind::Formatted(Box::new(value), conversion, spec)));
    }
    if !literal.is_empty() { values.push(expr(DExprKind::Constant(Const::Str(literal)))); } Ok(values)
}

#[derive(Default)]
struct DSymbols { locals: Vec<String>, globals: Vec<String>, nonlocals: Vec<String>, uses: Vec<String>, error: Option<String>, generator: bool }
fn d_push_name(names: &mut Vec<String>, name: &str) { if !names.iter().any(|x| x == name) { names.push(name.to_owned()); } }
impl DSymbols {
    fn target(&mut self, expr: &DExpr) {
        match &expr.kind {
            DExprKind::Name(name) => d_push_name(&mut self.locals,name),
            DExprKind::Tuple(values) | DExprKind::List(values) => for value in values { self.target(value); },
            DExprKind::Star(value) => self.target(value),
            DExprKind::Subscript(a,b) => { self.expr(a); self.expr(b); },
            DExprKind::Attribute(a,_) => self.expr(a), _ => (),
        }
    }
    fn expr(&mut self, expr: &DExpr) {
        match &expr.kind {
            DExprKind::Name(name) => d_push_name(&mut self.uses,name),
            DExprKind::Named(name,value) => { d_push_name(&mut self.locals,name); self.expr(value); },
            DExprKind::Yield(value,_) => { self.generator = true; if let Some(value) = value { self.expr(value); } },
            DExprKind::Lambda(params,_) => { for value in &params.defaults { self.expr(value); } for (_,value) in &params.kwdefaults { self.expr(value); } },
            DExprKind::Comprehension { element,value,generators,.. } => {
                // Iteration variables belong to the implicit comprehension function.
                // Named expressions, however, bind in the containing scope.
                if let Some(first) = generators.first() { self.expr(&first.iter); }
                self.comprehension_named(element); if let Some(value) = value { self.comprehension_named(value); }
                for generator in generators { self.comprehension_named(&generator.iter); for value in &generator.filters { self.comprehension_named(value); } }
            }
            DExprKind::List(values) | DExprKind::Tuple(values) | DExprKind::Set(values) | DExprKind::Joined(values) | DExprKind::Bool(_,values) => for value in values { self.expr(value); },
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
        let mut nested = Self::default(); nested.expr(expr);
        for name in nested.locals { d_push_name(&mut self.locals,&name); }
    }
    fn block(&mut self, body: &[DStmt]) { for stmt in body { self.stmt(stmt); } }
    fn stmt(&mut self, stmt: &DStmt) {
        match &stmt.kind {
            DStmtKind::Assign(targets,value) => { self.expr(value); for target in targets { self.target(target); } },
            DStmtKind::AugAssign(target,_,value) => { self.target(target); self.expr(value); },
            DStmtKind::Delete(targets) => for target in targets { self.target(target); },
            DStmtKind::Expr(value) => self.expr(value),
            DStmtKind::If(test,body,tail) | DStmtKind::While(test,body,tail) => { self.expr(test); self.block(body); self.block(tail); },
            DStmtKind::For(target,iter,body,tail) => { self.expr(iter); self.target(target); self.block(body); self.block(tail); },
            DStmtKind::Function(name,params,_,decorators) => {
                d_push_name(&mut self.locals,name); for value in decorators { self.expr(value); }
                for value in &params.defaults { self.expr(value); } for (_,value) in &params.kwdefaults { self.expr(value); }
            }
            DStmtKind::Class(name,bases,keywords,_,decorators) => {
                d_push_name(&mut self.locals,name); for value in decorators { self.expr(value); } for value in bases { self.expr(value); } for (_,value) in keywords { self.expr(value); }
            }
            DStmtKind::Global(names) => for name in names {
                if !self.globals.contains(name) && (self.locals.contains(name) || self.uses.contains(name)) {
                    self.error = Some(format!("SyntaxError: name '{name}' is used prior to global declaration (line {})",stmt.line));
                }
                if self.nonlocals.contains(name) { self.error = Some(format!("SyntaxError: name '{name}' is both nonlocal and global (line {})",stmt.line)); }
                d_push_name(&mut self.globals,name);
            },
            DStmtKind::Nonlocal(names) => for name in names {
                if !self.nonlocals.contains(name) && (self.locals.contains(name) || self.uses.contains(name)) {
                    self.error = Some(format!("SyntaxError: name '{name}' is used prior to nonlocal declaration (line {})",stmt.line));
                }
                if self.globals.contains(name) { self.error = Some(format!("SyntaxError: name '{name}' is both global and nonlocal (line {})",stmt.line)); }
                d_push_name(&mut self.nonlocals,name);
            },
            DStmtKind::Return(value) => if let Some(value) = value { self.expr(value); },
            DStmtKind::Raise(value,cause) => { if let Some(value) = value { self.expr(value); } if let Some(cause) = cause { self.expr(cause); } },
            DStmtKind::Assert(test,message) => { self.expr(test); if let Some(message) = message { self.expr(message); } },
            DStmtKind::Try(body,handlers,tail,finally) => {
                self.block(body); for (exception,name,handler) in handlers { if let Some(exception) = exception { self.expr(exception); } if let Some(name) = name { d_push_name(&mut self.locals,name); } self.block(handler); } self.block(tail); self.block(finally);
            }
            DStmtKind::With(items,body) => { for (value,target) in items { self.expr(value); if let Some(target) = target { self.target(target); } } self.block(body); },
            DStmtKind::Import(names) => for (name,alias) in names { d_push_name(&mut self.locals,alias.as_ref().map(|x| x.as_str()).unwrap_or_else(|| name.split('.').next().unwrap())); },
            DStmtKind::ImportFrom(_,names,_) => for (name,alias) in names { if name != "*" { d_push_name(&mut self.locals,alias.as_ref().unwrap_or(name)); } },
            _ => (),
        }
    }
}

struct DLoop { start: usize, breaks: Vec<usize>, continues: Vec<usize> }
struct DCtx { index: usize, loops: Vec<DLoop>, scopes: Vec<(ScopeKind,Vec<String>)> }
struct DCompiler { codes: Vec<Code>, filename: String, offset: usize, temporary: usize, interactive: bool }
impl DCompiler {
    fn error(&self, line: usize, message: &str) -> String { format!("SyntaxError: {message} ({}:{line})",self.filename) }
    fn temporary(&mut self, ctx: &DCtx) -> String {
        let name = format!("\0dynamic{}",self.temporary); self.temporary += 1;
        self.codes[ctx.index].locals.push(name.clone()); name
    }
    fn emit(&mut self, ctx: &DCtx, op: Op, line: usize, column: usize) -> usize {
        let at = self.codes[ctx.index].ops.len(); self.codes[ctx.index].ops.push(Instr { op,line,column }); at
    }
    fn here(&self, ctx: &DCtx) -> usize { self.codes[ctx.index].ops.len() }
    fn patch(&mut self, ctx: &DCtx, at: usize, target: usize) {
        match &mut self.codes[ctx.index].ops[at].op {
            Op::Jump(t) | Op::JumpFalse(t) | Op::JumpTrue(t) | Op::ForIter(t) | Op::SetupExcept(t) | Op::SetupFinally(t) | Op::Break(t) | Op::Continue(t) => *t = target,
            _ => unreachable!("not a branch instruction"),
        }
    }
    fn code(&mut self, name: &str, kind: ScopeKind, params: &DParams, body: &[DStmt], enclosing: &DCtx) -> Result<usize,String> {
        let mut symbols = DSymbols::default(); symbols.block(body);
        if let Some(error) = symbols.error { return Err(error); }
        for name in params.params.positional.iter().chain(params.params.kwonly.iter()).chain(params.params.vararg.iter()).chain(params.params.kwarg.iter()) {
            if symbols.globals.contains(name) || symbols.nonlocals.contains(name) { return Err(self.error(body.first().map(|x|x.line).unwrap_or(1),"parameter is declared global or nonlocal")); }
            d_push_name(&mut symbols.locals,name);
        }
        for name in &symbols.nonlocals {
            if symbols.globals.contains(name) { return Err(self.error(1,"name is both global and nonlocal")); }
            let found = enclosing.scopes.iter().rev().any(|(kind,names)| (*kind == ScopeKind::Function || *kind == ScopeKind::Comprehension) && names.contains(name));
            if !found { return Err(self.error(1,&format!("no binding for nonlocal '{name}' found"))); }
        }
        symbols.locals.retain(|name| !symbols.globals.contains(name) && !symbols.nonlocals.contains(name));
        if symbols.generator && kind == ScopeKind::Class { return Err(self.error(1,"yield outside function")); }
        let index = self.codes.len();
        self.codes.push(Code { name:name.to_owned(),filename:self.filename.clone(),kind:kind.clone(),locals:symbols.locals.clone(),globals:symbols.globals,nonlocals:symbols.nonlocals,params:params.params.clone(),ops:Vec::new(),is_generator:symbols.generator });
        let mut scopes = enclosing.scopes.clone(); scopes.push((kind,symbols.locals));
        let mut ctx = DCtx { index,loops:Vec::new(),scopes };
        self.block(&mut ctx,body)?;
        self.emit(&ctx,Op::Const(Const::None),body.last().map(|x|x.line).unwrap_or(1),0); self.emit(&ctx,Op::Return,body.last().map(|x|x.line).unwrap_or(1),0);
        Ok(index)
    }
    fn block(&mut self, ctx: &mut DCtx, body: &[DStmt]) -> Result<(),String> { for stmt in body { self.stmt(ctx,stmt)?; } Ok(()) }
    fn stmt(&mut self, ctx: &mut DCtx, stmt: &DStmt) -> Result<(),String> {
        let line = stmt.line; let col = stmt.column;
        match &stmt.kind {
            DStmtKind::Pass | DStmtKind::Global(_) | DStmtKind::Nonlocal(_) => { self.emit(ctx,Op::Nop,line,col); }
            DStmtKind::Expr(value) => { self.expr(ctx,value)?; self.emit(ctx,if self.interactive && ctx.index == 0 { Op::PrintExpr } else { Op::Pop },line,col); }
            DStmtKind::Assign(targets,value) => {
                if matches!(&value.kind,DExprKind::Name(name) if name == "$unbound_annotation") { for target in targets { if !matches!(target.kind,DExprKind::Name(_) | DExprKind::Attribute(..) | DExprKind::Subscript(..)) { return Err(self.error(line,"illegal target for annotation")); } } return Ok(()); }
                self.expr(ctx,value)?;
                for (index,target) in targets.iter().enumerate() { if index + 1 < targets.len() { self.emit(ctx,Op::Dup,line,col); } self.store(ctx,target)?; }
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
                let code = self.code(name,ScopeKind::Function,params,body,ctx)?;
                self.emit(ctx,Op::MakeFunction { code:self.offset+code,defaults:params.defaults.len(),kwdefaults:params.kwdefaults.iter().map(|(name,_)|name.clone()).collect() },line,col);
                for _ in decorators { self.emit(ctx,Op::Call { pos:1,keywords:Vec::new() },line,col); }
                self.emit(ctx,Op::Store(name.clone()),line,col);
            }
            DStmtKind::Class(name,bases,keywords,body,decorators) => {
                for decorator in decorators { self.expr(ctx,decorator)?; } for base in bases { self.expr(ctx,base)?; } for (_,value) in keywords { self.expr(ctx,value)?; }
                let code = self.code(name,ScopeKind::Class,&DParams::default(),body,ctx)?;
                self.emit(ctx,Op::MakeClass { name:name.clone(),code:self.offset+code,bases:bases.len(),keywords:keywords.iter().map(|(name,_)|name.clone()).collect() },line,col);
                for _ in decorators { self.emit(ctx,Op::Call { pos:1,keywords:Vec::new() },line,col); } self.emit(ctx,Op::Store(name.clone()),line,col);
            }
            DStmtKind::Return(value) => {
                if !matches!(self.codes[ctx.index].kind,ScopeKind::Function | ScopeKind::Comprehension) { return Err(self.error(line,"return outside function")); }
                if let Some(value) = value { self.expr(ctx,value)?; } else { self.emit(ctx,Op::Const(Const::None),line,col); } self.emit(ctx,Op::Return,line,col);
            }
            DStmtKind::Raise(value,cause) => {
                if let Some(value) = value { self.expr(ctx,value)?; } if let Some(cause) = cause { self.expr(ctx,cause)?; }
                self.emit(ctx,Op::Raise(if cause.is_some() { 2 } else if value.is_some() { 1 } else { 0 }),line,col);
            }
            DStmtKind::Assert(test,message) => {
                self.expr(ctx,test)?; let end = self.emit(ctx,Op::JumpTrue(0),line,col); self.emit(ctx,Op::Load("AssertionError".to_owned()),line,col);
                if let Some(message) = message { self.expr(ctx,message)?; } self.emit(ctx,Op::Call { pos:if message.is_some(){1}else{0},keywords:Vec::new() },line,col); self.emit(ctx,Op::Raise(1),line,col); self.patch(ctx,end,self.here(ctx));
            }
            DStmtKind::Try(body,handlers,tail,finally) => self.try_statement(ctx,body,handlers,tail,finally,line,col)?,
            DStmtKind::With(items,body) => self.with_statement(ctx,items,body,line,col)?,
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
    fn with_statement(&mut self, ctx: &mut DCtx, items: &[(DExpr,Option<DExpr>)], body: &[DStmt], line: usize, col: usize) -> Result<(),String> {
        if items.is_empty() { return self.block(ctx,body); }
        let (manager,target) = &items[0]; let manager_tmp = self.temporary(ctx); let exit_tmp = self.temporary(ctx); let enter_tmp = self.temporary(ctx); let exceptional_tmp = self.temporary(ctx);
        self.expr(ctx,manager)?; self.emit(ctx,Op::Store(manager_tmp.clone()),line,col);
        self.emit(ctx,Op::Load(manager_tmp.clone()),line,col); self.emit(ctx,Op::GetAttr("__exit__".to_owned()),line,col); self.emit(ctx,Op::Store(exit_tmp.clone()),line,col);
        self.emit(ctx,Op::Load(manager_tmp),line,col); self.emit(ctx,Op::GetAttr("__enter__".to_owned()),line,col); self.emit(ctx,Op::Call { pos:0,keywords:Vec::new() },line,col); self.emit(ctx,Op::Store(enter_tmp.clone()),line,col);
        self.emit(ctx,Op::Const(Const::Bool(false)),line,col); self.emit(ctx,Op::Store(exceptional_tmp.clone()),line,col);
        let final_setup = self.emit(ctx,Op::SetupFinally(0),line,col); let except_setup = self.emit(ctx,Op::SetupExcept(0),line,col);
        if let Some(target) = target { self.emit(ctx,Op::Load(enter_tmp),line,col); self.store(ctx,target)?; }
        self.with_statement(ctx,&items[1..],body,line,col)?;
        self.emit(ctx,Op::PopHandler,line,col); self.emit(ctx,Op::PopHandler,line,col); let normal_final = self.emit(ctx,Op::Jump(0),line,col);
        self.patch(ctx,except_setup,self.here(ctx)); self.emit(ctx,Op::Const(Const::Bool(true)),line,col); self.emit(ctx,Op::Store(exceptional_tmp.clone()),line,col);
        self.emit(ctx,Op::Load(exit_tmp.clone()),line,col); self.emit(ctx,Op::Load("type".to_owned()),line,col); self.emit(ctx,Op::LoadException,line,col); self.emit(ctx,Op::Call { pos:1,keywords:Vec::new() },line,col);
        self.emit(ctx,Op::LoadException,line,col); self.emit(ctx,Op::Const(Const::None),line,col); self.emit(ctx,Op::Call { pos:3,keywords:Vec::new() },line,col);
        let suppressed = self.emit(ctx,Op::JumpTrue(0),line,col); self.emit(ctx,Op::Raise(0),line,col); self.patch(ctx,suppressed,self.here(ctx));
        self.emit(ctx,Op::ClearException,line,col); self.emit(ctx,Op::PopHandler,line,col); let suppress_final = self.emit(ctx,Op::Jump(0),line,col);
        let final_start = self.here(ctx); self.patch(ctx,normal_final,final_start); self.patch(ctx,suppress_final,final_start); self.patch(ctx,final_setup,final_start);
        self.emit(ctx,Op::Load(exceptional_tmp),line,col); let skip = self.emit(ctx,Op::JumpTrue(0),line,col);
        self.emit(ctx,Op::Load(exit_tmp),line,col); for _ in 0..3 { self.emit(ctx,Op::Const(Const::None),line,col); }
        self.emit(ctx,Op::Call { pos:3,keywords:Vec::new() },line,col); self.emit(ctx,Op::Pop,line,col); self.patch(ctx,skip,self.here(ctx)); self.emit(ctx,Op::EndFinally,line,col); Ok(())
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
            DExprKind::Name(name) => { self.emit(ctx,Op::Load(name.clone()),line,col); }
            DExprKind::List(items) | DExprKind::Tuple(items) => {
                let tuple = matches!(expr.kind,DExprKind::Tuple(_)); let unpack = items.iter().any(|x|matches!(x.kind,DExprKind::Star(_)));
                for item in items { if let DExprKind::Star(value) = &item.kind { self.expr(ctx,value)?; } else { self.expr(ctx,item)?; if unpack { self.emit(ctx,Op::BuildTuple(1),line,col); } } }
                let op = match (tuple,unpack) { (false,false)=>Op::BuildList(items.len()),(true,false)=>Op::BuildTuple(items.len()),(false,true)=>Op::BuildListUnpack(items.len()),(true,true)=>Op::BuildTupleUnpack(items.len()) };
                self.emit(ctx,op,line,col);
            }
            DExprKind::Set(items) => {
                let unpack = items.iter().any(|x|matches!(x.kind,DExprKind::Star(_)));
                if unpack { self.emit(ctx,Op::Load("set".to_owned()),line,col); }
                for item in items { if let DExprKind::Star(value) = &item.kind { self.expr(ctx,value)?; } else { self.expr(ctx,item)?; if unpack { self.emit(ctx,Op::BuildTuple(1),line,col); } } }
                if unpack { self.emit(ctx,Op::BuildTupleUnpack(items.len()),line,col); self.emit(ctx,Op::Call { pos:1,keywords:Vec::new() },line,col); } else { self.emit(ctx,Op::BuildSet(items.len()),line,col); }
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
                    for arg in args { if let DExprKind::Star(value) = &arg.kind { self.expr(ctx,value)?; } else { self.expr(ctx,arg)?; self.emit(ctx,Op::BuildTuple(1),line,col); } }
                    self.emit(ctx,Op::BuildTupleUnpack(args.len()),line,col);
                    if !keywords.is_empty() { self.emit(ctx,Op::BuildDict(0),line,col); for (name,value) in keywords { if let Some(name) = name { self.emit(ctx,Op::Const(Const::Str(name.clone())),line,col); self.expr(ctx,value)?; self.emit(ctx,Op::BuildDict(1),line,col); } else { self.expr(ctx,value)?; } self.emit(ctx,Op::Binary("kwargs_merge".to_owned()),line,col); } }
                    self.emit(ctx,Op::CallEx { kwargs:!keywords.is_empty() },line,col);
                }
            }
            DExprKind::Named(name,value) => { self.expr(ctx,value)?; self.emit(ctx,Op::Dup,line,col); self.emit(ctx,Op::Store(name.clone()),line,col); }
            DExprKind::Lambda(params,body) => {
                for value in &params.defaults { self.expr(ctx,value)?; } for (_,value) in &params.kwdefaults { self.expr(ctx,value)?; }
                let stmt = DStmt { kind:DStmtKind::Return(Some(*body.clone())),line,column:col };
                let code = self.code("<lambda>",ScopeKind::Function,params,&[stmt],ctx)?;
                self.emit(ctx,Op::MakeFunction { code:self.offset+code,defaults:params.defaults.len(),kwdefaults:params.kwdefaults.iter().map(|(name,_)|name.clone()).collect() },line,col);
            }
            DExprKind::Yield(value,from) => {
                if !matches!(self.codes[ctx.index].kind,ScopeKind::Function | ScopeKind::Comprehension) { return Err(self.error(line,"yield outside function")); }
                self.codes[ctx.index].is_generator = true;
                if let Some(value) = value { self.expr(ctx,value)?; } else { self.emit(ctx,Op::Const(Const::None),line,col); }
                if *from { self.emit(ctx,Op::GetYieldFromIter,line,col); self.emit(ctx,Op::YieldFrom,line,col); } else { self.emit(ctx,Op::Yield,line,col); }
            }
            DExprKind::Joined(values) => { for value in values { self.expr(ctx,value)?; } self.emit(ctx,Op::BuildString(values.len()),line,col); }
            DExprKind::Formatted(value,conversion,spec) => { self.expr(ctx,value)?; if let Some(spec) = spec { self.expr(ctx,spec)?; } self.emit(ctx,Op::FormatValue { conversion:*conversion,spec:spec.is_some() },line,col); }
            DExprKind::Comprehension { kind,element,value,generators } => self.comprehension(ctx,kind,element,value.as_deref(),generators,line,col)?,
            DExprKind::Star(_) => return Err(self.error(line,"starred expression is not allowed here")),
        }
        Ok(())
    }
    fn comprehension(&mut self, outer: &mut DCtx, kind: &str, element: &DExpr, value: Option<&DExpr>, generators: &[DGenerator], line: usize, col: usize) -> Result<(),String> {
        if generators.is_empty() { return Err(self.error(line,"comprehension requires a generator")); }
        let mut symbols = DSymbols::default();
        for generator in generators { symbols.target(&generator.target); }
        let mut named = DSymbols::default(); named.expr(element); if let Some(value) = value { named.expr(value); } for generator in generators { for value in &generator.filters { named.expr(value); } }
        for name in &named.locals { if symbols.locals.contains(name) { return Err(self.error(line,"assignment expression cannot rebind a comprehension iteration variable")); } }
        symbols.locals.push(".0".to_owned());
        let mut globals = Vec::new(); let mut nonlocals = Vec::new();
        for name in named.locals { if self.codes[outer.index].kind == ScopeKind::Module || self.codes[outer.index].globals.contains(&name) { globals.push(name); } else { nonlocals.push(name); } }
        let index = self.codes.len(); let mut params = Params::default(); params.positional.push(".0".to_owned());
        self.codes.push(Code { name:format!("<{kind}comp>"),filename:self.filename.clone(),kind:ScopeKind::Comprehension,locals:symbols.locals.clone(),globals,nonlocals,params,ops:Vec::new(),is_generator:kind=="generator" });
        let mut scopes = outer.scopes.clone(); scopes.push((ScopeKind::Comprehension,symbols.locals)); let mut ctx = DCtx { index,loops:Vec::new(),scopes };
        let result = if kind == "generator" { None } else { let tmp = self.temporary(&ctx); self.emit(&ctx,match kind { "list"=>Op::BuildList(0),"set"=>Op::BuildSet(0),_=>Op::BuildDict(0) },line,col); self.emit(&ctx,Op::Store(tmp.clone()),line,col); Some(tmp) };
        self.comprehension_loop(&mut ctx,kind,element,value,generators,0,result.as_deref(),line,col)?;
        if let Some(result) = result { self.emit(&ctx,Op::Load(result),line,col); } else { self.emit(&ctx,Op::Const(Const::None),line,col); } self.emit(&ctx,Op::Return,line,col);
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

fn compile_dynamic(source: &str, filename: &str, mode: &str, code_offset: usize) -> Result<Vec<Code>,String> {
    if !["exec","eval","single"].contains(&mode) { return Err("ValueError: compile() mode must be 'exec', 'eval' or 'single'".to_owned()); }
    let body = if mode == "eval" {
        let mut parser = DParser::new(source)?; while matches!(parser.token().kind,DTokenKind::Newline) { parser.at += 1; }
        let value = parser.expression_list()?; while matches!(parser.token().kind,DTokenKind::Newline) { parser.at += 1; }
        if !matches!(parser.token().kind,DTokenKind::Eof) { return Err(parser.error("unexpected token after expression")); }
        vec![DStmt { line:value.line,column:value.column,kind:DStmtKind::Expr(value) }]
    } else { DParser::new(source)?.parse()? };
    if mode == "single" && (body.is_empty() || body.iter().any(|stmt| stmt.line != body[0].line)) { return Err(format!("SyntaxError: multiple statements found while compiling a single statement ({filename}:1)")); }
    let mut symbols = DSymbols::default(); symbols.block(&body);
    if let Some(error) = symbols.error { return Err(error); }
    if !symbols.nonlocals.is_empty() { return Err(format!("SyntaxError: nonlocal declaration not allowed at module level ({filename}:1)")); }
    let code = Code { name:"<module>".to_owned(),filename:filename.to_owned(),kind:ScopeKind::Module,locals:symbols.locals.clone(),globals:symbols.globals,nonlocals:Vec::new(),params:Params::default(),ops:Vec::new(),is_generator:false };
    let mut compiler = DCompiler { codes:vec![code],filename:filename.to_owned(),offset:code_offset,temporary:0,interactive:mode=="single" };
    let mut ctx = DCtx { index:0,loops:Vec::new(),scopes:vec![(ScopeKind::Module,symbols.locals)] };
    if mode == "eval" {
        if let DStmtKind::Expr(value) = &body[0].kind { compiler.expr(&mut ctx,value)?; }
    } else {
        compiler.block(&mut ctx,&body)?;
        compiler.emit(&ctx,Op::Const(Const::None),body.last().map(|x|x.line).unwrap_or(1),0);
    }
    compiler.emit(&ctx,Op::Return,body.last().map(|x|x.line).unwrap_or(1),0); Ok(compiler.codes)
}
