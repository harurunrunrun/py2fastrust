"""CP-first dictionary copies preserve aliases and logical cursor history."""
import unittest
import test_native_annotations_assertions as support
from py2fastrust import TranspileOptions,transpile

CASES={'positioned_dense_copy_holes': ('data = {0:0,1:10,2:20,3:30,4:40}\n'
                                 'del data[0]\n'
                                 'copy = data.copy()\n'
                                 'stream = iter(copy)\n'
                                 'print(next(stream))\n'
                                 'del copy[1]\n'
                                 'copy[9] = 90\n'
                                 'print(list(stream),list(data))\n',
                                 ('',)),
 'positioned_sparse_copy': ('data = {key:key for key in range(120)}\n'
                            'for key in range(119):\n'
                            '    del data[key]\n'
                            'copy = data.copy()\n'
                            'stream = iter(copy)\n'
                            'print(next(stream))\n'
                            'print(next(stream,-1),list(data),list(copy))\n',
                            ('',)),
 'bool_int_key_representative': ('data = {True:[1],2:[2],3:[3],4:[4],5:[5]}\n'
                                 'del data[2]\n'
                                 'del data[3]\n'
                                 'copy = data.copy()\n'
                                 'data[1].append(9)\n'
                                 'copy[1] = [7]\n'
                                 'print(list(data),list(copy),data[True],copy[True])\n',
                                 ('',)),
 'counter_constructor_copy': ('from collections import Counter\n'
                              'data = Counter({key:key+1 for key in range(120)})\n'
                              'for key in range(119):\n'
                              '    del data[key]\n'
                              'copy = data.copy()\n'
                              'print(list(copy),copy[119],copy[0],len(data))\n',
                              ('',)),
 'defaultdict_copy_factory_alias': ('from collections import defaultdict\n'
                                    'data = defaultdict(list)\n'
                                    'for key in range(120):\n'
                                    '    data[key].append(key)\n'
                                    'for key in range(119):\n'
                                    '    del data[key]\n'
                                    'copy = data.copy()\n'
                                    'data[119].append(7)\n'
                                    'copy[200].append(8)\n'
                                    'print(list(data),list(copy),data[119],copy[119],copy[200])\n',
                                    ('',)),
 'clear_retained_cursor': ('data = {1:1,2:2,3:3}\n'
                           'stream = iter(data)\n'
                           'print(next(stream))\n'
                           'data.clear()\n'
                           'data[4] = 4\n'
                           'data[5] = 5\n'
                           'data[6] = 6\n'
                           'print(list(stream),data.copy())\n',
                           ('',)),
 'empty_after_deletions': ('data = {key:key for key in range(120)}\n'
                           'for key in range(120):\n'
                           '    del data[key]\n'
                           'print(data.copy(),list(data))\n'
                           'data[700] = 9\n'
                           'print(data.copy())\n',
                           ('',)),
 'original_copy_cost_source': ('n, repetitions = map(int, input().split())\n'
                               'data = {key: key for key in range(n)}\n'
                               'for key in range(n - 1):\n'
                               '    del data[key]\n'
                               'for offset in range(2 * n):\n'
                               '    key = n + offset\n'
                               '    data[key] = offset\n'
                               '    del data[key]\n'
                               'cursor = iter(data)\n'
                               'print(next(cursor))\n'
                               'snapshots = []\n'
                               'checksum = 0\n'
                               'for index in range(repetitions):\n'
                               '    snapshot = data.copy()\n'
                               '    if index % 100 == 0:\n'
                               '        snapshots.append(snapshot)\n'
                               '    checksum += snapshot.popitem()[0]\n'
                               'print(checksum, sum(len(snapshot) for snapshot in snapshots))\n',
                               ('32 9\n', '300 10\n')),
 'ordered_shared_payload_copy': ('class Storage:\n'
                                 '    def __init__(self):\n'
                                 '        self.data = {key:[key] for key in range(120)}\n'
                                 'owner = Storage()\n'
                                 'for key in range(119):\n'
                                 '    del owner.data[key]\n'
                                 'first = owner.data.copy()\n'
                                 'second = owner.data.copy()\n'
                                 'owner.data[119].append(9)\n'
                                 'print(first,second,first[119] is second[119],len(owner.data))\n',
                                 ('',))}
BOUNDARY_CASES={'captured_copy_method': 'data = {key:key for key in range(120)}\n'
                         'clone = data.copy\n'
                         'for key in range(119):\n'
                         '    del data[key]\n'
                         'print(clone(),data)\n',
 'reentrant_read_copy': 'class Item:\n'
                        '    def __repr__(self):\n'
                        "        return 'count='+str(len(data.copy()))\n"
                        'data = {0:Item(),1:Item(),2:Item()}\n'
                        'del data[0]\n'
                        'print(data)\n',
 'ordered_sparse_copy_without_churn': 'class Box:\n'
                                      '    def __init__(self):\n'
                                      '        self.data = {key:key*3 for key in range(120)}\n'
                                      'box = Box()\n'
                                      'for key in range(119):\n'
                                      '    del box.data[key]\n'
                                      'row = [7]\n'
                                      'box.data[119] = row\n'
                                      'first = box.data.copy()\n'
                                      'second = box.data.copy()\n'
                                      'row.append(8)\n'
                                      'print(first,second,first[119] is '
                                      'second[119],len(box.data))\n'}

class DictionaryCopyCompactionBoundaryTests(unittest.TestCase):
    def test_existing_captured_copy_and_container_display_boundaries(self):
        for name,source in BOUNDARY_CASES.items():
            line,needle={'captured_copy_method':(2,'copy'),'reentrant_read_copy':(6,'source __repr__'),'ordered_sparse_copy_without_churn':(12,"'is'")}[name]
            for integer in ('i64','i128','bigint'):
                with self.subTest(name=name,integer=integer):
                    result=transpile(source,TranspileOptions(integer=integer))
                    self.assertFalse(result.success)
                    self.assertTrue(any(item.code=='E006'and item.line==line and needle in item.message
                                        for item in result.diagnostics),result.diagnostics)


class DictionaryCopyCompactionExecutionTests(unittest.TestCase):
    pass

def _case(name):
    def test(self):support.AnnotationAndAssertionExecutionTests.compare(self,*CASES[name])
    return test
for _name in CASES:setattr(DictionaryCopyCompactionExecutionTests,'test_'+_name,_case(_name))

if __name__=='__main__':unittest.main()
