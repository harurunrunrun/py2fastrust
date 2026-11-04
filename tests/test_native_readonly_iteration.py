"""Proved loop leases preserve aliases, eager arguments and every exit edge."""
import shutil
import unittest
import test_native_union_ordering as helpers


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class NativeReadonlyIterationTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeUnionOrderingTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeUnionOrderingTests.tearDownClass.__func__)
    compile=helpers.NativeUnionOrderingTests.compile
    exercise=helpers.NativeUnionOrderingTests.exercise

    def test_disjoint_append(self):
        self.exercise('rows=[[1,2,3]]\noutput=[]\nfor value in rows[0]:output.append(value+1)\nprint(rows,output)\n',('',))

    def test_source_parent_cleared(self):
        self.exercise('rows=[[1,2,3]]\nfor value in rows[0]:\n print(value)\n rows.clear()\nprint(rows)\n',('',))

    def test_callback_alias_mutation(self):
        self.exercise('def change(row,value):\n if value==1:row.append(4)\nrows=[[1,2,3]]\nfor value in rows[0]:\n print(value)\n change(rows[0],value)\nprint(rows)\n',('',))

    def test_callback_disjoint_mutation(self):
        self.exercise('def add(output,value):output.append(value)\nrows=[[1,2,3]]\noutput=[]\nfor value in rows[0]:add(output,value)\nprint(rows,output)\n',('',))

    def test_repeated_actual_same_object(self):
        self.exercise('rows=[[1,2,3]]*2\nfor value in rows[0]:\n print(value)\n if value==1:rows[1].append(4)\nprint(rows)\n',('',))

    def test_nested_readers(self):
        self.exercise('rows=[[1,2,3]]\ntotal=0\nfor value in rows[0]:\n for other in rows[0]:total+=value*other\nprint(total)\n',('',))

    def test_break_continue_else(self):
        self.exercise('rows=[[1,2,3]]\nresult=[]\nfor value in rows[0]:\n if value==2:continue\n result.append(value)\n if value==3:break\nelse:result.append(9)\nprint(result)\n',('',))

    def test_nested_mutating_reader_once(self):
        self.exercise('rows=[[1,2]]\nfor value in rows[0]:\n for other in rows[0]:\n  print(value,other)\n  if value==1 and other==1:rows[0].append(3)\nprint(rows)\n',('',))

    def test_typed_zero_and_else_lease_release(self):
        self.exercise('rows=[list(range(int(input())))]\nfor value in rows[0]:print(value)\nelse:rows[0].append(99)\nprint(rows)\n',('0\n', '3\n'))

    def test_post_loop_mutation(self):
        self.exercise('rows=[[1,2,3]]\nfor value in rows[0]:print(value)\nrows[0].append(99)\nprint(rows)\n',('',))

    def test_callee_read_then_parent_mutate_after_return(self):
        self.exercise('def first(row):\n for value in row:return value\n return -1\nrows=[[1,2,3]]\nprint(first(rows[0]))\nrows[0].append(99)\nprint(rows)\n',('',))

    def test_enumerate_start_pops_source(self):
        self.exercise('rows=[[1,2,3]]\nfor index,value in enumerate(rows[0],rows[0].pop()):print(index,value)\nprint(rows)\n',('',))

    def test_enumerate_start_replaces_parent(self):
        self.exercise('def start(rows):\n rows[0]=[9]\n return 5\nrows=[[1,2]]\nfor index,value in enumerate(rows[0],start(rows)):print(index,value)\nprint(rows)\n',('',))

    def test_enumerate_else_releases_lease(self):
        self.exercise('rows=[[1,2,3]]\nfor index,value in enumerate(rows[0]):print(index,value)\nelse:rows[0].clear()\nprint(rows)\n',('',))

    def test_mutating_global_receiver_rebound(self):
        self.exercise('def mark():current.append(9)\na=[1,2]\nb=[3,4]\ncurrent=a\nfor stage in range(2):\n for value in b:\n  mark()\n  print(value)\n  break\n current=b\nprint(a,b)\n',("",))

    def test_returned_global_source_rebound(self):
        self.exercise('def current_values():return current\na=[1,2]\nb=[3,4]\ncurrent=a\nfor stage in range(2):\n for value in current_values():\n  b.append(9)\n  print(value)\n  break\n current=b\nprint(a,b)\n',("",))

    def test_transitive_returned_global_rebound(self):
        self.exercise('def helper():return current\ndef current_values():return helper()\na=[1,2]\nb=[3,4]\ncurrent=a\nfor stage in range(2):\n for value in current_values():\n  b.append(9)\n  print(value)\n  break\n current=b\nprint(a,b)\n',("",))

    def test_returned_nested_global_rebound(self):
        self.exercise('def current_values():return holder[0]\na=[1,2]\nb=[3,4]\nholder=[a]\nfor stage in range(2):\n for value in current_values():\n  b.append(9)\n  print(value)\n  break\n holder=[b]\nprint(a,b)\n',("",))

    def test_captured_default_retains_original(self):
        self.exercise('a=[1,2]\nb=[3,4]\ndef original(values=a):return values\ncurrent=a\nfor stage in range(2):\n for value in original():\n  b.append(9)\n  print(value)\n  break\n current=b\nprint(a,b)\n',("",))

    def test_captured_default_alias_after_clear(self):
        self.exercise('row=[1]\ndef add(target=row):target.append(2)\nrow.clear()\nrow.append(1)\nfor value in row:\n add()\n print(value)\n break\nprint(row)\n',("",))

    def test_hidden_tuple_alias_after_clear(self):
        self.exercise('row=[1]\nholder=(row,)\nrow.clear()\nrow.append(1)\nfor value in row:\n holder[0].append(2)\n print(value)\n break\nprint(row,holder)\n',("",))

    def test_rebound_after_clear_is_distinct(self):
        self.exercise('row=[1]\nholder=[row]\nrow.clear()\nrow=[3]\nfor value in row:\n holder[0].append(2)\n print(value)\nprint(row,holder)\n',("",))

    def test_same_clear_site_distinct_arguments(self):
        self.exercise('def reset(row):\n row.clear()\n row.append(1)\n return row\na=[1]\nb=[2]\nfor row in [a,b]:reset(row)\nfor value in a:\n b.append(3)\n print(value)\n break\nprint(a,b)\n',("",))

    def test_cleared_refilled_parent_getitem(self):
        self.exercise('def replace(holder,new):\n holder.clear()\n holder.append(new)\nold=[1,2]\nnew=[3,4]\nholder=[old]\nreplace(holder,new)\nfor value in holder[0]:\n new.append(9)\n print(value)\n break\nprint(old,new,holder)\n',("",))

    def test_cleared_refilled_parent_getter(self):
        self.exercise('def replace(holder,new):\n holder.clear()\n holder.append(new)\ndef load(holder):return holder[0]\nold=[1,2]\nnew=[3,4]\nholder=[old]\nreplace(holder,new)\nfor value in load(holder):\n new.append(9)\n print(value)\n break\nprint(old,new,holder)\n',("",))

    def test_returned_refilled_parent_item(self):
        self.exercise('def replace(holder,new):\n holder.clear()\n holder.append(new)\n return holder[0]\nold=[1,2]\nnew=[3,4]\nholder=[old]\nsource=replace(holder,new)\nfor value in source:\n new.append(9)\n print(value)\n break\nprint(old,new,holder)\n',("",))

    def test_deque_destination(self):
        self.exercise('from collections import deque\nrows=[[1,2,3]]\noutput=deque()\nfor value in rows[0]:output.append(value)\nprint(list(output),output.popleft())\n',("",))

    def test_set_destination(self):
        self.exercise('rows=[[1,2,1,3]]\nseen=set()\noutput=[]\nfor value in rows[0]:\n if value not in seen:\n  seen.add(value)\n  output.append(value)\nprint(output,len(seen))\n',("",))

    def test_dict_destination(self):
        self.exercise('rows=[[1,2,1,3]]\ncounts={}\nfor value in rows[0]:counts[value]=counts.get(value,0)+1\nprint(sorted(counts.items()))\n',("",))

    def test_heap_destination(self):
        self.exercise('import heapq\nrows=[[3,1,2]]\nqueue=[]\nfor value in rows[0]:heapq.heappush(queue,(value,-value))\nwhile queue:print(heapq.heappop(queue))\n',("",))

    def test_bisect_destination(self):
        self.exercise('import bisect\nrows=[[3,1,2]]\noutput=[]\nfor value in rows[0]:bisect.insort(output,value)\nprint(rows,output)\n',("",))

    def test_bisect_alias_source(self):
        self.exercise('import bisect\nrows=[[1,2,3]]\noutput=rows[0]\nfor value in rows[0]:\n bisect.insort(output,9)\n print(value)\n break\nprint(rows,output)\n',("",))

    def test_deep_parent_clear_refill_alias(self):
        self.exercise('def refill(holder, item):\n    holder.clear()\n    holder.append(item)\nfirst, second, inserted = [1], [2], [7]\nold, new = [first], [second]\nparent = [old]\nrefill(parent, new)\nparent[0].clear()\nparent[0].append(inserted)\nfor value in new[0]:\n    inserted.append(9)\n    print(value)\n    break\nprint(old, new, parent)\n',("",))

    def test_loop_write_before_parent_retarget(self):
        self.exercise('def refill(holder, item):\n    holder.clear()\n    holder.append(item)\nfirst, second, inserted = [1], [2], [7]\nold, new = [first], [second]\nparent = [old]\nfor phase in range(2):\n    parent[0].append(inserted)\n    if phase == 0:\n        refill(parent, new)\nfor value in new[-1]:\n    inserted.append(9)\n    print(value)\n    break\nprint(old, new, parent)\n',("",))

    def test_deep_iter_source(self):
        self.exercise('def refill(holder, item):\n    holder.clear()\n    holder.append(item)\nfirst, second, inserted = [1], [2], [7]\nold, new = [first], [second]\nparent = [old]\nrefill(parent, new)\nparent[0].clear()\nparent[0].append(inserted)\nfor value in iter(new[0]):\n    inserted.append(9)\n    print(value)\n    break\nprint(old, new, parent)\n',("",))

    def test_deep_stored_enumerate_source(self):
        self.exercise('def refill(holder, item):\n    holder.clear()\n    holder.append(item)\nfirst, second, inserted = [1], [2], [7]\nold, new = [first], [second]\nparent = [old]\nrefill(parent, new)\nparent[0].clear()\nparent[0].append(inserted)\ncursor = enumerate(new[0], 5)\nfor index, value in cursor:\n    inserted.append(9)\n    print(index, value)\n    break\nprint(old, new, parent)\n',("",))

    def test_deep_stored_iter_consumed_by_list(self):
        self.exercise('def refill(holder, item):\n    holder.clear()\n    holder.append(item)\nfirst, second, inserted = [1], [2], [7]\nold, new = [first], [second]\nparent = [old]\nrefill(parent, new)\nparent[0].clear()\nparent[0].append(inserted)\ncursor = iter(new[0])\nfor value in [1, 2]:\n    print(value, list(cursor))\nprint(old, new, parent)\n',("",))

    def test_reiterated_cursor(self):
        self.exercise('values=[1,2,3]\ncursor=iter(values)\nfor step in range(4):cursor=iter(cursor)\nprint(list(cursor),values)\n',("",))

    def test_reiterated_cursor_through_function(self):
        self.exercise('def again(cursor):return iter(cursor)\nvalues=[1,2,3]\ncursor=iter(values)\nfor step in range(4):cursor=again(cursor)\nprint(list(cursor),values)\n',("",))

    def test_copied_nested_reference(self):
        self.exercise('def refill(holder, item):\n    holder.clear()\n    holder.append(item)\nfirst, second = [1], [2]\nold, new = [first], [second]\nparent = [old]\nrefill(parent, new)\ncopied = parent[0].copy()\nselected = copied[0]\nfor value in selected:\n    second.append(9)\n    print(value)\n    break\nprint(first, second, parent)\n',("",))

    def test_popped_nested_reference(self):
        self.exercise('def refill(holder, item):\n    holder.clear()\n    holder.append(item)\nfirst, second = [1], [2]\nold, new = [first], [second]\nparent = [old]\nrefill(parent, new)\nselected = parent[0].pop()\nfor value in selected:\n    second.append(9)\n    print(value)\n    break\nprint(first, second, parent)\n',("",))

    def test_dict_values_reference(self):
        self.exercise('def refill(holder, item):\n    holder.clear()\n    holder.append(item)\nfirst, second = [1], [2]\nold, new = {"item": first}, {"item": second}\nparent = [old]\nrefill(parent, new)\nselected = list(parent[0].values())[0]\nfor value in selected:\n    second.append(9)\n    print(value)\n    break\nprint(first, second, parent)\n',("",))

    def test_identity_cache_distinguishes_symbolic_receivers(self):
        self.exercise('def refill(holder, item):\n    holder.clear()\n    holder.append(item)\ndef identity(item):return item\nfirst, second, third = [1], [2], [3]\nold, left, right = [first], [second], [third]\np, q = [old], [old]\nrefill(p, left)\nrefill(q, right)\nidentity(p[0])\nselected = identity(q[0])\nfor value in selected[0]:\n    third.append(9)\n    print(value)\n    break\nprint(first, second, third)\n',("",))

    def test_transitive_cache_distinguishes_symbolic_receivers(self):
        self.exercise('def refill(holder, item):\n    holder.clear()\n    holder.append(item)\ndef identity(item):return item\ndef outer(item):return identity(item)\nfirst, second, third = [1], [2], [3]\nold, left, right = [first], [second], [third]\np, q = [old], [old]\nrefill(p, left)\nrefill(q, right)\nouter(p[0])\nselected = outer(q[0])\nfor value in selected[0]:\n    third.append(9)\n    print(value)\n    break\nprint(first, second, third)\n',("",))

    def test_loop_header_symbolic_argument_cache(self):
        self.exercise('def refill(holder, item):\n    holder.clear()\n    holder.append(item)\ndef identity(item):return item\nfirst, second, third = [1], [2], [3]\nold, left, right = [first], [second], [third]\np, q = [old], [old]\nrefill(p, left)\nrefill(q, right)\nholder = p\nfor phase in range(2):\n    selected = identity(holder[0])\n    for value in selected[0]:\n        third.append(9)\n        print(value)\n        break\n    holder = q\nprint(first, second, third)\n',("",))

    def test_transitive_loop_header_symbolic_argument_cache(self):
        self.exercise('def refill(holder, item):\n    holder.clear()\n    holder.append(item)\ndef identity(item):return item\ndef outer(item):return identity(item)\nfirst, second, third = [1], [2], [3]\nold, left, right = [first], [second], [third]\np, q = [old], [old]\nrefill(p, left)\nrefill(q, right)\nholder = p\nfor phase in range(2):\n    selected = outer(holder[0])\n    for value in selected[0]:\n        third.append(9)\n        print(value)\n        break\n    holder = q\nprint(first, second, third)\n',("",))

    def test_global_cache_distinguishes_symbolic_bindings(self):
        self.exercise('def refill(holder, item):\n    holder.clear()\n    holder.append(item)\ndef current_values():return current\nfirst, second, third = [1], [2], [3]\nold, left, right = [first], [second], [third]\np, q = [old], [old]\nrefill(p, left)\nrefill(q, right)\ncurrent = p[0]\nfor phase in range(2):\n    for value in current_values()[0]:\n        third.append(9)\n        print(value)\n        break\n    current = q[0]\nprint(first, second, third)\n',("",))

    def test_transitive_global_cache_distinguishes_symbolic_bindings(self):
        self.exercise('def refill(holder, item):\n    holder.clear()\n    holder.append(item)\ndef helper():return current\ndef current_values():return helper()\nfirst, second, third = [1], [2], [3]\nold, left, right = [first], [second], [third]\np, q = [old], [old]\nrefill(p, left)\nrefill(q, right)\ncurrent = p[0]\nfor phase in range(2):\n    for value in current_values()[0]:\n        third.append(9)\n        print(value)\n        break\n    current = q[0]\nprint(first, second, third)\n',("",))

    def test_effectful_attribute_iteration_target(self):
        self.exercise("events=[]\nclass Slot:\n def __init__(self):self.value=0\nslot=Slot()\nvalues=[2,3]\ndef receiver():\n events.append('target')\n values.append(7)\n return slot\nfor receiver().value in values:\n print(slot.value,values)\n break\nprint(events)\n",("",))

    def test_preloop_sort_callback_cannot_hide_new_heap_aliases(self):
        self.exercise('first=[1]\nsecond=[2]\nholder=[first]\ndef key(value):\n holder[0]=second\n return value\norder=[3,1,2]\norder.sort(key=key)\nfor value in holder[0]:\n second.append(9)\n print(value)\n break\nprint(first,second,holder,order)\n',("",))


class NativeIterationIdentityFactsTests(unittest.TestCase):
    def fact(self,source):
        import ast
        from py2fastrust.frontend import build_program
        from py2fastrust.native_constraints import analyze
        unit=build_program(source,"iteration_effects.py").main
        statement=max((node for node in ast.walk(unit.tree)if isinstance(node,ast.For)),key=lambda node:node.lineno)
        return analyze(unit).scope().iteration_access[unit.ordinal(statement)]

    def test_global_binding_dependencies(self):
        for source in ('def mark():current.append(9)\na=[1,2]\nb=[3,4]\ncurrent=a\nfor stage in range(2):\n for value in b:\n  mark()\n  print(value)\n  break\n current=b\nprint(a,b)\n', 'def current_values():return current\na=[1,2]\nb=[3,4]\ncurrent=a\nfor stage in range(2):\n for value in current_values():\n  b.append(9)\n  print(value)\n  break\n current=b\nprint(a,b)\n', 'def helper():return current\ndef current_values():return helper()\na=[1,2]\nb=[3,4]\ncurrent=a\nfor stage in range(2):\n for value in current_values():\n  b.append(9)\n  print(value)\n  break\n current=b\nprint(a,b)\n', 'def current_values():return holder[0]\na=[1,2]\nb=[3,4]\nholder=[a]\nfor stage in range(2):\n for value in current_values():\n  b.append(9)\n  print(value)\n  break\n holder=[b]\nprint(a,b)\n'):
            with self.subTest(source=source):
                self.assertFalse(self.fact(source).readonly)

    def test_clear_epochs_keep_physical_identity(self):
        for source in ('row=[1]\nholder=[row]\nrow.clear()\nrow.append(1)\nfor value in row:\n holder[0].append(2)\n print(value)\n break\nprint(row,holder)\n', 'row=[1]\ndef add(target=row):target.append(2)\nrow.clear()\nrow.append(1)\nfor value in row:\n add()\n print(value)\n break\nprint(row)\n', 'row=[1]\nholder=(row,)\nrow.clear()\nrow.append(1)\nfor value in row:\n holder[0].append(2)\n print(value)\n break\nprint(row,holder)\n'):
            with self.subTest(source=source):
                self.assertFalse(self.fact(source).readonly)

    def test_clear_refill_field_aliases(self):
        for source in ('def replace(holder,new):\n holder.clear()\n holder.append(new)\nold=[1,2]\nnew=[3,4]\nholder=[old]\nreplace(holder,new)\nfor value in holder[0]:\n new.append(9)\n print(value)\n break\nprint(old,new,holder)\n', 'def replace(holder,new):\n holder.clear()\n holder.append(new)\ndef load(holder):return holder[0]\nold=[1,2]\nnew=[3,4]\nholder=[old]\nreplace(holder,new)\nfor value in load(holder):\n new.append(9)\n print(value)\n break\nprint(old,new,holder)\n'):
            with self.subTest(source=source):
                self.assertFalse(self.fact(source).readonly)

    def test_captured_defaults_keep_old_binding(self):
        for source in ('a=[1,2]\nb=[3,4]\ndef original(values=a):return values\ncurrent=a\nfor stage in range(2):\n for value in original():\n  b.append(9)\n  print(value)\n  break\n current=b\nprint(a,b)\n',):
            with self.subTest(source=source):
                self.assertTrue(self.fact(source).readonly)

    def test_symbolic_field_writes_reach_current_objects(self):
        for source in ('def refill(holder, item):\n    holder.clear()\n    holder.append(item)\nfirst, second, inserted = [1], [2], [7]\nold, new = [first], [second]\nparent = [old]\nrefill(parent, new)\nparent[0].clear()\nparent[0].append(inserted)\nfor value in new[0]:\n    inserted.append(9)\n    print(value)\n    break\nprint(old, new, parent)\n', 'def refill(holder, item):\n    holder.clear()\n    holder.append(item)\ndef get(holder):\n    return holder[0]\nfirst, second, inserted = [1], [2], [7]\nold, new = [first], [second]\nparent = [old]\nrefill(parent, new)\nget(parent).clear()\nget(parent).append(inserted)\nfor value in get(new):\n    inserted.append(9)\n    print(value)\n    break\nprint(old, new, parent)\n', 'def refill(holder, item):\n    holder.clear()\n    holder.append(item)\nfirst, second, inserted = [1], [2], [7]\nold, new = [first], [second]\nparent = [old]\nfor phase in range(2):\n    parent[0].append(inserted)\n    if phase == 0:\n        refill(parent, new)\nfor value in new[-1]:\n    inserted.append(9)\n    print(value)\n    break\nprint(old, new, parent)\n'):
            with self.subTest(source=source):
                fact=self.fact(source)
                self.assertFalse(fact.readonly)
                self.assertTrue(fact.sources.intersection(fact.mutations))

    def test_stored_iterators_retain_symbolic_input_roots(self):
        for source in ('def refill(holder, item):\n    holder.clear()\n    holder.append(item)\nfirst, second, inserted = [1], [2], [7]\nold, new = [first], [second]\nparent = [old]\nrefill(parent, new)\nparent[0].clear()\nparent[0].append(inserted)\nfor value in iter(new[0]):\n    inserted.append(9)\n    print(value)\n    break\nprint(old, new, parent)\n', 'def refill(holder, item):\n    holder.clear()\n    holder.append(item)\nfirst, second, inserted = [1], [2], [7]\nold, new = [first], [second]\nparent = [old]\nrefill(parent, new)\nparent[0].clear()\nparent[0].append(inserted)\ncursor = enumerate(new[0], 5)\nfor index, value in cursor:\n    inserted.append(9)\n    print(index, value)\n    break\nprint(old, new, parent)\n'):
            with self.subTest(source=source):
                fact=self.fact(source)
                self.assertFalse(fact.readonly)
                self.assertTrue(fact.sources.intersection(fact.mutations))

    def test_method_results_retain_symbolic_fields(self):
        for source in ('def refill(holder, item):\n    holder.clear()\n    holder.append(item)\nfirst, second = [1], [2]\nold, new = [first], [second]\nparent = [old]\nrefill(parent, new)\ncopied = parent[0].copy()\nselected = copied[0]\nfor value in selected:\n    second.append(9)\n    print(value)\n    break\nprint(first, second, parent)\n', 'def refill(holder, item):\n    holder.clear()\n    holder.append(item)\nfirst, second = [1], [2]\nold, new = [first], [second]\nparent = [old]\nrefill(parent, new)\nselected = parent[0].pop()\nfor value in selected:\n    second.append(9)\n    print(value)\n    break\nprint(first, second, parent)\n', 'def refill(holder, item):\n    holder.clear()\n    holder.append(item)\nfirst, second = [1], [2]\nold, new = {"item": first}, {"item": second}\nparent = [old]\nrefill(parent, new)\nselected = parent[0].get("item")\nfor value in selected:\n    second.append(9)\n    print(value)\n    break\nprint(first, second, parent)\n', 'def refill(holder, item):\n    holder.clear()\n    holder.append(item)\nfirst, second = [1], [2]\nold, new = {"item": first}, {"item": second}\nparent = [old]\nrefill(parent, new)\nselected = list(parent[0].values())[0]\nfor value in selected:\n    second.append(9)\n    print(value)\n    break\nprint(first, second, parent)\n'):
            with self.subTest(source=source):
                fact=self.fact(source)
                self.assertFalse(fact.readonly)
                self.assertTrue(fact.sources.intersection(fact.mutations))

    def test_cached_calls_keep_widened_symbolic_arguments(self):
        for source in ('def refill(holder, item):\n    holder.clear()\n    holder.append(item)\ndef identity(item):return item\nfirst, second, third = [1], [2], [3]\nold, left, right = [first], [second], [third]\np, q = [old], [old]\nrefill(p, left)\nrefill(q, right)\nholder = p\nfor phase in range(2):\n    selected = identity(holder[0])\n    for value in selected[0]:\n        third.append(9)\n        print(value)\n        break\n    holder = q\nprint(first, second, third)\n', 'def refill(holder, item):\n    holder.clear()\n    holder.append(item)\ndef identity(item):return item\ndef outer(item):return identity(item)\nfirst, second, third = [1], [2], [3]\nold, left, right = [first], [second], [third]\np, q = [old], [old]\nrefill(p, left)\nrefill(q, right)\nholder = p\nfor phase in range(2):\n    selected = outer(holder[0])\n    for value in selected[0]:\n        third.append(9)\n        print(value)\n        break\n    holder = q\nprint(first, second, third)\n'):
            with self.subTest(source=source):
                fact=self.fact(source)
                self.assertFalse(fact.readonly)
                self.assertTrue(fact.sources.intersection(fact.mutations))

    def test_global_dependencies_keep_symbolic_binding_paths(self):
        for source in ('def refill(holder, item):\n    holder.clear()\n    holder.append(item)\ndef current_values():return current\nfirst, second, third = [1], [2], [3]\nold, left, right = [first], [second], [third]\np, q = [old], [old]\nrefill(p, left)\nrefill(q, right)\ncurrent = p[0]\nfor phase in range(2):\n    for value in current_values()[0]:\n        third.append(9)\n        print(value)\n        break\n    current = q[0]\nprint(first, second, third)\n', 'def refill(holder, item):\n    holder.clear()\n    holder.append(item)\ndef helper():return current\ndef current_values():return helper()\nfirst, second, third = [1], [2], [3]\nold, left, right = [first], [second], [third]\np, q = [old], [old]\nrefill(p, left)\nrefill(q, right)\ncurrent = p[0]\nfor phase in range(2):\n    for value in current_values()[0]:\n        third.append(9)\n        print(value)\n        break\n    current = q[0]\nprint(first, second, third)\n'):
            with self.subTest(source=source):
                fact=self.fact(source)
                self.assertFalse(fact.readonly)
                self.assertTrue(fact.sources.intersection(fact.mutations))

    def test_unmodeled_iteration_targets_are_opaque(self):
        for source in ('values=[1,2,3]\nalias=values\nfor alias[0] in values:\n print(values)\n', 'values=[(1,8),(2,9)]\nfor first,values[0] in values:\n print(first,values)\n'):
            with self.subTest(source=source):
                fact=self.fact(source)
                self.assertFalse(fact.readonly)
                self.assertTrue(fact.opaque)

    def test_unfinished_cfg_fixed_point_is_not_a_disjointness_proof(self):
        fact=self.fact('first=[1]\nsecond=[2]\np0=first\np1=second\np2=second\np3=second\np4=second\np5=second\np6=second\np7=second\np8=second\np9=second\np10=second\np11=second\np12=second\np13=second\np14=second\np15=second\np16=second\np17=second\np18=second\np19=second\np20=second\np21=second\np22=second\np23=second\np24=second\np25=second\np26=second\np27=second\np28=second\np29=second\np30=second\np31=second\np32=second\np33=second\np34=second\np35=second\np36=second\np37=second\np38=second\np39=second\np40=second\np41=second\np42=second\np43=second\np44=second\np45=second\np46=second\np47=second\np48=second\np49=second\np50=second\np51=second\np52=second\np53=second\np54=second\np55=second\np56=second\np57=second\np58=second\np59=second\np60=second\np61=second\np62=second\np63=second\np64=second\np65=second\np66=second\np67=second\np68=second\np69=second\np70=second\np71=second\np72=second\np73=second\np74=second\np75=second\np76=second\np77=second\np78=second\np79=second\np80=second\np81=second\np82=second\np83=second\np84=second\np85=second\np86=second\np87=second\np88=second\np89=second\np90=second\np91=second\np92=second\np93=second\np94=second\np95=second\np96=second\np97=second\np98=second\np99=second\np100=second\np101=second\np102=second\np103=second\np104=second\np105=second\np106=second\np107=second\np108=second\np109=second\np110=second\np111=second\np112=second\np113=second\np114=second\np115=second\np116=second\np117=second\np118=second\np119=second\np120=second\np121=second\np122=second\np123=second\np124=second\np125=second\np126=second\np127=second\np128=second\np129=second\np130=second\np131=second\ntotal=0\nfor phase in range(int(input())):\n    for value in p131:\n        first.append(9)\n        total+=value\n        break\n    p131=p130\n    p130=p129\n    p129=p128\n    p128=p127\n    p127=p126\n    p126=p125\n    p125=p124\n    p124=p123\n    p123=p122\n    p122=p121\n    p121=p120\n    p120=p119\n    p119=p118\n    p118=p117\n    p117=p116\n    p116=p115\n    p115=p114\n    p114=p113\n    p113=p112\n    p112=p111\n    p111=p110\n    p110=p109\n    p109=p108\n    p108=p107\n    p107=p106\n    p106=p105\n    p105=p104\n    p104=p103\n    p103=p102\n    p102=p101\n    p101=p100\n    p100=p99\n    p99=p98\n    p98=p97\n    p97=p96\n    p96=p95\n    p95=p94\n    p94=p93\n    p93=p92\n    p92=p91\n    p91=p90\n    p90=p89\n    p89=p88\n    p88=p87\n    p87=p86\n    p86=p85\n    p85=p84\n    p84=p83\n    p83=p82\n    p82=p81\n    p81=p80\n    p80=p79\n    p79=p78\n    p78=p77\n    p77=p76\n    p76=p75\n    p75=p74\n    p74=p73\n    p73=p72\n    p72=p71\n    p71=p70\n    p70=p69\n    p69=p68\n    p68=p67\n    p67=p66\n    p66=p65\n    p65=p64\n    p64=p63\n    p63=p62\n    p62=p61\n    p61=p60\n    p60=p59\n    p59=p58\n    p58=p57\n    p57=p56\n    p56=p55\n    p55=p54\n    p54=p53\n    p53=p52\n    p52=p51\n    p51=p50\n    p50=p49\n    p49=p48\n    p48=p47\n    p47=p46\n    p46=p45\n    p45=p44\n    p44=p43\n    p43=p42\n    p42=p41\n    p41=p40\n    p40=p39\n    p39=p38\n    p38=p37\n    p37=p36\n    p36=p35\n    p35=p34\n    p34=p33\n    p33=p32\n    p32=p31\n    p31=p30\n    p30=p29\n    p29=p28\n    p28=p27\n    p27=p26\n    p26=p25\n    p25=p24\n    p24=p23\n    p23=p22\n    p22=p21\n    p21=p20\n    p20=p19\n    p19=p18\n    p18=p17\n    p17=p16\n    p16=p15\n    p15=p14\n    p14=p13\n    p13=p12\n    p12=p11\n    p11=p10\n    p10=p9\n    p9=p8\n    p8=p7\n    p7=p6\n    p6=p5\n    p5=p4\n    p4=p3\n    p3=p2\n    p2=p1\n    p1=p0\nprint(total,len(first),len(second))\n')
        self.assertFalse(fact.readonly)
        self.assertTrue(fact.opaque)

    def test_unknown_preloop_heap_effects_invalidate_disjointness(self):
        fact=self.fact('first=[1]\nsecond=[2]\nholder=[first]\ndef key(value):\n holder[0]=second\n return value\norder=[3,1,2]\norder.sort(key=key)\nfor value in holder[0]:\n second.append(9)\n print(value)\n break\nprint(first,second,holder,order)\n')
        self.assertFalse(fact.readonly)
        self.assertTrue(fact.opaque)

    def test_unmodeled_container_reference_writes_are_opaque(self):
        for source in ('first,second=[1],[2]\nholder={"item":first}\nholder.update(item=second)\nfor value in holder["item"]:\n second.append(9)\n print(value)\n break\nprint(holder)\n', 'first,second=[1],[2]\nholder={"item":first}\nholder.update([("item",second)])\nfor value in holder["item"]:\n second.append(9)\n print(value)\n break\nprint(holder)\n', 'first,second=[1],[2]\nholder={"item":first}\nalias=holder\nholder|={"item":second}\nfor value in alias["item"]:\n second.append(9)\n print(value)\n break\nprint(alias)\n', 'from collections import deque\nfirst,second=[1],[2]\nholder=deque([first])\nalias=holder\nholder += [second]\nfor value in alias[-1]:\n second.append(9)\n print(value)\n break\nprint(list(alias))\n'):
            with self.subTest(source=source):
                fact=self.fact(source)
                self.assertFalse(fact.readonly)
                self.assertTrue(fact.opaque)

    def test_unmodeled_free_scopes_are_not_module_global_summaries(self):
        for source in ('first,second=[1],[2]\ncurrent=first\ndef outer():\n current=second\n def get():return current\n return get()\npicked=outer()\nfor value in picked:\n second.append(9)\n print(value)\n break\nprint(first,second)\n', 'first,second=[1],[2]\ncurrent=first\ndef outer():\n current=second\n def get():return current\n return get\ngetter=outer()\npicked=getter()\nfor value in picked:\n second.append(9)\n print(value)\n break\nprint(first,second)\n'):
            with self.subTest(source=source):
                fact=self.fact(source)
                self.assertFalse(fact.readonly)
                self.assertTrue(fact.opaque)
