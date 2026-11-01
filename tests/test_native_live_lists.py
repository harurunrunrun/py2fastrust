"""Live builtin list traversal retains identity across source-side effects."""
import shutil
import unittest
import test_native_union_ordering as helpers


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeLiveListTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeUnionOrderingTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeUnionOrderingTests.tearDownClass.__func__)
    compile=helpers.NativeUnionOrderingTests.compile
    exercise=helpers.NativeUnionOrderingTests.exercise

    def test_append_growth(self):
        self.exercise('a=[1]\nfor x in a:\n print(x,end="|")\n if x<5:a.append(x+1)\nprint(a)\n',('',))

    def test_alias_append(self):
        self.exercise('a=[1]\nb=a\nfor x in a:\n print(x,end="|")\n if x<4:b.append(x+1)\nprint(a,b,a is b)\n',('',))

    def test_pop_tail(self):
        self.exercise('a=[1,2,3,4]\nfor x in a:\n print(x,a.pop())\nprint(a)\n',('',))

    def test_pop_front(self):
        self.exercise('a=[1,2,3,4,5]\nfor x in a:\n print(x,a.pop(0))\nprint(a)\n',('',))

    def test_store_element(self):
        self.exercise('a=[1,2,3]\nfor x in a:\n print(x,end="|")\n a[-1]=7\nprint(a)\n',('',))

    def test_delete_element(self):
        self.exercise('a=[1,2,3,4]\nfor x in a:\n print(x,end="|")\n del a[0]\nprint(a)\n',('',))

    def test_clear_then_append(self):
        self.exercise('a=[1,2]\nfor x in a:\n print(x,end="|")\n if x==1:\n  a.clear()\n  a.extend([3,4])\nprint(a)\n',('',))

    def test_extend_growth(self):
        self.exercise('a=[1]\nfor x in a:\n print(x,end="|")\n if x==1:a.extend([2,3])\nprint(a)\n',('',))

    def test_insert_then_break(self):
        self.exercise('a=[1,2,3]\nfor x in a:\n a.insert(0,9)\n print(x,a)\n break\nprint(a)\n',('',))

    def test_remove_current(self):
        self.exercise('a=[1,2,3,4,5]\nfor x in a:\n print(x,end="|")\n a.remove(x)\nprint(a)\n',('',))

    def test_reverse_source(self):
        self.exercise('a=[1,2,3]\nfor x in a:\n print(x,end="|")\n a.reverse()\nprint(a)\n',('',))

    def test_sort_source(self):
        self.exercise('a=[3,1,2]\nfor x in a:\n print(x,end="|")\n a.sort()\nprint(a)\n',('',))

    def test_inplace_add(self):
        self.exercise('a=[1]\nfor x in a:\n print(x,end="|")\n if x==1:a+=[2,3]\nprint(a)\n',('',))

    def test_inplace_multiply(self):
        self.exercise('a=[1,2]\nfor x in a:\n a*=2\n print(x,a)\n break\n',('',))

    def test_replace_owner(self):
        self.exercise('a=[1,2,3]\nfor x in a:\n print(x,end="|")\n a=[8,9]\nprint(a)\n',('',))

    def test_delete_owner(self):
        self.exercise('a=[1,2,3]\nfor x in a:\n if x==1:del a\n print(x,end="|")\nprint()\n',('',))

    def test_delete_owner_error(self):
        self.exercise('a=[1,2]\nfor x in a:\n del a\n print(x)\n',('',))

    def test_target_replaces_owner(self):
        self.exercise('a=[1,2,3]\nfor a in a:print(a)\nprint(a)\n',('',))

    def test_nested_loops(self):
        self.exercise('a=[1,2,3]\nfor x in a:\n for y in a:\n  print(x,y)\n  if y==1:a[-1]=7\nprint(a)\n',('',))

    def test_continue_and_else(self):
        self.exercise('a=[1]\nfor x in a:\n if x<4:\n  a.append(x+1)\n  continue\n print(x)\nelse:print("done")\nprint(a,x)\n',('',))

    def test_break_and_else(self):
        self.exercise('a=[1]\nfor x in a:\n a.append(x+1)\n if x==3:break\nelse:print("never")\nprint(a,x)\n',('',))

    def test_enumerate_growth(self):
        self.exercise('a=[1]\nfor i,x in enumerate(a,7):\n print(i,x)\n if x<4:a.append(x+1)\nprint(a)\n',('',))

    def test_zip_growth(self):
        self.exercise('a=[1]\nfor x,y in zip(a,range(5)):\n print(x,y)\n if x<4:a.append(x+1)\nprint(a)\n',('',))

    def test_saved_enumerate(self):
        self.exercise('a=[1]\nit=enumerate(a)\nfor i,x in it:\n print(i,x)\n if x<4:a.append(x+1)\nprint(a)\n',('',))

    def test_mapped_growth(self):
        self.exercise('a=[1]\nfor x in map(int,a):\n print(x)\n if x<4:a.append(x+1)\nprint(a)\n',('',))

    def test_filtered_growth(self):
        self.exercise('a=[1]\nfor x in filter(None,a):\n print(x)\n if x<4:a.append(x+1)\nprint(a)\n',('',))

    def test_generator_growth(self):
        self.exercise('a=[1]\nfor x in (v for v in a):\n print(x)\n if x<4:a.append(x+1)\nprint(a)\n',('',))

    def test_mutating_comprehension(self):
        self.exercise('a=[1,2,3,4]\nb=[x for x in a if a.pop()>0]\nprint(a,b)\n',('',))

    def test_mutating_sum_generator(self):
        self.exercise('a=[1,2,3,4]\nprint(sum(x+a.pop() for x in a),a)\n',('',))

    def test_callback_growth(self):
        self.exercise('def add(a,x):\n if x<4:a.append(x+1)\na=[1]\nfor x in a:\n print(x)\n add(a,x)\nprint(a)\n',('',))

    def test_local_growth(self):
        self.exercise('def run():\n a=[1]\n for x in a:\n  print(x)\n  if x<4:a.append(x+1)\n print(a)\nrun()\n',('',))

    def test_zero_trip(self):
        self.exercise('a=[]\nx=99\nfor x in a:a.append(1)\nelse:print("empty")\nprint(a,x)\n',('',))

    def test_readonly_list(self):
        self.exercise('a=[1,2,3,4]\ns=0\nfor x in a:s+=x*x\nprint(s,a)\n',('',))

    def test_readonly_snapshot(self):
        self.exercise('a=[1,2,3]\nfor x in a.copy():\n a.append(x+10)\nprint(a)\n',('',))
