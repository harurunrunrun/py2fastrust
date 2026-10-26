// Public source locations for exceptions and context managers. These records
// expose source metadata; CPython bytecode offsets and live frame internals
// are deliberately outside this runtime's implementation.
impl Runtime {
    fn exception_traceback(&mut self, error: &PyException) -> Value {
        if let Some(value) = error.attributes.get("__traceback__") {
            return value.clone();
        }
        let mut next = Value::None;
        // Error sites are appended as an exception leaves each inner frame.
        // Prepending in that order produces the public outer-to-inner chain.
        for (filename, line, name) in &error.trace {
            let name = match name.as_str() {
                "lambda" => "<lambda>",
                other => other,
            };
            let code = self.obj_value(Object::Record {
                name: "code".into(),
                fields: vec![
                    ("co_filename".into(), Value::Str(filename.clone().into())),
                    ("co_name".into(), Value::Str(name.into())),
                ],
            });
            let frame = self.obj_value(Object::Record {
                name: "frame".into(),
                fields: vec![
                    ("f_code".into(), code),
                    ("f_lineno".into(), Value::Int(Int::from_i128(*line as i128).into())),
                ],
            });
            next = self.obj_value(Object::Record {
                name: "traceback".into(),
                fields: vec![
                    ("tb_lineno".into(), Value::Int(Int::from_i128(*line as i128).into())),
                    ("tb_frame".into(), frame),
                    ("tb_next".into(), next),
                ],
            });
        }
        next
    }
}
