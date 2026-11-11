"""Fresh word consumers retain binding, conversion and target effect order."""
import ast
import shutil
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions
from py2fastrust import native_integer_word_maps as words
import test_native_class_iterators as support


def program(assignment,text='"1 2 3 4"',result='head,tail',method='split()',prefix=''):
 return prefix+'class Reader:\n def run(self,text):\n  '+assignment+'=map(int,text.'+method+')\n  return '+result+'\nprint(Reader().run('+text+'))\n'


CASES={
 'prefix':program('head,*tail'),
 'suffix':program('*body,last',result='body,last'),
 'both':program('head,*middle,last',result='head,middle,last'),
 'empty':program('*tail,',text='""',result='tail'),
 'empty_middle':program('head,*middle,last',text='"1 2"',result='head,middle,last'),
 'short':program('head,*middle,last',text='"1"',result='head,middle,last'),
 'bad_before_short':program('head,*middle,last',text='"bad"',result='head,middle,last'),
 'bad_left_before_right':program('head,*middle,last',text='"1 bad_left bad_right"',result='head,middle,last'),
 'reverse_bad_left_before_right':program('head,*middle,last',text='"1 bad_left bad_right"',result='head,middle,last',method='rsplit()'),
 'reverse_limit':program('head,*tail',text='"1,2,3,4"',method='rsplit(",",2)'),
 'bytes':program('head,*tail',text='b"1 -2 3_000"'),
 'bytes_reverse':program('*body,last',text='b"1,-2,3_000"',result='body,last',method='rsplit(b",")'),
 'unicode_words':program('head,*tail',text='"１２\u3000-٣٤ ५६"'),
 'multiline_error':'''class Reader:
 def run(self,text):
  head,*tail=(
   map(int,text.split())
  )
  return head,tail
print(Reader().run('1 bad'))
''',
 'strict_before_parse':'''def mark():
 print('strict')
 return False
class Reader:
 def run(self,text):
  head,*tail=map(int,text.split(),strict=mark())
  return head,tail
print(Reader().run('bad 2'))
''',
 'split_before_strict':'''def mark():
 print('strict')
 return False
class Reader:
 def run(self,text):
  head,*tail=map(int,text.split(''),strict=mark())
  return head,tail
print(Reader().run('1 2'))
''',
 'strict_raises_before_parse':'''def mark():
 print('strict')
 raise ValueError('strict failed')
class Reader:
 def run(self,text):
  head,*tail=map(int,text.split(),strict=mark())
  return head,tail
print(Reader().run('bad 2'))
''',
 'captured_identities_before_source_effect':'''make=map
parse=int
def source():
 global make,parse
 make=7
 parse=None
 print('source')
 return '1 2 3'
class Reader:
 def run(self):
  head,*tail=make(parse,source().split())
  return head,tail
print(Reader().run())
''',
 'target_effect_after_conversions':'''bucket=[0]
def place():
 print('target')
 return bucket
class Reader:
 def run(self,text):
  place()[0],*tail=map(int,text.split())
  return bucket,tail
print(Reader().run('1 2 3'))
''',
 'no_target_effect_after_bad_conversion':'''bucket=[0]
def place():
 print('target')
 return bucket
class Reader:
 def run(self,text):
  place()[0],*tail=map(int,text.split())
  return bucket,tail
print(Reader().run('1 bad'))
''',
 'saved_iterator_alias':'''class Reader:
 def run(self,text):
  stream=map(int,text.split())
  alias=stream
  print(next(stream))
  head,*tail=alias
  return head,tail,list(stream)
print(Reader().run('1 2 3 4'))
''',
 'chained_iterator_alias':'''class Reader:
 def run(self,text):
  first=second=map(int,text.split())
  print(next(first))
  head,*tail=second
  return head,tail,list(first)
print(Reader().run('1 2 3 4'))
''',
 'source_callback_keeps_its_effects':'''parse=int
def int(word):
 print('convert',word)
 return parse(word)+1
class Reader:
 def run(self,text):
  head,*tail=map(int,text.split())
  return head,tail
print(Reader().run('1 2 3'))
''',
}


class ImmediateWordConsumerProofs(unittest.TestCase):
 def selected(self,name,mode='i64'):
  selected=[];original=words.emit_unpack_assignment
  def inspect(emitter,node):
   before=ast.dump(emitter.model.unit.tree,include_attributes=True)
   result=original(emitter,node)
   self.assertEqual(before,ast.dump(emitter.model.unit.tree,include_attributes=True))
   if result is not None:selected.append(result)
   return result
  with patch.object(words,'emit_unpack_assignment',inspect):
   result=transpile(CASES[name],TranspileOptions(integer=mode,license='none'))
  self.assertTrue(result.success,result.diagnostics)
  return result,selected

 def test_fresh_consumers_have_no_heap_iterator_or_word_span_vector(self):
  for mode in ('i64','i128','bigint'):
   for name in ('prefix','suffix','both','bytes'):
    with self.subTest(mode=mode,name=name):
     result,selected=self.selected(name,mode)
     self.assertTrue(selected)
     self.assertNotIn('words:Vec<(usize,usize)>',result.rust_source)
     self.assertNotIn('Vec::<(usize,usize)>::new()',result.rust_source)
     self.assertNotIn('Rc::new(RefCell::new(ClassIteratorState_',result.rust_source)

 def test_escaping_iterators_and_source_callables_retain_their_own_protocol(self):
  for name in ('saved_iterator_alias','chained_iterator_alias','source_callback_keeps_its_effects'):
   with self.subTest(name=name):
    _,selected=self.selected(name)
    self.assertFalse(selected)


@unittest.skipUnless(shutil.which('rustc'),'rustc required')
class ImmediateWordConsumerExecution(unittest.TestCase):
 cases=CASES
 check=support.IteratorExecutionTests.check


def runtime_case(name):
 def test(self):self.check(name)
 return test
for _name in CASES:
 setattr(ImmediateWordConsumerExecution,'test_'+_name,runtime_case(_name))
