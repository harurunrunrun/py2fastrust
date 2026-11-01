"""Native primitive type checks retain captured type identities and ordering."""
import unittest
import test_native_class_iterators as execution


CASES = {
    'primitive_types': '''print(isinstance(3,int),isinstance(True,int),isinstance(3,bool),isinstance(True,bool))
print(isinstance(3,float),isinstance(3.0,float),isinstance('x',str),isinstance(b'x',str))
print(isinstance(None,int),isinstance([1],list),isinstance(range(2),range))
''',
    'parameter_alternatives': '''def check(value):return isinstance(value,int),isinstance(value,list)
print(check(2),check('x'),check(True),check(None),check([1]))
''',
    'type_parameter': '''def check(value,kind):return isinstance(value,kind)
print(check(2,int),check('x',str),check(None,list),check(True,bool))
''',
    'type_tuple': '''print(isinstance(2,(str,int)),isinstance('x',(str,int)))
print(isinstance(None,()),isinstance([1],(str,list)))
''',
    'short_circuit_invalid_type': '''print(isinstance(1,(int,7)))
print('before')
print(isinstance('x',(int,7)))
''',
    'function_is_not_a_type': '''def invalid():return 1
print('before')
print(isinstance(3,invalid))
''',
    'saved_alias': '''check=isinstance
isinstance=7
print(check(True,int),check('x',str))
''',
    'callee_before_arguments': '''check=isinstance
def other(value,kind):return False
def change():
 global check
 check=other
 return 3
print(check(change(),int))
print(check(3,int))
''',
    'object_created_before_type_check': '''class Box:
 def __init__(self):print('created')
print(isinstance(Box(),int))
''',
    'variadic_tuple_is_not_a_list': '''def check(*values):return isinstance(values,list),isinstance(values,int)
print(check(),check(1,2))
''',
    'argument_count_effects': '''def mark(value):print(value);return value
isinstance(mark(1),int,mark(3))
''',
    'keyword_effects': '''def mark(value):print(value);return value
isinstance(object=mark(1),class_or_tuple=int)
''',
}


CASES.update({'container_alias_types': 'mapping_type=dict\n'
                          'sequence_type=tuple\n'
                          'dict=7\n'
                          'tuple=9\n'
                          'print(isinstance({1:2},mapping_type),isinstance((),sequence_type))\n',
 'container_types': 'print(isinstance((),tuple),isinstance([1],tuple),isinstance(tuple([1]),tuple))\n'
                    'print(isinstance({1:2},dict),isinstance({1,2},set),isinstance({},set),isinstance([],dict))\n',
 'iter_identity_no_demand': 'def callback(value):\n'
                            " print('callback',value)\n"
                            ' return value\n'
                            'stream=map(callback,[1])\n'
                            'print(isinstance(iter(stream),map))\n',
 'iterator_types_no_body_execution': 'def callback(value):\n'
                                     " print('callback',value)\n"
                                     ' return value+1\n'
                                     'stream=map(callback,[1])\n'
                                     'print(isinstance(stream,map),isinstance(stream,zip),isinstance(stream,filter))\n'
                                     'print(isinstance(zip([1],[2]),zip),isinstance(filter(callback,[1]),filter))\n',
 'non_type_builtin_after_match': 'print(isinstance([], (list,print)))\n'
                                 "print('before')\n"
                                 'print(isinstance((), (list,print)))\n',
 'valid_type_tuple_before_match': 'print(isinstance(1,(map,zip,filter,enumerate,tuple,dict,set,int)))\n',
 'variadic_type_info': 'def check(value,*classes):return isinstance(value,classes)\n'
                       "print(check(3,int,str),check(None,int,list),check('x',str,bool),check(1))\n"
                       'print(check((),tuple,dict),check({1:2},list,dict),check({1},set))\n'})


class NativeTypeCheckTests(unittest.TestCase):
    cases = CASES
    check = execution.IteratorExecutionTests.check

    def test_containers_and_lazy_iterator_type_identities(self):
        for name in ('container_types', 'iterator_types_no_body_execution', 'valid_type_tuple_before_match', 'variadic_type_info', 'container_alias_types', 'non_type_builtin_after_match', 'iter_identity_no_demand'):
            with self.subTest(name=name):self.check(name)

    def test_primitive_and_finite_type_alternatives(self):
        for name in ('primitive_types', 'parameter_alternatives', 'type_parameter', 'type_tuple'):
            with self.subTest(name=name):self.check(name)

    def test_errors_and_type_tuple_short_circuit(self):
        for name in ('short_circuit_invalid_type', 'function_is_not_a_type', 'argument_count_effects', 'keyword_effects'):
            with self.subTest(name=name):self.check(name)

    def test_aliases_and_creation_order(self):
        for name in ('saved_alias', 'callee_before_arguments', 'object_created_before_type_check', 'variadic_tuple_is_not_a_list'):
            with self.subTest(name=name):self.check(name)


if __name__=='__main__':unittest.main()
