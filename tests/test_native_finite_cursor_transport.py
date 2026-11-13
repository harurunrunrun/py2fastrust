"""CP-first finite existing-cursor alternatives preserve state and identity."""
import shutil,unittest
import test_native_class_iterators as iterator_tests

CASES={'conditional_returns': 'def choose(flag):\n'
                        '    if flag:\n'
                        '        return iter([2,4,6])\n'
                        '    return iter((7,9))\n'
                        'cursor=choose(int(input()))\n'
                        'alias=cursor\n'
                        'print(next(cursor),list(alias),next(cursor,100))\n',
 'branch_state_and_live_list': 'left=[3,5]\n'
                               'right=[10,20,30]\n'
                               'a=iter(left)\n'
                               'b=iter(right)\n'
                               'print(next(a),next(b))\n'
                               'if int(input()):\n'
                               '    cursor=a\n'
                               'else:\n'
                               '    cursor=b\n'
                               'left.append(7)\n'
                               'right.append(40)\n'
                               'alias=cursor\n'
                               'print(next(cursor),list(alias),list(a),list(b))\n',
 'parameter_alias_identity': 'def take(cursor):\n'
                             '    alias=iter(cursor)\n'
                             '    print(alias is cursor,id(alias)==id(cursor))\n'
                             '    print(next(alias),next(cursor,99))\n'
                             '    return alias\n'
                             'flag=int(input())\n'
                             'cursor=iter([8,6,4]) if flag else iter((1,2,3))\n'
                             'other=take(cursor)\n'
                             'print(other is cursor,list(other),next(cursor,55))\n',
 'heterogeneous_elements': 'def choose(flag):\n'
                           '    if flag:\n'
                           '        return iter([1,2])\n'
                           '    return iter(["north","south"])\n'
                           'cursor=choose(int(input()))\n'
                           'print(next(cursor),list(cursor),next(cursor,None))\n',
 'nested_consumers': 'def choose(flag):\n'
                     '    if flag:\n'
                     '        return iter([0,1,2,3])\n'
                     '    return iter((4,0,5))\n'
                     'def double(value):\n'
                     '    print("double",value)\n'
                     '    return 2*value\n'
                     'cursor=choose(int(input()))\n'
                     'mapped=map(double,cursor)\n'
                     'print("created")\n'
                     'print(list(enumerate(filter(None,mapped),10)),next(cursor,-1))\n',
 'for_and_comprehension': 'a=iter([2,4,6,8])\n'
                          'b=iter((1,3,5,7))\n'
                          'cursor=a if int(input()) else b\n'
                          'for value in cursor:\n'
                          '    print(value)\n'
                          '    if value>=3:\n'
                          '        break\n'
                          'print([value+1 for value in cursor],list(a),list(b))\n',
 'hint_after_iterator': 'def choose(flag):\n'
                        '    return iter([4,5,6]) if flag else iter((7,8,9))\n'
                        'cursor=choose(int(input()))\n'
                        'class Source:\n'
                        '    def __iter__(self):\n'
                        '        print("iter")\n'
                        '        return cursor\n'
                        '    def __len__(self):\n'
                        '        print("len",next(cursor))\n'
                        '        return 1\n'
                        'values=[0]\n'
                        'values.extend(Source())\n'
                        'print(values,next(cursor,-1))\n',
 'generator_late_binding': 'value=3\n'
                           'def ascending():\n'
                           '    print("start A")\n'
                           '    yield value\n'
                           '    yield value+1\n'
                           'def descending():\n'
                           '    print("start B")\n'
                           '    yield value\n'
                           '    yield value-1\n'
                           'cursor=ascending() if int(input()) else descending()\n'
                           'alias=iter(cursor)\n'
                           'print(type(cursor) is type(alias),cursor is alias)\n'
                           'value=10\n'
                           'print(next(alias))\n'
                           'value=20\n'
                           'print(list(cursor))\n',
 'callback_error_order': 'def convert(value):\n'
                         '    print("convert",value)\n'
                         '    return 12//value\n'
                         'def choose(flag):\n'
                         '    if flag:\n'
                         '        return map(convert,[2,0,3])\n'
                         '    return map(convert,(4,0,5))\n'
                         'cursor=choose(int(input()))\n'
                         'print("created")\n'
                         'print(next(cursor))\n'
                         'print(list(cursor))\n',
 'shared_row_elements': 'row=[1]\n'
                        'left=iter([row,row])\n'
                        'right=iter((row,row))\n'
                        'cursor=left if int(input()) else right\n'
                        'first=next(cursor)\n'
                        'first.append(8)\n'
                        'rest=list(cursor)\n'
                        'rest[0].append(9)\n'
                        'print(row,first,rest,first is rest[0])\n',
 'default_shared_cursor': 'left=iter([1,2,3])\n'
                          'right=iter((4,5,6))\n'
                          'cursor=left if int(input()) else right\n'
                          'def consume(iterator=cursor):\n'
                          '    return next(iterator,99)\n'
                          'cursor=iter([100])\n'
                          'print(consume(),consume(),consume(),consume(),list(cursor))\n',
 'zip_and_any': 'def choose(flag):\n'
                '    return iter([0,0,5,6]) if flag else iter((0,7,8))\n'
                'cursor=choose(int(input()))\n'
                'print(any(cursor))\n'
                'print(list(zip(cursor,[10,11,12])),list(cursor))\n'}


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class FiniteCursorTransport(unittest.TestCase):
    check=iterator_tests.IteratorExecutionTests.check
    cases=CASES

    def run_case(self,name):
        for data in ("0\n","1\n"):
            self.inputs={name:data}
            with self.subTest(name=name,input=data):self.check(name)


for _name in CASES:
    setattr(FiniteCursorTransport,"test_"+_name,lambda self,name=_name:self.run_case(name))


PROVIDERS={'itertools_sequence_providers': 'from itertools import chain,pairwise,islice\n'
                                 'def choose(flag):\n'
                                 '    return iter([1,2,3,4]) if flag else iter((5,6,7))\n'
                                 'flag=int(input())\n'
                                 'cursor=choose(flag)\n'
                                 'combined=chain(cursor,[9])\n'
                                 'print(next(combined),list(combined),list(cursor))\n'
                                 'print(list(pairwise(choose(flag))))\n'
                                 'print(list(islice(choose(flag),1,3)))\n',
 'accumulate_provider': 'from itertools import accumulate\n'
                        'def choose(flag):\n'
                        '    return iter([1,2,3]) if flag else iter((4,5))\n'
                        'cursor=choose(int(input()))\n'
                        'prefixes=accumulate(cursor)\n'
                        'print(next(prefixes),list(prefixes),list(cursor))\n',
 'product_provider': 'from itertools import product\n'
                     'def choose(flag):\n'
                     '    return iter([2,3]) if flag else iter((4,5,6))\n'
                     'cursor=choose(int(input()))\n'
                     'values=product(cursor,[0,1])\n'
                     'print(list(cursor))\n'
                     'print(next(values),list(values))\n',
 'source_generator_for': 'def choose(flag):\n'
                         '    return iter([2,4]) if flag else iter((7,9))\n'
                         'def doubled(cursor):\n'
                         '    for value in cursor:\n'
                         '        yield value*2\n'
                         'cursor=choose(int(input()))\n'
                         'stream=doubled(cursor)\n'
                         'print("created")\n'
                         'print(next(stream),list(stream),list(cursor))\n',
 'retained_expression_outer': 'def choose(flag):\n'
                              '    return iter([3,4]) if flag else iter((8,9,10))\n'
                              'cursor=choose(int(input()))\n'
                              'stream=(value+10 for value in cursor)\n'
                              'print(next(cursor))\n'
                              'print(next(stream),list(stream),list(cursor))\n',
 'alternative_callback_writes': 'value=0\n'
                                'def first(item):\n'
                                '    global value\n'
                                '    value="first"\n'
                                '    print("first",item)\n'
                                '    return item+1\n'
                                'def second(item):\n'
                                '    global value\n'
                                '    value=22\n'
                                '    print("second",item)\n'
                                '    return item+2\n'
                                'a=map(first,[1,2])\n'
                                'b=map(second,(3,4))\n'
                                'cursor=a if int(input()) else b\n'
                                'for item in cursor:\n'
                                '    print(item,value)\n'
                                'print(list(a),list(b),value)\n',
 'callback_stop_recovery': 'def convert(value):\n'
                           '    print("convert",value)\n'
                           '    if value==2:\n'
                           '        raise StopIteration("pause")\n'
                           '    return value\n'
                           'a=map(convert,[1,2,3])\n'
                           'b=map(convert,(4,2,5))\n'
                           'cursor=a if int(input()) else b\n'
                           'for value in cursor:\n'
                           '    print("value",value)\n'
                           'print("later",next(cursor,99),next(cursor,77))\n',
 'empty_cursor_default_effects': 'def choose(flag):\n'
                                 '    return iter([]) if flag else iter([7])\n'
                                 'def default():\n'
                                 '    print("default")\n'
                                 '    return 99\n'
                                 'cursor=choose(int(input()))\n'
                                 'print(next(cursor,default()),next(cursor,default()),list(cursor))\n',
 'callback_for_error_frames': 'def convert(value):\n'
                              '    print("convert",value)\n'
                              '    return 20//value\n'
                              'a=map(convert,[2,0,3])\n'
                              'b=map(convert,(4,0,5))\n'
                              'cursor=a if int(input()) else b\n'
                              'for value in cursor:\n'
                              '    print("value",value)\n'}


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class FiniteCursorProviders(unittest.TestCase):
    check=iterator_tests.IteratorExecutionTests.check
    run_case=FiniteCursorTransport.run_case
    cases=PROVIDERS

    def test_source_generator_iterator_parameter_boundary(self):
        from py2fastrust import transpile,TranspileOptions
        source=PROVIDERS['source_generator_for']
        for mode in ('i64','i128','bigint'):
            converted=transpile(source,TranspileOptions(integer=mode,filename='generator_cursor_boundary.py',license='none'))
            self.assertFalse(converted.success)
            self.assertEqual(converted.diagnostics[0].code,'E006')
            self.assertEqual(converted.diagnostics[0].line,3)
            self.assertIn('owned source generator frame payload',converted.diagnostics[0].message)


for _name in PROVIDERS:
    if _name!='source_generator_for':
        setattr(FiniteCursorProviders,"test_"+_name,lambda self,name=_name:self.run_case(name))


class FiniteCursorFacts(unittest.TestCase):
    def test_transport_requires_every_actual_registry_member(self):
        import ast
        from types import SimpleNamespace
        from py2fastrust.native_class_iterators import Iterators
        from py2fastrust.native_finite_cursors import members
        from py2fastrust.native_types import UnionType
        plan=SimpleNamespace(index=0);registry=Iterators(SimpleNamespace())
        first=registry._record(plan,ast.Constant(1),'source')
        second=registry._record(plan,ast.Constant(2),'source')
        foreign_registry=Iterators(SimpleNamespace())
        foreign=foreign_registry._record(plan,ast.Constant(3),'source')
        valid=UnionType((first.kind,second.kind))
        self.assertEqual(members(registry,valid),valid.alternatives)
        self.assertFalse(members(registry,UnionType((second.kind,foreign.kind))))
        self.assertFalse(members(registry,UnionType((first.kind,'int'))))
        self.assertFalse(members(registry,first.kind))

    def test_element_alternatives_retain_producer_cells_and_allocations(self):
        import ast
        from types import SimpleNamespace
        from py2fastrust.native_class_iterators import Iterators
        from py2fastrust.native_classes import Cell,shape
        from py2fastrust.native_types import UnionType,ListType
        plan=SimpleNamespace(index=0);registry=Iterators(SimpleNamespace())
        first=registry._record(plan,ast.Constant(1),'source')
        second=registry._record(plan,ast.Constant(2),'source')
        left=Cell('list',(Cell('int'),),list_origins=frozenset({'left'}))
        right=Cell('list',(Cell('str'),),list_origins=frozenset({'right'}))
        first.element=left;second.element=right
        item=registry.item(UnionType((first.kind,second.kind)))
        self.assertIs(item.args[0],left);self.assertIs(item.args[1],right)
        self.assertIsNot(left.root(),right.root())
        self.assertEqual((shape(left),shape(right)),(ListType('int'),ListType('str')))
        self.assertEqual((left.list_origins,right.list_origins),(frozenset({'left'}),frozenset({'right'})))
