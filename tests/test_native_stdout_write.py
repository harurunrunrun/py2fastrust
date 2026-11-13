"""Canonical standard-output writes preserve real callable identity and order."""
import unittest

from py2fastrust import TranspileOptions, transpile
import test_native_annotations_assertions as support
import test_native_class_iterators as iterator_support


CASES = {
    'text_count_empty_and_print_order': '''import sys
print('start', end=':')
print(sys.stdout.write('ab\\n'))
print(sys.stdout.write(''))
sys.stdout.write('tail')
print(':end')
''',
    'stream_and_method_aliases': '''from sys import stdout as output
send = output.write
flush = output.flush
print(send('left'))
print(flush())
print(send('right\\n'))
''',
    'callable_parameter_and_callback': '''import sys
def send(writer, value):
    return writer(value)
print(send(sys.stdout.write, 'xy'))
print(list(map(sys.stdout.write, ('a', '', 'bc'))))
''',
    'argument_effects_precede_write': '''import sys
def argument():
    print('argument')
    return 'payload'
print('result', sys.stdout.write(argument()))
''',
    'nested_write_argument_and_flush': '''import sys
def argument():
    count = sys.stdout.write('inner:')
    sys.stdout.flush()
    return str(count)
count = sys.stdout.write(argument())
print(':', count)
''',
    'finite_text_or_number': '''import sys
def choose(flag):
    if flag:
        return 'accepted'
    return 12
print('before')
print(sys.stdout.write(choose(int(input()))))
''',
    'arity_after_all_argument_effects': '''import sys
def argument(value):
    print('argument', value)
    return value
sys.stdout.write(argument('first'), argument('second'))
''',
    'keyword_after_argument_effect': '''import sys
def argument():
    print('argument')
    return 'payload'
sys.stdout.write(text=argument())
''',
    'missing_argument': '''import sys
print('before')
sys.stdout.write()
''',
    'nontext_does_not_call_str': '''import sys
class Message:
    def __str__(self):
        print('unexpected str')
        return 'message'
print('before')
sys.stdout.write(Message())
''',
    'bytes_are_not_text': '''import sys
print('before')
sys.stdout.write(b'abc')
''',
    'flush_argument_effect_and_arity': '''import sys
def argument():
    print('argument')
    return 1
sys.stdout.flush(argument())
''',
    'shadowed_module_and_custom_writer': '''import sys
class Output:
    def write(self, text):
        print('custom', text)
        return 17
sys = Output()
print(sys.write('payload'))
''',
    'reader_and_writer_aliases_share_buffers': '''import sys
read = sys.stdin.readline
write = sys.stdout.write
line = read()
print(write(line), write('!'))
''',
    'no_normal_argument_keeps_earlier_output': '''import sys
def fail():
    print('argument')
    return 1 // 0
print('before')
sys.stdout.write(fail())
''',
    'canonical_and_user_write_are_distinct': '''from sys import stdout
class Sink:
    def write(self, value):
        print('custom', value)
        return 31
print(Sink().write('message'), stdout.write('native:'))
''',
    'saved_alias_before_scalar_rebind': '''from sys import stdout
write = stdout.write
saved = write
write = 19
print(saved('saved:'), write)
''',
    'module_stream_and_closure_aliases': '''import sys as system
module = system
output = module.stdout
def create():
    writer = output.write
    def send(value):
        return writer(value)
    return send
send = create()
print(send('closure:'))
''',
    'starred_argument_and_keyword_binding_order': '''import sys
def positional():
    print('positional')
    return ('x',)
def keyword():
    print('keyword')
    return 'y'
sys.stdout.write(text=keyword(), *positional())
''',
    'flush_keyword_effect': '''import sys
def argument():
    print('argument')
    return 1
sys.stdout.flush(extra=argument())
''',
    'stream_is_not_text': '''from sys import stdout
stdout.write(stdout)
''',
    'method_is_not_text': '''import sys
sys.stdout.write(sys.stdout.write)
''',
}

UNICODE = '''import sys
write = sys.stdout.write
print(write('é日😀\\n'))
print(write('e\\u0301'))
print(write(''))
'''

BOUNDARIES = {
    'replacement': ('import sys\nsys.stdout = None\nsys.stdout.write("x")\n', 'replacement streams'),
    'binary_buffer': ('import sys\nsys.stdout.buffer.write(b"x")\n', 'binary'),
    'encoding_reconfiguration': ('import sys\nsys.stdout.reconfigure(encoding="ascii")\n', 'reconfigure'),
}


class StdoutWriteExecutionTests(unittest.TestCase):
    pass


class StdoutWriteBoundaryTests(unittest.TestCase):
    def test_imported_module_rebinding_retains_its_existing_boundary(self):
        for mode in ('i64', 'i128', 'bigint'):
            converted = transpile(CASES['shadowed_module_and_custom_writer'], TranspileOptions(integer=mode))
            self.assertFalse(converted.success)
            self.assertTrue(any(item.code == 'E006' and item.line == 6
                                and 'imported reference' in item.message for item in converted.diagnostics),
                            converted.diagnostics)

    def test_unimplemented_stream_protocols_are_named(self):
        for name, (source, reason) in BOUNDARIES.items():
            for mode in ('i64', 'i128', 'bigint'):
                with self.subTest(name=name, mode=mode):
                    converted = transpile(source, TranspileOptions(integer=mode))
                    self.assertFalse(converted.success)
                    self.assertTrue(any(item.code == 'E006' and item.line > 0 and reason in item.message
                                        for item in converted.diagnostics), converted.diagnostics)

    def test_unicode_counts_characters(self):
        self.cases = {'unicode_stdout_character_count': UNICODE}
        iterator_support.IteratorExecutionTests.check(self, 'unicode_stdout_character_count')


def _case(name):
    def test(self):
        inputs = ('0\n', '1\n') if name == 'finite_text_or_number' else ('line\\n\n',) if name == 'reader_and_writer_aliases_share_buffers' else ('',)
        support.AnnotationAndAssertionExecutionTests.compare(self, CASES[name], inputs)
    return test


for _name in CASES:
    if _name != 'shadowed_module_and_custom_writer':
        setattr(StdoutWriteExecutionTests, 'test_' + _name, _case(_name))


if __name__ == '__main__':
    unittest.main()
