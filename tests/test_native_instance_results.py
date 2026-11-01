"""Mutable object handles keep identity across finite result and binding joins."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import TranspileOptions, transpile

PROGRAMS = {'constructor_if_expression': 'class Box:\n'
                              '    def __init__(self, value):\n'
                              '        self.values = [value]\n'
                              'flag=int(input())\n'
                              'value=Box(3) if flag else 0\n'
                              'print(value is None)\n',
 'constructor_if_statement': 'class Box:\n'
                             '    def __init__(self, value):\n'
                             '        self.values = [value]\n'
                             'flag=int(input())\n'
                             'if flag:\n'
                             '    value=Box(3)\n'
                             'else:\n'
                             '    value=0\n'
                             'print(value is None)\n',
 'returned_shared_instance': 'class Box:\n'
                             '    def __init__(self, value):\n'
                             '        self.values = [value]\n'
                             'box=Box(3)\n'
                             'def choose(flag):\n'
                             '    if flag:\n'
                             '        return box\n'
                             '    return 0\n'
                             'value=choose(int(input()))\n'
                             'box.values.append(9)\n'
                             'print(value is box, box.values)\n',
 'distinct_classes': 'class Box:\n'
                     '    def __init__(self, value):\n'
                     '        self.values = [value]\n'
                     'class Other:\n'
                     '    def __init__(self):\n'
                     '        self.value=7\n'
                     'left=Box(3)\n'
                     'right=Other()\n'
                     'def choose(flag):\n'
                     '    if flag:\n'
                     '        return left\n'
                     '    return right\n'
                     'value=choose(int(input()))\n'
                     'left.values.append(9)\n'
                     'print(value is left, value is right, left.values)\n',
 'tuple_result': 'class Box:\n'
                 '    def __init__(self, value):\n'
                 '        self.values = [value]\n'
                 'box=Box(3)\n'
                 'def choose(flag):\n'
                 '    if flag:\n'
                 '        return (box, 5)\n'
                 '    return (0, 5)\n'
                 'pair=choose(int(input()))\n'
                 'box.values.append(9)\n'
                 'print(pair[0] is box, pair[1], box.values)\n',
 'list_instances_and_integers': 'class Box:\n'
                                '    def __init__(self, value):\n'
                                '        self.values = [value]\n'
                                'box=Box(3)\n'
                                'values=[box,0]\n'
                                'values.append(box)\n'
                                'box.values.append(9)\n'
                                'print(values[0] is box, values[1] is box, values[2] is box, '
                                'box.values)\n',
 'loop_binding_changes': 'class Box:\n'
                         '    def __init__(self, value):\n'
                         '        self.values = [value]\n'
                         'box=Box(3)\n'
                         'value=box\n'
                         'for i in range(int(input())):\n'
                         '    if i%2:\n'
                         '        value=box\n'
                         '    else:\n'
                         '        value=i\n'
                         'box.values.append(9)\n'
                         'print(value is box,box.values)\n',
 'constructor_effects': 'class Box:\n'
                        '    def __init__(self, value):\n'
                        '        print("constructed",value)\n'
                        '        self.value=value\n'
                        'def argument():\n'
                        '    print("argument")\n'
                        '    return int(input())\n'
                        'flag=int(input())\n'
                        'if flag:\n'
                        '    value=Box(argument())\n'
                        'else:\n'
                        '    value=0\n'
                        'print(value is None)\n'}


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeInstanceResultTests(unittest.TestCase):
    def compare(self, name):
        source=PROGRAMS[name]
        inputs=("0\n","1\n","2\n","3\n") if name=="loop_binding_changes" else ("0\n","1\n")
        if name=="constructor_effects":inputs=("0\n","1\n12\n","1\nbad\n")
        references=[subprocess.run([sys.executable,"-c",source],input=data,capture_output=True,
                                  text=True,timeout=10) for data in inputs]
        with tempfile.TemporaryDirectory(prefix="pytors-instance-results-") as directory:
            for integer in ("i64","i128","bigint"):
                result=transpile(source,TranspileOptions(integer=integer,license="none"))
                self.assertTrue(result.success,result.diagnostics)
                self.assertEqual(result.backend,"native")
                path=Path(directory)/"main.rs";path.write_text(result.rust_source)
                for release in (False,True):
                    binary=Path(directory)/"main"
                    compiled=subprocess.run(["rustc","--edition=2021",*(["-O"] if release else []),
                        str(path),"-o",str(binary)],capture_output=True,text=True,timeout=90)
                    self.assertEqual(compiled.returncode,0,compiled.stderr)
                    for data,reference in zip(inputs,references):
                        with self.subTest(program=name,integer=integer,release=release,input=data):
                            actual=subprocess.run([str(binary)],input=data,capture_output=True,text=True,
                                timeout=10,env={"PATH":"/unavailable","PYTHONPATH":"/unavailable"})
                            self.assertEqual((actual.returncode,actual.stdout),
                                (reference.returncode,reference.stdout),actual.stderr+reference.stderr)
                            if reference.returncode:
                                self.assertEqual(actual.stderr.splitlines()[-1],reference.stderr.splitlines()[-1])
                            else:self.assertEqual(actual.stderr,"")

    def test_constructor_if_expression(self):
        self.compare('constructor_if_expression')

    def test_constructor_if_statement(self):
        self.compare('constructor_if_statement')

    def test_returned_shared_instance(self):
        self.compare('returned_shared_instance')

    def test_distinct_classes(self):
        self.compare('distinct_classes')

    def test_tuple_result(self):
        self.compare('tuple_result')

    def test_list_instances_and_integers(self):
        self.compare('list_instances_and_integers')

    def test_loop_binding_changes(self):
        self.compare('loop_binding_changes')

    def test_constructor_effects(self):
        self.compare('constructor_effects')

