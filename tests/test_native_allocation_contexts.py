"""Finite heap-site summaries retain actual reference and fresh-object semantics."""
import unittest
import test_native_module_linking as runtime_support


class AllocationContextRuntimeTests(unittest.TestCase):
    exercise=runtime_support.NativeLinkedModuleTests.exercise

    def test_fresh_factory_same_comprehension_site(self):
        self.exercise({'main.py': 'def make(value):\n    return [value]\nrows = [make(i) for i in range(3)]\nrows[0].append(9)\nprint(rows, rows[0] is rows[1])\n'})

    def test_fresh_factory_repeated_loop_site(self):
        self.exercise({'main.py': 'def make(value):\n    return [value]\nrows = []\nfor i in range(4):\n    rows.append(make(i))\nrows[0][0] = 99\nprint(rows, rows[0] is rows[3])\n'})

    def test_fresh_copy_loop_and_old_alias(self):
        self.exercise({'main.py': 'def duplicate(values):\n    return values.copy()\nrow = [1]\nrows = [row]\nfor i in range(3):\n    row = duplicate(row)\n    rows.append(row)\nrows[0].append(9)\nprint(rows, rows[0] is rows[1], rows[1] is rows[2])\n'})

    def test_argument_alias_returns_stay_distinct(self):
        self.exercise({'main.py': 'def identity(values):\n    return values\nleft = [1]\nright = [2]\na = identity(left)\nb = identity(right)\na.append(7)\nprint(a is left, b is right, a is b, left, right)\n'})

    def test_argument_alias_same_callsite(self):
        self.exercise({'main.py': 'def identity(values):\n    return values\nrows = [[1], [2]]\naliases = [identity(row) for row in rows]\naliases[0].append(9)\nprint(rows, aliases[0] is rows[0], aliases[0] is aliases[1])\n'})

    def test_self_arguments_matrix_replacement(self):
        self.exercise({'main.py': 'def combine(left, right):\n    return [[left[i][j] + right[i][j] for j in range(2)] for i in range(2)]\nmatrix = [[1, 2], [3, 4]]\nfor _ in range(5):\n    matrix = combine(matrix, matrix)\nprint(matrix)\n'})

    def test_recursive_fresh_allocation(self):
        self.exercise({'main.py': 'def create(depth):\n    if depth:\n        create(depth - 1)\n    return [depth]\nrows = [create(i) for i in range(3)]\nrows[0].append(8)\nprint(rows, rows[0] is rows[1])\n'})

    def test_growing_history_of_fresh_results(self):
        self.exercise({'main.py': 'def fresh(previous):\n    return [previous[0] + 1]\nrows = [[0]]\nwhile len(rows) < 4:\n    rows.append(fresh(rows[-1]))\nprint(rows, rows[0] is rows[1], rows[2] is rows[3])\n'})

    def test_parent_repeated_fresh_owner_collision(self):
        self.exercise({'main.py': 'def fresh(previous):return [len(previous)]\nprevious=[99]\nfor _ in range(5):\n    old=previous\n    previous=fresh(previous)\n    print(old is previous,old,previous)\n    previous.append(4)\n'})

    def test_repeated_mutating_caller_owned_input(self):
        self.exercise({'main.py': 'def update(values):\n    values.append(1)\n    return values.copy()\nprevious=[0]\nfor _ in range(4):\n    previous=update(previous)\nprint(previous)\n'})


class AllocationContextMetadataTests(unittest.TestCase):
    def test_alias_return_summaries_keep_each_actual_argument(self):
        import ast
        from py2fastrust.frontend import build_program
        from py2fastrust.native_constraints import analyze
        source='def identity(values):return values\nleft=[1]\nright=[2]\na=identity(left)\nb=identity(right)\nprint(a is left,b is right)\n'
        unit=build_program(source,'allocation_aliases.py').main
        facts=analyze(unit).scope()
        left=facts.values[unit.ordinal(unit.tree.body[1].value)]
        right=facts.values[unit.ordinal(unit.tree.body[2].value)]
        self.assertNotEqual(left,right)
        self.assertEqual(facts.values[unit.ordinal(unit.tree.body[3].value)],left)
        self.assertEqual(facts.values[unit.ordinal(unit.tree.body[4].value)],right)

    def test_repeated_owner_site_is_still_a_caller_owned_input(self):
        from py2fastrust.frontend import build_program
        from py2fastrust.native_constraints import Solver,SemanticGraph,Allocation
        source='def update(values):\n    values.append(1)\n    return values.copy()\nprevious=[0]\nfor _ in range(4):\n    previous=update(previous)\nprint(previous)\n'
        collisions=[]
        test=self
        class Probe(Solver):
            def record_mutation(self,receiver,context):
                super().record_mutation(receiver,context)
                if context[0]is None:return
                incoming=self.incoming_allocations(context)
                for allocation in self.provenance(receiver).alternatives:
                    if isinstance(allocation,Allocation)and allocation.site[0]==self.allocation_context(context):
                        collisions.append(allocation)
                        test.assertIn(allocation,incoming)
                        test.assertIn(allocation,self.shared_references)
        Probe(SemanticGraph(build_program(source,'allocation_generations.py').main)).solve()
        self.assertTrue(collisions,'the loop must revisit an allocation produced at the same coarse owner site')
