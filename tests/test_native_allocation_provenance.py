"""Mutations follow symbolic allocation fields, rather than guessing row types."""

import unittest

from py2fastrust.frontend import build_program
from py2fastrust.native_constraints import (
    Projection, SemanticGraph, Solver, Variable, analyze, value,
)
from py2fastrust.native_types import EMPTY, ListType, TupleType
from py2fastrust.native_key_types import SetType


class AllocationProvenanceTests(unittest.TestCase):
    def analyze(self, source):
        unit = build_program(source, "provenance.py").main
        return unit, analyze(unit)

    def allocation(self, unit, facts, node):
        return facts.scope().allocations[unit.ordinal(node)]

    def test_comprehension_rows_receive_later_indexed_mutations(self):
        unit, facts = self.analyze('rows=[[] for _ in range(int(input()))]\nfor i in range(len(rows)):\n rows[i].append(i)\n')
        outer = unit.tree.body[0].value
        self.assertEqual(self.allocation(unit, facts, outer), ListType(ListType("int")))
        self.assertEqual(self.allocation(unit, facts, outer.elt), ListType("int"))

    def test_different_allocation_sites_keep_their_own_field_types(self):
        unit, facts = self.analyze('numbers=[[] for _ in range(2)]\nwords=[[] for _ in range(2)]\nnumbers[0].append(3)\nwords[0].append("word")\n')
        self.assertEqual(self.allocation(unit, facts, unit.tree.body[0].value), ListType(ListType("int")))
        self.assertEqual(self.allocation(unit, facts, unit.tree.body[1].value), ListType(ListType("str")))

    def test_iteration_tuple_projection_and_parameter_keep_object_provenance(self):
        unit, facts = self.analyze('''def add(row):
 row.append((1,"word"))
rows=[[] for _ in range(3)]
holder=(7,rows)
for row in holder[1]:
 add(row)
''')
        self.assertEqual(self.allocation(unit, facts, unit.tree.body[1].value),
                         ListType(ListType(TupleType(("int", "str")))))

    def test_set_members_and_nested_index_stores_share_the_same_resolution(self):
        unit, facts = self.analyze('groups=[set() for _ in range(2)]\ngroups[0].add("word")\nrows=[[1] for _ in range(2)]\nrows[0][0]=True\nrows[0][0]+=3\n')
        self.assertEqual(self.allocation(unit, facts, unit.tree.body[0].value), ListType(SetType("str")))
        self.assertEqual(self.allocation(unit, facts, unit.tree.body[2].value), ListType(ListType("int_bool")))

    def test_projected_clear_preserves_shared_layout_instead_of_inventing_name_epoch(self):
        unit, facts = self.analyze('rows=[[] for _ in range(2)]\nrows[0].append(1)\nrows[0].clear()\nrows[0].append(2)\n')
        self.assertEqual(self.allocation(unit, facts, unit.tree.body[0].value), ListType(ListType("int")))
        clear_site = unit.ordinal(unit.tree.body[2].value)
        self.assertNotIn(clear_site, facts.scope().resets)

    def test_unconstrained_rows_stay_bottom_and_symbolic_cycles_terminate(self):
        unit, facts = self.analyze('rows=[[] for _ in range(2)]\n')
        self.assertEqual(self.allocation(unit, facts, unit.tree.body[0].value), ListType(ListType(EMPTY)))
        solver = Solver(SemanticGraph(unit))
        field = Variable((None, 1), "element")
        allocation = solver.allocation(7, "list", (None, ()))
        solver.constrain(field, value(field).join(value(allocation)))
        self.assertEqual(solver.provenance(value(field)), value(allocation))
        projected = Projection(value(field), "iteration")
        solver.insert(value(projected), "element", value("str"))
        self.assertEqual(solver.kind(value(allocation)), ListType(EMPTY))


if __name__ == "__main__":
    unittest.main()
