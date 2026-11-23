"""del obj[key] dispatches to a source class's __delitem__, compared with CPython."""
import unittest

from test_native_exception_handlers import compare


class NativeSourceDelitemTests(unittest.TestCase):
    def test_delitem_receives_keys_and_errors_propagate(self):
        compare(self, '''class Shelf:
    def __init__(self):
        self.items = [10, 20, 30, 40]
        self.log = []
    def __getitem__(self, index):
        return self.items[index]
    def __delitem__(self, index):
        self.log.append(index)
        if index >= len(self.items):
            raise IndexError("shelf index out of range")
        del self.items[index]
class Labeled(Shelf):
    pass
shelf = Shelf()
del shelf[1]
del shelf[-1]
print(shelf.items, shelf.log, shelf[0])
other = Labeled()
del other[0]
print(other.items)
try:
    del other[9]
except IndexError as error:
    print("caught", error)
del other[7]
''', '')


if __name__ == '__main__':
    unittest.main()
