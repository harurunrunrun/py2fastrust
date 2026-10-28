"""Canonical callable scopes follow CPython's executable annotation contexts."""
import ast
import types
import unittest

from py2fastrust.frontend import parse_source


def compiled_lambdas(source):
    def walk(code):
        yield code
        for constant in code.co_consts:
            if isinstance(constant,types.CodeType):yield from walk(constant)
    return [code for code in walk(compile(source,'annotation_scope.py','exec',dont_inherit=True))if code.co_name=='<lambda>']


class SourceAnnotationScopeTests(unittest.TestCase):
    def check_lambdas(self,source):
        unit=parse_source(source,'annotation_scope.py')
        nodes=[node for node in ast.walk(unit.tree)if isinstance(node,ast.Lambda)]
        active=[node for node in nodes if id(node)in unit.function_signatures]
        self.assertEqual(len(active),len(compiled_lambdas(source)))
        for node in active:
            self.assertEqual(unit.scope_for(node).kind,'function')
            self.assertEqual(unit.scope_for(node).name,'lambda')
            arguments=(*node.args.posonlyargs,*node.args.args,*node.args.kwonlyargs)
            if node.args.vararg is not None:arguments+= (node.args.vararg,)
            if node.args.kwarg is not None:arguments+= (node.args.kwarg,)
            self.assertEqual({symbol.name for symbol in unit.scope_for(node).symbols if symbol.has('parameter')},
                             {unit.name_for(argument)for argument in arguments})
        for node in ast.walk(unit.tree):unit.ordinal(node)
        return unit,nodes,active

    def test_future_parameter_return_annotations_keep_syntax_without_callable_frames(self):
        source='from __future__ import annotations\ndef f(x:(lambda hidden:hidden))->(lambda output:output):pass\n'
        unit,nodes,active=self.check_lambdas(source)
        self.assertEqual(active,[])
        self.assertEqual(len(nodes),2)
        self.assertTrue(all(id(node)not in unit.definition_scopes for node in nodes))
        self.assertFalse({'hidden','output'}&{binding.name for binding in unit.bindings})
        self.assertEqual([unit.nodes[unit.ordinal(node)].line for node in nodes],[2,2])

    def test_default_and_ordinary_lambdas_remain_executable_with_future_annotations(self):
        body='def f(x:(lambda hidden:hidden)=(lambda default:default)):return x\ng=lambda live:live\n'
        for prefix,expected in(('',{'hidden','default','live'}),('from __future__ import annotations\n',{'default','live'})):
            with self.subTest(future=bool(prefix)):
                unit,nodes,active=self.check_lambdas(prefix+body)
                names={unit.signature_for(node).positional[0]for node in active}
                self.assertEqual(names,expected)

    def test_same_line_annotation_does_not_take_runtime_lambda_symbol_table(self):
        source='from __future__ import annotations\nvalue:(lambda invisible:invisible)=lambda actual:actual\n'
        unit,nodes,active=self.check_lambdas(source)
        self.assertEqual(len(active),1)
        self.assertEqual(unit.signature_for(active[0]).positional,('actual',))
        self.assertFalse('invisible'in{binding.name for binding in unit.bindings})

    def test_local_annotations_are_not_evaluated_with_or_without_future(self):
        body='def f():\n value:(lambda invisible:invisible)=lambda actual:actual\n return value\n'
        for prefix in('','from __future__ import annotations\n'):
            with self.subTest(future=bool(prefix)):
                unit,nodes,active=self.check_lambdas(prefix+body)
                self.assertEqual(len(active),1)
                self.assertEqual(unit.signature_for(active[0]).positional,('actual',))
                self.assertFalse('invisible'in{binding.name for binding in unit.bindings})

    def test_nonsimple_target_annotations_have_no_executable_lambda(self):
        body='class Owner:pass\nobj=Owner()\nobj.field:(lambda invisible:invisible)=lambda actual:actual\n'
        unit,nodes,active=self.check_lambdas(body)
        self.assertEqual(len(active),1)
        self.assertEqual(unit.signature_for(active[0]).positional,('actual',))

    def test_nonsimple_target_and_value_keep_their_distinct_official_scopes(self):
        source='(lambda target:target)().field:(lambda annotation:annotation)=(lambda rhs:rhs)\n'
        unit,nodes,active=self.check_lambdas(source)
        self.assertEqual(len(active),2)
        self.assertEqual({unit.signature_for(node).positional[0]for node in active},{'target','rhs'})

    def test_stringized_annotation_comprehension_has_no_binding_effects(self):
        source='from __future__ import annotations\nvalue:[(lambda ghost:ghost)for target in data]=1\n'
        unit,nodes,active=self.check_lambdas(source)
        self.assertEqual(active,[])
        self.assertFalse({'ghost','target','data'}&{binding.name for binding in unit.bindings})
        self.assertFalse(any(scope.kind=='comprehension'for scope in unit.scopes))
        comprehension=next(node for node in ast.walk(unit.tree)if isinstance(node,ast.ListComp))
        self.assertEqual(unit.nodes[unit.ordinal(comprehension)].line,2)

    def test_lazy_module_and_class_annotation_lambdas_keep_real_callable_frames(self):
        source='value:(lambda module:module)\nclass Owner:\n field:(lambda member:member)\n'
        unit,nodes,active=self.check_lambdas(source)
        self.assertEqual(len(active),2)
        self.assertEqual({unit.signature_for(node).positional[0]for node in active},{'module','member'})


if __name__=='__main__':unittest.main()
