"""A failed indexed value cannot fabricate None or execute a later store."""
import ast,shutil,unittest
from types import SimpleNamespace
import test_native_stdio as stdio_tests
from py2fastrust import TranspileOptions,transpile

HEADER='class Marker:\n    pass\nmarker=Marker()\n'
TRACE='''def trace(label,value):
    print(label)
    return value
'''

class AbruptPointRevisitContracts(unittest.TestCase):
    class Model:
        integer='i64'
        def __init__(self):
            self.records={};self.nodes={};self.values={}
            self.namespace=SimpleNamespace(contribute=lambda *args,**kwargs:False)
        def cell(self,plan,node,tag=None,args=()):
            from py2fastrust.native_classes import Cell,merge
            value=self.nodes.setdefault((plan.index,id(node)),Cell())
            if tag is not None:merge(value,Cell(tag,args),node,allow_unresolved=True)
            self.records[plan.index,id(node)]=value
            return value
        def remember(self,plan,node,value):self.records[plan.index,id(node)]=value;return value
        def expression(self,plan,node,environment):return self.values[id(node)]
        def contribute(self,target,source,node):
            from py2fastrust.native_classes import merge
            merge(target,source,node,allow_unresolved=True)

    def test_tuple_abrupt_prefix_is_removed_when_producer_becomes_live(self):
        from py2fastrust.native_classes import Cell,shape
        from py2fastrust.native_types import EMPTY,TupleType
        from py2fastrust.native_abrupt_values import analyze_tuple
        model=self.Model();plan=SimpleNamespace(index=0);node=ast.parse('(first,second)',mode='eval').body
        model.values={id(node.elts[0]):Cell(EMPTY),id(node.elts[1]):Cell('str')}
        self.assertEqual(shape(analyze_tuple(model,plan,node,{})),EMPTY)
        self.assertIn((0,id(node)),model.abrupt_tuple_prefixes)
        model.values[id(node.elts[0])]=Cell('int')
        self.assertEqual(shape(analyze_tuple(model,plan,node,{})),TupleType(('int','str')))
        self.assertNotIn((0,id(node)),model.abrupt_tuple_prefixes)
        self.assertEqual(shape(model.records[0,id(node)]),TupleType(('int','str')))

    def test_subscript_point_recovers_from_none_to_live_list_alternative(self):
        from py2fastrust.native_classes import Cell,shape
        from py2fastrust.native_types import EMPTY
        from py2fastrust.native_union_sequences import analyze_subscript
        model=self.Model();model.final=False;plan=SimpleNamespace(index=0);node=ast.parse('owner[0]',mode='eval').body
        self.assertEqual(shape(analyze_subscript(model,plan,node,Cell('none'),Cell('int'))),EMPTY)
        owner=Cell('union',(Cell('none'),Cell('list',(Cell('int'),))))
        self.assertEqual(shape(analyze_subscript(model,plan,node,owner,Cell('int'))),'int')
        self.assertEqual(shape(model.records[0,id(node)]),'int')


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeAbruptSubscriptTests(unittest.TestCase):
    setUpClass=classmethod(stdio_tests.NativeStdioTests.setUpClass.__func__)
    tearDownClass=classmethod(stdio_tests.NativeStdioTests.tearDownClass.__func__)
    compile=stdio_tests.NativeStdioTests.compile
    differential=stdio_tests.NativeStdioTests.differential

    def test_tuple_stops_after_original_receiver_and_index_effects(self):
        source=HEADER+TRACE+'''answer=(trace('prefix',1),trace('receiver',7)[trace('index',0)],trace('unreachable',9))
print('after')
'''
        self.differential(source,profiles=(False,True))

    def test_assignment_targets_do_not_run_after_failing_rhs(self):
        source=HEADER+TRACE+'''def target():
    print('target')
    return [0]
target()[0]=other=trace('rhs',7)[trace('index',0)]
print('after')
'''
        self.differential(source,profiles=(False,True))

    def test_annotated_assignment_target_waits_for_rhs(self):
        source=HEADER+TRACE+'''def target():
    print('target')
    return [0]
target()[0]: int=trace('rhs',None)[trace('index',0)]
print('after')
'''
        self.differential(source,profiles=(False,True))

    def test_failing_nested_owner_does_not_evaluate_outer_index(self):
        source=HEADER+TRACE+'''answer=trace('owner',7)[trace('inner index',0)][trace('outer index',1)]
print('after')
'''
        self.differential(source,profiles=(False,True))

    def test_failing_index_retains_outer_owner_evaluation(self):
        source=HEADER+TRACE+'''answer=trace('outer owner',[10])[trace('index owner',7)[trace('index key',0)]]
print('after')
'''
        self.differential(source,profiles=(False,True))

    def test_closed_bad_indices_and_tuple_bounds_keep_original_error(self):
        for expression in ["(1,2)[7]", "'abc'[None]", "b'ab'[1.5]", "[8]['key']"]:
            self.differential(HEADER+'result='+expression+'\nprint(99)\n',profiles=(False,True))

    def test_mixed_live_and_abrupt_receiver_preserves_successful_edge(self):
        source=HEADER+'''flag=int(input())
row=[4] if flag else 7
values=[]
print('before')
x=row[0]
values.append(x)
print(values)
'''
        self.differential(source,[b'0\n',b'1\n'],profiles=(False,True))

    def test_bare_expression_ends_only_its_normal_edge(self):
        source=HEADER+TRACE+'''trace('receiver',None)[trace('key',0)]
print('unreachable')
'''
        self.differential(source,profiles=(False,True))

    def test_invalid_weighted_edge_does_not_pollute_parent_layout(self):
        source='''class Walker:
    def __init__(self,adj,weighted):
        self.adj=adj
        self.weighted=weighted
        self.parent=[-1]*len(adj)
        self.walk()
    def walk(self):
        adj,parent=self.adj,self.parent
        stack=[0]
        while stack:
            v=stack.pop()
            if self.weighted:
                for edge in adj[v]:
                    u,w=edge[0],edge[1]
                    parent[u]=(v,w)
                    stack.append(u)
            else:
                for u in adj[v]:
                    parent[u]=v
                    stack.append(u)
    def ancestor(self,u):
        while self.parent[u]>=0:
            u=self.parent[u]
        return u
weighted=bool(int(input()))
walker=Walker([[1],[]],weighted)
print(walker.parent,walker.ancestor(1))
'''
        self.differential(source,[b'0\n',b'1\n'],profiles=(False,True))

    def test_imported_callee_result_widens_from_none_to_live_tuple(self):
        from test_native_pending_geometry import PendingGeometryExecution
        module='''def choose(flag):
    if flag:return later()
    return None

def later():
    return 4,9
'''
        source='''from nodes import choose
row=choose(int(input()))
print('before')
pair=row[0],row[1]
print(pair)
'''
        PendingGeometryExecution.check_module(self,module,source,[b'0\n',b'1\n'])

    def test_class_try_finally_retains_existing_explicit_boundary(self):
        source=HEADER+'''try:
    x=None[0]
finally:
    print('cleanup')
'''
        result=transpile(source,TranspileOptions(filename='cleanup.py'))
        self.assertFalse(result.success)
        message='\n'.join(map(str,result.diagnostics))
        self.assertIn('cleanup.py:',message)
        self.assertIn('E006',message)
