"""Concatenation producers remain part of the shared list element ABI."""
import ast
import unittest

import test_native_annotations_assertions as support

CASES={'append_dynamic_then_iadd': ('rows=[]\nfor _ in range(int(input())):rows.append(tuple(map(int,input().split())))\nlower=min(a for a,b in rows)\nrows += [(lower,7)]\ndef total():return sum(a for a,b in rows)\nprint(rows,total())\n', ('2\n3 4\n1 2\n', '0\n', '1\n3\n', '1\n3 4 5\n')), 'reverse_before_growth': ('rows=[]\nfor _ in range(int(input())):rows.append(tuple(map(int,input().split())))\nprint([b for a,b in reversed(rows)])\nrows += [(8,9)]\ndef total():return len(rows)\nprint(rows,total())\n', ('2\n3 4\n1 2\n', '0\n', '1\n3\n')), 'concat_keeps_outer_alias_distinct': ('rows=[]\nrows.append(tuple(map(int,input().split())))\nalias=rows\ncombined=rows+[(8,9)]\ndef lengths():return len(rows),len(combined)\ncombined.append((10,11))\nprint(alias is rows,combined is rows,rows,combined,lengths())\n', ('3 4\n',)), 'callback_rhs_mutation': ('rows=[]\nrows.append(tuple(map(int,input().split())))\ndef more():\n print("right")\n rows.append((5,6))\n return [(7,8)]\nprint(min(a for a,b in rows))\nrows += more()\nprint(rows)\n', ('3 4\n', '3\n')), 'nested_mutable_aliases': ('row=[1]\nitems=[]\nitems.append((row,2))\nalias=items\nitems += [(row,"tag")]\nitems[0][0].append(3)\ndef current():return row\nprint(items,alias is items,items[0][0] is items[1][0],current())\n', ('',)), 'genuine_none_row': ('rows=[]\nif int(input()):rows.append(None)\nelse:rows.append((3,4))\nprint(min(a for a,b in rows))\nrows += [(8,9)]\ndef current():return rows\nprint(current())\n', ('0\n', '1\n')), 'retained_cursor_sees_extension': ('rows=[]\nrows.append(tuple(map(int,input().split())))\nstream=iter(rows)\nrows += [(8,9)]\ndef size():return len(rows)\nfor a,b in stream:print(a,b)\nprint(size())\n', ('3 4\n', '3\n')), 'source_function_concat': ('def combine(first,second):return first+second\nrows=[]\nrows.append(tuple(map(int,input().split())))\nprint(min(a for a,b in rows))\ncombined=combine(rows,[(8,9)])\ndef size():return len(combined)\nprint(rows,combined,size())\n', ('3 4\n', '3\n')), 'self_extension': ('rows=[]\nrows.append(tuple(map(int,input().split())))\nrows += rows\ndef current():return rows\nprint(current())\n', ('3 4\n',)), 'homogeneous_shared_scalar_control': ('values=[]\nfor index in range(3):values.append(index)\nvalues += [7,9]\ndef current():return values\nprint(current())\n', ('',)), 'shared_inner_list_control': ('row=[1]\nvalues=[]\nvalues.append(row)\nvalues += [row]\nvalues[1].append(7)\ndef current():return values\nprint(current(),values[0] is values[1])\n', ('',)), 'unbound_rhs_precedes_growth': ('rows=[]\nrows.append((1,2))\nprint(min(a for a,b in rows))\nrows += absent\ndef current():return rows\nprint(current())\n', ('',))}

CASES.update({'deduplicated_dynamic_rows': ('rows=[tuple(map(int,input().split()))for _ in range(int(input()))]\nlocations={}\nselected=[]\nfor index,row in enumerate(rows):\n if row not in locations:\n  locations[row]=index\n  selected.append(row)\nlower=min(a for a,b in selected)\nselected += [(lower,7)]\ndef first():return selected[0]\nprint(selected,first())\n', ('3\n3 4\n1 2\n3 4\n', '0\n', '1\n3\n')), 'scalar_read_before_none_growth': ('values=[]\nvalues.append(3)\nprint(values[0]+2)\nvalues += [None]\ndef current():return values\nprint(current())\n', ('',)), 'separate_source_layouts': ('def combine(first,second):return first+second\nfirst=[]\nfirst.append((3,4))\nprint(combine(first,[(5,6)]))\nsecond=[]\nsecond.append(("a","b"))\nprint(combine(second,[("c","d")]))\n', ('',)), 'callback_rhs_failure_no_growth': ('rows=[]\nrows.append(tuple(map(int,input().split())))\ndef more():\n print("right")\n rows.append((5,6))\n return [(1//int(input()),8)]\nprint(min(a for a,b in rows))\nrows += more()\nprint(rows)\n', ('3 4\n0\n', '3 4\n1\n')), 'duplicate_dynamic_rows_with_global_unpacks': ('rows=[tuple(map(int,input().split()))for _ in range(int(input()))]\nlocations={}\nselected=[]\nfor index,row in enumerate(rows):\n if row in locations:continue\n locations[row]=index\n selected.append(row)\nlower=min(a for a,b in selected)\nselected += [(lower,7)]\ndef delta(first,second):\n a,b=selected[first]\n c,d=selected[second]\n return a*d-b*c\nprint(selected,delta(0,-1))\n', ('3\n3 4\n1 2\n3 4\n', '1\n3\n'))})


class ListConcatenationFlowExecutionTests(unittest.TestCase):
    compare = support.AnnotationAndAssertionExecutionTests.compare


def _case(name):
    def test(self):
        self.compare(*CASES[name])
    return test


for _name in CASES:
    setattr(ListConcatenationFlowExecutionTests, 'test_' + _name, _case(_name))


class ListConcatenationFlowMetadataTests(unittest.TestCase):
    def model(self):
        from py2fastrust.frontend import build_program
        from py2fastrust.native_classes import Model
        source = CASES['deduplicated_dynamic_rows'][0]
        unit = build_program(source, 'list_concat_flow.py').main
        original = ast.dump(unit.tree, include_attributes=True)
        model = Model(unit.tree, unit.filename, 'i64', unit.native_imports,
                      unit=unit).run()
        self.assertEqual(ast.dump(unit.tree, include_attributes=True), original)
        unit.check_identity(source, unit.filename)
        return model

    def test_original_producer_evidence_is_separate_from_the_merged_member(self):
        from py2fastrust.native_classes import shape
        from py2fastrust.native_types import TupleType
        model = self.model()
        inputs = model.list_concatenation_inputs
        self.assertTrue(inputs)
        from py2fastrust.native_types import alternatives
        self.assertTrue(any(TupleType(('int', 'int')) in alternatives(shape(value))
                            for value in inputs.values()))
        for key, source in inputs.items():
            left, right = key[-2:]
            self.assertIsNot(source.root(), left.root())
            self.assertIsNot(source.root(), right.root())

    def test_cursor_element_uses_the_solved_stored_owner_abi(self):
        from py2fastrust.native_classes import shape
        from py2fastrust.native_types import ListType, TupleType, TupleSequenceType
        from py2fastrust.native_types import alternatives
        model = self.model()
        sources = [generator.outer.record for generator in model.generators.records]
        self.assertTrue(sources)
        for record in sources:
            source = shape(record.source)
            self.assertIsInstance(source, ListType)
            self.assertEqual(source.element, shape(record.element))
            self.assertEqual(set(alternatives(source.element)),
                             {TupleType(('int', 'int')), TupleSequenceType('int')})


if __name__ == '__main__':
    unittest.main()
