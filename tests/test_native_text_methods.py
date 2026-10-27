"""Character operations and join timing against CPython 3.14."""
import itertools
import shutil
import unittest

import test_native_slices as _slices


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeTextMethodTests(unittest.TestCase):
    def compare(self, source, inputs=("",)):
        return _slices.NativeSliceTests.compare(self, source, inputs, modes=("i64", "i128"))

    def test_strip_unicode_whitespace_and_character_sets(self):
        source = '''s=input()
chars=input()
print(s.strip(),s.lstrip(),s.rstrip(),sep="|")
print(s.strip(None),s.lstrip(None),s.rstrip(None),sep="|")
print(s.strip(chars),s.lstrip(chars),s.rstrip(chars),sep="|")
print(s.strip(""),sep="|")
'''
        self.compare(source,[f"{s}\n{chars}\n" for s,chars in [
            ("", ""), ("  a b  ", " "), ("abcabc", "ab"),
            ("\x1c\u0085\u2003猫🐈\u3000\x1f", "猫🐈"), ("猫海猫海", "海猫"),
            ("\ufeffa\u200b", "\ufeff\u200b"), ("🐈abc🐈", "🐈")]])

    def test_count_nonoverlap_empty_pattern_and_character_bounds(self):
        source = '''s=input()
pattern=input()
print(s.count(pattern),s.count(pattern,None,None))
n=int(input())
for _ in range(n):
    start,stop=map(int,input().split())
    print(s.count(pattern,start,stop))
'''
        bounds = list(itertools.product([-2**63,-100,-6,-1,0,1,6,100,2**63-1],repeat=2))
        suffix=str(len(bounds))+"\n"+"".join(f"{a} {b}\n" for a,b in bounds)
        self.compare(source,[f"{s}\n{p}\n{suffix}" for s,p in [
            ("", ""), ("", "a"), ("aaaaa", "aa"), ("ababa", "aba"),
            ("猫🐈猫🐈海", "猫🐈"), ("猫🐈猫🐈海", ""), ("éé🐈", "́"),
            ("abc", "abcdef")]])

    def test_join_literals_nested_generators_and_filters(self):
        source = '''n=int(input())
print("-".join(["猫","海","🐈"]))
print("|".join(("a","","b")))
print("猫".join([]),"x".join(()),sep="|")
print("|".join(str(i*j) for i in range(n) if i%2 for j in range(3) if j!=1))
print("".join("o" if i%2 else "x" for i in range(n)))
'''
        self.compare(source,["0\n","1\n","7\n"])

    def test_receiver_arguments_and_generator_failure_timing(self):
        source = '''def text(x):
    print(x)
    return input()
def piece(i):
    print(i)
    return str(12//i)
print(text(1).strip(text(2)))
print(text(3).count(text(4),int(input()),int(input())))
print(text(5).join(piece(i) for i in [1,2,0,3]))
print(99)
'''
        self.compare(source,["abccba\nab\nabcabc\nab\n0\n6\n,\n",
                             "abccba\nab\nabcabc\nab\ninvalid\n6\n,\n"])

    def test_methods_inside_specialized_functions(self):
        source = '''def clean(s):
    return s.strip(" 海")
def score(s):
    return s.count("猫",0,None)
def make(n):
    return ":".join(str(i) for i in range(n))
print(clean(" 海猫海 "),score("猫海猫"),make(5))
'''
        self.compare(source)


if __name__ == "__main__":
    unittest.main()
