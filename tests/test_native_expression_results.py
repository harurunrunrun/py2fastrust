"""Actual conditional values move owned containers or retain shared identity."""
import shutil
import unittest
import test_native_union_ordering as helpers

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeExpressionResultTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeUnionOrderingTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeUnionOrderingTests.tearDownClass.__func__)
    compile=helpers.NativeUnionOrderingTests.compile
    exercise=helpers.NativeUnionOrderingTests.exercise

    def test_required_original(self):
        self.exercise('flag=int(input())\nvalues=[2]if flag else []\nif (values if flag else None)and values[-1]==2:\n print("yes")\nif (None if flag else values)or not values:\n print("other")\nprint(values)\n',('0\n', '1\n'))

    def test_owned_branches(self):
        self.exercise('flag=int(input())\nvalues=[2] if flag else []\nvalues.append(5)\nprint(values)\n',('0\n', '1\n'))

    def test_named_aliases(self):
        self.exercise('flag=int(input())\nleft=[2]\nright=[8]\nchosen=left if flag else right\nchosen.append(11)\nprint(chosen is left,chosen is right,left,right)\n',('0\n', '1\n'))

    def test_mixed_and(self):
        self.exercise('items=list(range(int(input())))\nresult=items and 7\nprint(result,result is items,items)\n',('0\n', '1\n', '3\n'))

    def test_chain_identity(self):
        self.exercise('first=[]\nsecond=[4]\nthird=[9]\nchosen=first or second and third\nchosen.append(10)\nprint(chosen is third,first,second,third)\n',('',))

    def test_nullable_alias(self):
        self.exercise('flag=int(input())\nitem=[2]\nmaybe=item if flag else None\nprint(maybe,bool(maybe),maybe is None,maybe is item)\nitem.append(3)\nprint(maybe,item)\n',('0\n', '1\n'))

    def test_skipped_pop(self):
        self.exercise('items=[1,2]\nchosen=items or items.pop()\nprint(chosen is items,items)\nprint(next(iter(items),None))\n',('',))

    def test_executed_clear_branch(self):
        self.exercise('flag=int(input())\nitems=[1,2]\nchosen=items if flag else (items.clear() or [])\nprint(chosen,chosen is items,items)\n',('0\n', '1\n'))

    def test_skipped_unbound(self):
        self.exercise('flag=int(input())\nif flag:missing=[8]\nitems=[1]\nchosen=items or missing\nprint(chosen is items,chosen)\n',('0\n', '1\n'))

    def test_conditional_unbound(self):
        self.exercise('flag=int(input())\nif flag:missing=[8]\nitems=[]\nchosen=items or missing\nprint(chosen is missing,chosen)\n',('0\n', '1\n'))

    def test_owned_mapping(self):
        self.exercise('flag=int(input())\nchosen={1:2} if flag else {}\nprint(chosen)\n',('0\n', '1\n'))

    def test_operand_effects(self):
        self.exercise('left=[1,2]\nright=[3,4]\nchosen=(left.pop() and right) or left\nprint(chosen is right,left,right)\n',('',))

    def test_branches_distinct_payloads(self):
        self.exercise('flag=int(input())\nleft=[1]\nchosen=left if flag else "plain"\nleft.append(3)\nprint(chosen,chosen is left,left)\n',('0\n', '1\n'))

    def test_empty_join_mutation(self):
        self.exercise('flag=int(input())\nleft=[]\nright=[3]\nchosen=left if flag else right\nchosen.extend([4,5])\nprint(chosen is left,chosen is right,left,right)\n',('0\n', '1\n'))

    def test_owned_set(self):
        self.exercise('flag=int(input())\nchosen={1,2} if flag else set()\nprint(len(chosen),1 in chosen)\n',('0\n', '1\n'))

    def test_nested_row_aliases(self):
        self.exercise('flag=int(input())\nleft=[[1],[2]]\nright=[[3]]\nchosen=left if flag else right\nrow=chosen[0]\nrow.append(5)\nprint(chosen is left,chosen is right,left,right,row)\n',('0\n', '1\n'))

    def test_selected_row_survives_parent_clear(self):
        self.exercise('flag=int(input())\nparent=[[1],[2]]\nchosen=parent[0] if flag else parent[1]\nparent.clear()\nchosen.append(9)\nprint(chosen,parent)\n',('0\n', '1\n'))

    def test_indexed_branch_error(self):
        self.exercise('flag=int(input())\nvalues=[[1]]\nchosen=values[0] if flag else values[2]\nprint(chosen)\n',('0\n', '1\n'))

    def test_owned_list_chain(self):
        self.exercise('answer=[] or [2] and [3]\nanswer.append(5)\nprint(answer)\n',('',))

    def test_owned_list_text(self):
        self.exercise('flag=int(input())\nlabel="ok"\nchosen=[] if flag else label\nprint(chosen,bool(chosen),len(chosen))\n',('0\n', '1\n'))

    def test_branch_effect_order(self):
        self.exercise('flag=int(input())\nleft=[1]\nright=[2]\nchosen=left if flag else right.pop()\nprint(chosen,left,right)\n',('0\n', '1\n'))

    def test_finite_membership_effects(self):
        self.exercise('flag=int(input())\nchosen={1,2} if flag else set()\nvalues=[1,2]\nprint(values.pop() in chosen,values)\nprint(values.pop() not in chosen,values)\n',('0\n', '1\n'))

    def test_finite_mapping_membership(self):
        self.exercise('flag=int(input())\nchosen={1:2} if flag else {}\nprint(1 in chosen,2 not in chosen,len(chosen),chosen)\n',('0\n', '1\n'))

    def test_finite_list_ordering(self):
        self.exercise('flag=int(input())\nleft=[1]\nmaybe=left if flag else None\nright=[2]\nprint(maybe==left,maybe!=right,maybe is left)\nprint(maybe<right)\n',('0\n', '1\n'))

    def test_finite_comparison_chain_skips_error(self):
        self.exercise('flag=int(input())\nleft=[1]\nmaybe=left if flag else None\ntail=[]\nprint(maybe is None or maybe<[0]<tail.pop())\nprint(tail)\n',('0\n', '1\n'))

    def test_finite_read_after_later_mutation(self):
        self.exercise('flag=int(input())\nitems=[1,2]\nchosen=items if flag else None\nprint(chosen==items,chosen is items)\nprint(chosen==items.pop())\nprint(chosen,items)\n',('0\n', '1\n'))

    def test_finite_comparison_chain_executes_error(self):
        self.exercise('flag=int(input())\nleft=[1]\nmaybe=left if flag else None\ntail=[]\nprint(maybe is None or maybe<[2]<tail.pop())\nprint(tail)\n',('0\n','1\n'))

    def test_borrowed_mutable_sets_and_mappings_require_real_shared_storage(self):
        from py2fastrust import transpile,TranspileOptions
        for source in ('flag=int(input())\nitems={1}\nchosen=items if flag else {2}\nprint(chosen)\n',
                       'flag=int(input())\nitems={1:2}\nchosen=items if flag else {}\nprint(chosen)\n'):
            for mode in ('i64','i128','bigint'):
                result=transpile(source,TranspileOptions(integer=mode))
                self.assertFalse(result.success)
                self.assertEqual(result.diagnostics[0].code,'E006')
                self.assertIn('actual-value result ownership',result.diagnostics[0].message)

    def test_returned_nullable_alias(self):
        self.exercise('def choose(items,flag):\n return items if flag else None\nflag=int(input())\noriginal=[2]\nchosen=choose(original,flag)\noriginal.append(5)\nprint(chosen,chosen is original,original)\n',('0\n', '1\n'))

    def test_returned_owned_branch(self):
        self.exercise('def choose(flag):\n return [2] if flag else []\nflag=int(input())\nchosen=choose(flag)\nalias=chosen\nalias.append(5)\nprint(chosen is alias,chosen)\n',('0\n', '1\n'))

    def test_reselected_finite_alias(self):
        self.exercise('flag=int(input())\nitems=[2]\nchosen=items if flag else "other"\nsecond=chosen or [8]\nitems.append(4)\nprint(chosen,second,chosen is items,second is items,items)\n',('0\n', '1\n'))

    def test_returned_distinct_shared_layouts(self):
        self.exercise('def choose(left,right,flag):\n if flag:return left\n return right\nflag=int(input())\nleft=[1]\nright=[True]\nchosen=choose(left,right,flag)\nprint(chosen,chosen is left,chosen is right)\n',('0\n', '1\n'))

    def test_cfg_multiple_shared_aliases(self):
        self.exercise('flag=int(input())\noriginal=[2]\nif flag:chosen=original\nelse:chosen=0\nfirst=second=chosen\noriginal.append(8)\nprint(first,second,first is original,second is original,original)\n',('0\n', '1\n'))

    def test_cfg_distinct_shared_layouts(self):
        self.exercise('flag=int(input())\nleft=[1]\nright=[True]\nif flag:chosen=left\nelse:chosen=right\nalias=chosen\nprint(alias,alias is left,alias is right)\n',('0\n', '1\n'))

    def test_cfg_alias_after_missing_branch(self):
        self.exercise('if int(input()):chosen=[1]\nprint("before",end="|")\nfirst=second=chosen\nprint(first is second,first)\n',('0\n', '1\n'))

    def test_cfg_nested_nullable_aliases(self):
        self.exercise('flag=int(input())\noriginal=[2]\nif flag:chosen=original\nelse:chosen=None\nfirst=second=chosen\noriginal.clear()\nprint(first,second,first is original,second is None)\n',('0\n', '1\n'))

    def test_independent_nested_result_error_order(self):
        self.exercise("def mark(items):\n print('mark')\n items.append(2)\n return None\na=[]\nflag=int(input())\nselected=(a if flag else None) or (mark(a) and 1//0) or a\nprint(selected,a,selected is a)\nprint((selected if flag else 1//0))\n",('0\n', '1\n'))

    def test_none_and_integer(self):
        self.exercise('def mark():\n print("mark",end="|")\n return None\nprint(mark() and int(input()))\n',('3\n',))

    def test_none_or_integer(self):
        self.exercise('def mark():\n print("mark",end="|")\n return None\nprint(mark() or int(input()))\n',('3\n', '0\n'))

    def test_none_container_and_scalar_alternatives(self):
        self.exercise('def mark():\n print("mark",end="|")\n return None\nprint((mark() and [1])or[2])\nprint((mark() and b"x")or"text")\n',('',))
