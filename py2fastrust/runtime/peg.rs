// Packrat PEG execution over Python tokens. All continuations, including
// left-recursion growth, live on a heap stack instead of the Rust call stack.
// The grammar tables are generated from CPython's licensed, pinned grammar.
#[derive(Clone, Copy)]
enum PegExpr {
    Choice(&'static [usize]), Sequence(&'static [usize]), Rule(usize),
    Token(&'static str), Literal(&'static str, bool),
    Optional(usize), Repeat(usize, usize), Gather(usize, usize),
    Look(usize, bool), Force(usize), Bind(&'static str, usize), Cut, Fail,
}
struct PegRule {
    name: &'static str, expression: usize, component: usize, recursive: bool,
}
#[derive(Clone, Debug)]
struct PegToken {
    kind: String, text: String, line: usize, column: usize,
}
#[derive(Clone, Debug)]
enum PegNodeKind { Rule(usize), Binding(&'static str), Token(usize) }
#[derive(Clone, Debug)]
struct PegNode { kind: PegNodeKind, start: usize, end: usize, children: Vec<usize> }
#[derive(Debug)]
struct PegTree { nodes: Vec<PegNode>, root: usize }
#[derive(Debug)]
struct PegError { line: usize, column: usize, expected: Vec<&'static str> }
#[derive(Clone)]
struct PegMatched { end: usize, children: Vec<usize>, cut: bool }
impl PegMatched {
    fn empty(position: usize) -> Self { Self { end: position, children: Vec::new(), cut: false } }
}
#[derive(Clone, Copy)]
struct PegFailure { cut: bool, eager: bool }
impl PegFailure { fn ordinary() -> Self { Self { cut: false, eager: false } } }
type PegOutcome = Result<PegMatched, PegFailure>;
struct PegMemo { active: bool, result: PegOutcome }
enum PegStep { Expression(usize, usize), Rule(usize, usize), Result(PegOutcome) }
enum PegContinuation {
    Sequence(&'static [usize], usize, PegMatched),
    Choice(&'static [usize], usize, usize),
    Optional(usize),
    Repeat { expression: usize, minimum: usize, count: usize, matched: PegMatched },
    GatherFirst { separator: usize, body: usize },
    GatherSeparator { separator: usize, body: usize, matched: PegMatched },
    GatherBody { separator: usize, body: usize, matched: PegMatched, delimiter: PegMatched },
    Look { position: usize, positive: bool },
    Bind { name: &'static str, position: usize },
    Force,
    Rule { rule: usize, position: usize, best: Option<PegMatched> },
}
struct PegParser<'a> {
    tokens: &'a [PegToken], nodes: Vec<PegNode>,
    memo: std::collections::HashMap<(usize, usize), PegMemo>,
    farthest: usize, expected: std::collections::BTreeSet<&'static str>, quiet: usize,
}
impl<'a> PegParser<'a> {
    fn new(tokens: &'a [PegToken]) -> Self {
        Self { tokens, nodes: Vec::new(), memo: std::collections::HashMap::new(),
            farthest: 0, expected: std::collections::BTreeSet::new(), quiet: 0 }
    }
    fn fail(&mut self, position: usize, expected: &'static str) -> PegOutcome {
        if self.quiet == 0 {
            if position > self.farthest { self.farthest = position; self.expected.clear(); }
            if position == self.farthest { self.expected.insert(expected); }
        }
        Err(PegFailure::ordinary())
    }
    fn node(&mut self, kind: PegNodeKind, start: usize, matched: PegMatched) -> PegMatched {
        let index = self.nodes.len();
        self.nodes.push(PegNode { kind, start, end: matched.end, children: matched.children });
        PegMatched { end: matched.end, children: vec![index], cut: matched.cut }
    }
    fn terminal(&mut self, position: usize, expected: &'static str, literal: bool) -> PegOutcome {
        let accepted = self.tokens.get(position).is_some_and(|token| {
            if literal { token.text == expected || (expected == "!=" && token.kind == "NOTEQUAL") }
            else { token.kind == expected && !(expected == "NAME" && PEG_HARD_KEYWORDS.contains(&token.text.as_str())) }
        });
        if !accepted { return self.fail(position, expected); }
        Ok(self.node(PegNodeKind::Token(position), position,
                     PegMatched::empty(position + 1)))
    }
    fn run(&mut self, start_rule: usize) -> PegOutcome {
        let mut stack = Vec::<PegContinuation>::new();
        let mut step = PegStep::Rule(start_rule, 0);
        loop {
            step = match step {
                PegStep::Rule(rule, position) => {
                    if let Some(cached) = self.memo.get(&(rule, position)) {
                        PegStep::Result(cached.result.clone())
                    } else {
                        self.memo.insert((rule, position), PegMemo { active: true, result: Err(PegFailure::ordinary()) });
                        stack.push(PegContinuation::Rule { rule, position, best: None });
                        PegStep::Expression(PEG_RULES[rule].expression, position)
                    }
                }
                PegStep::Expression(expression, position) => match PEG_EXPRESSIONS[expression] {
                    PegExpr::Token(name) => PegStep::Result(self.terminal(position, name, false)),
                    PegExpr::Literal(text, _soft) => PegStep::Result(self.terminal(position, text, true)),
                    PegExpr::Rule(rule) => PegStep::Rule(rule, position),
                    PegExpr::Fail => PegStep::Result(Err(PegFailure::ordinary())),
                    PegExpr::Cut => { let mut matched = PegMatched::empty(position); matched.cut = true; PegStep::Result(Ok(matched)) },
                    PegExpr::Sequence(items) => if items.is_empty() {
                        PegStep::Result(Ok(PegMatched::empty(position)))
                    } else {
                        stack.push(PegContinuation::Sequence(items, 0, PegMatched::empty(position)));
                        PegStep::Expression(items[0], position)
                    },
                    PegExpr::Choice(items) => if items.is_empty() {
                        PegStep::Result(Err(PegFailure::ordinary()))
                    } else {
                        stack.push(PegContinuation::Choice(items, 0, position));
                        PegStep::Expression(items[0], position)
                    },
                    PegExpr::Optional(child) => { stack.push(PegContinuation::Optional(position)); PegStep::Expression(child, position) },
                    PegExpr::Repeat(child, minimum) => {
                        stack.push(PegContinuation::Repeat { expression: child, minimum, count: 0, matched: PegMatched::empty(position) });
                        PegStep::Expression(child, position)
                    },
                    PegExpr::Gather(separator, body) => {
                        stack.push(PegContinuation::GatherFirst { separator, body });
                        PegStep::Expression(body, position)
                    },
                    PegExpr::Look(child, positive) => {
                        self.quiet += 1;
                        stack.push(PegContinuation::Look { position, positive });
                        PegStep::Expression(child, position)
                    },
                    PegExpr::Force(child) => { stack.push(PegContinuation::Force); PegStep::Expression(child, position) },
                    PegExpr::Bind(name, child) => { stack.push(PegContinuation::Bind { name, position }); PegStep::Expression(child, position) },
                },
                PegStep::Result(result) => {
                    let continuation = match stack.pop() { Some(value) => value, None => return result };
                    match continuation {
                        PegContinuation::Sequence(items, index, mut matched) => match result {
                            Ok(mut next) => {
                                matched.end = next.end; matched.cut |= next.cut; matched.children.append(&mut next.children);
                                if index + 1 == items.len() { PegStep::Result(Ok(matched)) }
                                else { let position = matched.end; stack.push(PegContinuation::Sequence(items, index + 1, matched)); PegStep::Expression(items[index + 1], position) }
                            },
                            Err(mut error) => { error.cut |= matched.cut; PegStep::Result(Err(error)) },
                        },
                        PegContinuation::Choice(items, index, position) => match result {
                            Err(error) if !error.cut && !error.eager && index + 1 < items.len() => {
                                stack.push(PegContinuation::Choice(items, index + 1, position)); PegStep::Expression(items[index + 1], position)
                            },
                            other => PegStep::Result(other),
                        },
                        PegContinuation::Optional(position) => match result {
                            Err(error) if !error.cut && !error.eager => PegStep::Result(Ok(PegMatched::empty(position))),
                            other => PegStep::Result(other),
                        },
                        PegContinuation::Repeat { expression, minimum, count, mut matched } => match result {
                            Ok(mut next) if next.end > matched.end => {
                                matched.end = next.end; matched.cut |= next.cut; matched.children.append(&mut next.children);
                                let position = matched.end;
                                stack.push(PegContinuation::Repeat { expression, minimum, count: count + 1, matched });
                                PegStep::Expression(expression, position)
                            },
                            Ok(_) if count >= minimum => PegStep::Result(Ok(matched)),
                            Err(error) if !error.cut && !error.eager && count >= minimum => PegStep::Result(Ok(matched)),
                            Ok(_) => PegStep::Result(Err(PegFailure::ordinary())),
                            Err(error) => PegStep::Result(Err(error)),
                        },
                        PegContinuation::GatherFirst { separator, body } => match result {
                            Ok(matched) => { let position = matched.end; stack.push(PegContinuation::GatherSeparator { separator, body, matched }); PegStep::Expression(separator, position) },
                            other => PegStep::Result(other),
                        },
                        PegContinuation::GatherSeparator { separator, body, matched } => match result {
                            Ok(delimiter) => { let position = delimiter.end; stack.push(PegContinuation::GatherBody { separator, body, matched, delimiter }); PegStep::Expression(body, position) },
                            Err(error) if !error.cut && !error.eager => PegStep::Result(Ok(matched)),
                            Err(error) => PegStep::Result(Err(error)),
                        },
                        PegContinuation::GatherBody { separator, body, mut matched, mut delimiter } => match result {
                            Ok(mut next) if next.end > matched.end => {
                                matched.cut |= delimiter.cut | next.cut; matched.end = next.end;
                                matched.children.append(&mut delimiter.children); matched.children.append(&mut next.children);
                                let position = matched.end;
                                stack.push(PegContinuation::GatherSeparator { separator, body, matched });
                                PegStep::Expression(separator, position)
                            },
                            Err(error) if !error.cut && !error.eager => PegStep::Result(Ok(matched)),
                            Err(error) => PegStep::Result(Err(error)),
                            Ok(_) => PegStep::Result(Ok(matched)),
                        },
                        PegContinuation::Look { position, positive } => {
                            self.quiet -= 1;
                            if let Err(error) = result { if error.eager { step = PegStep::Result(Err(error)); continue; } }
                            PegStep::Result(if result.is_ok() == positive { Ok(PegMatched::empty(position)) } else { Err(PegFailure::ordinary()) })
                        },
                        PegContinuation::Force => PegStep::Result(result.map_err(|mut error| { error.eager = true; error })),
                        PegContinuation::Bind { name, position } => PegStep::Result(result.map(|matched| self.node(PegNodeKind::Binding(name), position, matched))),
                        PegContinuation::Rule { rule, position, best } => {
                            if result.as_ref().err().is_some_and(|error| error.eager) {
                                self.memo.insert((rule, position), PegMemo { active: false, result: result.clone() });
                                PegStep::Result(result)
                            } else if let Ok(mut matched) = result {
                                if best.as_ref().is_some_and(|previous| previous.end >= matched.end) {
                                    let final_result = Ok(best.unwrap());
                                    self.memo.insert((rule, position), PegMemo { active: false, result: final_result.clone() });
                                    PegStep::Result(final_result)
                                } else {
                                    matched.cut = false;
                                    let matched = self.node(PegNodeKind::Rule(rule), position, matched);
                                    if PEG_RULES[rule].recursive {
                                        self.memo.insert((rule, position), PegMemo { active: true, result: Ok(matched.clone()) });
                                        // An indirectly recursive peer may have memoized a
                                        // shorter result while this rule still had its old seed.
                                        for &peer in PEG_COMPONENTS[PEG_RULES[rule].component] {
                                            if self.memo.get(&(peer, position)).is_some_and(|entry| !entry.active) { self.memo.remove(&(peer, position)); }
                                        }
                                        stack.push(PegContinuation::Rule { rule, position, best: Some(matched) });
                                        PegStep::Expression(PEG_RULES[rule].expression, position)
                                    } else {
                                        self.memo.insert((rule, position), PegMemo { active: false, result: Ok(matched.clone()) });
                                        PegStep::Result(Ok(matched))
                                    }
                                }
                            } else {
                                let final_result = best.ok_or_else(PegFailure::ordinary);
                                self.memo.insert((rule, position), PegMemo { active: false, result: final_result.clone() });
                                PegStep::Result(final_result)
                            }
                        },
                    }
                },
            };
        }
    }
    fn error(&self) -> PegError {
        let token = self.tokens.get(self.farthest).or_else(|| self.tokens.last());
        PegError { line: token.map(|t| t.line).unwrap_or(1), column: token.map(|t| t.column).unwrap_or(0), expected: self.expected.iter().copied().collect() }
    }
    fn parse(mut self, mode: &str) -> Result<PegTree, PegError> {
        let name = match mode { "exec" => "file", "single" => "interactive", "eval" => "eval", "func_type" => "func_type", _ => return Err(self.error()) };
        let start = PEG_RULES.iter().position(|rule| rule.name == name).unwrap();
        match self.run(start) {
            Ok(matched) if matched.end == self.tokens.len()
                || (mode == "single" && matched.end + 1 == self.tokens.len() && self.tokens[matched.end].kind == "ENDMARKER") =>
                Ok(PegTree { root: matched.children[0], nodes: self.nodes }),
            Ok(matched) => { self.fail(matched.end, "ENDMARKER").ok(); Err(self.error()) },
            Err(_) => Err(self.error()),
        }
    }
}
