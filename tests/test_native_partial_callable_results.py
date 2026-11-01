"""Captured empty builtin results retain their structural element constraints."""
import shutil
import unittest
from tests import test_native_module_linking as linked_helpers


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class PartialCallableResultTests(unittest.TestCase):
    exercise=linked_helpers.NativeLinkedModuleTests.exercise

    def test_builtin_empty_list_through_parameter(self):
        self.exercise({'main.py':"""class Marker:pass
def create(factory):return factory()
a=create(list)
a.append(7)
print(a)
"""})

    def test_builtin_empty_list_stored_in_container(self):
        self.exercise({'main.py':"""class Marker:pass
constructors=[list]
a=constructors[0]()
a.append('x')
print(a)
"""})

    def test_builtin_empty_list_in_field(self):
        self.exercise({'main.py':"""class Box:
 def __init__(self):self.factory=list
b=Box()
a=b.factory()
a.append(8)
print(a)
"""})
