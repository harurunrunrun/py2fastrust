"""Linear State producers return their actual source value with the witness."""
import ast
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from py2fastrust.frontend import parse_source
from py2fastrust.native_classes import Cell, Expression, InstanceType, shape
from py2fastrust.native_source_state import Registry, StateSlot, explicit_return, producer_result
from py2fastrust.native_types import NullableType
import test_native_source_state as source_tests


OWNER = InstanceType('Context')


def producer_fixture(source, result=OWNER, arguments=None):
    unit=parse_source(source,'producer_return_contract.py')
    node=next(node for node in unit.tree.body if isinstance(node,ast.FunctionDef))
    scope=unit.scope_for(node).ordinal
    arguments=arguments or {'owner':OWNER}
    plan=SimpleNamespace(index=12,node=node,result=Cell(result),
        runtime_parameters=tuple(arguments),arguments={name:Cell(kind)for name,kind in arguments.items()})
    rows=tuple(unit.bindings)
    def binding(value):
        ordinal=unit.ordinal(value)
        return next((row for row in rows if row.node==ordinal),None)
    lexical=SimpleNamespace(parent_scope=lambda plan:None,scope=lambda plan:scope,
        binding=binding,execution_scope=lambda value:value,field_for=lambda node:None,environments={})
    model=SimpleNamespace(unit=unit,integer='i64',lexical=lexical,
        namespace=SimpleNamespace(owns=lambda plan,node:False),
        resolved_name=lambda plan,node:unit.name_for(node))
    registry=Registry.__new__(Registry);registry.model=model;registry.rows=rows
    registry.kind=lambda plan,node:shape(plan.arguments[node.id])if isinstance(node,ast.Name)and node.id in plan.arguments else'int'
    slot=StateSlot('values','int',frozenset({(5,1)}))
    registry.slot=lambda plan,node:slot
    return registry,plan,scope


class ProducerReturnContracts(unittest.TestCase):
    def select(self,registry,plan):
        with patch('py2fastrust.native_class_calls.synchronous',return_value=True):
            return registry.producer(plan)

    def test_actual_official_readonly_formal_may_follow_the_single_append(self):
        registry,plan,_=producer_fixture('def enter(owner):\n    values.append(13)\n    return owner\n')
        producer=self.select(registry,plan)
        self.assertIsNotNone(producer)
        self.assertIs(producer.plan,plan)
        self.assertIs(producer.node,plan.node.body[0].value)
        scalar,plan,_=producer_fixture('def enter(owner, answer=37):\n    values.append(13)\n    return answer\n',
            result='int',arguments={'owner':OWNER,'answer':'int'})
        self.assertIsNotNone(self.select(scalar,plan))

    def test_hidden_producer_capture_and_mismatched_result_keep_ordinary_entry(self):
        for reason in ('hidden_store','capture','namespace','field','result_kind','point_kind'):
            with self.subTest(reason=reason):
                registry,plan,scope=producer_fixture('def enter(owner):\n    values.append(13)\n    return owner\n')
                if reason=='hidden_store':
                    registry.rows+= (SimpleNamespace(owner=scope,name='owner',role='delete'),)
                elif reason=='capture':registry.model.lexical.environments[scope]=SimpleNamespace(fields={'owner':object()})
                elif reason=='namespace':registry.model.namespace.owns=lambda plan,node:True
                elif reason=='field':registry.model.lexical.field_for=lambda node:object()
                elif reason=='result_kind':plan.result=Cell('int')
                else:registry.kind=lambda plan,node:'int'
                self.assertIsNone(self.select(registry,plan))

    def test_nonformal_return_early_return_and_multiple_appends_decline(self):
        for source in (
                'def enter(owner):\n    values.append(13)\n    return make_owner()\n',
                'def enter(owner):\n    values.append(13)\n    result=owner\n    return result\n',
                'def enter(owner):\n    return owner\n    values.append(13)\n',
                'def enter(owner):\n    values.append(13)\n    values.append(17)\n    return owner\n'):
            registry,plan,_=producer_fixture(source)
            self.assertIsNone(self.select(registry,plan),source)

    def test_explicit_and_implicit_none_producers_still_select(self):
        for ending in ('','    return\n','    return None\n'):
            registry,plan,_=producer_fixture('def enter(owner):\n    values.append(13)\n'+ending,result='none')
            self.assertIsNotNone(self.select(registry,plan))

    def test_explicit_return_evaluates_and_coerces_the_actual_value_once(self):
        node=ast.parse('return owner').body[0]
        actual=Expression('checked_actual_owner',OWNER)
        emitter=SimpleNamespace(plan=SimpleNamespace(result=Cell(OWNER)),source_state_producer=object(),
            expression=Mock(return_value=actual),coerce=Mock(return_value='coerced_actual_owner'))
        code=explicit_return(emitter,node)
        self.assertEqual(code,'return Ok((coerced_actual_owner,class_state_effect_value));')
        emitter.expression.assert_called_once_with(node.value)
        emitter.coerce.assert_called_once_with(actual,OWNER,node)
        self.assertNotIn('((),',code)

    def test_non_none_error_tail_is_preserved_and_nullable_none_tail_is_coerced(self):
        for result_kind,tail,expected in (
                (OWNER,'Err(original_error)','Err(original_error)'),
                ('none','Ok(())','Ok((coerced_none,class_state_effect_value))'),
                (NullableType(OWNER),'Ok(old_none)','Ok((coerced_none,class_state_effect_value))')):
            with self.subTest(result_kind=result_kind):
                node=ast.parse('def enter(owner): pass').body[0]
                emitter=SimpleNamespace(plan=SimpleNamespace(node=node,result=Cell(result_kind)),
                    source_state_producer=SimpleNamespace(slot=SimpleNamespace(kind='int')),
                    rust_type=lambda kind:'Witness',coerce=Mock(return_value='coerced_none'))
                result,actual_tail,initial=producer_result(emitter,'OriginalResult',tail)
                self.assertEqual(result,'(OriginalResult,Witness)')
                self.assertEqual(actual_tail,expected)
                self.assertEqual(initial,'let class_state_effect_value:Witness;')
                if result_kind==OWNER:emitter.coerce.assert_not_called()
                else:self.assertEqual(emitter.coerce.call_args.args[0],Expression('()','none'))

    def test_nonproducer_return_and_result_paths_remain_untouched(self):
        emitter=SimpleNamespace()
        self.assertIsNone(explicit_return(emitter,ast.parse('return 7').body[0]))
        self.assertEqual(producer_result(emitter,'Result','original_tail'),('Result','original_tail',''))


# Exact frozen originals are populated below; these are execution regressions,
# separate from the compiler-only contracts above.
SOURCES = {'with_as_actual_identity': 'class Context:\n'
                            '    values = []\n'
                            '    def __init__(self, value):\n'
                            '        self.value = value\n'
                            '    def __enter__(self):\n'
                            '        Context.values.append(self.value)\n'
                            '        return self\n'
                            '    def __exit__(self, kind, error, trace):\n'
                            '        print("exit", self.value)\n'
                            '        Context.values.pop()\n'
                            '    @classmethod\n'
                            '    def current(cls):\n'
                            '        return cls.values[-1]\n'
                            'manager = Context(int(input()))\n'
                            'with manager as entered:\n'
                            '    print(entered is manager, entered.value, Context.current())\n'
                            'print(len(Context.values))\n',
 'readonly_default_formal_value': 'class Context:\n'
                                  '    values = []\n'
                                  '    def __init__(self, value):\n'
                                  '        self.value = value\n'
                                  '    def __enter__(self, answer=37):\n'
                                  '        Context.values.append(self.value)\n'
                                  '        return answer\n'
                                  '    def __exit__(self, kind, error, trace):\n'
                                  '        print("exit", self.value)\n'
                                  '        Context.values.pop()\n'
                                  '    @classmethod\n'
                                  '    def current(cls):\n'
                                  '        return cls.values[-1]\n'
                                  'with Context(5) as answer:\n'
                                  '    print(answer, Context.current())\n'
                                  'print(len(Context.values))\n',
 'returned_self_keeps_error_cleanup': 'class Context:\n'
                                      '    values = []\n'
                                      '    def __init__(self, value):\n'
                                      '        self.value = value\n'
                                      '    def __enter__(self):\n'
                                      '        Context.values.append(self.value)\n'
                                      '        return self\n'
                                      '    def __exit__(self, kind, error, trace):\n'
                                      '        print("exit", self.value)\n'
                                      '        Context.values.pop()\n'
                                      '    @classmethod\n'
                                      '    def current(cls):\n'
                                      '        return cls.values[-1]\n'
                                      'manager = Context(9)\n'
                                      'with manager as entered:\n'
                                      '    print(entered is manager, entered.value)\n'
                                      '    print(1 // 0)\n'}


@unittest.skipUnless(source_tests.shutil.which('rustc'),'rustc is required')
class ProducerReturnExecution(unittest.TestCase):
    def exercise(self,name,inputs):
        with patch.dict(source_tests.SOURCES,SOURCES):
            source_tests.NativeSourceStateExecutionTests.exercise(self,name,inputs)

    def test_with_as_preserves_actual_identity_and_runtime_value(self):
        self.exercise('with_as_actual_identity',('7\n','-11\n'))

    def test_readonly_default_return_preserves_its_original_value(self):
        self.exercise('readonly_default_formal_value',('',))

    def test_non_none_return_keeps_body_error_and_cleanup(self):
        self.exercise('returned_self_keeps_error_cleanup',('',))


if __name__=='__main__':
    unittest.main()
