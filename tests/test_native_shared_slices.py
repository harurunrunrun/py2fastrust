"""Shared slices copy the outer list after evaluating all original bounds."""
import shutil
import unittest

import test_native_unpack_exact_lengths as execution


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class SharedSliceExecution(execution.ExactUnpackLengthTests):
    def test_eager_lengths_and_lazy_error_order(self):
        cases=(
            ('flat','a=[1,2,3,4]\nalias=a\nb=a[1:4:2]\nb.append(9)\na[1]=7\nprint(a,alias,b,a[::-1])\n',''),
            ('nested','rows=[[1],[2],[3]]\nother=rows[1:]\nother[0].append(9)\nother.append([7])\nprint(rows,other)\n',''),
            ('bound_mutation','a=[1,2,3]\nalias=a\ndef lower(v):\n v.append(4)\n print("lower",end="|")\n return 1\nb=a[lower(alias):]\nprint(a,b)\n',''),
            ('owner_rebind','values=[1,2,3]\ndef choose():\n global values\n values=[9]\n return 1\nresult=values[choose():]\nprint(values,result)\n',''),
            ('zero_step','a=[1,2,3]\nalias=a\ndef bound(v,tag):\n print(tag,end="|")\n v.append(8)\n return 0\nb=a[bound(alias,"lo"):bound(alias,"hi"):bound(alias,"step")]\n',''),
            ('large_bounds','a=[1,2,3]\nalias=a\nprint(a[-10**15:10**15],a[::-10**15])\n',''),
        )
        original=execution.CASES
        try:
            execution.CASES=cases
            super().test_eager_lengths_and_lazy_error_order()
        finally:execution.CASES=original


if __name__=='__main__':
    unittest.main()
