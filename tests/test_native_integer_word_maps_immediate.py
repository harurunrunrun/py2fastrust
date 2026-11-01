"""Immediate integer-word list/unpack collectors preserve Python effects."""
import shutil
import unittest
import test_native_class_iterators as iterator_tests

CASES={'frame_list_text': 'class Box:\n'
                    ' def run(self,text):return list(map(int,text.split()))\n'
                    'print(Box().run("2 -7 10 1_000"))\n',
 'frame_list_bytes': 'class Box:\n'
                     ' def run(self,text):return list(map(int,text.split()))\n'
                     'print(Box().run(b"2 -7 10 1_000"))\n',
 'frame_unpack_text': 'class Box:\n'
                      ' def run(self,text):\n'
                      '  a,b,c=map(int,text.split())\n'
                      '  return a+b+c\n'
                      'print(Box().run("2 -7 10"))\n',
 'frame_unpack_short': 'class Box:\n'
                       ' def run(self,text):\n'
                       '  a,b,c=map(int,text.split())\n'
                       '  return a+b+c\n'
                       'print(Box().run("2 -7"))\n',
 'frame_unpack_long': 'class Box:\n'
                      ' def run(self,text):\n'
                      '  a,b=map(int,text.split())\n'
                      '  return a+b\n'
                      'print(Box().run("2 -7 10"))\n',
 'frame_unpack_bad_extra': 'class Box:\n'
                           ' def run(self,text):\n'
                           '  a,b=map(int,text.split())\n'
                           '  return a+b\n'
                           'print(Box().run("2 -7 bad"))\n',
 'frame_unpack_bad_before_short': 'class Box:\n'
                                  ' def run(self,text):\n'
                                  '  a,b,c=map(int,text.split())\n'
                                  '  return a+b+c\n'
                                  'print(Box().run("2 bad"))\n',
 'frame_empty_unpack': 'class Box:\n'
                       ' def run(self,text):\n'
                       '  ()=map(int,text.split())\n'
                       '  return 7\n'
                       'print(Box().run(""))\n',
 'frame_empty_unpack_bad_extra': 'class Box:\n'
                                 ' def run(self,text):\n'
                                 '  ()=map(int,text.split())\n'
                                 '  return 7\n'
                                 'print(Box().run("bad"))\n',
 'frame_split_effects': 'class Box:\n'
                        ' def run(self,text):\n'
                        '  def sep():\n'
                        '   print("separator")\n'
                        '   return ","\n'
                        '  return '
                        'list(map(int,text.split(sep=sep(),maxsplit=-1)))\n'
                        'print(Box().run("2,-7,10"))\n',
 'frame_rsplit_list': 'class Box:\n'
                      ' def run(self,text):return '
                      'list(map(int,text.rsplit(",")))\n'
                      'print(Box().run("2,-7,10"))\n',
 'frame_saved_words_remain_live': 'class Box:\n'
                                  ' def run(self,text):\n'
                                  '  words=text.split()\n'
                                  '  words[0]="7"\n'
                                  '  return list(map(int,words))\n'
                                  'print(Box().run("2 -7 10"))\n',
 'frame_multiline_unpack_error': 'class Box:\n'
                                 ' def run(self,text):\n'
                                 '  a,b=(\n'
                                 '   map(int,text.split())\n'
                                 '  )\n'
                                 '  return a+b\n'
                                 'print(Box().run("2 bad"))\n',
 'frame_multiline_list_error': 'class Box:\n'
                               ' def run(self,text):\n'
                               '  return list(\n'
                               '   map(int,text.split())\n'
                               '  )\n'
                               'print(Box().run("2 bad"))\n',
 'frame_long_invalid_list': 'class Box:\n'
                            ' def run(self,text):return '
                            'list(map(int,text.split()))\n'
                            "print(Box().run('9999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999bad'))\n",
 'frame_long_invalid_cursor': 'class Box:\n'
                              ' def run(self,text):\n'
                              '  words=map(int,text.split())\n'
                              '  return list(words)\n'
                              "print(Box().run('9999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999bad'))\n",
 'unicode_frame_list': 'class Box:\n'
                       ' def run(self,text):return '
                       'list(map(int,text.split()))\n'
                       'print(Box().run("１２\u3000-٣٤ ५६"))\n',
 'frame_integer_widths': 'class Box:\n'
                         ' def run(self,text):return '
                         'list(map(int,text.split()))\n'
                         'print(Box().run("-9223372036854775808 '
                         '9223372036854775807"))\n'}

CASES.update({'captured_list_alias': 'collect=list\n'
                        'class Box:\n'
                        ' def run(self,text):return '
                        'collect(map(int,text.split()))\n'
                        'print(Box().run("2 -7 10"))\n',
 'captured_list_before_shadow': 'collect=list\n'
                                'list=7\n'
                                'class Box:\n'
                                ' def run(self,text):return '
                                'collect(map(int,text.split()))\n'
                                'print(Box().run("2 -7 10"))\n',
 'captured_list_before_source_effect': 'collect=list\n'
                                       'def source():\n'
                                       ' global collect\n'
                                       ' collect=None\n'
                                       ' print("source")\n'
                                       ' return "2 -7 10"\n'
                                       'class Box:\n'
                                       ' def run(self):return '
                                       'collect(map(int,source().split()))\n'
                                       'print(Box().run())\n'})

@unittest.skipUnless(shutil.which("rustc"),"rustc required")
class ImmediateIntegerWords(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check

    def test_frame_list_text(self):
        self.check('frame_list_text')

    def test_frame_list_bytes(self):
        self.check('frame_list_bytes')

    def test_frame_unpack_text(self):
        self.check('frame_unpack_text')

    def test_frame_unpack_short(self):
        self.check('frame_unpack_short')

    def test_frame_unpack_long(self):
        self.check('frame_unpack_long')

    def test_frame_unpack_bad_extra(self):
        self.check('frame_unpack_bad_extra')

    def test_frame_unpack_bad_before_short(self):
        self.check('frame_unpack_bad_before_short')

    def test_frame_empty_unpack(self):
        self.check('frame_empty_unpack')

    def test_frame_empty_unpack_bad_extra(self):
        self.check('frame_empty_unpack_bad_extra')

    def test_frame_split_effects(self):
        self.check('frame_split_effects')

    def test_frame_rsplit_list(self):
        self.check('frame_rsplit_list')

    def test_frame_saved_words_remain_live(self):
        self.check('frame_saved_words_remain_live')

    def test_frame_multiline_unpack_error(self):
        self.check('frame_multiline_unpack_error')

    def test_frame_multiline_list_error(self):
        self.check('frame_multiline_list_error')

    def test_frame_long_invalid_list(self):
        self.check('frame_long_invalid_list')

    def test_frame_long_invalid_cursor(self):
        self.check('frame_long_invalid_cursor')

    def test_unicode_frame_list(self):
        self.check('unicode_frame_list')

    def test_frame_integer_widths(self):
        self.check('frame_integer_widths')


    def test_captured_list_alias(self):
        self.check('captured_list_alias')

    def test_captured_list_before_shadow(self):
        self.check('captured_list_before_shadow')

    def test_captured_list_before_source_effect(self):
        self.check('captured_list_before_source_effect')

