"""Captured builtin identities and live module binding presence against CPython."""
import unittest
from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import build_program
from py2fastrust.references import BuiltinIdentity
from py2fastrust.native_classes import Model,shape
import test_native_aot_callables as helpers

CASES={'required_print_shadow': ('write=print\n'
                           "result=write('alias',sep=':',end='|',flush=True)\n"
                           'print(result)\n'
                           'def print(x):\n'
                           ' return x+3\n'
                           'write(print(4))\n',
                           ('',)),
 'capture_abs_then_len': ('callback=abs\n'
                          'def change():\n'
                          ' global callback\n'
                          ' callback=len\n'
                          ' print("change")\n'
                          ' return -3\n'
                          'print(callback(change()),callback([1,2]))\n',
                          ('',)),
 'global_builtin_callee_before_arguments': ('emit=print\n'
                                            'def change():\n'
                                            ' global print\n'
                                            ' print=len\n'
                                            ' emit("change")\n'
                                            ' return "abc"\n'
                                            'print(change())\n'
                                            'emit(print([1,2]))\n'
                                            'del print\n'
                                            'print("restored")\n',
                                            ('',)),
 'builtin_shadow_delete_restore': ('emit=print\n'
                                   'print=7\n'
                                   'emit("shadow",print)\n'
                                   'del print\n'
                                   'print("restored")\n',
                                   ('',)),
 'delete_absent_builtin_raises': ('emit=print\nemit("before")\ndel print\nemit("never")\n', ('',)),
 'local_builtin_parameter': ('def apply(len,value):return len(value)\nprint(apply(abs,-3))\n',
                             ('',)),
 'local_builtin_unbound': ('def run():\n print(len([1,2]))\n len=abs\nrun()\n', ('',)),
 'captured_default_keeps_builtin': ('measure=len\n'
                                    'def apply(value,callback=measure):return callback(value)\n'
                                    'measure=abs\n'
                                    'print(apply([1,2]),apply(-3,measure))\n',
                                    ('',)),
 'builtin_source_definition_default': ('read=len\n'
                                       'def len(value):return 99\n'
                                       'def apply(value,callback=read):return callback(value)\n'
                                       'print(read([1,2]),len([1,2]),apply([1,2,3]))\n',
                                       ('',)),
 'conditional_builtin_and_source': ('def score(value):return 10\n'
                                    'callback=len if int(input()) else score\n'
                                    'print(callback([1,2]))\n',
                                    ('0\n', '1\n')),
 'builtin_collection_references': ('def score(value):return 10\n'
                                   'callbacks=[len,score,len]\n'
                                   'print(callbacks[0]([1,2]),callbacks.pop(1)([1]),callbacks[1]([1,2,3]))\n',
                                   ('',)),
 'builtin_identity': ('saved=len\nprint(saved is len,saved==len,saved is abs,len!=abs)\n', ('',)),
 'primitive_builtin_aliases': ('parse=int\n'
                               'text=str\n'
                               'magnitude=abs\n'
                               'total=sum\n'
                               'small=min\n'
                               'large=max\n'
                               'print(parse("-12"),text(7),magnitude(-4),total([1,2,3]),small(4,2,3),large([4,2,3]))\n',
                               ('',)),
 'input_alias': ('read=input\nprint(read(),read())\n', ('first\nsecond\n', '\nlast\n', 'only\n')),
 'len_error_after_argument_effects': ('def mark(value):\n'
                                      ' print("argument",value)\n'
                                      ' return value\n'
                                      'measure=len\n'
                                      'measure(mark([1]),mark([2]))\n',
                                      ('',)),
 'len_keyword_error_after_effects': ('def mark():\n'
                                     ' print("argument")\n'
                                     ' return [1]\n'
                                     'measure=len\n'
                                     'measure(value=mark())\n',
                                     ('',)),
 'print_separator_error_after_effects': ('def mark(value):\n'
                                         ' print("argument",value)\n'
                                         ' return value\n'
                                         'emit=print\n'
                                         'emit(mark(1),sep=mark(3),end=mark("end"))\n',
                                         ('',)),
 'global_fallback_after_function_delete': ('emit=print\n'
                                           'def print(value):return value+3\n'
                                           'emit(print(4))\n'
                                           'del print\n'
                                           'print("builtin")\n',
                                           ('',)),
 'optional_module_shadow_restores_builtin': ('read=len\n'
                                             'if int(input()):len=abs\n'
                                             'print(len([1,2])if not int(input()) else len(-3))\n',
                                             ('0\n0\n', '1\n1\n')),
 'globals_does_not_insert_builtin': ('saved=print\n'
                                     'print("print"in globals())\n'
                                     'print=7\n'
                                     'saved("print"in globals())\n'
                                     'del print\n'
                                     'saved("print"in globals())\n',
                                     ('',)),
 'capture_function_before_after_override': ('def capture():return print\n'
                                            'saved=capture()\n'
                                            'def print(value):return value+3\n'
                                            'saved(print(4))\n'
                                            'saved(capture()(4))\n',
                                            ('',)),
 'function_delete_reveals_builtin': ('saved=print\n'
                                     'def print(value):return value+3\n'
                                     'def erase():\n'
                                     ' global print\n'
                                     ' del print\n'
                                     'saved(print(4))\n'
                                     'erase()\n'
                                     'print("restored")\n',
                                     ('',)),
 'globals_live_writes': ('g=globals()\n'
                         'def add():\n'
                         ' global VALUE\n'
                         ' VALUE=3\n'
                         'def clear():\n'
                         ' global VALUE\n'
                         ' del VALUE\n'
                         'print("VALUE"in g,g is globals())\n'
                         'add()\n'
                         'print("VALUE"in g)\n'
                         'clear()\n'
                         'print("VALUE"in g)\n',
                         ('',)),
 'globals_relative_length': ('g=globals()\n'
                             'base=len(g)\n'
                             'x=3\n'
                             'print(len(g)-base,"x"in g)\n'
                             'del x\n'
                             'print(len(g)-base,"x"in g)\n',
                             ('',)),
 'globals_comprehension_isolation': ('g=globals()\n'
                                     'values=[hidden for hidden in range(3)]\n'
                                     'print("hidden"in g,"values"in g)\n',
                                     ('',)),
 'globals_unhashable_key': ('print("before")\nprint([]in globals())\n', ('',)),
 'global_transitive_rebinding': ('saved=print\n'
                                 'def outer():inner()\n'
                                 'def inner():\n'
                                 ' global print\n'
                                 ' print=len\n'
                                 'outer()\n'
                                 'saved(print([1,2]))\n'
                                 'del print\n'
                                 'print("restored")\n',
                                 ('',)),
 'builtin_alias_join_keeps_declaration_identity': ('def choose(flag):\n'
                                                   ' if flag:callback=abs\n'
                                                   ' else:callback=list\n'
                                                   ' return callback\n'
                                                   'captured=choose(1)\n'
                                                   'magnitude=abs\n'
                                                   'print(captured is abs,magnitude(-3))\n',
                                                   ('',)),
 'class_shadow_capture': ('class len:\n'
                          ' def __init__(self):print("init")\n'
                          'factory=len\n'
                          'factory()\n'
                          'print("constructed")\n',
                          ('',)),
 'module_shadow_call': ('import sys as len\nlen()\n', ('',)),
 'class_shadow_direct_constructor': ('class len:\n'
                                     ' def __init__(self):self.value=3\n'
                                     'print(len().value)\n',
                                     ('',)),
 'module_shadow_ordinary_reader': ('import sys as len\n'
                                   'read=len.stdin.readline\n'
                                   'print(read().strip())\n',
                                   ('line\n',)),
 'module_shadow_input_attribute': ('import sys as input\nprint(input.stdin.readline().strip())\n',
                                   ('line\n',)),
 'ordinary_module_reader_after_import': ('import sys as len\n'
                                         'class Reader:\n'
                                         ' def take(self):return len.stdin.readline().strip()\n'
                                         'print(Reader().take())\n',
                                         ('line\n',)),
 'ordinary_reader_definition_before_import': ('class Reader:\n'
                                              ' def take(self):return '
                                              'sys.stdin.readline().strip()\n'
                                              'import sys\n'
                                              'print(Reader().take())\n',
                                              ('line\n',)),
 'future_module_default_is_not_prebound': ('class Holder:\n'
                                           ' def get(self,value=sys.stdin.readline()):return '
                                           'value\n'
                                           'import sys\n'
                                           'print(Holder().get())\n',
                                           ('line\n',)),
 'imported_module_rebinding_is_not_local': ('import sys\n'
                                            'class Reader:\n'
                                            ' def change(self):\n'
                                            '  global sys\n'
                                            '  sys=3\n'
                                            ' def take(self):\n'
                                            '  self.change()\n'
                                            '  return sys.stdin.readline()\n'
                                            'print(Reader().take())\n',
                                            ('line\n',))}


CASES.update({'lambda_builtin_default_shadow': ('write=print\n'
                                   'selected=lambda value,callback=len:callback(value)\n'
                                   'len=abs\n'
                                   'write(selected([1,2]),len(-4))\n',
                                   ('',)),
 'lambda_builtin_family': ('callbacks=[lambda value:len(value)+1,len]\n'
                           'print(callbacks[0]([1,2]),callbacks[1]([1,2,3]),callbacks[0] is '
                           'callbacks[1])\n',
                           ('',)),
 'lambda_runtime_binding_error': ('selected=lambda value:value\n'
                                  'callbacks=[selected,len]\n'
                                  'callbacks[0](1,2)\n',
                                  ('',)),
 'len_lambda_type_error': ('selected=lambda value:value\nmeasure=len\nmeasure(selected)\n', ('',)),
 'lexical_builtin_choice': ('def choose(flag):\n'
                            ' def local(value):return len(value)+1\n'
                            ' return local if flag else len\n'
                            'selected=choose(int(input()))\n'
                            'print(selected([1,2]),selected is len)\n',
                            ('0\n', '1\n')),
 'lexical_builtin_default': ('def make(callback=print):\n'
                             ' def emit(value):return callback(value)\n'
                             ' return emit\n'
                             'selected=make()\n'
                             'print(selected(7))\n',
                             ('',)),
 'lexical_builtin_identity': ('def choose():\n'
                              ' def local(value):return value\n'
                              ' return [local,local,len]\n'
                              'callbacks=choose()\n'
                              'print(callbacks[0] is callbacks[1],callbacks[0] is len,callbacks[2] '
                              'is len,callbacks[0](7))\n',
                              ('',)),
 'lexical_globals_visibility': ('def inspect():\n'
                                ' def count():return len(globals())\n'
                                ' return count\n'
                                'selected=inspect()\n'
                                'print("print"in globals())\n'
                                'selected()\n'
                                'print("print"in globals())\n',
                                ('',))})

CASES.update({
    "static_builtin_map": ("convert=int\nprint(list(map(convert,input().split())))\n", ("1 -2 3\n",)),
    "static_builtin_sort_key": ("key=abs\nvalues=[-4,2,-1]\nvalues.sort(key=key)\nprint(values)\n", ("",)),
    "static_builtin_print": ("emit=print\nemit(3)\n", ("",)),
    "static_builtin_len": ("measure=len\nprint(measure([1,2]))\n", ("",)),
})


CASES.update({'lambda_builtin_callee_before_write': ('call=lambda value:value+1\n'
                                        'def replace():\n'
                                        ' global call\n'
                                        ' call=len\n'
                                        ' return 3\n'
                                        'print(call(replace()),call([1,2]))\n',
                                        ('',)),
 'lambda_builtin_local_narrowing': ('def run(flag):\n'
                                    ' selected=lambda value:value+1\n'
                                    ' if flag:selected=len\n'
                                    ' return selected([1,2]) if flag else selected(3)\n'
                                    'print(run(int(input())))\n',
                                    ('0\n', '1\n'))})

class NativeBuiltinCallableTests(unittest.TestCase):
    cases=CASES
    filename="<input>"
    setUpClass=classmethod(helpers.NativeCallableCellTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeCallableCellTests.tearDownClass.__func__)
    exercise=helpers.NativeCallableCellTests.exercise

    def test_original_builtin_and_source_function_shadow_lifetime(self):
        self.exercise("required_print_shadow")

    def test_current_callee_precedes_argument_rebinding(self):
        for name in ("capture_abs_then_len","global_builtin_callee_before_arguments","global_transitive_rebinding"):
            self.exercise(name)

    def test_shadow_deletion_and_absent_module_binding(self):
        for name in ("builtin_shadow_delete_restore","delete_absent_builtin_raises","global_fallback_after_function_delete","function_delete_reveals_builtin"):
            self.exercise(name)

    def test_local_and_parameter_bindings_never_fall_back(self):
        for name in ("local_builtin_parameter","local_builtin_unbound"):
            self.exercise(name)

    def test_defaults_capture_builtin_identity(self):
        for name in ("captured_default_keeps_builtin","builtin_source_definition_default"):
            self.exercise(name)

    def test_collections_conditionals_and_identity(self):
        for name in ("conditional_builtin_and_source","builtin_collection_references","builtin_identity","optional_module_shadow_restores_builtin"):
            self.exercise(name)

    def test_shared_primitive_builtin_adapters(self):
        self.exercise("primitive_builtin_aliases")

    def test_input_alias_line_empty_and_eof(self):
        self.exercise("input_alias")

    def test_invalid_calls_keep_argument_effects_and_messages(self):
        for name in ("len_error_after_argument_effects","len_keyword_error_after_effects","print_separator_error_after_effects"):
            self.exercise(name)

    def test_captured_global_reference_across_function_calls(self):
        self.exercise("capture_function_before_after_override")

    def test_globals_view_observes_real_bindings_without_inserting_builtins(self):
        for name in ("globals_does_not_insert_builtin","globals_live_writes","globals_relative_length","globals_comprehension_isolation","globals_unhashable_key"):
            self.exercise(name)

    def test_local_alias_join_cannot_widen_builtin_declaration(self):
        self.exercise("builtin_alias_join_keeps_declaration_identity")
        source,_=CASES["builtin_alias_join_keeps_declaration_identity"]
        unit=build_program(source,"<input>").main
        model=Model(unit.tree,unit.filename,"i64",unit.native_imports,unit=unit)
        model.run()
        self.assertEqual(shape(model.callable_cells.builtin_cells["abs"]).targets,(BuiltinIdentity("abs"),))
        self.assertEqual(shape(model.callable_cells.builtin_cells["list"]).targets,(BuiltinIdentity("list"),))

    def test_unpruned_builtin_lifetime(self):
        self.exercise("required_print_shadow",prune=False)

    def test_unobserved_builtin_namespace_adds_no_runtime_storage(self):
        source="class Box:\n def add(self,value):return value+1\nprint(Box().add(3))\n"
        result=transpile(source,TranspileOptions(filename="<input>"))
        self.assertTrue(result.success,result.diagnostics)
        for text in ("ClassFunctionRef","ClassGlobalsView","present:","struct ClassGlobals"):
            self.assertNotIn(text,result.rust_source)

    def test_class_constructor_and_module_readers_keep_existing_adapters(self):
        for name in ("class_shadow_direct_constructor","ordinary_module_reader_after_import","ordinary_reader_definition_before_import"):
            self.exercise(name)

    def test_captured_class_shadow_keeps_constructor_dispatch(self):
        self.exercise("class_shadow_capture")

    def test_imported_reference_initialization_and_mutation_fail_closed(self):
        for name,reason in (("future_module_default_is_not_prebound","import binding initialization"),
                            ("imported_module_rebinding_is_not_local","stored imported-reference binding")):
            source,_=CASES[name]
            for mode in ("i64","i128","bigint"):
                with self.subTest(name=name,mode=mode):
                    result=transpile(source,TranspileOptions(integer=mode,filename="<input>"))
                    self.assertFalse(result.success)
                    self.assertIn(reason,result.diagnostics[0].message)

    def test_canonical_member_descriptor_uses_shared_reference_family(self):
        from py2fastrust.native_aot_callables import AotFunctionType,variant,ordered_targets
        from py2fastrust.native_module_calls import BuiltinRef
        from py2fastrust.native_types import reference_cloneable,immutable
        member=BuiltinRef("math","gcd")
        builtin=BuiltinIdentity("len")
        family=AotFunctionType.from_targets((member,7,builtin))
        self.assertEqual(family.definitions,(7,))
        self.assertEqual(family.builtins,(builtin,))
        self.assertEqual(family.members,(member,))
        self.assertEqual(family.targets,ordered_targets((member,builtin,7)))
        self.assertEqual(variant(member),"ClassFunctionRef::M_math_gcd")
        self.assertEqual(family.join(AotFunctionType((8,))).definitions,(7,8))
        self.assertTrue(reference_cloneable(family))
        self.assertFalse(immutable(family))

    def test_builtin_variants_coexist_with_lexical_and_lambda_payloads(self):
        for name in ("lexical_builtin_default","lambda_builtin_family","lambda_builtin_default_shadow","lexical_builtin_choice","len_lambda_type_error","lambda_runtime_binding_error","lexical_builtin_identity","lexical_globals_visibility"):
            self.exercise(name)

    def test_static_builtin_alias_consumers_keep_ordinary_lowering(self):
        for source in ("convert=int\nprint(list(map(convert,input().split())))\n", "key=abs\nvalues=[-4,2,-1]\nvalues.sort(key=key)\nprint(values)\n", "emit=print\nemit(3)\n", "measure=len\nprint(measure([1,2]))\n"):
            for mode in ("i64","i128","bigint"):
                result=transpile(source,TranspileOptions(integer=mode))
                self.assertTrue(result.success,result.diagnostics)
                self.assertNotIn("ClassFunctionRef",result.rust_source)
                self.assertNotIn("class_function_",result.rust_source)

    def test_static_builtin_alias_consumers_execute_without_carriers(self):
        for name in ("static_builtin_map","static_builtin_sort_key","static_builtin_print","static_builtin_len"):
            self.exercise(name)

    def test_unaliased_builtin_calls_keep_existing_direct_adapters(self):
        from py2fastrust.native_frame_selection import select_frames
        for source in ("print(str(),bool(),int())\n", "print(float(3))\n", "print(abs(-3),len([1,2]))\n"):
            unit=build_program(source,"<input>").main
            self.assertFalse(select_frames(unit).required)

    def test_builtin_spelling_is_separate_from_canonical_namespace_key(self):
        from py2fastrust.references import resolve_static_callable,UnknownReference
        class QualifiedName(str):
            python_name="len"
        key=QualifiedName("\0module/len")
        node=__import__("ast").parse("len",mode="eval").body
        options=dict(name_for=lambda node:key,builtin_spelling=lambda name:name.python_name)
        self.assertEqual(resolve_static_callable(node,{},**options),BuiltinIdentity("len"))
        self.assertIsInstance(resolve_static_callable(node,{},global_bound_names={key},**options),UnknownReference)

    def test_source_payload_narrowing_coexists_with_builtin_variants(self):
        for name in ("lambda_builtin_callee_before_write","lambda_builtin_local_narrowing"):
            self.exercise(name)
