"""A witnessed receiver is total only for its original sealed formal place."""
import ast
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from py2fastrust.frontend import parse_source
from py2fastrust.native_classes import Cell, Expression, InstanceType
from py2fastrust.native_class_namespaces import ClassMember
from py2fastrust.native_module_linking import ClassReferenceType
from py2fastrust.native_source_state import StateSlot, StateMode, total_read
from py2fastrust.native_source_total_places import receiver_elidable
from py2fastrust.native_types import ListType, UnionType
import test_native_source_state as source_tests

SOURCES = {'readonly_class_formal': 'class Stack:\n'
                          '    items = []\n'
                          '    def __init__(self, value):\n'
                          '        self.value = value\n'
                          '    def __enter__(self):\n'
                          '        self.items.append(self.value)\n'
                          '    def __exit__(self, kind, error, trace):\n'
                          '        self.items.pop()\n'
                          '    @classmethod\n'
                          '    def current(cls):\n'
                          '        return cls.items[-1]\n'
                          'with Stack(int(input())):\n'
                          '    print(Stack.current(), Stack.current() + 2)\n',
 'ordinary_readonly_class_formal': 'class Stack:\n'
                                   '    items = []\n'
                                   '    def __init__(self, value):\n'
                                   '        self.value = value\n'
                                   '    def __enter__(self):\n'
                                   '        self.items.append(self.value)\n'
                                   '    def __exit__(self, kind, error, trace):\n'
                                   '        self.items.pop()\n'
                                   '    @classmethod\n'
                                   '    def current(cls):\n'
                                   '        return cls.items[-1]\n'
                                   'def tail(owner):\n'
                                   '    return owner.items[-1]\n'
                                   'with Stack(2.5):\n'
                                   '    print(tail(Stack), tail(Stack) + 0.5)\n',
 'reassigned_same_kind_formal': 'class Stack:\n'
                                '    items = []\n'
                                '    def __init__(self, value):\n'
                                '        self.value = value\n'
                                '    def __enter__(self):\n'
                                '        self.items.append(self.value)\n'
                                '    def __exit__(self, kind, error, trace):\n'
                                '        self.items.pop()\n'
                                '    @classmethod\n'
                                '    def current(cls):\n'
                                '        cls = Stack\n'
                                '        return cls.items[-1]\n'
                                'with Stack(7):\n'
                                '    print(Stack.current())\n',
 'effectful_owner_call_keeps_print': 'class Stack:\n'
                                     '    items = []\n'
                                     '    def __init__(self, value):\n'
                                     '        self.value = value\n'
                                     '    def __enter__(self):\n'
                                     '        self.items.append(self.value)\n'
                                     '    def __exit__(self, kind, error, trace):\n'
                                     '        self.items.pop()\n'
                                     '    @classmethod\n'
                                     '    def current(cls):\n'
                                     '        return cls.items[-1]\n'
                                     'def owner():\n'
                                     '    print("owner")\n'
                                     '    return Stack\n'
                                     'with Stack(7):\n'
                                     '    print(owner().items[-1])\n',
 'namespace_replacement_invalidates_witness': 'class Stack:\n'
                                              '    items = []\n'
                                              '    def __init__(self, value):\n'
                                              '        self.value = value\n'
                                              '    def __enter__(self):\n'
                                              '        self.items.append(self.value)\n'
                                              '    def __exit__(self, kind, error, trace):\n'
                                              '        self.items.pop()\n'
                                              '    @classmethod\n'
                                              '    def current(cls):\n'
                                              '        return cls.items[-1]\n'
                                              'with Stack(7):\n'
                                              '    Stack.items = [19]\n'
                                              '    print(Stack.current())\n',
 'aliased_element_write_invalidates_witness': 'class Stack:\n'
                                              '    items = []\n'
                                              '    def __init__(self, value):\n'
                                              '        self.value = value\n'
                                              '    def __enter__(self):\n'
                                              '        self.items.append(self.value)\n'
                                              '    def __exit__(self, kind, error, trace):\n'
                                              '        self.items.pop()\n'
                                              '    @classmethod\n'
                                              '    def current(cls):\n'
                                              '        return cls.items[-1]\n'
                                              'with Stack(7):\n'
                                              '    alias = Stack.items\n'
                                              '    alias[-1] = 23\n'
                                              '    print(Stack.current())\n'}


def fixture(body='return owner.items[-1]', parameters='owner'):
    source='class Owner:\n    items = []\ndef tail('+parameters+'):\n'+''.join('    '+line+'\n'for line in body.splitlines())
    unit=parse_source(source, filename='source_total_place_contract.py')
    function=unit.tree.body[1]
    node=next(n for n in ast.walk(function)if isinstance(n,ast.Subscript)and isinstance(n.value,ast.Attribute))
    attribute=node.value;receiver=attribute.value
    names=tuple(arg.arg for arg in (*function.args.posonlyargs,*function.args.args,*function.args.kwonlyargs))
    plan=SimpleNamespace(node=function,index=17,runtime_parameters=names,
                         arguments={name:Cell(ClassReferenceType(9))for name in names})
    owner=SimpleNamespace(node=unit.tree.body[0],index=9)
    slot=StateSlot('slot','int',frozenset({'origin'}),owner)
    member=ClassMember(owner,'items',slot.key)
    fields=[(slot.key,ListType('int'))]
    namespace=SimpleNamespace(fields=lambda:fields,owns=lambda plan,node:False)
    rows={row.node:row for row in unit.bindings}
    scope=unit.scope_for(function).ordinal
    def execution_scope(value):
        while unit.scopes[value].kind=='comprehension':value=unit.scopes[value].parent
        return value
    lexical=SimpleNamespace(scope=lambda plan:unit.scope_for(plan.node).ordinal,
        binding=lambda node:rows.get(unit.ordinal(node)),execution_scope=execution_scope,
        environments={},field_for=lambda node:None)
    model=SimpleNamespace(unit=unit,namespace=namespace,lexical=lexical,
        class_namespaces=SimpleNamespace(owners={9:owner},attribute_reads={(17,id(attribute)):(member,)},instance_reads={}),
        resolved_name=lambda plan,node:node.attr if isinstance(node,ast.Attribute)else node.id)
    mode=StateMode(reads={id(node):slot})
    values={slot.key:'class_state_value_0'}
    state=SimpleNamespace(model=model,barrier=None,bridges={0:object()},slots={slot.key:slot},
        modes={('function',17):mode},rows=tuple(unit.bindings),copy_kind=lambda kind:kind=='int',
        class_root=lambda current:current is owner)
    model.source_state=state
    kinds={id(receiver):ClassReferenceType(9),id(attribute):ListType('int'),id(node):'int'}
    captured=[]
    emitter=SimpleNamespace(model=model,plan=plan,source_state_active=(mode,values),
        kind=lambda node:kinds.get(id(node)),expression=lambda node:captured.append(node)or Expression('original_receiver()',ListType('int')),
        capture=lambda value:('let checked=original_receiver();',value))
    return SimpleNamespace(unit=unit,node=node,attribute=attribute,receiver=receiver,scope=scope,
        emitter=emitter,state=state,mode=mode,slot=slot,member=member,owner=owner,fields=fields,kinds=kinds,captured=captured)


class NativeSourceTotalPlaceContracts(unittest.TestCase):
    def test_original_readonly_formal_consumes_the_actual_witness_without_receiver_work(self):
        f=fixture()
        self.assertTrue(receiver_elidable(f.emitter,f.node,f.slot))
        result=total_read(f.emitter,f.node)
        self.assertEqual((result.code,result.kind),('class_state_value_0','int'))
        self.assertEqual(f.captured,[])

    def test_reassignment_deletion_and_hidden_exception_producers_keep_checked_receiver(self):
        for body in ('owner = Owner\nreturn owner.items[-1]',
                     'del owner\nreturn owner.items[-1]',
                     'try:\n    pass\nexcept Exception as owner:\n    pass\nreturn owner.items[-1]'):
            with self.subTest(body=body):
                f=fixture(body)
                self.assertFalse(receiver_elidable(f.emitter,f.node,f.slot))
                result=total_read(f.emitter,f.node)
                self.assertIn('original_receiver()',result.code)
                self.assertEqual(f.captured,[f.attribute])

    def test_nonlocal_producer_and_readonly_capture_keep_their_environment(self):
        f=fixture('def change():\n    nonlocal owner\n    owner = Owner\nchange()\nreturn owner.items[-1]')
        self.assertFalse(receiver_elidable(f.emitter,f.node,f.slot))
        f=fixture()
        f.emitter.model.lexical.environments[f.scope]=SimpleNamespace(fields={'owner':object()})
        self.assertFalse(receiver_elidable(f.emitter,f.node,f.slot))

    def test_global_effectful_and_comprehension_owner_places_are_not_formals(self):
        for body,parameters in (('return Owner.items[-1]',''),
                                ('return supplier().items[-1]','owner'),
                                ('return [owner.items[-1] for owner in [Owner]][0]','owner')):
            with self.subTest(body=body):
                f=fixture(body,parameters)
                self.assertFalse(receiver_elidable(f.emitter,f.node,f.slot))
                total_read(f.emitter,f.node)
                self.assertEqual(f.captured,[f.attribute])

    def test_point_argument_owner_and_member_must_match_the_same_exact_class_slot(self):
        f=fixture();f.kinds[id(f.receiver)]=InstanceType('Owner')
        self.assertFalse(receiver_elidable(f.emitter,f.node,f.slot))
        f=fixture();f.kinds[id(f.receiver)]=UnionType((ClassReferenceType(9),ClassReferenceType(10)))
        self.assertFalse(receiver_elidable(f.emitter,f.node,f.slot))
        f=fixture();f.emitter.plan.arguments['owner']=Cell('union',(Cell(ClassReferenceType(9)),Cell(ClassReferenceType(10))))
        self.assertFalse(receiver_elidable(f.emitter,f.node,f.slot))
        for attribute,value in (('owner',object()),('key','other'),('plan',object()),('function_cell',object())):
            f=fixture();setattr(f.member,attribute,value)
            self.assertFalse(receiver_elidable(f.emitter,f.node,f.slot))

    def test_missing_registered_mode_witness_and_presence_proof_decline(self):
        for mutation in ('values','mode','slots','barrier','generation','bridges','copy'):
            with self.subTest(mutation=mutation):
                f=fixture()
                if mutation=='values':f.emitter.source_state_active[1].clear()
                elif mutation=='mode':f.state.modes.clear()
                elif mutation=='slots':f.state.slots.clear()
                elif mutation=='barrier':f.state.barrier='unclosed lifetime'
                elif mutation=='generation':f.state.class_root=lambda owner:False
                elif mutation=='bridges':f.state.bridges.clear()
                else:f.state.copy_kind=lambda kind:False
                self.assertFalse(receiver_elidable(f.emitter,f.node,f.slot))

    def test_unclosed_member_protocol_and_physical_storage_do_not_elide(self):
        f=fixture('return owner.items[0]')
        self.assertFalse(receiver_elidable(f.emitter,f.node,f.slot))
        f=fixture();f.emitter.model.class_namespaces.instance_reads[17,id(f.attribute)]=True
        self.assertFalse(receiver_elidable(f.emitter,f.node,f.slot))
        f=fixture();f.fields[:]=[(f.slot.key,ListType('float'))]
        self.assertFalse(receiver_elidable(f.emitter,f.node,f.slot))


class NativeSourceTotalPlaceFullModels(unittest.TestCase):
    def test_real_readonly_classmethod_and_function_emit_plain_scalar_witness(self):
        for name in ('readonly_class_formal','ordinary_readonly_class_formal'):
            for integer in ('i64','i128'):
                with self.subTest(name=name,integer=integer):
                    result,model,reads,exports=source_tests.convert(SOURCES[name],integer)
                    self.assertTrue(result.success,result.diagnostics)
                    self.assertTrue(model.source_state.bridges)
                    self.assertTrue(exports)
                    self.assertTrue(any(value.code.startswith('class_state_value_')and '{'not in value.code for _,value in reads))

    def test_real_reassigned_and_effectful_places_keep_receiver_evaluation(self):
        for name in ('reassigned_same_kind_formal','effectful_owner_call_keeps_print'):
            with self.subTest(name=name):
                result,_,reads,_=source_tests.convert(SOURCES[name])
                self.assertTrue(result.success,result.diagnostics)
                self.assertTrue(reads)
                self.assertTrue(all('{'in value.code for _,value in reads))


@unittest.skipUnless(source_tests.shutil.which('rustc'),'rustc is required')
class NativeSourceTotalPlaceExecution(unittest.TestCase):
    def exercise(self,name,inputs):
        with patch.dict(source_tests.SOURCES,SOURCES):
            source_tests.NativeSourceStateExecutionTests.exercise(self,name,inputs)

    def test_readonly_formals_keep_runtime_values(self):
        self.exercise('readonly_class_formal',('7\n','13\n'))
        self.exercise('ordinary_readonly_class_formal',('',))

    def test_mutating_and_effectful_receivers_keep_source_behavior(self):
        for name in ('reassigned_same_kind_formal','effectful_owner_call_keeps_print',
                     'namespace_replacement_invalidates_witness','aliased_element_write_invalidates_witness'):
            self.exercise(name,('',))


if __name__=='__main__':
    unittest.main()
