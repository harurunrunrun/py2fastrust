"""Logical inlined-comprehension bindings supplement the official frontend."""
import ast
from pathlib import Path
import tempfile
import unittest

from py2fastrust.frontend import parse_source,build_program,native_namespace_diagnostic,_scope_metadata


class SourceComprehensionScopeTests(unittest.TestCase):
    def binding(self,unit,node):
        return next(value for value in unit.bindings if value.node==unit.ordinal(node))

    def test_inline_forms_have_local_targets_and_enclosing_first_iterable(self):
        for expression,name in (("[range for range in range(3)]","listcomp"),
                                ("{range for range in range(3)}","setcomp"),
                                ("{range:range+1 for range in range(3)}","dictcomp")):
            with self.subTest(expression=expression):
                unit=parse_source("values="+expression+"\n")
                node=unit.tree.body[0].value;scope=unit.scope_for(node)
                self.assertEqual((scope.name,scope.kind,scope.parent),(name,"comprehension",0))
                target=node.generators[0].target
                self.assertEqual(self.binding(unit,target).owner,scope.ordinal)
                self.assertEqual(unit.nodes[unit.ordinal(target)].scope,scope.ordinal)
                self.assertEqual(self.binding(unit,node.generators[0].iter.func).owner,0)
                for value in ast.walk(node.key if isinstance(node,ast.DictComp)else node.elt):
                    if isinstance(value,ast.Name):self.assertEqual(self.binding(unit,value).owner,scope.ordinal)
                target_symbol=next(value for value in scope.symbols if value.name=="range")
                self.assertTrue({"local","assigned","comp_iter"}<=target_symbol.flags)

    def test_all_targets_are_local_before_later_iterables_execute(self):
        unit=parse_source("z=8\nvalues=[x for x in range(2) for y in z for z in (1,)]\n")
        node=unit.tree.body[1].value;scope=unit.scope_for(node)
        before_store=node.generators[1].iter
        self.assertEqual(self.binding(unit,before_store).owner,scope.ordinal)
        self.assertEqual(unit.nodes[unit.ordinal(before_store)].scope,scope.ordinal)

    def test_nested_scopes_skip_comp_only_names_in_the_physical_parent(self):
        source='''x=9
def f(n):
 first=[x for x in range(n)]
 second=[x for y in range(n)]
 return [[(x,y) for y in range(x)] for x in range(n)]
'''
        unit=parse_source(source);function=unit.tree.body[1]
        first=function.body[0].value;second=function.body[1].value
        self.assertEqual(self.binding(unit,second.elt).owner,0)
        self.assertNotIn("x",unit.signature_for(function).local_names)
        outer=function.body[2].value;inner=outer.elt
        outer_scope=unit.scope_for(outer);inner_scope=unit.scope_for(inner)
        self.assertEqual(inner_scope.parent,outer_scope.ordinal)
        self.assertEqual(self.binding(unit,inner.generators[0].iter.args[0]).owner,outer_scope.ordinal)
        self.assertEqual(unit.nodes[unit.ordinal(inner.generators[0].iter.args[0])].scope,outer_scope.ordinal)
        self.assertEqual(self.binding(unit,inner.elt.elts[0]).owner,outer_scope.ordinal)
        self.assertEqual(self.binding(unit,inner.elt.elts[1]).owner,inner_scope.ordinal)

    def test_official_lambda_and_generator_ids_reparent_to_logical_scope(self):
        source="def f(n):\n return [(lambda:x,(x for y in range(x))) for x in range(n)]\n"
        unit=parse_source(source);official,_=_scope_metadata(unit.table)
        self.assertGreater(len(unit.scopes),len(official))
        for before,after in zip(official,unit.scopes):
            self.assertEqual((before.ordinal,before.name,before.kind,before.line),(after.ordinal,after.name,after.kind,after.line))
        node=unit.tree.body[0].body[0].value;scope=unit.scope_for(node)
        function,generator=node.elt.elts
        for child in (function,generator):
            child_scope=unit.scope_for(child)
            self.assertLess(child_scope.ordinal,len(official))
            self.assertEqual(child_scope.parent,scope.ordinal)
            self.assertIn(child_scope.ordinal,scope.children)
        self.assertEqual(self.binding(unit,function.body).owner,scope.ordinal)
        self.assertEqual(self.binding(unit,generator.elt).owner,scope.ordinal)
        self.assertEqual(self.binding(unit,generator.generators[0].iter.args[0]).owner,scope.ordinal)
        self.assertEqual(unit.nodes[unit.ordinal(generator.generators[0].iter.args[0])].scope,scope.ordinal)
        self.assertEqual(ast.dump(unit.tree,include_attributes=True),ast.dump(ast.parse(source),include_attributes=True))

    def test_same_line_callable_tables_follow_default_iterable_filter_body_order(self):
        source="values=[lambda value=(lambda:target),*,other=(lambda:keyword):body for target in (lambda:iterator)() if (lambda:condition)()]\n"
        unit=parse_source(source);node=unit.tree.body[0].value;scope=unit.scope_for(node)
        outer=node.elt;default=outer.args.defaults[0];keyword=outer.args.kw_defaults[0]
        checks=((node.generators[0].iter.func,"iterator",0),
                (node.generators[0].ifs[0].func,"condition",scope.ordinal),
                (default,"target",scope.ordinal),(keyword,"keyword",scope.ordinal),
                (outer,"body",scope.ordinal))
        for function,reference,parent in checks:
            with self.subTest(reference=reference):
                metadata=unit.scope_for(function)
                self.assertIn(reference,{symbol.name for symbol in metadata.symbols})
                self.assertEqual(metadata.parent,parent)
        self.assertEqual(self.binding(unit,default.body).owner,scope.ordinal)
        self.assertIn("value",unit.signature_for(outer).local_names)
        self.assertIn("other",unit.signature_for(outer).local_names)

    def test_dict_key_value_and_nested_generator_tables_match_official_traversal(self):
        unit=parse_source("values={(lambda:key)():(lambda:value)()for target in range(2)}\n")
        node=unit.tree.body[0].value
        for function,reference in ((node.key.func,"key"),(node.value.func,"value")):
            self.assertIn(reference,{symbol.name for symbol in unit.scope_for(function).symbols})
            self.assertEqual(self.binding(unit,function.body).owner,0)
        unit=parse_source("values=[(a for a in (b for b in range(target)))for target in range(2)]\n")
        inline=unit.tree.body[0].value;outer=inline.elt;inner=outer.generators[0].iter
        self.assertIn("a",{symbol.name for symbol in unit.scope_for(outer).symbols})
        self.assertIn("b",{symbol.name for symbol in unit.scope_for(inner).symbols})
        self.assertEqual(unit.scope_for(outer).parent,unit.scope_for(inline).ordinal)
        self.assertEqual(unit.scope_for(inner).parent,unit.scope_for(inline).ordinal)
        self.assertEqual(self.binding(unit,outer.elt).owner,unit.scope_for(outer).ordinal)
        self.assertEqual(self.binding(unit,inner.elt).owner,unit.scope_for(inner).ordinal)

    def test_walrus_respects_global_nonlocal_and_nested_lambda_namespaces(self):
        source='''state=0
def outer():
 captured=0
 def f():
  nonlocal captured
  global state
  a=[(captured:=x,state:=x) for x in range(3)]
  b=[lambda:(local:=x) for x in range(3)]
  return a,b
 return f
'''
        unit=parse_source(source);outer=unit.tree.body[1];function=outer.body[1]
        expression=function.body[2].value
        scope=unit.scope_for(expression)
        captured,state=(value.target for value in expression.elt.elts)
        self.assertEqual(self.binding(unit,captured).owner,unit.scope_for(outer).ordinal)
        self.assertEqual(self.binding(unit,state).owner,0)
        for target in (captured,state):
            self.assertEqual(self.binding(unit,target).scope,scope.ordinal)
            self.assertEqual(unit.nodes[unit.ordinal(target)].scope,scope.ordinal)
        function_expression=function.body[3].value.elt
        self.assertEqual(self.binding(unit,function_expression.body.target).owner,unit.scope_for(function_expression).ordinal)

    def test_walrus_in_a_nested_generator_skips_all_comprehension_scopes(self):
        unit=parse_source("def f():\n return [((saved:=y) for y in range(x)) for x in range(3)]\n")
        function=unit.tree.body[0];generator=function.body[0].value.elt
        target=generator.elt.target
        self.assertEqual(self.binding(unit,target).owner,unit.scope_for(function).ordinal)
        self.assertEqual(self.binding(unit,target).scope,unit.scope_for(generator).ordinal)

    def test_class_iterable_uses_class_namespace_but_body_skips_it(self):
        source='''def outer():
 value=8
 class C:
  value=3
  values=[(value,__class__) for x in range(value)]
 return C
'''
        unit=parse_source(source);outer=unit.tree.body[0];owner=outer.body[1];node=owner.body[1].value
        self.assertEqual(self.binding(unit,node.generators[0].iter.args[0]).owner,unit.scope_for(owner).ordinal)
        self.assertEqual(self.binding(unit,node.elt.elts[0]).owner,unit.scope_for(outer).ordinal)
        self.assertEqual(self.binding(unit,node.elt.elts[1]).owner,0)
        method_unit=parse_source("class C:\n def method(self):\n  return [__class__ for x in range(2)]\n")
        owner=method_unit.tree.body[0];method=owner.body[0];expression=method.body[0].value
        self.assertEqual(self.binding(method_unit,expression.elt).owner,method_unit.scope_for(owner).ordinal)
        private=parse_source("class _C:\n values=[__value for __value in (1,)]\n")
        node=private.tree.body[0].body[0].value
        self.assertEqual(self.binding(private,node.elt).name,"_C__value")
        self.assertEqual(self.binding(private,node.elt).owner,private.scope_for(node).ordinal)

    def test_reserved_target_names_do_not_rebind_the_module_namespace(self):
        for name in ("__name__","__builtins__","range"):
            with self.subTest(name=name):
                unit=parse_source(f"values=[{name} for {name} in (1,)]\n")
                self.assertIsNone(native_namespace_diagnostic(unit))
                stores=[value for value in unit.bindings if value.name==name and value.role=="store"]
                self.assertTrue(stores)
                self.assertTrue(all(unit.scopes[value.owner].kind=="comprehension"for value in stores))
        unit=parse_source("values=[__name__ for __name__ in (1,)]\n__name__='changed'\n")
        diagnostic=native_namespace_diagnostic(unit)
        self.assertEqual((diagnostic.code,diagnostic.line),("E006",2))
        unit=parse_source("values=[(__name__:=x) for x in (1,)]\n")
        self.assertEqual(native_namespace_diagnostic(unit).code,"E006")

    def test_scope_source_maps_are_stable_and_metadata_never_executes_source(self):
        with tempfile.TemporaryDirectory(prefix="pytors-source-scopes-")as directory:
            marker=Path(directory)/"executed"
            source=f"values=[__import__('pathlib').Path({str(marker)!r}).write_text('bad') for x in (1,)]\n"
            first=build_program(source);second=build_program(source)
            self.assertFalse(marker.exists())
            self.assertEqual(first.source_map,second.source_map)
            by_scope={}
            for location in first.source_map:by_scope.setdefault(location.code,[]).append(location.instruction)
            for values in by_scope.values():self.assertEqual(values,list(range(len(values))))


if __name__=="__main__":unittest.main()
