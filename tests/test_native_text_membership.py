"""Text containment observes native text views without copying either operand."""
import unittest
import test_native_atexit as shutdown_tests
import test_native_slices as slice_tests


CASES = {
    'fields_and_empty_patterns': '''class Label:
 def __init__(self,text):self.text=text
 def has(self,pattern):return pattern in self.text
label=Label("cobalt-lantern")
for pattern in ["","lan","moon","cobalt-lantern-longer"]:
 print(label.has(pattern),pattern not in label.text)
print(label.text)
''',
    'evaluation_and_chaining': '''events=[]
def pattern():
 events.append(1)
 return "ray"
def text():
 events.append(2)
 return "sunray"
def other():
 events.append(3)
 return "cloud"
print(pattern() in text() != other())
print(events)
events.clear()
print(other() in text() != pattern())
print(events)
''',
    'unicode_views': '''class Label:
 def __init__(self,text):self.text=text
label=Label("銀河🐧é")
for pattern in ["","銀河","🐧","é","é","月"]:
 print(pattern in label.text,pattern not in label.text)
''',
}


class NativeTextMembershipTests(unittest.TestCase):
    def test_fields_and_empty_patterns(self):
        shutdown_tests.AtexitExecutionTests.compare(self, CASES['fields_and_empty_patterns'])

    def test_evaluation_and_chaining(self):
        shutdown_tests.AtexitExecutionTests.compare(self, CASES['evaluation_and_chaining'])

    def test_unicode_in_ascii_mode(self):
        shutdown_tests.AtexitExecutionTests.compare(self, CASES['unicode_views'])

    def test_unicode_mode(self):
        slice_tests.NativeSliceTests.compare(self, CASES['unicode_views'])
