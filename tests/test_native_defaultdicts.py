"""Captured defaultdict factories share the typed dictionary ownership model."""
import shutil
import unittest
from unittest.mock import patch

from py2fastrust import transpile
from py2fastrust.frontend import build_program
from py2fastrust.native_module_capabilities import needs_linked_members
from tests import test_native_module_linking as linked_helpers


class DefaultDictCapabilityTests(unittest.TestCase):
    def test_canonical_constructor_selection_never_enters_legacy_codegen(self):
        source='import collections as library\nmake=library.defaultdict\nd=make(int)\nd[1]+=1\nprint(d[1])\n'
        self.assertTrue(needs_linked_members(build_program(source,'main.py')))
        with patch('py2fastrust.codegen.generate',side_effect=AssertionError('legacy generation entered')):
            result=transpile(source)
        self.assertTrue(result.success,result.diagnostics)
        self.assertEqual(result.backend,'native')

    def test_recursive_ownership_has_a_positioned_cycle_diagnostic(self):
        sources=['from collections import defaultdict\ndef build():\n d=defaultdict(lambda:d)\n return d\nx=build()\n', "from collections import defaultdict\nd=defaultdict(list)\nd['self']=d\n"]
        for source in sources:
            with self.subTest(source=source):
                result=transpile(source)
                self.assertFalse(result.success)
                self.assertEqual(result.diagnostics[0].code,'E006')
                self.assertGreater(result.diagnostics[0].line,0)
                self.assertIn('cycl',result.diagnostics[0].message.lower())


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class DefaultDictExecutionTests(unittest.TestCase):
    exercise=linked_helpers.NativeLinkedModuleTests.exercise

    def test_list_grouping(self):
        self.exercise({'main.py':"from collections import defaultdict\nd=defaultdict(list)\nfor key,value in [('a',3),('b',7),('a',5)]:d[key].append(value)\nprint(dict(d),d['a'],d['a'] is d['b'],d.default_factory is list)\n"})

    def test_int_frequencies(self):
        self.exercise({'main.py':"from collections import defaultdict\nd=defaultdict(int)\nfor word in ['cat','owl','cat','cat','dog']:d[word]+=1\nprint(dict(d),d['missing'],len(d),d.default_factory is int)\n"})

    def test_set_grouping(self):
        self.exercise({'main.py':'from collections import defaultdict\nd=defaultdict(set)\nfor key,value in [(1,3),(2,7),(1,3),(1,5)]:d[key].add(value)\nprint(sorted(d[1]),sorted(d[2]),d[1] is d[2],d.default_factory is set)\n'})

    def test_get_setdefault_do_not_call_factory(self):
        self.exercise({'main.py':"from collections import defaultdict\ncalls=[]\ndef make():\n calls.append(1)\n return []\nd=defaultdict(make)\nprint(d.get('x'),d.get('x',[8]),'x' in d,len(d),calls)\na=d.setdefault('x',[3])\na.append(4)\nprint(d['x'],d.setdefault('x',[9]),calls,len(d))\nprint(d['y'],calls,len(d))\n"})

    def test_captured_compiled_factory(self):
        self.exercise({'main.py':"from collections import defaultdict\ndef build(start):\n value=[start]\n def make():\n  value[0]+=1\n  return [value[0]]\n return defaultdict(make)\nd=build(10)\nprint(d['a'],d['a'],d['b'],dict(d))\n"})

    def test_shared_factory_result(self):
        self.exercise({'main.py':"from collections import defaultdict\nshared=[]\nd=defaultdict(lambda:shared)\nd['a'].append(5)\nprint(d['b'],d['a'] is d['b'],shared)\n"})

    def test_bound_factory_method(self):
        self.exercise({'main.py':'from collections import defaultdict\nclass Factory:\n def __init__(self):self.count=0\n def make(self):\n  self.count+=1\n  return [self.count]\nf=Factory()\nd=defaultdict(f.make)\nprint(d[1],d[2],d[1],f.count)\n'})

    def test_factory_preinserts_same_numeric_key(self):
        self.exercise({'main.py':'from collections import defaultdict\ndef make():\n d[1]=[7]\n return [8]\nd=defaultdict(make)\nprint(d[True],dict(d),list(d))\n'})

    def test_factory_exception(self):
        self.exercise({'main.py':"from collections import defaultdict\ndef make():\n print('factory')\n return 1//0\nd=defaultdict(make)\nprint(d['x'])\n"})

    def test_factory_requires_argument(self):
        self.exercise({'main.py':"from collections import defaultdict\ndef make(value):return value\nd=defaultdict(make)\nprint(d['x'])\n"})

    def test_none_factory_missing(self):
        self.exercise({'main.py':"from collections import defaultdict\nd=defaultdict(None,{'a':3})\nprint(d['a'],d.get('missing'),len(d))\nprint(d['missing'])\n"})

    def test_factory_mutation(self):
        self.exercise({'main.py':"from collections import defaultdict\nd=defaultdict(list)\nd['a'].append(3)\nd.default_factory=lambda:[9]\nprint(d['a'],d['b'],dict(d))\nd.default_factory=None\nprint(d.get('c'),len(d),d.default_factory is None)\nprint(d['c'])\n"})

    def test_factory_changes_itself(self):
        self.exercise({'main.py':'from collections import defaultdict\ndef make():\n d.default_factory=None\n return [7]\nd=defaultdict(make)\nprint(d[1],d.default_factory is None)\nprint(d[2])\n'})

    def test_factory_becomes_noncallable(self):
        self.exercise({'main.py':"from collections import defaultdict\nd=defaultdict(list)\nd['a'].append(1)\nd.default_factory=3\nprint(d['a'],d.default_factory)\nprint(d['b'])\n"})

    def test_copy_preserves_factory_and_values(self):
        self.exercise({'main.py':"from collections import defaultdict\nd=defaultdict(list)\nd['a'].append(1)\ne=d.copy()\ne['a'].append(2)\ne['b'].append(3)\nprint(dict(d),dict(e),d['a'] is e['a'],e.default_factory is d.default_factory)\nd.default_factory=None\nprint(e['c'],e.default_factory is list)\n"})

    def test_constructor_initial_mapping_and_keywords(self):
        self.exercise({'main.py':"from collections import defaultdict\nd=defaultdict(int,{'a':2},b=3)\nprint(dict(d),d['z'],d.default_factory is int)\n"})

    def test_live_views_and_iterator_size_error(self):
        self.exercise({'main.py':"from collections import defaultdict\nd=defaultdict(int,{'a':1})\nitems=d.items()\nd['b']+=2\nprint(list(items))\nfor key in d:\n print(key)\n d['c']+=1\n"})

    def test_zero_reads_before_key_argument_rebind(self):
        self.exercise({'main.py':"from collections import defaultdict\nd=defaultdict(int)\nold=d\ndef key():\n global d\n d=defaultdict(int)\n return 'a'\nold[key()]+=3\nprint(dict(old),dict(d))\n"})

    def test_factory_type_identity(self):
        self.exercise({'main.py':'from collections import defaultdict\nd=defaultdict(list)\nprint(isinstance(d,defaultdict),isinstance(d,dict),isinstance({},defaultdict))\nprint(d.default_factory is list,isinstance(d.default_factory,list))\n'})

    def test_builtin_factory_representation(self):
        self.exercise({'main.py':"from collections import defaultdict\nprint(defaultdict(),defaultdict(None),defaultdict(list),defaultdict(int,{'a':3}))\n"})

    def test_factory_mutates_cached_scalar_field(self):
        self.exercise({'main.py':'from collections import defaultdict\nclass Box:\n def __init__(self):self.count=0\nbox=Box()\ndef make():\n box.count+=1\n return 0\nd=defaultdict(make)\nanswer=0\nfor i in range(4):\n answer+=box.count\n value=d[i]\n answer+=box.count\nprint(answer,box.count,dict(d))\n'})

    def test_factory_rebinds_cached_list_field(self):
        self.exercise({'main.py':'from collections import defaultdict\nclass Box:\n def __init__(self):\n  self.count=0\n  self.values=[]\nbox=Box()\ndef make():\n box.count+=1\n box.values=[box.count]\n return 0\nd=defaultdict(make)\nanswer=[]\nfor i in range(3):\n before=box.values\n value=d[i]\n answer.append(box.values[0])\nprint(answer,box.values)\n'})

    def test_first_iterable_before_later_keyword(self):
        self.exercise({'main.py':"from collections import defaultdict\nrows=[('a',[1])]\ndef source():\n print('source')\n return rows\ndef later():\n print('later')\n rows.append(('b',[2]))\n return [9]\nd=defaultdict(list,((key,value)for key,value in source()),z=later())\nprint(dict(d))\n"})

    def test_initial_generator_body_error(self):
        self.exercise({'main.py':'from collections import defaultdict\nd=defaultdict(int,((value,10//value)for value in [2,0]))\nprint(dict(d))\n'})

    def test_user_collections_module_keeps_its_own_export(self):
        self.exercise({'main.py':'from collections import defaultdict\nprint(defaultdict(int))\n',
                       'collections.py':'def defaultdict(factory):return factory()+7\n'})

    def test_captured_vector_factory(self):
        self.exercise({'main.py':"from collections import defaultdict\ndef solve(width):\n buckets=defaultdict(lambda:[0]*width)\n for group,column in [('a',0),('b',2),('a',0),('a',1)]:\n  buckets[group][column]+=1\n print(dict(buckets),buckets['a'] is buckets['b'])\nsolve(3)\n"})

    def test_nested_defaultdict_factory(self):
        self.exercise({'main.py':'from collections import defaultdict\nd=defaultdict(lambda:defaultdict(int))\nfor a,b in [(1,2),(1,2),(2,1),(1,3)]:d[a][b]+=1\nprint(d[1][2],d[2][1],len(d),dict(d[1]),dict(d[2]))\n'})

    def test_builtin_dict_factory(self):
        self.exercise({'main.py':"from collections import defaultdict\nd=defaultdict(dict)\nd[1]['x']=7\nd[2]['x']=9\nprint(dict(d),d[1] is d[2],d.default_factory is dict)\n"})

    def test_coordinate_tuple_keys(self):
        self.exercise({'main.py':'from collections import defaultdict\nd=defaultdict(int)\nfor x,y in [(1,2),(1,2),(2,1),(0,0)]:d[(x,y)]+=1\nprint(sorted(d.items()),d[(4,5)],len(d))\n'})

    def test_unhashable_before_factory_call(self):
        self.exercise({'main.py':"from collections import defaultdict\ndef make():\n print('factory must not run')\n return 7\nd=defaultdict(make)\nprint(d[[]])\n"})

    def test_invalid_constructor_factory(self):
        self.exercise({'main.py':"from collections import defaultdict\ndef later():\n print('later')\n return {'x':3}\nd=defaultdict(7,later())\nprint(d)\n"})
