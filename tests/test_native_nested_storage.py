"""Nested integer lists preserve reference identity and operand evaluation order."""
import shutil
import unittest
import test_native_union_ordering as helpers


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeNestedStorageTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeUnionOrderingTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeUnionOrderingTests.tearDownClass.__func__)
    compile=helpers.NativeUnionOrderingTests.compile
    exercise=helpers.NativeUnionOrderingTests.exercise

    def test_rows_have_shared_identity_and_survive_parent_clear(self):
        self.exercise('''row=[2,4]
a=[row,row]
b=a[0]
a.clear()
b.append(6)
print(row,b,a,row is b)
''',('',))

    def test_shallow_copy_and_repetition_keep_row_identity(self):
        self.exercise('''a=[[1],[2]]
b=a.copy()
c=a*2
d=a+a
b[0].append(7)
c[-1].append(8)
print(a,b,c,d,a[0] is b[0],c[0] is c[2])
''',('',))

    def test_comprehensions_allocate_distinct_rows(self):
        self.exercise('''n=int(input())
a=[[] for _ in range(n)]
for i in range(n):
 a[i].append(i)
print(a)
''',('0\n','1\n','4\n'))

    def test_comprehension_and_row_iteration_preserve_aliases(self):
        self.exercise('''a=[[i,i+1]for i in range(3)]
b=[row for row in a]
for row in a:
 row.append(9)
print(a,b)
''',('',))

    def test_three_dimensions_and_chained_assignment(self):
        self.exercise('''a=[[[1]],[[2]]]
b=c=a[0][0]
b.append(3)
c[0]=4
print(a,b,c,b is c)
''',('',))

    def test_read_index_side_effects_run_before_borrow(self):
        self.exercise('''a=[2,0]
print(a[a.pop()],a)
b=[[2,0]]
print(b[0][b[0].pop()],b)
''',('',))

    def test_index_error_uses_length_after_index_mutation(self):
        self.exercise('''a=[[4,1]]
print("before",end="|")
print(a[0][a[0].pop()])
''',('',))

    def test_assignment_rhs_precedes_receiver_and_indices(self):
        self.exercise('''def mark(tag,value):
 print(tag,end="|")
 return value
a=[[1,2],[3,4]]
a[mark("row",0)][mark("index",-1)]=mark("rhs",7)
print(a)
''',('',))

    def test_augmented_assignment_reads_before_rhs_and_rechecks_negative_index(self):
        self.exercise('''a=[[10,20,30]]
a[0][-1]+=a[0].pop()
print(a)
b=[[1],[2],[3]]
b[0][0]+=b.pop()[0]
print(b)
''',('',))

    def test_assignment_negative_index_renormalizes_after_rhs(self):
        self.exercise('''a=[[1,2,3]]
a[0][-1]=a[0].pop()
print(a)
b=[[4],[5],[6]]
b[-1]=b.pop()
print(b)
''',('',))

    def test_plain_print_observes_later_mutation_star_print_snapshots(self):
        self.exercise('''a=[[1,2],[3]]
row=a[0]
print(a,row,a.clear(),row.append(8),row)
a=[[1],[2]]
print(*a,a.pop(),a)
''',('',))

    def test_list_iteration_mutation_has_short_borrows(self):
        self.exercise('''a=[[1,2,3,4]]
for value in a[0]:
 print(value,end="|")
 if value==1:a[0].pop()
 if value==2:a[0].append(9)
print(a)
''',('',))

    def test_owner_replacement_does_not_redirect_captured_row(self):
        self.exercise('''a=[[1,2],[3]]
row=a[0]
a[0]=[7,8]
row.append(9)
print(a,row)
''',('',))

    def test_len_and_sort_lambda_use_current_aliased_contents(self):
        self.exercise('''a=[[3,1,2]]
b=a[0]
b.sort(key=lambda x:-x)
print(a,len(a),len(b),sorted(b,key=lambda x:x))
b.pop()
print(len(a[0]),next(iter(range(len(b)))))
''',('',))

    def test_bounds_errors_retain_position_and_side_effects(self):
        self.exercise('''a=[[1]]
print("before",end="|")
a[0][-1]+=a[0].pop()
''',('',))

    def test_branch_and_loop_reference_carriers(self):
        self.exercise('''a=[[1],[2]]
if int(input()):
 row=a[0]
else:
 row=a[1]
for i in range(3):
 row.append(i)
print(a,row)
''',('0\n','1\n'))

    def test_integer_modes_use_same_shared_layout(self):
        self.exercise('''a=[[1099511627776,-1099511627776]]
a[0][-1]+=a[0][0]
print(a,sum(a[0]),min(a[0]),max(a[0]))
''',('',))

    def test_nested_values_compare_and_identity_is_separate(self):
        self.exercise('''a=[[1],[2]]
b=[[1],[3]]
c=a.copy()
print(a==b,a<b,a<=b,b>a,b>=a,a!=b,a is c,a[0]is c[0])
print([1]in a,[7]not in a)
''',('',))

    def test_shared_function_arguments_and_return_values_retain_identity(self):
        self.exercise('''def change(rows):
 row=rows[0]
 row.append(7)
 return row
a=[[1],[2]]
b=change(a)
b.append(8)
print(a,b,a[0]is b)
''',('',))

    def test_reversed_creation_captures_length_before_later_arguments(self):
        self.exercise('''a=[[1,2,3]]
print(sum(reversed(a[0]),a[0].pop()),a)
b=[[4,5,6]]
print(list(reversed(b[0])),b)
''',('',))


class NativeNestedStorageFactsTests(unittest.TestCase):
    def test_layout_constraints_do_not_create_runtime_object_identities(self):
        from py2fastrust.frontend import build_program
        from py2fastrust.native_constraints import SemanticGraph,Solver,Allocation,value
        from py2fastrust.native_types import ListType
        unit=build_program('rows=[[1],[2]]\ncopy=rows.copy()\ncopy[0].append(3)\n','facts.py').main
        solver=Solver(SemanticGraph(unit))
        facts=solver.solve()
        source=unit.tree.body[0].value
        self.assertEqual(facts.scope().allocations[unit.ordinal(source)],ListType(ListType('int')))
        outer=next(item for item in solver.allocations.values() if item.site[1]==unit.ordinal(source))
        identities=solver.provenance(solver.field(outer,'element')).alternatives
        self.assertTrue(identities)
        self.assertTrue(all(isinstance(item,Allocation)for item in identities))
        self.assertEqual(len(identities),2)

    def test_recursive_shared_list_layout_remains_explicitly_unsupported(self):
        from py2fastrust import transpile
        result=transpile('a=[]\na.append(a)\nprint(a)\n')
        self.assertFalse(result.success)
        self.assertTrue(result.diagnostics)
        self.assertEqual(result.diagnostics[0].code,'E006')


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeNestedComparisonTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeUnionOrderingTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeUnionOrderingTests.tearDownClass.__func__)
    compile=helpers.NativeUnionOrderingTests.compile
    exercise=helpers.NativeUnionOrderingTests.exercise

    def test_shared_and_unique_lists_compare_by_contents_and_numeric_elements(self):
        self.exercise('''a=[[1,2]]
row=a[0]
print(row==[1,2],[1,2]==row,row!=[1,2],row<[1,3],[1,1]<row)
print(row==[True,2],row>[False,9],row is None,row is not None,row is [1,2])
print([True,2]in a,9 not in a,a.count([1,2]),a.index([True,2]))
''',('',))

    def test_list_scalar_ordering_errors_have_python_types_and_operand_order(self):
        self.exercise('''def mark(tag,value):
 print(tag,end="|")
 return value
a=[[1]]
print(mark("first",3)<a[0]<mark("skipped",4))
''',('',))

    def test_nested_immutable_tuple_rows_and_ordering(self):
        self.exercise('''a=[[]for _ in range(3)]
a[0].append((2,7,1))
a[0].append((1,9,3))
a[1].append((0,4,2))
for neighbor,weight,index in a[0]:
 print(neighbor,weight,index)
a[0].sort(key=lambda edge:edge[1])
print(a,sorted(a),a==[[(2,7,1),(1,9,3)],[(0,4,2)],[]])
''',('',))

    def test_literal_row_sources_and_shared_lambda_parameters(self):
        self.exercise('''print(sum(len(row)for row in [[1,2],[],[3]]))
a=[[2,1],[4,3]]
a[0].sort(key=lambda value:-value)
print(sorted(a,key=lambda row:row[0]))
print((lambda row:row.append(7))(a[0]),a)
''',('',))

    def test_sort_callback_cannot_observe_shared_alias_or_parent(self):
        from py2fastrust import transpile,TranspileOptions
        for source in ('a=[[2,1]]\nb=a[0]\nb.sort(key=lambda value:len(a[0])+value)\n',
                       'a=[[2,1]]\nb=a[0]\na[0].sort(key=lambda value:len(b)+value)\n'):
            for mode in ('i64','i128','bigint'):
                result=transpile(source,TranspileOptions(integer=mode))
                self.assertFalse(result.success)
                self.assertEqual(result.diagnostics[0].code,'E006')

    def test_repeated_same_shape_function_calls_preserve_each_argument_identity(self):
        self.exercise('''def wrap(row):
 return [row]
def forward(row):
 return wrap(row)
a=[1]
b=[2]
x=wrap(a)
y=wrap(b)
z=forward(a)
y[0].append(7)
z[0].append(8)
print(a,b,x,y,z,x[0]is z[0],x[0]is y[0])
''',('',))

    def test_calls_with_different_shared_objects_apply_mutations_to_each(self):
        self.exercise('''def add(rows,number):
 rows[0].append(number)
 return rows[0]
a=[[1]]
b=[[2]]
x=add(a,7)
y=add(b,8)
x.append(9)
y.append(10)
print(a,b,x,y)
''',('',))


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class SharedListInplaceTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeUnionOrderingTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeUnionOrderingTests.tearDownClass.__func__)
    compile=helpers.NativeUnionOrderingTests.compile
    exercise=helpers.NativeUnionOrderingTests.exercise

    def test_name_aliases_and_self_extension_keep_the_same_object(self):
        self.exercise('''outer=[[1,2]]
row=outer[0]
alias=row
row += [3]
row += row
print(outer,row,alias,row is alias)
row *= 2
print(outer,row,alias,row is alias)
''',('',))

    def test_rhs_pop_and_generators_are_consumed_once_after_left_capture(self):
        self.exercise('''outer=[[2,3,1]]
row=outer[0]
row += [row.pop()]
print(outer)
row *= row.pop()
print(outer)
row += (value for value in range(3))
row += (8,9)
print(outer,row)
''',('',))

    def test_zero_negative_and_bool_repeat_preserve_aliases(self):
        self.exercise('''outer=[[1,2],[3,4]]
row=outer[0]
alias=row
row *= 0
print(outer,alias,row is alias)
row += [7]
row *= -2
print(outer,alias)
row += [8]
row *= True
print(outer,alias)
row=outer[1]
row *= False
print(outer)
''',('',))

    def test_none_rhs_errors_follow_rhs_side_effects(self):
        for operator in ('+=','*='):
            self.exercise('def mark():\n print("rhs",end="|")\n return None\nouter=[[1]]\nrow=outer[0]\nprint("before",end="|")\nrow '+operator+' mark()\n',('',))

    def test_tuple_payload_and_nested_rows_are_shallow_shared(self):
        self.exercise('''a=[[(1,2)]]
row=a[0]
row += [(3,4)]
row *= 2
print(a)
b=[[[1],[2]]]
rows=b[0]
rows += rows
rows *= 2
rows[0].append(7)
print(b)
''',('',))

    def test_augmented_row_assignment_rechecks_index_after_mutation(self):
        self.exercise('''a=[[1],[2],[3]]
alias=a[-1]
a[-1] += a.pop()
print(a,alias)
b=[[1],[2],[3]]
alias=b[-1]
b[-1] *= len(b.pop())+1
print(b,alias)
''',('',))

    def test_huge_repeat_count_has_index_sized_overflow(self):
        self.exercise('outer=[[1]]\nrow=outer[0]\nprint("before",end="|")\nrow *= 18446744073709551616\n',('',),modes=('i128','bigint'))

    def test_borrowed_rhs_lists_text_and_mappings_remain_available(self):
        self.exercise('''outer=[[]]
row=outer[0]
other=[4,5]
row += other
print(outer,other)
mapping={7:2,8:3}
row += mapping
print(outer,mapping)
letters=[["x"]]
word="ab"
letters[0] += word
print(letters,word)
''',('',))

    def test_mapping_print_uses_the_common_scalar_representation_and_identity(self):
        self.exercise('''mapping={(1,False):("x",None),(2,True):b"bytes"}
print(mapping)
print(mapping,mapping.clear(),mapping)
''',('',))

    def test_unbound_left_reference_precedes_rhs_effects(self):
        self.exercise('''def mark():
 print("rhs",end="|")
 return [2]
outer=[[1]]
if int(input()):row=outer[0]
row += mark()
print(outer,row)
''',('0\n','1\n'))

    def test_plain_aliases_and_mutating_functions_use_shared_references(self):
        self.exercise('''def add(values,number):
 values.append(number)
def take(values):
 return values.pop()
def identity(values):
 return values
a=[1,2]
b=a
add(a,3)
print(a,b,take(b),a is b)
c=identity(a)
c += [4]
print(a,b,c,c is a)
x=y=[7]
x.append(8)
print(x,y,x is y)
''',('',))

    def test_shared_and_unique_branch_alternatives_keep_one_reference_layout(self):
        self.exercise('''a=[1]
if int(input()):
 b=a
else:
 b=[2]
b.append(7)
print(a,b)
''',('0\n','1\n'))

    def test_mapping_original_numeric_keys_order_clear_and_nested_values(self):
        self.exercise('''d={True:("first",None),2:("second",None)}
d[1]=("updated",None)
print(d)
d.clear()
d[4]=("fourth",None)
d[3]=("third",None)
print(d)
''',('',))

    def test_mapping_key_deletion_keeps_the_original_boundary_source(self):
        self.exercise('d={1:2}\ndel d[1]\nprint(d)\n',('',))
