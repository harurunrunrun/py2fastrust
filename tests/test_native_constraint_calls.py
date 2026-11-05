"""Compiler transfer depth, caller references and abort cleanup are semantic."""
import sys
import unittest
from types import MethodType

from py2fastrust.frontend import parse_source
from py2fastrust.native_constraints import (
    Allocation, FunctionValue, SemanticGraph, Solver, analyze,
)
from py2fastrust.native_types import ListType


class ConstraintCallStackTests(unittest.TestCase):
    def test_long_acyclic_dependencies_keep_the_host_recursion_limit(self):
        count = 160
        source = '\n'.join(
            f'def step_{index}(value):\n return step_{index + 1}(value) + 1'
            for index in range(count)
        )
        source += f'\ndef step_{count}(value):\n return value * 2\nanswer = step_0(3)\n'
        unit = parse_source(source, 'long_constraint_calls.py')
        limit = sys.getrecursionlimit()
        result = analyze(unit)
        self.assertEqual(sys.getrecursionlimit(), limit)
        self.assertEqual(len(result.scopes), count + 2)
        call = unit.tree.body[-1].value
        self.assertEqual(result.scope().expressions[unit.ordinal(call)], 'int')

    def test_returned_caller_alias_keeps_the_actual_allocation(self):
        source = ('def get(rows, index):\n    return rows[index]\n'
                  'def write(row):\n    row.append(9)\n    return row[0]\n'
                  'rows = [[1], [2]]\nheld = get(rows, 0)\n'
                  'print(write(held), rows, held is rows[0])\n')
        unit = parse_source(source, 'caller_alias.py')
        solver = Solver(SemanticGraph(unit))
        result = solver.solve()
        call = unit.tree.body[3].value
        site = unit.ordinal(call)
        held = result.scope().values[site]
        origins = {part for part in solver.provenance(held).alternatives
                   if isinstance(part, Allocation)}
        self.assertTrue(origins)
        self.assertTrue(origins <= solver.shared_references)
        self.assertEqual(result.scope().expressions[site], ListType('int'))

    def test_nested_callback_loops_preserve_disjoint_mutation_summaries(self):
        source = ('def same(row):\n    return row\n'
                  'def append_all(destination, rows):\n'
                  '    for row in rows:\n'
                  '        for item in same(row):\n'
                  '            destination.append(item)\n'
                  '    return len(destination)\n'
                  'rows = [[1, 2], [], [3]]\noutput = [9]\n'
                  'print(append_all(output, rows), output, rows)\n')
        unit = parse_source(source, 'callback_loops.py')
        result = analyze(unit)
        scope = result.scope(unit.tree.body[1],
                             (ListType('int'), ListType(ListType('int'))))
        self.assertEqual(len(scope.iteration_access), 2)
        for access in scope.iteration_access.values():
            self.assertTrue(access.readonly)
            self.assertFalse(access.opaque)
            self.assertTrue(access.sources)
            self.assertTrue(access.mutations)
            self.assertTrue(access.sources.isdisjoint(access.mutations))

    def test_real_recursive_source_edge_remains_a_conservative_summary(self):
        source = ('def recurse(value):\n'
                  '    if value:\n        return recurse(value - 1)\n'
                  '    return 0\nresult = recurse(3)\n')
        unit = parse_source(source, 'recursive_constraint_call.py')
        solver = Solver(SemanticGraph(unit))
        result = solver.solve()
        self.assertFalse(solver.active)
        self.assertLessEqual(len(result.scopes), 3)
        calls = [call for scope in result.scopes.values() for call in scope.calls.values()]
        self.assertTrue(any(any(isinstance(identity, FunctionValue)
                                for identity in call.identity.alternatives)
                            for call in calls))
        self.assertTrue(solver.iteration_access.unknown_heap)

    def test_nested_analysis_abort_closes_every_effect_scope(self):
        source = ('def child(values):\n'
                  ' return sum([ABORT for item in values])\n'
                  'def parent(values):\n'
                  ' for value in values:\n  child(values)\n'
                  'values=[1,2]\nparent(values)\n')
        unit = parse_source(source, 'abort_constraint_call.py')
        solver = Solver(SemanticGraph(unit))
        original = solver.lookup
        failure = RuntimeError('injected compiler lookup failure')
        entered = []

        def lookup(current, name, state, globals, locals):
            if name == 'ABORT':
                entered.append((len(current.active),
                                len(current.iteration_access.functions),
                                len(current.iteration_access.loops),
                                len(current.active_iterations)))
                raise failure
            return original(name, state, globals, locals)

        solver.lookup = MethodType(lookup, solver)
        with self.assertRaises(RuntimeError) as raised:
            solver.solve()
        self.assertIs(raised.exception, failure)
        self.assertEqual(entered, [(2, 2, 1, 2)])
        self.assertFalse(solver.active)
        self.assertFalse(solver.iteration_access.functions)
        self.assertFalse(solver.iteration_access.loops)
        self.assertFalse(solver.active_iterations)
        self.assertTrue(all(summary.opaque
                            for summary in solver.iteration_access.summaries.values()))
        self.assertTrue(all(summary.opaque for _, summary
                            in solver.iteration_access.records.values()))


if __name__ == '__main__':
    unittest.main()
