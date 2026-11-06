"""One source binder and one private mask govern physical parameter projection."""
import ast
from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from py2fastrust.call_semantics import FunctionSignature
from py2fastrust.native_captured_invocations import BoundInvocation, bind_definition
from py2fastrust.native_classes import Cell, ClassUnsupported, Emitter, Expression
from py2fastrust.native_module_linking import ClassReferenceType
from py2fastrust.native_operand_demands import ClassOperand
from py2fastrust.native_types import MaybeType


CLASS = ClassReferenceType(7)


def binding_fixture():
    node=ast.parse('def choose(cls, amount=3, *, extra=4): return amount').body[0]
    source=SimpleNamespace(index=31,node=node,signature=FunctionSignature.from_ast(node),
        arguments={'cls':Cell(CLASS),'amount':Cell('int'),'extra':Cell('int')})
    defaults=Mock(return_value={'amount':Expression('default_amount','int'),
                               'extra':Expression('default_extra','int')})
    lexical=SimpleNamespace(parent_scope=lambda plan:None)
    model=SimpleNamespace(callable_cells=SimpleNamespace(plans={9:source}),lexical=lexical,
        emitter=lambda plan:SimpleNamespace(captured_defaults=defaults))
    coercions=[]
    def coerce(value,kind,site):
        coercions.append((value,kind,site))
        return value.code
    emitter=SimpleNamespace(model=model,plan=SimpleNamespace(index=70),coerce=coerce,
        function_name=lambda plan:'class_function_'+str(plan.index))
    site=ast.parse('choose(5)',mode='eval').body
    projection=SimpleNamespace(plan=source,mode=object(),erased_names=frozenset({'cls'}),
        erased_ordinals=(0,))
    return emitter,source,site,projection,defaults,coercions


def binder_patches(stack,source,projection,*,context_parameter='',context=''):
    stack.enter_context(patch('py2fastrust.native_function_instances.instanced',return_value=False))
    stack.enter_context(patch('py2fastrust.native_frame_specialization.native_target',return_value=source))
    selected=stack.enter_context(patch('py2fastrust.native_operand_demands.bound_projection',return_value=projection))
    stack.enter_context(patch('py2fastrust.native_call_context_effects.unused_parent',return_value=True))
    stack.enter_context(patch('py2fastrust.native_class_binding_contexts.parameter',return_value=context_parameter))
    invoke=stack.enter_context(patch('py2fastrust.native_class_binding_contexts.invocation',return_value=context))
    return selected,invoke


class OperandBindingProjectionContracts(unittest.TestCase):
    def test_original_signature_binds_once_before_token_projection_and_coercion(self):
        emitter,source,node,projection,defaults,coercions=binding_fixture()
        token=ClassOperand(CLASS,object())
        self.assertFalse(hasattr(token,'code'))
        explicit=Expression('explicit_extra','int')
        real_bind=FunctionSignature.bind;calls=[]
        def bind(signature,*args,**kwargs):
            calls.append((signature,args,kwargs))
            return real_bind(signature,*args,**kwargs)
        with ExitStack()as stack:
            selected,context=binder_patches(stack,source,projection)
            stack.enter_context(patch.object(FunctionSignature,'bind',bind))
            bound=bind_definition(emitter,node,9,[token],[('extra',explicit)])
        self.assertEqual(len(calls),1)
        defaults.assert_called_once_with(source)
        semantic_binding=selected.call_args.args[-1]
        self.assertIs(semantic_binding['cls'],token)
        self.assertIs(semantic_binding['extra'],explicit)
        self.assertEqual(semantic_binding.defaults,frozenset({'amount'}))
        self.assertEqual(bound.values,('default_amount','explicit_extra'))
        self.assertIs(bound.projection,projection)
        self.assertEqual([value.code for value,_,_ in coercions],['default_amount','explicit_extra'])
        self.assertIsNone(context.call_args.args[2])

    def test_ordinary_values_and_actual_class_context_are_retained(self):
        emitter,source,node,_,defaults,coercions=binding_fixture()
        receiver=Expression('actual_class',CLASS)
        capture=object()
        with ExitStack()as stack:
            _,context=binder_patches(stack,source,None,context_parameter=',class_defining_class:&ClassClassRef',
                                    context=',&captured_actual_class')
            bound=bind_definition(emitter,node,9,[receiver],[],captured_class_context=capture)
        self.assertIsNone(bound.projection)
        self.assertEqual(bound.values,('actual_class','default_amount','default_extra'))
        self.assertEqual(len(coercions),3)
        self.assertEqual(bound.extra_context,',&captured_actual_class')
        self.assertEqual(context.call_args.args[2],'actual_class')
        self.assertIs(context.call_args.kwargs['captured_class_context'],capture)
        self.assertIn('actual_class,default_amount,default_extra',bound.call_code(emitter))
        defaults.assert_called_once_with(source)

    def test_missing_argument_keeps_original_signature_failure_before_projection(self):
        emitter,source,node,projection,_,coercions=binding_fixture()
        source.signature=FunctionSignature.declaration(('cls','required'))
        with ExitStack()as stack:
            selected,context=binder_patches(stack,source,projection)
            with self.assertRaisesRegex(ClassUnsupported,'missing required argument: required'):
                bind_definition(emitter,node,9,[ClassOperand(CLASS,object())],[])
        selected.assert_not_called();context.assert_not_called()
        self.assertEqual(coercions,[])

    def test_projected_capability_cannot_call_an_ordinary_or_continuation_entry(self):
        emitter,source,_,projection,_,_=binding_fixture()
        bound=BoundInvocation(source,source,('amount',),'',projection)
        with self.assertRaisesRegex(ValueError,'certified private entry'):
            bound.call_code(emitter)
        with self.assertRaisesRegex(ValueError,'ordinary frame ABI'):
            bound.frame_code()
        ordinary=BoundInvocation(source,source,('actual_class','amount'),'')
        self.assertIn('class_function_31',ordinary.call_code(emitter))
        self.assertIn('ClassNativeFrame_31',ordinary.frame_code())

    def test_token_cannot_reach_a_value_coercion_or_class_context_consumer(self):
        for projected,context_parameter,expected in (
                (False,'','value parameter'),
                (True,',class_defining_class:&ClassClassRef','class context')):
            with self.subTest(projected=projected):
                emitter,source,node,projection,_,coercions=binding_fixture()
                with ExitStack()as stack:
                    binder_patches(stack,source,projection if projected else None,
                                   context_parameter=context_parameter)
                    with self.assertRaisesRegex(ValueError,expected):
                        bind_definition(emitter,node,9,[ClassOperand(CLASS,object())],[])
                self.assertTrue(all(not isinstance(value,ClassOperand)for value,_,_ in coercions))


def header_fixture():
    node=ast.parse('def read(cls, amount): return amount').body[0]
    plan=SimpleNamespace(index=31,node=node,runtime_parameters=('cls','amount'),
        arguments={'cls':Cell(CLASS),'amount':Cell('int')},result=Cell('int'))
    lexical=SimpleNamespace(scope=lambda current:4,environments={},initialize=lambda emitter:'',
        signature=lambda current:'')
    model=SimpleNamespace(lexical=lexical,namespace=SimpleNamespace(local_kind=lambda current,name:None))
    emitter=Emitter.__new__(Emitter)
    emitter.model=model;emitter.plan=plan
    emitter.slots={('cls',CLASS):'slot_cls',('amount','int'):'slot_amount',('local','int'):'slot_local'}
    emitter.owned_matrices={};emitter.record_places={};emitter.owned_local_lists={};emitter.reference_slots={}
    def rust_type(kind):
        if isinstance(kind,MaybeType):return 'Option<'+rust_type(kind.value)+'>'
        return 'ClassClassRef'if kind==CLASS else'NativeInt'
    emitter.rust_type=rust_type
    emitter.statements=lambda statements:'return Ok(class_argument_1);'
    emitter.coerce=lambda value,kind,site:value.code
    emitter.slot=lambda name,kind:'slot_'+name
    emitter.function_name=lambda current:'class_state_function_31'
    emitter.location_code=lambda:'("original.py","read")'
    projection=SimpleNamespace(plan=plan,mode=object(),erased_names=frozenset({'cls'}),erased_ordinals=(0,))
    return emitter,projection


class OperandPrivateHeaderContracts(unittest.TestCase):
    def generate(self,emitter,projection):
        with ExitStack()as stack:
            registry=stack.enter_context(patch('py2fastrust.native_operand_demands.private_projection',return_value=projection))
            stack.enter_context(patch('py2fastrust.native_typed_continuations.generate',return_value=None))
            stack.enter_context(patch('py2fastrust.native_value_classes.borrowed_self',return_value=False))
            stack.enter_context(patch('py2fastrust.native_owned_object_places.receiver',return_value=False))
            stack.enter_context(patch('py2fastrust.native_primitive_parameter_places.slot_required',return_value=True))
            stack.enter_context(patch('py2fastrust.native_class_binding_contexts.parameter',return_value=''))
            stack.enter_context(patch('py2fastrust.native_class_calls.entry_result',return_value=True))
            code=emitter.generate()
        self.assertEqual(registry.call_count,2)
        return code

    def test_same_mask_removes_private_header_slot_and_initializer_without_renumbering(self):
        emitter,projection=header_fixture()
        code=self.generate(emitter,projection)
        self.assertNotIn('class_argument_0',code)
        self.assertNotIn('slot_cls',code)
        self.assertIn('class_argument_1:NativeInt',code)
        self.assertIn('slot_amount:Option<NativeInt>=None',code)
        self.assertIn('slot_amount=Some(class_argument_1)',code)
        self.assertIn('slot_local:Option<NativeInt>=None',code)

    def test_without_private_projection_all_source_formals_and_slots_remain(self):
        emitter,_=header_fixture()
        code=self.generate(emitter,None)
        self.assertIn('class_argument_0:ClassClassRef',code)
        self.assertIn('class_argument_1:NativeInt',code)
        self.assertIn('slot_cls:Option<ClassClassRef>=None',code)
        self.assertIn('slot_cls=Some(class_argument_0)',code)
        self.assertIn('slot_local:Option<NativeInt>=None',code)


if __name__=='__main__':
    unittest.main()
