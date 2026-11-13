"""type(value) returns real finite class objects over the typed native ABI."""
import shutil,unittest
import test_native_stdio as stdio_tests
from py2fastrust import transpile,TranspileOptions

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class TypeObjectExecutionTests(unittest.TestCase):
    setUpClass=classmethod(stdio_tests.NativeStdioTests.setUpClass.__func__)
    tearDownClass=classmethod(stdio_tests.NativeStdioTests.tearDownClass.__func__)
    compile=stdio_tests.NativeStdioTests.compile
    differential=stdio_tests.NativeStdioTests.differential

    def test_scalars_and_containers_return_actual_class_singletons(self):
        self.differential('''print(type(7),type(True),type(1.5),type('x'),type(b'x'),type(None))
print(type([1]),type((1,)),type({1:2}),type({1,2}),type(range(3)))
print(type(7)is int,type(True)is bool,type(True)is int,type(7)is bool)
print(type([1])is list,type((1,))is tuple,type({})is dict,type(set())is set)
print(type(1)==int,type(1)!=bool,bool(type(None)))
''',profiles=(False,True))

    def test_module_and_singleton_metatypes_keep_truthful_identity(self):
        self.differential('''import sys
print(type(sys),isinstance(sys,type(sys)),type(type(sys))is type)
print(type(NotImplemented),isinstance(NotImplemented,type(NotImplemented)))
''',profiles=(False,True))

    def test_object_base_and_complex_class_identity(self):
        self.differential('''print(isinstance(1,object),isinstance(None,object),isinstance(type(1),object))
value=(-1)**0.5
print(type(value),type(value)is complex,isinstance(value,object))
print(type(complex)is type,complex.__name__)
''',profiles=(False,True))

    def test_str_repr_and_class_metadata(self):
        self.differential('''kind=type(7)
print(str(kind),repr(kind),kind.__name__,kind.__qualname__,kind.__module__)
print(type(None).__name__,str(type(None)),type(type(None))is type)
print(type.__name__,type(type)is type,str(type))
''',profiles=(False,True))

    def test_alias_defaults_and_returned_constructor_calls(self):
        self.differential('''inspect=type
def query(value,kind=inspect):return kind(value)
def construct(factory,value):return factory(value)
integer=query(7)
text=query('x')
sequence=query([])
print(integer('23'),text(31),sequence((1,2)))
print(construct(integer,'42'),query(False)is bool,query(7)is int)
none=query(None)
print(none(),none is type(None),type(integer)is inspect)
''',profiles=(False,True))

    def test_finite_bool_integer_and_container_alternatives(self):
        self.differential('''flag=int(input())
value=True if flag else 7
kind=type(value)
print(kind,kind is bool,kind is int,kind('1'))
value=[1,2] if flag else (1,2)
kind=type(value)
print(kind,kind is list,kind is tuple)
''',[b'0\n',b'1\n'],profiles=(False,True))

    def test_canonical_builtin_namespace_exports_and_replacement(self):
        self.differential('''import builtins as namespace
from builtins import type as inspect
saved=namespace.type
print(inspect(1)is namespace.int,saved(False)is namespace.bool)
namespace.type=lambda value:'replacement'
print(saved(1)is namespace.int,namespace.type(1),type(1))
''',profiles=(False,True))

    def test_class_constructor_alias_rebinding_preserves_the_initializer_abi(self):
        self.differential('''class Record:
    def __init__(self,value):self.value=value
Saved=Record
first=Saved(2)
Record=int
second=Saved(3)
print(first.value,second.value)
''',profiles=(False,True))

    def test_explicit_unbound_initializer_uses_its_real_finite_receiver_type(self):
        self.differential('''class Record:
    def __init__(self,value):self.value=value
item=Record(4)
print(item.value)
Record.__init__(7,9)
''',profiles=(False,True))

    def test_returned_class_guards_narrow_original_values(self):
        self.differential('''def examine(value):
    integer=type(1)
    if isinstance(value,integer):
        print(value.bit_length())
    else:
        print(value.upper())
examine(7 if int(input()) else 'abc')
''',[b'0\n',b'1\n'],profiles=(False,True))

    def test_source_class_with_a_builtin_spelling_keeps_distinct_identity(self):
        self.differential('''class int: pass
value=int()
print(type(value)is int,type(7)is int,type(value)==type(7))
''',profiles=(False,True))

    def test_returned_builtin_class_is_a_real_default_factory(self):
        self.differential('''from collections import defaultdict
factory=type(0)
counts=defaultdict(factory)
counts[3]+=1
print(counts[3],counts[4],len(counts),counts.default_factory is int)
''',profiles=(False,True))

    def test_type_factory_binding_error_is_deferred_until_the_missing_read(self):
        self.differential('''from collections import defaultdict
values=defaultdict(type)
print('constructed',len(values))
print(values[3])
''',profiles=(False,True))

    def test_operand_effects_execute_once_before_class_observers(self):
        self.differential('''counter=0
def value():
    global counter
    counter+=1
    print('value',counter)
    return 7
print(type(value())is int,counter)
print(type(value()).__name__,counter)
''',profiles=(False,True))

    def test_actual_source_class_reference_survives_public_rebinding(self):
        self.differential('''class Original:
    def __init__(self,x=4):self.x=x
Saved=Original
item=Saved(7)
Original=int
kind=type(item)
print(kind is Saved,kind is Original,kind==Saved)
other=kind(11)
print(other.x,type(other)is kind,type(kind)is type)
''',profiles=(False,True))

    def test_source_class_lookup_uses_definition_holder_and_not_payload_fields(self):
        self.differential('''class Box:
    def __init__(self,x):self.x=x
    def kind(self):return type(self)
obj=Box(9)
print(type(obj)is Box,obj.kind()is Box,type(obj.kind())is type)
print(isinstance(obj,type(obj)),isinstance(Box,type))
''',profiles=(False,True))

    def test_type_and_constructor_names_can_be_shadowed(self):
        self.differential('''saved_type=type
saved_int=int
type=lambda value:13
int=9
print(saved_type(7)is saved_int,saved_type(7)is int,type('x'))
print(saved_type(True)is bool,saved_type(saved_type)is saved_type)
''',profiles=(False,True))

    def test_type_as_a_lazy_callback_does_not_call_or_pull_the_operand_twice(self):
        self.differential('''stream=map(type,[1,False,None])
print(list(stream))
print(list(filter(type,[0,False,None])))
''',profiles=(False,True))

    def test_isinstance_accepts_returned_builtin_classes_and_type_itself(self):
        self.differential('''integer=type(0)
boolean=type(False)
classes=(type([]),type(()))
print(isinstance(True,integer),isinstance(1,boolean),isinstance([],classes))
print(isinstance(int,type),isinstance(type,type),isinstance(type(1),type))
print(isinstance(None,type(None)),isinstance(1,type(None)))
''',profiles=(False,True))

    def test_builtin_function_and_source_function_metatypes(self):
        self.differential('''def callback(x):return x
class Receiver:
    def run(self,x):return x
obj=Receiver()
print(type(callback),type(obj.run),type(len),type(int))
print(type(callback)is type(lambda x:x),type(obj.run)is type(obj.run))
''',profiles=(False,True))

    def test_wrong_argument_shapes_preserve_all_explicit_effects(self):
        for call in ['type()','type(mark(1),mark(2))','type(object=mark(1))','type(mark(1),object=mark(2))']:
            source='''def mark(value):
    print('arg',value)
    return value
'''+call+'\n'
            self.differential(source,profiles=(False,True))

    def test_returned_constructor_binding_errors_preserve_all_arguments(self):
        for call in ['kind(mark(1),mark(2),mark(3))','kind(value=mark(1))']:
            source='''def mark(value):
    print('arg',value)
    return value
kind=type(1)
'''+call+'\n'
            self.differential(source,profiles=(False,True))


class TypeObjectBoundaryTests(unittest.TestCase):
    def test_shared_module_guard_refinement_keeps_its_existing_boundary(self):
        source='''integer=type(1)
value=7 if int(input()) else 'abc'
if isinstance(value,integer):
    print(value.bit_length())
else:
    print(value.upper())
'''
        result=transpile(source,TranspileOptions(filename='shared.py'))
        self.assertFalse(result.success)
        self.assertIn('bit_length',result.diagnostics[0].message)
        self.assertIn('int | str',result.diagnostics[0].message)

    def test_three_argument_dynamic_class_creation_is_specific(self):
        result=transpile("type('New',(),{})\n",TranspileOptions(filename='class.py'))
        self.assertFalse(result.success)
        self.assertIn('three-argument type',result.diagnostics[0].message)
        self.assertIn('dynamic class',result.diagnostics[0].message)
        self.assertEqual(result.diagnostics[0].line,1)

    def test_unrepresented_metatype_has_an_actual_value_and_protocol(self):
        for source,part in [('print(type(iter([1,2])))\n','actual Python class object'),
                            ('kind=type(lambda x:x)\nkind(1)\n','function class'),
                            ('print(type(1).__mro__)\n','__mro__'),('print(id(type(1)))\n','class-object address')]:
            with self.subTest(source=source):
                result=transpile(source,TranspileOptions(filename='meta.py'))
                self.assertFalse(result.success)
                self.assertIn(part,result.diagnostics[0].message)
                self.assertGreater(result.diagnostics[0].line,0)
