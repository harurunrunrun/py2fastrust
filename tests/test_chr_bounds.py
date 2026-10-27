"""chr validates its original integer before narrowing to a Unicode scalar."""
import shutil
import unittest
import test_codecs


@unittest.skipUnless(shutil.which('rustc'), 'rustc is required')
class ChrBoundsTests(unittest.TestCase):
    setUpClass = classmethod(test_codecs.CodecTests.setUpClass.__func__)
    tearDownClass = classmethod(test_codecs.CodecTests.tearDownClass.__func__)
    compare = test_codecs.CodecTests.compare

    def test_valid_scalars_and_out_of_range_integers_do_not_truncate(self):
        self.compare('''
            for value in [0,65,127,128,0xd7ff,0xe000,0xffff,0x10000,0x10ffff]:
                print(ascii(chr(value)),ord(chr(value)))
            for value in [-1,0x110000,0x100000000,0x100000041,0x7fffffffffffffff]:
                try:print(ascii(chr(value)))
                except ValueError as error:print(type(error).__name__,str(error))
        ''')

    def test_index_protocol_and_native_integer_subclasses(self):
        self.compare('''
            class Number:
                def __init__(self,value):self.value=value
                def __index__(self):print('index',self.value);return self.value
            class Native(int):
                def __index__(self):raise AssertionError('native payload wins')
            for value in [Number(65),Number(0x100000041),Native(65),Native(0x100000041)]:
                try:print(ascii(chr(value)))
                except ValueError as error:print(type(error).__name__,str(error))
        ''')


if __name__=='__main__':
    unittest.main()
