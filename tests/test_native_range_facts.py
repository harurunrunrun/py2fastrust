"""Pure shared graph proofs for captured range regions and immutable owners."""
import random
from dataclasses import dataclass,replace
from types import MappingProxyType
import unittest
from unittest.mock import patch

from py2fastrust.frontend import build_program
from py2fastrust.native_constraints import analyze
from py2fastrust.native_range_facts import derive_regions
from py2fastrust.literal_semantics import integer_policy


def term_endpoints(term,lo,hi,scalars,lengths,bits):
    """Reference only: paired affine endpoints retain source correlations."""
    minimum=-(1<<(bits-1));maximum=(1<<(bits-1))-1
    op=term.operation
    if op=="induction":result=(lo,hi)
    elif op=="literal":result=(term.value,term.value)
    elif op=="invariant":result=(scalars[term.value],scalars[term.value])
    elif op=="owner_length":result=(lengths[term.value],lengths[term.value])
    elif op in {"len","UAdd"}:result=term_endpoints(term.operands[0],lo,hi,scalars,lengths,bits)
    elif op=="USub":
        child=term_endpoints(term.operands[0],lo,hi,scalars,lengths,bits)
        result=None if child is None else (-child[0],-child[1])
    else:
        left,right=(term_endpoints(child,lo,hi,scalars,lengths,bits) for child in term.operands)
        if left is None or right is None:return None
        if op=="Add":result=tuple(a+b for a,b in zip(left,right))
        elif op=="Sub":result=tuple(a-b for a,b in zip(left,right))
        elif op=="Mult":result=tuple(a*b for a,b in zip(left,right))
        else:raise AssertionError(op)
    return result if result is not None and minimum<=min(result)<=max(result)<=maximum else None


def term_interval(term,lo,hi,scalars,lengths,bits):
    endpoints=term_endpoints(term,lo,hi,scalars,lengths,bits)
    return None if endpoints is None else (min(endpoints),max(endpoints))


def wrapped_term(term,induction,scalars,lengths,bits):
    policy=integer_policy(bits);op=term.operation
    if op=="induction":return induction
    if op=="literal":return term.value
    if op=="invariant":return scalars[term.value]
    if op=="owner_length":return policy.normalize(lengths[term.value])
    values=[wrapped_term(child,induction,scalars,lengths,bits) for child in term.operands]
    if op in {"len","UAdd"}:return values[0]
    if op=="USub":return policy.normalize(-values[0])
    a,b=values
    return policy.normalize(a+b if op=="Add" else a-b if op=="Sub" else a*b)


class RangeFactTests(unittest.TestCase):
    def analyze(self,source,bits=64):
        unit=build_program(source,"regions.py").main
        result=analyze(unit)
        return unit,result,derive_regions(result,result.scope(),bits)

    def ordinary(self,source,bits=64):
        unit,result,facts=self.analyze(source,bits)
        return unit,result,next(fact for key,fact in facts.items() if isinstance(key,int))

    def test_canonical_range_and_len_aliases_supply_roles_and_intermediates(self):
        unit,result,fact=self.ordinary('run=range\nsize=len\nn=int(input())\ns=input()\nfor i in run(0,n,True):\n print(s[i+2],s[i+size(s)-size(s)])\n')
        self.assertEqual(fact.domain.target,"i")
        self.assertEqual(fact.domain.unit_step,1)
        self.assertEqual(fact.domain.start_site,unit.ordinal(unit.tree.body[4].iter.args[0]))
        self.assertEqual(len(fact.accesses),2)
        self.assertEqual({owner.name for owner in fact.readonly_owners},{"s"})
        term=fact.accesses[1].affine
        self.assertEqual((term.operation,term.operands[0].operation),("Sub","Add"))
        self.assertEqual(term.operands[1].operation,"len")
        self.assertFalse(fact.vectorizable_when_guarded)
        self.assertTrue(any(effect.kind=="io" for effect in fact.effects))

    def test_numeric_invariants_and_length_owners_have_distinct_capture_roles(self):
        _,_,fact=self.ordinary('n=int(input())\nm=int(input())\ns=input()\nt=input()\nfor i in range(n):\n answer=s[i+m-len(t)]\n')
        self.assertEqual(fact.invariant_names,frozenset({"m"}))
        owners={owner.name:owner for owner in fact.readonly_owners}
        self.assertEqual(set(owners),{"s","t"})
        self.assertEqual(owners["t"].read_sites,())
        self.assertIn("t",fact.definitely_bound)

    def test_nonaffine_reads_keep_readonly_owner_opportunity(self):
        _,_,fact=self.ordinary('n=int(input())\ns=input()\nfor i in range(n):\n print(s[i%len(s)])\n')
        self.assertEqual(fact.accesses,())
        self.assertEqual([owner.name for owner in fact.readonly_owners],["s"])
        self.assertEqual(len(fact.readonly_owners[0].read_sites),1)

    def test_owner_rebinding_callbacks_and_mutation_reject_unsafe_hoisting(self):
        programs=(
            'n=int(input())\ns=input()\nfor i in range(n):\n s="new"\n print(s[i])\n',
            'def callback(x):\n print(x)\n return x\nn=int(input())\ns=input()\nfor i in range(n):\n callback(i)\n print(s[i])\n',
            'n=int(input())\ns=input()\na=[]\nfor i in range(n):\n a.append(i)\n print(s[i])\n',
        )
        for source in programs:
            with self.subTest(source=source):self.assertEqual(dict(self.analyze(source)[2]),{})

    def test_unknown_constructor_callbacks_are_conservatively_excluded(self):
        source='def bound(n):\n print(n)\n return n\nn=int(input())\ns=input()\nfor i in range(bound(n)):\n print(s[i])\n'
        self.assertEqual(dict(self.analyze(source)[2]),{})
        source='n=int(input())\ns=input()\nfor i in range(int(input())):\n print(s[i])\n'
        self.assertEqual(len(self.analyze(source)[2]),1)

    def test_unproved_attribute_getters_do_not_hide_owner_or_namespace_effects(self):
        source='n=int(input())\ns=input()\nobj=object()\nfor i in range(n):\n value=obj.field\n print(s[i])\n'
        self.assertEqual(dict(self.analyze(source)[2]),{})

    def test_immutable_alias_keeps_original_owner_after_other_name_rebinds(self):
        _,_,fact=self.ordinary('n=int(input())\ns=input()\nt=s\nfor i in range(n):\n s="new"\n print(t[i])\n')
        self.assertEqual([owner.name for owner in fact.readonly_owners],["t"])
        self.assertEqual(len(fact.accesses),1)
        self.assertIn("s",fact.written_names)

    def test_maybe_unbound_owner_or_invariant_never_moves_a_read(self):
        source='n=int(input())\nif n:s=input()\nfor i in range(n):\n print(s[i])\n'
        self.assertEqual(dict(self.analyze(source)[2]),{})
        _,_,fact=self.ordinary('n=int(input())\ns=input()\nif n:m=1\nfor i in range(n):\n print(s[i+m])\n')
        self.assertEqual(fact.accesses,())
        self.assertEqual([owner.name for owner in fact.readonly_owners],["s"])

    def test_written_index_invariants_and_induction_target_keep_checked_reads(self):
        for statement in ('m+=1','i+=1'):
            with self.subTest(statement=statement):
                _,_,fact=self.ordinary('n=int(input())\nm=int(input())\ns=input()\nfor i in range(n):\n print(s[i+m])\n '+statement+'\n')
                self.assertEqual(fact.accesses,())
                self.assertEqual([owner.name for owner in fact.readonly_owners],["s"])

    def test_one_clause_comprehensions_keep_filters_and_source_scope(self):
        source='n=int(input())\noffset=int(input())\ns=input()\nt=input()\nanswer=sum(s[j+offset]!=t[j] for j in range(n) if s[j]!="x")\n'
        unit,_,facts=self.analyze(source)
        expression=unit.tree.body[4].value.args[0]
        fact=facts[(unit.ordinal(expression),0)]
        self.assertEqual(fact.domain.target,"j")
        self.assertEqual(len(fact.accesses),3)
        self.assertEqual({owner.name for owner in fact.readonly_owners},{"s","t"})
        self.assertEqual(fact.invariant_names,frozenset({"offset"}))
        self.assertTrue(fact.vectorizable_when_guarded)

    def test_unknown_range_alias_and_nonunit_steps_have_only_readonly_facts(self):
        for step in ('2','-1','step'):
            _,_,fact=self.ordinary('n=int(input())\nstep=int(input())\ns=input()\nfor i in range(0,n,'+step+'):\n print(s[i])\n')
            self.assertIsNone(fact.domain)
            self.assertEqual(fact.accesses,())
        _,_,fact=self.ordinary('n=int(input())\ns=input()\nfor i in range(n):\n print(s[i])\n',0)
        self.assertEqual(fact.accesses,())
        self.assertEqual(len(fact.readonly_owners),1)

    def test_wrapped_literals_and_every_intermediate_arithmetic_step_are_preserved(self):
        for bits in (64,128):
            maximum=(1<<(bits-1))-1
            source=f'n=int(input())\ns=input()\nfor i in range(n):\n print(s[i+({maximum}+1)],s[-(-i)],s[2*i-i],s[i+{1<<bits}])\n'
            _,_,fact=self.ordinary(source,bits)
            self.assertEqual(len(fact.accesses),4)
            self.assertIsNone(term_interval(fact.accesses[0].affine,0,2,{}, {"s":5},bits))
            self.assertIsNone(term_interval(fact.accesses[1].affine,-(1<<(bits-1)),-(1<<(bits-1)),{}, {"s":5},bits))
            self.assertIsNone(term_interval(fact.accesses[2].affine,maximum-1,maximum,{}, {"s":5},bits))
            self.assertEqual(term_interval(fact.accesses[2].affine,0,4,{}, {"s":5},bits),(0,4))
            self.assertEqual(term_interval(fact.accesses[3].affine,0,4,{}, {"s":5},bits),(0,4))

    def test_random_guard_success_implies_source_wrapping_and_bounds_agree(self):
        rng=random.Random(87104)
        expressions=('i+offset','i-offset','offset+i','2*i-i+offset','-(-i)+offset','i+len(s)-offset')
        accepted=0
        for bits in (64,128):
            for expression in expressions:
                _,_,fact=self.ordinary('n=int(input())\noffset=int(input())\ns=input()\nfor i in range(n):\n print(s['+expression+'])\n',bits)
                term=fact.accesses[0].affine
                for _ in range(300):
                    start=rng.randrange(-30,30);stop=rng.randrange(start,start+25)
                    offset=rng.randrange(-40,40);length=rng.randrange(1,80)
                    if stop==start:continue
                    interval=term_interval(term,start,stop-1,{"offset":offset},{"s":length},bits)
                    if interval is None or interval[0]<0 or interval[1]>=length:continue
                    accepted+=1
                    values=[wrapped_term(term,i,{"offset":offset},{"s":length},bits) for i in range(start,stop)]
                    self.assertTrue(all(0<=value<length for value in values))
                    self.assertEqual(values,list(range(values[0],values[0]+len(values))))
        self.assertGreater(accepted,100)

    def opaque_operand_facts(self,statement,kind):
        source='n=int(input())\ns=input()\npayload=[1]\nfor i in range(n):\n '+statement+'\n print(s[i])\n'
        return self.with_payload_kind(source,kind)

    def with_payload_kind(self,source,kind):
        unit=build_program(source,"opaque.py").main
        analysis=analyze(unit);facts=analysis.scope();kinds=dict(facts.expressions)
        for site,term in analysis.graph.expressions.items():
            if term.operation=="name" and term.data=="payload":kinds[site]=kind
        return derive_regions(analysis,replace(facts,expressions=MappingProxyType(kinds)),64)

    def test_builtin_conversion_and_formatting_reject_opaque_protocols(self):
        @dataclass(frozen=True)
        class Opaque:
            _native_kind_tag="opaque_instance"
        for statement in ('unused=bool(payload)','unused=len(payload)','unused=int(payload)',
                          'unused=float(payload)','unused=str(payload)','unused=repr(payload)',
                          'unused=ord(payload)','unused=abs(payload)','unused=pow(payload,2)',
                          'unused=list(payload)','unused=tuple(payload)','unused=set(payload)',
                          'unused=dict(payload)','print(payload)','unused=input(payload)',
                          'print(1,file=payload)','print(1,flush=payload)','unused=s.count(payload)'):
            with self.subTest(statement=statement):
                self.assertEqual(dict(self.opaque_operand_facts(statement,Opaque())),{})

    def test_nested_container_formatting_checks_every_opaque_leaf(self):
        from py2fastrust.native_types import TupleType,ListType,NullableType,UnionType
        from py2fastrust.native_key_types import SetType,DictType
        @dataclass(frozen=True)
        class Opaque:
            _native_kind_tag="opaque_nested_instance"
        leaf=Opaque()
        for kind in (ListType(leaf),TupleType(("int",leaf)),SetType(leaf),DictType("str",leaf),
                     ListType(TupleType(("str",ListType(leaf)))),NullableType(leaf),UnionType(("int",leaf))):
            for statement in ('print(payload)','unused=str(payload)','unused=repr(payload)','unused=input(payload)'):
                with self.subTest(kind=kind,statement=statement):
                    self.assertEqual(dict(self.opaque_operand_facts(statement,kind)),{})

    def test_exact_builtin_container_len_and_bool_do_not_inspect_elements(self):
        from py2fastrust.native_types import TupleType,ListType
        from py2fastrust.native_key_types import SetType,DictType
        @dataclass(frozen=True)
        class Opaque:
            _native_kind_tag="opaque_container_element"
        for kind in (ListType(Opaque()),TupleType((Opaque(),)),SetType(Opaque()),DictType("str",Opaque())):
            for statement in ('unused=len(payload)','unused=bool(payload)'):
                with self.subTest(kind=kind,statement=statement):
                    facts=self.opaque_operand_facts(statement,kind)
                    self.assertEqual(len(facts),1)
                    self.assertEqual(len(next(iter(facts.values())).accesses),1)

    def test_implicit_protocols_are_not_mistaken_for_pure_name_reads(self):
        @dataclass(frozen=True)
        class Opaque:
            _native_kind_tag="opaque_implicit_protocol"
        statements=('if payload:pass','while payload:break','unused=not payload',
                    'unused=payload and 1','unused=1 if payload else 2','unused=-payload',
                    'unused=payload+1','payload+=1','unused=payload==1','unused=payload<1',
                    'unused=1 in payload','unused=payload[0]','unused=payload[:]',
                    'unused=s[payload]','unused=s[:payload]','left,right=payload',
                    'for value in payload:pass','unused={payload:1}','unused={payload}')
        for statement in statements:
            with self.subTest(statement=statement):self.assertEqual(dict(self.opaque_operand_facts(statement,Opaque())),{})

    def test_builtin_truth_and_identity_do_not_call_opaque_elements(self):
        from py2fastrust.native_types import ListType
        @dataclass(frozen=True)
        class Opaque:
            _native_kind_tag="opaque_truth_and_identity"
        for statement in ('if payload:pass','unused=not payload','unused=payload and 1','print(1,flush=payload)'):
            self.assertEqual(len(self.opaque_operand_facts(statement,ListType(Opaque()))),1)
        self.assertEqual(len(self.opaque_operand_facts('unused=payload is None',Opaque())),1)
        self.assertEqual(len(self.opaque_operand_facts('unused=payload is not None',Opaque())),1)

    def test_builtin_getitem_does_not_call_elements_but_opaque_keys_can(self):
        from py2fastrust.native_types import ListType
        from py2fastrust.native_key_types import DictType
        @dataclass(frozen=True)
        class Opaque:
            _native_kind_tag="opaque_index_protocol"
        self.assertEqual(len(self.opaque_operand_facts('unused=payload[0]',ListType(Opaque()))),1)
        self.assertEqual(dict(self.opaque_operand_facts('unused=payload[0]',DictType(Opaque(),"int"))),{})
        self.assertEqual(len(self.opaque_operand_facts('unused=payload[0]',DictType("int",Opaque()))),1)

    def test_generator_iteration_and_filters_require_callback_free_context(self):
        @dataclass(frozen=True)
        class Opaque:
            _native_kind_tag="opaque_iteration_protocol"
        sources=('n=int(input())\ns=input()\npayload=[1]\nfor i in payload:print(s[0])\n',
                 'n=int(input())\ns=input()\npayload=[1]\nanswer=sum(s[j] for j in payload)\n',
                 'n=int(input())\ns=input()\npayload=[1]\nanswer=sum(s[j] for j in range(n) if payload)\n')
        for source in sources:self.assertEqual(dict(self.with_payload_kind(source,Opaque())),{})
        for source in ('n=int(input())\ns=input()\ng=(s[j] for j in range(n))\n',
                       'n=int(input())\ns=input()\nfor ch in (s[j] for j in range(n)):s="new"\n',
                       'def consume(g):return 1\nn=int(input())\ns=input()\nanswer=consume(s[j] for j in range(n))\n'):
            self.assertEqual(dict(self.analyze(source)[2]),{})
        source='n=int(input())\ns=input()\npayload=[1]\nanswer=sum(payload for j in range(n) if s[j]!="x")\n'
        self.assertEqual(dict(self.with_payload_kind(source,Opaque())),{})

    def test_hidden_repr_callback_is_a_concrete_future_class_counterexample(self):
        source='s="abc"\nclass Change:\n def __repr__(self):\n  global s\n  s="xyz"\n  return "item"\nitems=[Change()]\nfor i in range(3):\n str(items)\n print(s[i])\n'
        self.assertEqual(dict(self.analyze(source)[2]),{})

    def test_structural_container_len_in_canonical_range_construction_is_proved(self):
        source='items=["a","b"]\ns=input()\nfor i in range(len(items)):\n print(s[i])\n'
        _,_,fact=self.ordinary(source)
        self.assertIsNotNone(fact.domain)
        self.assertEqual(len(fact.accesses),1)

    def test_facts_are_derived_without_an_emitter_or_source_execution(self):
        from py2fastrust.native import _Generator
        from py2fastrust.native_scalar import ScalarGenerator
        from py2fastrust.native_bigint import BigIntGenerator
        source='n=int(input())\ns=input()\nfor i in range(n):\n print(s[i])\n'
        unit=build_program(source,"pure.py").main
        with patch.object(_Generator,'expression',side_effect=AssertionError('emitter')),patch.object(ScalarGenerator,'expression',side_effect=AssertionError('emitter')),patch.object(BigIntGenerator,'expression',side_effect=AssertionError('emitter')),patch('builtins.input',side_effect=AssertionError('source execution')):
            analysis=analyze(unit);facts=derive_regions(analysis,analysis.scope(),64)
        self.assertEqual(len(facts),1)


if __name__=='__main__':unittest.main()
