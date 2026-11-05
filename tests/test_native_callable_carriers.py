"""Physical callable families keep actual source identity in every storage role."""
import re,shutil,unittest
from unittest.mock import patch
from py2fastrust import transpile,TranspileOptions
from py2fastrust.native_callable_carriers import Registry,family_type,payload_type,tag
import test_native_class_iterators as execution

CASES={'singleton_parameter_local_and_field': 'def twice(value):return value*2\n'
                                        'class Runner:\n'
                                        ' def __init__(self,callback):self.callback=callback\n'
                                        ' def run(self,value):\n'
                                        '  local=self.callback\n'
                                        '  return local(value),local is self.callback\n'
                                        'def invoke(callback,value):return callback(value)\n'
                                        'r=Runner(twice)\n'
                                        'print(r.run(7),invoke(twice,4),r.callback is twice)\n',
 'closure_instance_payload_identity': 'def make(offset):\n'
                                      ' def add(value):return offset+value\n'
                                      ' return add\n'
                                      'class Runner:\n'
                                      ' def __init__(self,callback):self.callback=callback\n'
                                      ' def run(self,value):return self.callback(value)\n'
                                      'first=make(3)\n'
                                      'saved=first\n'
                                      'second=make(11)\n'
                                      'runner=Runner(first)\n'
                                      'print(runner.run(4),first is saved,first is second)\n'
                                      'runner.callback=second\n'
                                      'print(runner.run(4),first(4),second(4))\n',
 'finite_family_field_replacement': 'def twice(value):return value*2\n'
                                    'def shift(value):return value+9\n'
                                    'class Runner:\n'
                                    ' def __init__(self,callback):self.callback=callback\n'
                                    ' def run(self,value):return self.callback(value)\n'
                                    'r=Runner(twice)\n'
                                    'saved=r.callback\n'
                                    'print(r.run(3),r.callback is twice)\n'
                                    'r.callback=shift\n'
                                    'print(r.run(3),saved(3),r.callback is saved,r.callback is shift)\n',
 'finite_builtin_and_source_family': 'def shift(value):return value+9\n'
                                     'class Runner:\n'
                                     ' def run(self,index,value):\n'
                                     '  choices=[abs,shift]\n'
                                     '  saved=choices[index]\n'
                                     '  return saved(value),saved is choices[index]\n'
                                     'r=Runner()\n'
                                     'print(r.run(0,-4),r.run(1,-4))\n',
 'bound_method_payload_identity': 'class Counter:\n'
                                  ' def __init__(self,value):self.value=value\n'
                                  ' def add(self,amount):\n'
                                  '  self.value+=amount\n'
                                  '  return self.value\n'
                                  'class Runner:\n'
                                  ' def __init__(self,callback):self.callback=callback\n'
                                  ' def run(self,value):return self.callback(value)\n'
                                  'a=Counter(2)\n'
                                  'b=Counter(20)\n'
                                  'method=a.add\n'
                                  'r=Runner(method)\n'
                                  'print(r.run(3),method is r.callback,method==a.add,method is a.add)\n'
                                  'r.callback=b.add\n'
                                  'print(r.run(4),method(5),a.value,b.value)\n',
 'retained_classmethod_payload': 'def seed():\n'
                                 " print('default')\n"
                                 ' return 5\n'
                                 'class Counter:\n'
                                 ' base=7\n'
                                 ' @classmethod\n'
                                 ' def add(cls,value=seed()):return cls.base+value\n'
                                 'class Runner:\n'
                                 ' def __init__(self,callback):self.callback=callback\n'
                                 ' def run(self):return self.callback()\n'
                                 'saved=Counter.add\n'
                                 'r=Runner(saved)\n'
                                 'print(r.run(),saved==Counter.add,saved is Counter.add)\n'
                                 'Counter.base=11\n'
                                 'print(r.run(),saved(2))\n',
 'actual_callee_snapshot_before_args': 'def twice(value):return value*2\n'
                                       'def shift(value):return value+9\n'
                                       'chosen=twice\n'
                                       'def switch():\n'
                                       ' global chosen\n'
                                       " print('switch')\n"
                                       ' chosen=shift\n'
                                       ' return 4\n'
                                       'class Runner:\n'
                                       ' def run(self):return chosen(switch()),chosen(4)\n'
                                       'print(Runner().run())\n',
 'shared_mutable_default_data': 'def append(value,items=[]):\n'
                                ' items.append(value)\n'
                                ' return len(items),items[-1]\n'
                                'class Runner:\n'
                                ' def __init__(self,callback):self.callback=callback\n'
                                ' def run(self,value):return self.callback(value)\n'
                                'r=Runner(append)\n'
                                "print(r.run(3),r.run('text'),append(7))\n",
 'same_lexical_definition_repeated_defaults': 'def make():\n'
                                              ' result=[]\n'
                                              ' for offset in range(3):\n'
                                              '  def value(extra=offset):return extra\n'
                                              '  result.append(value)\n'
                                              ' return result\n'
                                              'class Runner:\n'
                                              ' def run(self):\n'
                                              '  items=make()\n'
                                              '  return [callback()for callback in items],items[0]is '
                                              'items[1],items[0]is items[0]\n'
                                              'print(Runner().run())\n',
 'lambda_instances_and_captured_cells': 'def make(value):return lambda extra:value+extra\n'
                                        'class Runner:\n'
                                        ' def run(self):\n'
                                        '  a=make(2)\n'
                                        '  b=make(8)\n'
                                        '  values=[a,b]\n'
                                        '  return [callback(3)for callback in values],a is b,a is values[0]\n'
                                        'print(Runner().run())\n',
 'invalid_callback_after_all_arguments': 'def value(first):return first\n'
                                         'def mark(item):\n'
                                         " print('arg',item)\n"
                                         ' return item\n'
                                         'class Runner:\n'
                                         ' def __init__(self,callback):self.callback=callback\n'
                                         ' def run(self):return self.callback(mark(1),mark(2))\n'
                                         'Runner(value).run()\n',
 'finite_builtin_types_and_function': 'def identity(value):return value\n'
                                      'class Runner:\n'
                                      ' def run(self,index):\n'
                                      '  choices=[int,str,identity]\n'
                                      '  current=choices[index]\n'
                                      '  return current(7),isinstance(7,int),current is choices[index]\n'
                                      'r=Runner()\n'
                                      'print(r.run(0),r.run(1),r.run(2))\n'}



def inspect(source):
    seen=[]
    original=Registry.runtime
    def observe(registry):
        declarations=original(registry)
        seen.append((registry,declarations))
        return declarations
    with patch.object(Registry,'runtime',observe):
        result=transpile(source,TranspileOptions(filename='carrier_case.py',license='none'))
    assert result.success,result.diagnostics
    assert len(seen)==1
    return result,*seen[0]


class ExactCallableCarrierProofs(unittest.TestCase):
    def test_singleton_storage_and_calls_have_no_callable_enum(self):
        result,registry,declarations=inspect(CASES['singleton_parameter_local_and_field'])
        self.assertNotIn('ClassFunctionRef',result.rust_source)
        self.assertNotIn('enum ClassCallableFamily_',result.rust_source)
        self.assertRegex(result.rust_source,r'field_0:Option<ClassCallablePayload_F[0-9]+>')
        self.assertRegex(result.rust_source,r'class_argument_[0-9]+:ClassCallablePayload_F[0-9]+')
        self.assertTrue(registry.finalized)
        for kind in registry.kinds.values():
            self.assertEqual(len(kind.targets),1)
            self.assertEqual(family_type(kind),payload_type(kind.targets[0]))

    def test_real_families_declare_only_their_semantic_alternatives(self):
        result,registry,declarations=inspect(CASES['finite_builtin_and_source_family'])
        joined=[kind for kind in registry.kinds.values()if len(kind.targets)>1]
        self.assertTrue(joined)
        self.assertNotIn('ClassFunctionRef',result.rust_source)
        for kind in joined:
            body=re.search(r'enum '+family_type(kind)+r'\{([^}]*)\}',declarations).group(1)
            variants=set(re.findall(r'([A-Za-z0-9_]+)\(ClassCallablePayload_',body))
            self.assertEqual(variants,{tag(target)for target in kind.targets})

    def test_closure_and_instance_data_are_retained_as_actual_payloads(self):
        for name in ('closure_instance_payload_identity','same_lexical_definition_repeated_defaults'):
            with self.subTest(name=name):
                _,registry,declarations=inspect(CASES[name])
                from py2fastrust.native_bound_methods import BoundMethodTarget
                source=[registry.layout(target)for target in registry.targets.values()if isinstance(target,int)]
                self.assertTrue(any('environment'in dict(layout.fields)for layout in source))
                self.assertTrue(all('ClassFunctionRef'not in kind for layout in source for _,kind in layout.fields))
                for number,plan in registry.model.callable_cells.plans.items():
                    self.assertEqual(registry.model.unit.ordinal(plan.node),number)

    def test_every_reached_schema_is_collected_before_runtime_declarations(self):
        for name in ('retained_classmethod_payload','shared_mutable_default_data','finite_family_field_replacement'):
            with self.subTest(name=name):
                result,registry,declarations=inspect(CASES[name])
                self.assertTrue(registry.finalized)
                self.assertNotIn('ClassFunctionRef',result.rust_source)
                for target in registry.targets.values():
                    self.assertIn('struct '+payload_type(target)+'{',declarations)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class ExactCallableCarrierExecution(unittest.TestCase):
    cases=CASES
    check=execution.IteratorExecutionTests.check

    def test_exact_callable_in_all_storage_roles(self):
        self.check('singleton_parameter_local_and_field')

    def test_finite_family_changes_preserve_current_target_and_saved_identity(self):
        self.check('finite_family_field_replacement')

    def test_actual_callee_payload_precedes_later_argument_mutation(self):
        self.check('actual_callee_snapshot_before_args')

    def test_retained_bound_receiver_identity_and_mutation(self):
        self.check('bound_method_payload_identity')
