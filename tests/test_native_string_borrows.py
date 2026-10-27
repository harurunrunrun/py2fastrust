"""Read-only String consumers borrow without changing Python evaluation order."""
from py2fastrust.native import try_generate_native
from test_native import NativeTests


class NativeStringBorrowTests(NativeTests):
    def test_unicode_reads_and_comparisons_do_not_clone_in_a_loop(self):
        source = '''
s = input()
t = input()
n = int(input())
total = 0
for i in range(n):
    total += len(s)
    print(s, len(s), s[0], s[-1], s == t, s < t, s > t)
    print("猫" in s, "é" not in s, str(s), len(str(s)))
print(total)
'''
        self.differential(source, ("猫🐈é\n猫🐈ê\n0\n", "猫🐈é\n猫🐈ê\n3\n", "abcd\nabc\n2\n"))
        rust = try_generate_native(source, "reads.py", "i64")
        main = rust[rust.index("fn main() {"):]
        loop = main[main.index("for "):main.index("\nstd::io::stdout()")]
        self.assertNotIn(".clone()", main)
        self.assertNotIn("String::from", loop)
        self.assertNotIn(".to_owned()", loop)
        self.assertIn(": &str =", loop)
        self.assertNotIn("enum Value", rust)

    def test_owned_temporary_reads_and_chains_preserve_input_snapshots(self):
        self.differential('''
def make(value):
    print("made", value)
    return "海" + str(value)
print(len(make(1)), make(2)[-1], make(3) == make(3), "海" in make(4))
print(len(input()), input()[int(input())], input() == input(), str(input()), input())
print("z" < "a" < input())
print(input())
''', ("猫🐈é\n猫🐈\n-1\nsame\nsame\nfirst\nsecond\nunused\n",
      "abc\nabc\n0\na\nb\nleft\nright\nlast\n"))

    def test_call_arguments_remain_owning_and_caller_strings_keep_their_values(self):
        source = '''
def mutate(value):
    before = value
    value += input()
    print("callee", before, value)
    return value
s = input()
saved = s
print(s, mutate(s), s)
print(saved, s, saved == s)
'''
        self.differential(source, ("猫🐈\n!\n", "\n海\n"))
        rust = try_generate_native(source, "snapshots.py", "i64")
        self.assertRegex(rust, r"fn native_function_\d+_str\(native_argument_0: String")
        main = rust[rust.index("fn main() {"):]
        # The saved binding and by-value argument still need owned snapshots.
        self.assertIn(".clone()", main)

    def test_index_and_comparison_call_order_and_short_circuit(self):
        self.differential('''
def index(value):
    print("index", value)
    return value
def make(value):
    print("make", value)
    return input()
s = input()
print(s, s[index(-1)], len(make(1)), s)
print(make(2) < make(3) < make(4))
print(input())
''', ("猫🐈\n海\na\nb\nc\ntail\n", "abc\nxyz\nz\na\nnot-consumed\n"))

    def test_string_conversions_read_borrowed_unicode_and_keep_errors(self):
        source = '''
text = input()
n = int(input())
for i in range(n):
    print("ready", len(text), bool(text), int(text), float(text))
'''
        self.differential(source, ("１２\n2\n", " -٤٢ \n1\n", "bad\n1\n", "\n1\n"))
        rust = try_generate_native(source, "conversion.py", "i128")
        main = rust[rust.index("fn main() {"):]
        self.assertNotIn(".clone()", main)

    def test_nested_owned_conditionals_and_boolean_results_remain_valid(self):
        self.differential('''
flag = int(input())
s = input()
t = input()
print(len(s if flag else t), (s if flag else t)[-1])
print((s or t), (t and s), len(str()), str(), str(str()), str(True))
print(len(input() + input()), (input() + input())[-1])
''', ("1\n猫\n海\na\nb\n🐈\né\n", "0\n\n海\n\n\nx\ny\n"))


for _name in dir(NativeTests):
    if _name.startswith("test_") and _name not in NativeStringBorrowTests.__dict__:
        setattr(NativeStringBorrowTests, _name, None)
del NativeTests
