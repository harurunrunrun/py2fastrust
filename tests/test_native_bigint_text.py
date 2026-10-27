"""Owned/borrowed strings keep the same semantics in arbitrary-precision mode."""
import shutil
import unittest

import test_native_slices as _slices
import test_native_text_methods as _methods


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeBigIntTextTests(unittest.TestCase):
    def compare(self,source,inputs=("",)):
        return _slices.NativeSliceTests.compare(self,source,inputs,modes=("bigint",))

    def test_strings_with_big_numbers_type_changes_and_copies(self):
        self.compare('''x=10**100
print(x)
x="猫🐈é"
a=b=x
other=x
x+="!"
print(x,other,a,b,len(other),other[0],other[-1])
print(3*"海","x"*-3,True*"a","海"+"風")
print(str(10**200),str(True),str(False),str(),bool(""),bool("猫"))
''')

    def test_text_input_unicode_integer_conversion_and_truth(self):
        source='''s=input()
t=input()
print(s,t,bool(s),s and t,s or t,sep="|")
print(len(s),len(t),s==t,s!=t,s<t,s<=t,s>t,s>=t)
print("猫" in s,"猫" not in t,str(s),int(t))
'''
        self.compare(source,["猫\n  -٤٢ \n","\n１２３\n","a\ninvalid\n"])

    def test_string_branches_and_loop_phis(self):
        source='''n=int(input())
s="old"
if n>0:
    s="晴"
else:
    s="雨"
for i in range(n):
    if i%2:
        s=s+"!"
    else:
        s=s+"?"
print(s)
'''
        self.compare(source,["0\n","1\n","6\n"])

    def test_big_bounds_and_index_errors(self):
        source='''s="猫🐈海"
n=int(input())
print(s[::n],s[::-n],s.count("",-n,n))
print(s[n])
'''
        self.compare(source,["1\n","-1\n","0\n",f"{10**200}\n",f"{-10**200}\n"])

    def test_repetition_overflow_order(self):
        source='''def text():
    print(1)
    return input()
def count():
    print(2)
    return int(input())
print(text()*count())
'''
        reverse='''def text():
    print(1)
    return input()
def count():
    print(2)
    return int(input())
print(count()*text())
'''
        self.compare(source,["猫\n3\n",f"\n{10**200}\n",f"\n{-10**200}\n"])
        self.compare(reverse,["3\n猫\n",f"{10**200}\n\n",f"{-10**200}\n\n"])

    def test_readonly_specializations_and_chained_comparisons(self):
        self.compare('''def format_number(x,prefix="猫"):
    return prefix+str(x)
def check(a,b,c):
    return a<b<c
print(format_number(10**100),format_number(True,"海"),check("a","b","c"))
print("1"!=1,"1"==1,"a"<"b"!=2<3)
''')

    test_strip = _methods.NativeTextMethodTests.test_strip_unicode_whitespace_and_character_sets
    test_count = _methods.NativeTextMethodTests.test_count_nonoverlap_empty_pattern_and_character_bounds
    test_join = _methods.NativeTextMethodTests.test_join_literals_nested_generators_and_filters
    test_join_order = _methods.NativeTextMethodTests.test_receiver_arguments_and_generator_failure_timing
    test_specialized_methods = _methods.NativeTextMethodTests.test_methods_inside_specialized_functions


if __name__=="__main__":
    unittest.main()
