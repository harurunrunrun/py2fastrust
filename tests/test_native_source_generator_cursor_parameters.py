"""CP-first owned cursor arguments, suspension state and real ownership barriers."""
import shutil,unittest
import test_native_class_iterators as iterator_tests

CASES={'shared_list_cursor_frames': 'def pairs(cursor):\n'
                              '    print("start",cursor is saved,id(cursor)==id(saved))\n'
                              '    yield next(cursor)\n'
                              '    print("resume")\n'
                              '    yield next(cursor)\n'
                              'values=[1,2,3,4,5]\n'
                              'saved=iter(values)\n'
                              'first=pairs(saved)\n'
                              'second=pairs(saved)\n'
                              'alias=first\n'
                              'print("created")\n'
                              'values.append(6)\n'
                              'print(next(first),next(second))\n'
                              'print(next(alias),next(second),next(saved))\n',
 'range_cursor_for': 'def squares(cursor):\n'
                     '    print("start")\n'
                     '    for value in cursor:\n'
                     '        yield value*value\n'
                     'cursor=iter(range(5,0,-1))\n'
                     'stream=squares(cursor)\n'
                     'print("created",next(cursor))\n'
                     'print(next(stream),list(stream),next(cursor,99))\n',
 'builtin_map_capture': 'def produce(cursor):\n'
                        '    print("body")\n'
                        '    for value in cursor:\n'
                        '        yield value+10\n'
                        'mapper=int\n'
                        'cursor=map(mapper,["2","3","4","5"])\n'
                        'mapper=str\n'
                        'stream=produce(cursor)\n'
                        'print("created",next(cursor))\n'
                        'print(next(stream),list(stream),next(cursor,None))\n',
 'finite_cursor_parameter': 'def choose(flag):\n'
                            '    return iter([2,4,6]) if flag else iter((7,9,11))\n'
                            'def produce(cursor):\n'
                            '    print("body")\n'
                            '    for value in cursor:\n'
                            '        yield value*3\n'
                            'cursor=choose(int(input()))\n'
                            'stream=produce(cursor)\n'
                            'print("created",next(cursor))\n'
                            'print(next(stream),list(stream),next(cursor,None))\n',
 'defaults_and_argument_effects': 'def mark(label,cursor):\n'
                                  '    print(label)\n'
                                  '    return cursor\n'
                                  'saved=iter([1,2,3,4])\n'
                                  'def produce(cursor=saved):\n'
                                  '    print("body",next(cursor))\n'
                                  '    yield next(cursor)\n'
                                  'saved=iter([7,8,9])\n'
                                  'first=produce()\n'
                                  'second=produce(mark("argument",saved))\n'
                                  'print("created")\n'
                                  'print(next(first),next(second),next(saved))\n',
 'parameter_rebinding': 'def produce(cursor):\n'
                        '    yield next(cursor)\n'
                        '    cursor=iter([99,100])\n'
                        '    yield next(cursor)\n'
                        'cursor=iter(range(1,6))\n'
                        'stream=produce(cursor)\n'
                        'print(next(stream),next(cursor))\n'
                        'print(next(stream),next(cursor),list(stream))\n',
 'creator_environment_retains_cursor': 'def make():\n'
                                       '    original=iter([4,5,6])\n'
                                       '    def produce(cursor):\n'
                                       '        print("same",(lambda:cursor is original)())\n'
                                       '        yield next(cursor)\n'
                                       '        yield next(cursor)\n'
                                       '    return produce(original)\n'
                                       'stream=make()\n'
                                       'print("created")\n'
                                       'print(next(stream),list(stream))\n',
 'cursor_outlives_owner': 'class Owner:\n'
                          '    def __init__(self):\n'
                          '        self.values=[3,7,11]\n'
                          '    def cursor(self):\n'
                          '        return iter(self.values)\n'
                          'def produce(cursor):\n'
                          '    yield next(cursor)\n'
                          '    yield next(cursor)\n'
                          'owner=Owner()\n'
                          'cursor=owner.cursor()\n'
                          'stream=produce(cursor)\n'
                          'del owner\n'
                          'print(next(stream),next(cursor),list(stream))\n',
 'deferred_exhaustion_error': 'def produce(cursor):\n'
                              '    print("body")\n'
                              '    yield next(cursor)\n'
                              'cursor=iter([])\n'
                              'stream=produce(cursor)\n'
                              'print("created")\n'
                              'print(next(stream))\n',
 'real_list_cursor_cycle': 'def produce(cursor):\n'
                           '    yield 0\n'
                           '    next(cursor,None)\n'
                           'values=[]\n'
                           'cursor=iter(values)\n'
                           'stream=produce(cursor)\n'
                           'values.append(stream)\n'
                           'print("created")\n',
 'real_callback_environment_cycle': 'def make():\n'
                                    '    retained=None\n'
                                    '    def produce(cursor):\n'
                                    '        yield 0\n'
                                    '        next(cursor,None)\n'
                                    '    def callback(value):\n'
                                    '        if retained is None:\n'
                                    '            print("empty")\n'
                                    '        return value\n'
                                    '    cursor=map(callback,[2,3])\n'
                                    '    retained=produce(cursor)\n'
                                    '    return retained\n'
                                    'stream=make()\n'
                                    'print("created")\n',
 'acyclic_callback_boundary': 'def make():\n'
                              '    offset=4\n'
                              '    return map(lambda value:value+offset,[1,2])\n'
                              'def produce(cursor):\n'
                              '    yield next(cursor)\n'
                              'stream=produce(make())\n'
                              'print(next(stream))\n',
 'gc_instance_owner_boundary': 'class Node:\n'
                               '    def __init__(self):\n'
                               '        self.next=None\n'
                               'node=Node()\n'
                               'node.next=node\n'
                               'def produce(cursor):\n'
                               '    yield 0\n'
                               '    next(cursor,None)\n'
                               'cursor=iter([node])\n'
                               'stream=produce(cursor)\n'
                               'print("created")\n',
 'returned_captured_alias': 'class Source:\n'
                            '    def __init__(self,cursor):\n'
                            '        self.saved=cursor\n'
                            '    def __iter__(self):\n'
                            '        print("iter")\n'
                            '        return self.saved\n'
                            'saved=iter([3,5,7,9])\n'
                            'source=Source(saved)\n'
                            'def produce():\n'
                            '    for value in source:\n'
                            '        yield value\n'
                            'stream=produce()\n'
                            'print("created",next(saved))\n'
                            'print(next(stream),next(saved),list(stream))\n',
 'returned_global_callback_cycle': 'def callbacks():\n'
                                   '    retained=None\n'
                                   '    def callback(value):\n'
                                   '        if retained is None:\n'
                                   '            print("empty")\n'
                                   '        return value\n'
                                   '    def store(value):\n'
                                   '        nonlocal retained\n'
                                   '        retained=value\n'
                                   '    return callback,store\n'
                                   'callback,store=callbacks()\n'
                                   'saved=map(callback,[1,2])\n'
                                   'class Source:\n'
                                   '    def __iter__(self):\n'
                                   '        return saved\n'
                                   'def produce():\n'
                                   '    for value in Source():\n'
                                   '        yield value\n'
                                   'stream=produce()\n'
                                   'store(stream)\n'
                                   'print("created")\n'}

BOUNDARIES={"real_list_cursor_cycle":"cycle","real_callback_environment_cycle":"cycle","acyclic_callback_boundary":"callable","gc_instance_owner_boundary":"collected class","returned_global_callback_cycle":"cycle"}


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class OwnedGeneratorCursorExecution(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check

    def run_case(self,name):
        for data in (("0\n","1\n")if name=="finite_cursor_parameter"else("",)):
            self.inputs={name:data}
            with self.subTest(name=name,input=data):self.check(name)


for _name in CASES:
    if _name not in BOUNDARIES:
        setattr(OwnedGeneratorCursorExecution,"test_"+_name,lambda self,name=_name:self.run_case(name))


class OwnedGeneratorCursorBoundaries(unittest.TestCase):
    def test_graph_without_actual_registry_cannot_create_a_receipt(self):
        from types import SimpleNamespace
        from py2fastrust.native_source_generator_cursor_ownership import capture
        model=SimpleNamespace()
        capture(model,{})
        self.assertFalse(hasattr(model,'source_generator_cursor_graph'))

    def test_actual_ownership_boundaries_remain_positioned(self):
        from py2fastrust import transpile,TranspileOptions
        for name,detail in BOUNDARIES.items():
            for mode in ("i64","i128","bigint"):
                with self.subTest(name=name,mode=mode):
                    result=transpile(CASES[name],TranspileOptions(integer=mode,filename=name+".py",license="none"))
                    self.assertFalse(result.success)
                    self.assertIsNone(result.rust_source)
                    self.assertTrue(result.diagnostics)
                    self.assertTrue(all(error.code=="E006"and error.line>0 for error in result.diagnostics))
                    self.assertIn(detail,result.diagnostics[0].message)

    def test_unavailable_or_incomplete_graph_metadata_never_authorizes_retention(self):
        from unittest import mock
        from py2fastrust import transpile,TranspileOptions
        import py2fastrust.native_source_generator_cursor_ownership as ownership
        original=ownership.capture
        def replacement(failure):
            def record(model,edges):
                if failure=='missing_receipt':return
                changed={key:set(values)for key,values in edges.items()}
                root=next(key for key in changed if key[0]=='iterator'and model.iterators.records[key[1]].operation=='source_generator')
                cursor=next(key for key in changed[root]if key[0]=='iterator')
                if failure=='missing_cursor':changed.pop(cursor)
                elif failure=='missing_root_edge':changed[root].remove(cursor)
                elif failure=='unknown_empty_node':
                    unknown=('uncertified_owner',1);changed[cursor].add(unknown);changed[unknown]=set()
                elif failure=='raw_cycle':changed[cursor].add(cursor)
                original(model,changed)
            return record
        expected={'missing_receipt':'receipt','missing_cursor':'coverage','missing_root_edge':'coverage','unknown_empty_node':'facet','raw_cycle':'cycle'}
        for failure,detail in expected.items():
            for mode in ('i64','i128','bigint'):
                with self.subTest(failure=failure,mode=mode),mock.patch.object(ownership,'capture',replacement(failure)):
                    result=transpile(CASES['shared_list_cursor_frames'],TranspileOptions(integer=mode,filename='ownership_fact_failure.py',license='none'))
                    self.assertFalse(result.success)
                    self.assertTrue(all(error.code=='E006'and error.line>0 for error in result.diagnostics))
                    self.assertIn(detail,result.diagnostics[0].message)

    def test_hidden_iter_return_is_included_before_receipt_capture(self):
        from unittest import mock
        from py2fastrust import transpile,TranspileOptions
        from py2fastrust.native_types import alternatives
        from py2fastrust.native_classes import shape
        import py2fastrust.native_source_generator_cursor_ownership as ownership
        observed=[];original=ownership.capture
        def record(model,edges):
            for cursor in model.iterators.records:
                if cursor.operation!='source_generator':continue
                plan=cursor.generator_plan
                for key,site in getattr(model.iterators,'source_protocol_sites',{}).items():
                    if key[0]!=plan.index:continue
                    for kind in alternatives(shape(site.callback.result)):
                        if model.iterators.owns(kind):
                            observed.append((('iterator',kind.index),frozenset(edges['iterator',cursor.index])))
            original(model,edges)
        with mock.patch.object(ownership,'capture',record):
            result=transpile(CASES['returned_captured_alias'],TranspileOptions(license='none'))
        self.assertTrue(result.success,result.diagnostics)
        self.assertTrue(observed)
        self.assertTrue(all(returned in edges for returned,edges in observed))


EXTRA={'multiline_callback_error': 'def produce(cursor):\n'
                             '    for value in (\n'
                             '        cursor\n'
                             '    ):\n'
                             '        yield value\n'
                             'cursor=map(int,["3","bad"])\n'
                             'stream=produce(cursor)\n'
                             'print(next(stream))\n'
                             'print(next(stream))\n',
 'real_none_loop': 'def produce(cursor):\n'
                   '    value=None\n'
                   '    for value in cursor:\n'
                   '        yield value\n'
                   '    yield value\n'
                   'cursor=iter([]) if int(input())==0 else iter([3])\n'
                   'stream=produce(cursor)\n'
                   'print("created")\n'
                   'print(list(stream))\n'}


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class OwnedGeneratorCursorExtra(unittest.TestCase):
    cases=EXTRA
    check=iterator_tests.IteratorExecutionTests.check

    def test_multiline_callback_error_keeps_original_expression_line(self):
        self.check("multiline_callback_error")

    def test_real_none_survives_zero_iteration(self):
        for data in ("0\n","1\n"):
            self.inputs={"real_none_loop":data}
            with self.subTest(input=data):self.check("real_none_loop")
