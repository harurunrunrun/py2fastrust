"""Typed exception identities, payload sharing, logical tracebacks, and cleanup."""
from pathlib import Path
import hashlib,os,re,shutil,subprocess,sys,tempfile,unittest
from unittest.mock import patch
from py2fastrust import transpile,TranspileOptions

CASES = [('raise_builtin_class_0',
  'print("before")\nraise ValueError\n',
  '',
  'c3d0b00e1a1e045c2462cd4c3b11e14e3498bf9404aba250f7dae5ea0ad0ca9b'),
 ('raise_class_alias_0',
  'Selected=RuntimeError\nprint("before")\nraise Selected\n',
  '',
  '40b0cf3a79d417eeaf470bf6e677ac5255737a5cbfcc68e2098987b2e476e71a'),
 ('raise_direct_instance_0',
  'print("before")\nraise TypeError("bad value")\n',
  '',
  '42703e2d689a1489d7abf1592b453fc4fddbe9227ecbc94916235ce72e629500'),
 ('constructor_arguments_in_order_0',
  "def mark(value):print(value);return value\nraise ValueError(mark('first'),mark(7))\n",
  '',
  'c508a17027ce7489a39767034928fea2dce6e742a805c2937380caf21f3952bb'),
 ('finite_exception_class_alias_0',
  "Selected=ValueError if int(input())else TypeError\nraise Selected('selected',4)\n",
  '0\n',
  '8ceb37af644def716d72a26ae6023aad1d1e53e586d50fc906bb4361755bada3'),
 ('finite_exception_class_alias_1',
  "Selected=ValueError if int(input())else TypeError\nraise Selected('selected',4)\n",
  '1\n',
  '8ceb37af644def716d72a26ae6023aad1d1e53e586d50fc906bb4361755bada3'),
 ('stored_exception_instance_alias_0',
  "error=ValueError('stored')\nalias=error\nprint(alias is error)\nraise alias\n",
  '',
  '2382900cc41891679808eca62235a20c87af3d4759290627716906ecfff16f9f'),
 ('mutable_constructor_argument_retained_0',
  'items=[1]\nerror=ValueError(items)\nitems.append(2)\nraise error\n',
  '',
  'dfe1b3ebe1be7c149bf524743a3c0f2cd6e8b0fe13008fda19668173fcceeec8'),
 ('zero_and_tuple_arguments_0',
  "error=ValueError()\nprint(str(error))\nraise ValueError(('x',3))\n",
  '',
  '9890a512cde11a28e010cf5a256e5ece2662f98756962b66361a5bc95f2702c3'),
 ('exception_value_str_observation_0',
  "error=TypeError('x',3)\nprint(str(error))\nraise error\n",
  '',
  '660df02ecc852f34b540fe81020c64e6b32a288c13ad078e98ce7f1b8d2157df'),
 ('traceback_retained_after_suppression_0',
  "error=ValueError('again')\n"
  'def fail():raise error\n'
  'class Guard:\n'
  ' def __enter__(self):return self\n'
  " def __exit__(self,a,b,c):print('suppress');return True\n"
  'with Guard():fail()\n'
  'raise error\n',
  '',
  '6c40604e22779c1f628846956b8b099506f416c11713c414b567309acdeb7820'),
 ('with_cleanup_on_explicit_raise_0',
  'class Guard:\n'
  " def __enter__(self):print('enter')\n"
  " def __exit__(self,a,b,c):print('exit')\n"
  "with Guard():raise ValueError('body')\n",
  '',
  '66c3b0f9f8b0af03f38af6e41035fa9bdc3dcbea99937f3219d5d812a9317ac3'),
 ('with_cleanup_error_context_0',
  'class Guard:\n'
  ' def __enter__(self):return self\n'
  " def __exit__(self,a,b,c):raise TypeError('cleanup')\n"
  "with Guard():raise ValueError('body')\n",
  '',
  '01c4daf80abe643ec9d25343b3a21c73b89882a004f0914119bd16f237250638'),
 ('stop_iteration_direct_0',
  'raise StopIteration(3)\n',
  '',
  '97fdc70df84bd4ed0aa2616ba5f79675337fccd2f01e2cf9015b8df17d096534'),
 ('stop_iteration_callback_map_resumes_0',
  'def word(value):\n'
  " print(value,end='|')\n"
  ' if value==2:raise StopIteration\n'
  ' return str(value)\n'
  'source=map(word,[1,2,3])\n'
  'print(list(source))\n'
  'print(next(source))\n',
  '',
  '2761bc58b36ee18c8abadd1c272699504534e02679a44aecb784858429760049'),
 ('stop_iteration_generator_direct_cause_0',
  'def word(value):\n'
  " if value==2:raise StopIteration('stopped')\n"
  ' return value\n'
  'print(list(word(value)for value in range(4)))\n',
  '',
  '94982b6a771ab8e01e5041554adb3abf832fb8a6a63af65fd86ce44687a435bc'),
 ('invalid_raised_value_0',
  'print("before")\nraise 3\n',
  '',
  '9455b4a5b3ff64684b5e0a413804904dadb493c7b8abc2eda58da6da6765942f'),
 ('constructor_error_after_argument_effects_0',
  "def mark():print('argument');return 3\nraise ValueError(unknown=mark())\n",
  '',
  'b0594b0f9d5245de7b0dbd8e4d59db177e17d1bb374fb7e41d01a05839e317ed'),
 ('same_instance_cleanup_does_not_chain_itself_0',
  "error=ValueError('same')\n"
  'class Guard:\n'
  ' def __enter__(self):return self\n'
  ' def __exit__(self,a,b,c):raise error\n'
  'with Guard():raise error\n',
  '',
  'dbf790d85732c727d7e0249b66b74dc44f96e19a8ae9d425cd69c2c64ce4b4fc'),
 ('reused_context_cycle_then_raise_first_0',
  "first=ValueError('one')\n"
  "second=TypeError('two')\n"
  'class Suppress:\n'
  ' def __enter__(self):return self\n'
  ' def __exit__(self,a,b,c):return True\n'
  'class RaiseFirst:\n'
  ' def __enter__(self):return self\n'
  ' def __exit__(self,a,b,c):raise first\n'
  'class RaiseSecond:\n'
  ' def __enter__(self):return self\n'
  ' def __exit__(self,a,b,c):raise second\n'
  'with Suppress():\n'
  ' with RaiseSecond():raise first\n'
  'with Suppress():\n'
  ' with RaiseFirst():raise second\n'
  'raise first\n',
  '',
  '3914fcb1187c4b423e59fd4d55b7f4ecd854bd94da65842c4341bc0d87575717'),
 ('reused_context_cycle_then_raise_second_0',
  "first=ValueError('one')\n"
  "second=TypeError('two')\n"
  'class Suppress:\n'
  ' def __enter__(self):return self\n'
  ' def __exit__(self,a,b,c):return True\n'
  'class RaiseFirst:\n'
  ' def __enter__(self):return self\n'
  ' def __exit__(self,a,b,c):raise first\n'
  'class RaiseSecond:\n'
  ' def __enter__(self):return self\n'
  ' def __exit__(self,a,b,c):raise second\n'
  'with Suppress():\n'
  ' with RaiseSecond():raise first\n'
  'with Suppress():\n'
  ' with RaiseFirst():raise second\n'
  'raise second\n',
  '',
  'aad3006cba2521808dec4e88eb71e3aa1a6be583b65146a2e93889de0bd81fdf'),
 ('context_retains_mutable_payload_0',
  'values=[1]\n'
  'first=ValueError(values)\n'
  "second=TypeError('cleanup')\n"
  'class Suppress:\n'
  ' def __enter__(self):return self\n'
  ' def __exit__(self,a,b,c):return True\n'
  'class Guard:\n'
  ' def __enter__(self):return self\n'
  ' def __exit__(self,a,b,c):raise second\n'
  'with Suppress():\n'
  ' with Guard():raise first\n'
  'values.append(2)\n'
  'raise second\n',
  '',
  'f369289a673773231b6dccd0565acd5eedb0190278e3494d09df2a02e9f93b51'),
 ('finite_exception_instance_choice_0',
  "error=ValueError('left')if int(input())else TypeError('right')\n"
  'print(repr(error),bool(error))\n'
  'raise error\n',
  '0\n',
  'd1b80a763c22ad1e91edb74e85276f512983ac5b372b51ece541ef6795db5cfe'),
 ('finite_exception_instance_choice_1',
  "error=ValueError('left')if int(input())else TypeError('right')\n"
  'print(repr(error),bool(error))\n'
  'raise error\n',
  '1\n',
  'd1b80a763c22ad1e91edb74e85276f512983ac5b372b51ece541ef6795db5cfe'),
 ('exception_class_sequence_0',
  "classes=[ValueError,TypeError]\nselected=classes[int(input())]\nraise selected('from sequence')\n",
  '0\n',
  'fa4164acae8f436348df720a8fe90a5da3e06a52395a8f28d09d0f52bf85aefa'),
 ('exception_class_sequence_1',
  "classes=[ValueError,TypeError]\nselected=classes[int(input())]\nraise selected('from sequence')\n",
  '1\n',
  'fa4164acae8f436348df720a8fe90a5da3e06a52395a8f28d09d0f52bf85aefa'),
 ('exception_return_from_function_0',
  'def make(value):return ValueError(value)\n'
  'def fail(error):raise error\n'
  'error=make([1,2])\n'
  'fail(error)\n',
  '',
  '62633670d7a9583cb3b7e810847ce2b6e308199f917d0590aaf6212eeec7f141'),
 ('exception_display_multiline_0',
  'error=RuntimeError("first\\nsecond")\nprint(str(error))\nraise error\n',
  '',
  'ea4d05ced4747c2955bd279b38d321eed4e14d6a2c40da6a0049c296309f696d'),
 ('context_observes_later_traceback',
  'first=ValueError("one")\n'
  'second=TypeError("two")\n'
  'class Suppress:\n'
  ' def __enter__(self):return self\n'
  ' def __exit__(self,a,b,c):return True\n'
  'class RaiseSecond:\n'
  ' def __enter__(self):return self\n'
  ' def __exit__(self,a,b,c):raise second\n'
  'with Suppress():\n'
  ' with RaiseSecond():raise first\n'
  'with Suppress():raise first\n'
  'raise second\n',
  '',
  '73a2c0ff4dd9eb4fc721ab2dcfca4f79aed5107799c2ab1cce88ce0235e24c9a'),
 ('pep479_cleanup_reuses_stop_instance',
  'error=StopIteration("same")\n'
  'class Guard:\n'
  ' def __enter__(self):return self\n'
  ' def __exit__(self,a,b,c):raise error\n'
  'def word():raise error\n'
  'with Guard():print(list(word()for _ in range(1)))\n',
  '',
  '457991d0c4798963fad565c2c62dc68ca42c0dfecb91fb83bc89df5925c699e9'),
 ('exception_type_predicates_0',
  'error=ValueError("x")if int(input())else TypeError("y")\n'
  'selected=ValueError if int(input())else TypeError\n'
  'print(isinstance(error,selected),isinstance(error,(ValueError,TypeError)),isinstance(3,ValueError),isinstance(ValueError,ValueError))\n',
  '0\n0\n',
  'ab4ff31e7f629039417bfe14d333fa212eafd50e6aa39ed4ebbdb590e898b604'),
 ('exception_type_predicates_1',
  'error=ValueError("x")if int(input())else TypeError("y")\n'
  'selected=ValueError if int(input())else TypeError\n'
  'print(isinstance(error,selected),isinstance(error,(ValueError,TypeError)),isinstance(3,ValueError),isinstance(ValueError,ValueError))\n',
  '0\n1\n',
  'ab4ff31e7f629039417bfe14d333fa212eafd50e6aa39ed4ebbdb590e898b604'),
 ('exception_type_predicates_2',
  'error=ValueError("x")if int(input())else TypeError("y")\n'
  'selected=ValueError if int(input())else TypeError\n'
  'print(isinstance(error,selected),isinstance(error,(ValueError,TypeError)),isinstance(3,ValueError),isinstance(ValueError,ValueError))\n',
  '1\n0\n',
  'ab4ff31e7f629039417bfe14d333fa212eafd50e6aa39ed4ebbdb590e898b604'),
 ('exception_type_predicates_3',
  'error=ValueError("x")if int(input())else TypeError("y")\n'
  'selected=ValueError if int(input())else TypeError\n'
  'print(isinstance(error,selected),isinstance(error,(ValueError,TypeError)),isinstance(3,ValueError),isinstance(ValueError,ValueError))\n',
  '1\n1\n',
  'ab4ff31e7f629039417bfe14d333fa212eafd50e6aa39ed4ebbdb590e898b604'),
 ('raise_stops_unreachable_lookup',
  'raise ValueError("stop")\nprint(missing_after_raise)\n',
  '',
  'f0fb19ff906bade48ffc1481a339dfaf5617d289d928e08a6448e63625fc2477'),
 ('review_typed_isinstance',
  'error=ValueError("x")\n'
  'print(isinstance(error,ValueError),isinstance(error,TypeError),isinstance(error,(TypeError,ValueError)))\n',
  '',
  '5bf8ed99d4441cd519c253768df84eef9155ae9af5d79f1b16086ca2d658de2c'),
 ('review_typed_classinfo_short_circuit',
  'error=ValueError("x")\n'
  'print(isinstance(error,(ValueError,123)))\n'
  'print(isinstance(error,(TypeError,123,ValueError)))\n',
  '',
  '2cf725b10e5ffe211e7f9b337b9ae402fbf49457047855d6ab65fe5602fc1256'),
 ('review_exception_identity',
  'def make(value):return RuntimeError(value)\n'
  'a=make(3)\n'
  'b=make(3)\n'
  'alias=a\n'
  'print(a is alias,a==alias,a is b,a==b,RuntimeError is RuntimeError,RuntimeError is ValueError)\n',
  '',
  '5a9732a7d6138b5976248e5669295ea7ce871a2ed88734d774d102e5a017d5b9'),
 ('review_numeric_conversion_type_name',
  'error=RuntimeError("7")\nprint(int(error))\n',
  '',
  '026e34d26baf08594446d273fc3bfce75c566024d0b0dd8790c6721cac02eed8'),
 ('review_mutable_nested_payload_cleanup',
  'values=[[1]]\n'
  'error=ValueError(values)\n'
  'class Change:\n'
  ' def __enter__(self):return self\n'
  ' def __exit__(self,a,b,c):\n'
  '  values[0].append(2)\n'
  '  print(str(error),repr(error))\n'
  '  return False\n'
  'with Change():raise error\n',
  '',
  'd8c57356181259f4c7ddab68c1426f72799f47233b15a3a77d22db973f0a64c6'),
 ('review_old_argument_binding_retained',
  'values=[]\n'
  'error=TypeError(values)\n'
  'alias=values\n'
  'values=[99]\n'
  'alias.append(7)\n'
  'print(error)\n'
  'raise error\n',
  '',
  'e1b7c89dc46de84313cae7783a742352d2db016817453f7225d54801025d034e'),
 ('review_three_exception_context_cycle',
  'first=ValueError("first")\n'
  'second=TypeError("second")\n'
  'third=RuntimeError("third")\n'
  'class Suppress:\n'
  ' def __enter__(self):return self\n'
  ' def __exit__(self,a,b,c):return True\n'
  'class First:\n'
  ' def __enter__(self):return self\n'
  ' def __exit__(self,a,b,c):raise first\n'
  'class Second:\n'
  ' def __enter__(self):return self\n'
  ' def __exit__(self,a,b,c):raise second\n'
  'class Third:\n'
  ' def __enter__(self):return self\n'
  ' def __exit__(self,a,b,c):raise third\n'
  'with Suppress():\n'
  ' with Second():raise first\n'
  'with Suppress():\n'
  ' with Third():raise second\n'
  'with Suppress():\n'
  ' with First():raise third\n'
  'raise second\n',
  '',
  '6da567af145c96afcb48e1731146f663b946c08dc073b3a467636d15f7197690'),
 ('review_context_trace_survives_local_frame',
  'class Suppress:\n'
  ' def __enter__(self):return self\n'
  ' def __exit__(self,a,b,c):return True\n'
  'class Raiser:\n'
  ' def __init__(self,error):self.error=error\n'
  ' def __enter__(self):return self\n'
  ' def __exit__(self,a,b,c):raise self.error\n'
  'def touch(error):raise error\n'
  'def make():\n'
  ' first=ValueError("first")\n'
  ' second=TypeError("second")\n'
  ' with Suppress():\n'
  '  with Raiser(second):raise first\n'
  ' with Suppress():touch(first)\n'
  ' return second\n'
  'raise make()\n',
  '',
  '3dd79271cd60767b30d5bc8fb0a3e511b854431db600e54cd65bfc3830d3c849'),
 ('identity_class_display_truth',
  'print(str(ValueError),repr(TypeError),bool(RuntimeError))\n',
  '',
  'fccbcecdac5edecfc5190ae0d465132eff3333b1f1b1053980a7421014f22686'),
 ('identity_value_truth_ignores_payload',
  'print(bool(ValueError()),bool(TypeError(0)),bool(RuntimeError(False)),bool(StopIteration([])))\n',
  '',
  '25fa046c65ba48397d08d2661e5f5a99dec374325c726bedf9b255690360bc18'),
 ('identity_class_conversion_type_name',
  'print(int(RuntimeError))\n',
  '',
  'e321561e96c7b7bd4f142f2a8afd1aaa2b198515a1bcc807e4bfaf97cc1c5789'),
 ('identity_alias_class_raise',
  'kind=StopIteration\nraise kind\n',
  '',
  'cd1a61e7ff8507f354d98d4bff2fc5b0364f1a6fdcf1eb0905e58d951a04e727'),
 ('identity_finite_class_raise_0',
  'kind=ValueError if int(input()) else TypeError\n'
  'error=kind("message")\n'
  'print(str(error),repr(error))\n'
  'raise error\n',
  '0\n',
  '253a707869391306bdbaf91d03b8833822fa76d4e24e78a50c11f5a6bde464d8'),
 ('identity_finite_class_raise_1',
  'kind=ValueError if int(input()) else TypeError\n'
  'error=kind("message")\n'
  'print(str(error),repr(error))\n'
  'raise error\n',
  '1\n',
  '253a707869391306bdbaf91d03b8833822fa76d4e24e78a50c11f5a6bde464d8'),
 ('identity_typed_non_stop_error_message',
  'def fail(value):\n'
  ' raise RuntimeError("StopIteration: misleading text")\n'
  'print(list(fail(value)for value in [1]))\n',
  '',
  '6673aa7324d265bf2d63562b2b7d5f31fe6067fb31d572e9a6c5e2305fd4b746'),
 ('identity_typed_stop_alias_generator',
  'kind=StopIteration\n'
  'def fail(value):\n'
  ' raise kind([value])\n'
  'print(list(fail(value)for value in [1]))\n',
  '',
  '627c1c034e44d3289bd831a6b80ba3459c00848a8dfd25af47a0fc6ab339127e'),
 ('cause_cleanup_replaces_wrapper',
  'stopped=StopIteration("stop")\n'
  'outer=RuntimeError("outer")\n'
  'class Suppress:\n'
  ' def __enter__(self):return self\n'
  ' def __exit__(self,a,b,c):return True\n'
  'class Raiser:\n'
  ' def __init__(self,error):self.error=error\n'
  ' def __enter__(self):return self\n'
  ' def __exit__(self,a,b,c):raise self.error\n'
  'def fail(value):raise stopped\n'
  'with Raiser(outer):\n'
  ' print(list(fail(value)for value in [1]))\n',
  '',
  'd2123aadf1220b7cbcde79b02e04419ae711f4a38664cdd8b1e0bfb4122e3fc3'),
 ('cause_cleanup_reuses_stop',
  'stopped=StopIteration("stop")\n'
  'outer=RuntimeError("outer")\n'
  'class Suppress:\n'
  ' def __enter__(self):return self\n'
  ' def __exit__(self,a,b,c):return True\n'
  'class Raiser:\n'
  ' def __init__(self,error):self.error=error\n'
  ' def __enter__(self):return self\n'
  ' def __exit__(self,a,b,c):raise self.error\n'
  'def fail(value):raise stopped\n'
  'with Raiser(stopped):\n'
  ' print(list(fail(value)for value in [1]))\n',
  '',
  '91860b2f491aa6b6097e7bb7b060e47fae8db2f16a0578c2994705c370c228a6'),
 ('cause_cause_context_cycle',
  'stopped=StopIteration("stop")\n'
  'outer=RuntimeError("outer")\n'
  'class Suppress:\n'
  ' def __enter__(self):return self\n'
  ' def __exit__(self,a,b,c):return True\n'
  'class Raiser:\n'
  ' def __init__(self,error):self.error=error\n'
  ' def __enter__(self):return self\n'
  ' def __exit__(self,a,b,c):raise self.error\n'
  'def fail(value):raise stopped\n'
  'with Suppress():\n'
  ' with Raiser(outer):\n'
  '  print(list(fail(value)for value in [1]))\n'
  'with Raiser(stopped):raise outer\n',
  '',
  'd9e60ac976db16f915fb7da133a56786c9cc0e78362fae62efd96f64ae92ed6c'),
 ('cause_cause_context_cycle_then_outer',
  'stopped=StopIteration("stop")\n'
  'outer=RuntimeError("outer")\n'
  'class Suppress:\n'
  ' def __enter__(self):return self\n'
  ' def __exit__(self,a,b,c):return True\n'
  'class Raiser:\n'
  ' def __init__(self,error):self.error=error\n'
  ' def __enter__(self):return self\n'
  ' def __exit__(self,a,b,c):raise self.error\n'
  'def fail(value):raise stopped\n'
  'with Suppress():\n'
  ' with Raiser(outer):\n'
  '  print(list(fail(value)for value in [1]))\n'
  'with Suppress():\n'
  ' with Raiser(stopped):raise outer\n'
  'raise outer\n',
  '',
  'dadea5b670a13382e72b9027b2c273258a4a305b02e7a47224b92aedf3434191')]

UNSUPPORTED = {'bare_raise_without_active_exception_0': 'print("before")\nraise\n',
 'explicit_cause_boundary_0': 'raise ValueError("outer")from TypeError("inner")\n',
 'exception_args_observation_0': 'error=ValueError("x",3)\nprint(error.args)\nraise error\n',
 'custom_exception_subclass_boundary_0': 'class Error(ValueError):pass\nraise Error("custom")\n',
 'review_exception_argument_cycle': 'items=[]\n'
                                    'error=ValueError(items)\n'
                                    'items.append(error)\n'
                                    'print(error)\n',
 'review_exception_args_observation': 'error=ValueError([1])\nprint(error.args)\n',
 'review_explicit_cause_not_yet_supported': 'raise RuntimeError("outer")from ValueError("inner")\n',
 'review_traceback_frame_keeps_local_identity': 'class Box:\n'
                                                ' def '
                                                '__init__(self):self.field_0=0;self.field_1=1;self.field_2=2;self.field_3=3;self.field_4=4;self.field_5=5;self.field_6=6;self.field_7=7;self.field_8=8;self.field_9=9;self.field_10=10\n'
                                                'error=ValueError("saved")\n'
                                                'saved=[]\n'
                                                'class Suppress:\n'
                                                ' def __enter__(self):return self\n'
                                                ' def __exit__(self,a,b,c):return True\n'
                                                'def fail():\n'
                                                ' box=Box()\n'
                                                ' saved.append(id(box))\n'
                                                ' raise error\n'
                                                'with Suppress():fail()\n'
                                                'new_box=Box()\n'
                                                'print(saved[0]==id(new_box))\n',
 'review_traceback_frame_keeps_local_identity_repeated': 'class Box:\n'
                                                         ' def '
                                                         '__init__(self):self.field_0=0;self.field_1=1;self.field_2=2;self.field_3=3;self.field_4=4;self.field_5=5;self.field_6=6;self.field_7=7;self.field_8=8;self.field_9=9;self.field_10=10\n'
                                                         'error=ValueError("saved")\n'
                                                         'saved=[]\n'
                                                         'class Suppress:\n'
                                                         ' def __enter__(self):return self\n'
                                                         ' def __exit__(self,a,b,c):return True\n'
                                                         'def fail():\n'
                                                         ' box=Box()\n'
                                                         ' saved.append(id(box))\n'
                                                         ' raise error\n'
                                                         'with Suppress():fail()\n'
                                                         'reused=False\n'
                                                         'for _ in range(100):\n'
                                                         ' new_box=Box()\n'
                                                         ' if id(new_box)==saved[0]:reused=True\n'
                                                         'print(reused)\n',
 'identity_class_identity_id': 'saved=ValueError\n'
                               'print(id(saved)==id(ValueError),id(ValueError)==id(TypeError))\n',
 'identity_builtin_alias': 'import builtins\nkind=builtins.ValueError\nraise kind("alias")\n'}

def canonical_error(stderr):
    rows=[];message=False
    for line in stderr.splitlines():
        if line=='Traceback (most recent call last):'or line.startswith('  File '):rows.append(line);message=False
        elif line in {'During handling of the above exception, another exception occurred:','The above exception was the direct cause of the following exception:'}:rows.append(line);message=False
        elif re.match(r'^[A-Za-z_][A-Za-z_0-9.]*(?:Error|Exception|Iteration)(?::|$)',line):rows.append(line);message=True
        elif message:rows.append(line)
    return rows

class NativeRaiseBoundaryTests(unittest.TestCase):
    def test_program_without_exception_values_omits_exception_protocol(self):
        source='class Box:\n def val(self):return 7\nprint(Box().val())\n'
        result=transpile(source)
        self.assertTrue(result.success,result.diagnostics)
        self.assertNotIn('ClassException',result.rust_source)
        self.assertNotIn('class_exception_',result.rust_source)

    def test_unsupported_exception_observation_protocols_are_positioned(self):
        for name,source in UNSUPPORTED.items():
            for mode in ('i64','i128','bigint'):
                with self.subTest(case=name,integer=mode):
                    result=transpile(source,TranspileOptions(filename='main.py',integer=mode))
                    self.assertFalse(result.success)
                    self.assertEqual(result.diagnostics[0].code,'E006')
                    self.assertGreater(result.diagnostics[0].line,0)
                    message=result.diagnostics[0].message
                    words=('frame-root','traceback frames')if 'local_identity'in name else ('active exception',)if 'bare_raise'in name else ('cause',)if 'cause'in name else ('inheritance',)if 'subclass'in name else ('class-object address',)if name=='identity_class_identity_id'else ('builtins',)if name=='identity_builtin_alias'else ('exception','recursive','ownership')
                    self.assertTrue(any(word in message for word in words),message)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeRaiseExecutionTests(unittest.TestCase):
    def exercise(self,source,stdin,string_mode='ascii',needs_unicode_repr=None):
        with tempfile.TemporaryDirectory(prefix='pytors-raise-')as directory:
            root=Path(directory);main=root/'main.py';main.write_text(source)
            expected=subprocess.run([sys.executable,'-S',str(main)],input=stdin,capture_output=True,text=True,timeout=15)
            for mode in ('i64','i128','bigint'):
                with self.subTest(integer=mode):
                    with patch('py2fastrust.codegen.generate',side_effect=AssertionError('legacy emitter entered')):
                        result=transpile(source,TranspileOptions(filename=str(main),integer=mode,string_mode=string_mode))
                    self.assertTrue(result.success,result.diagnostics)
                    self.assertEqual(result.backend,'native')
                    self.assertLess(len(result.rust_source.encode()),512*1024)
                    for marker in ('enum Value','enum Op','struct Runtime','struct PegParser'):
                        self.assertNotIn(marker,result.rust_source)
                    if string_mode=='ascii'or needs_unicode_repr is False:
                        self.assertNotIn('UNICODE LICENSE V3',result.rust_source)
                    elif needs_unicode_repr:
                        self.assertIn('UNICODE LICENSE V3',result.rust_source)
                    rust=root/(mode+'.rs');rust.write_text(result.rust_source)
                    for optimized in (False,True):
                        with self.subTest(optimized=optimized):
                            binary=root/(mode+('_release'if optimized else'_debug'))
                            build=subprocess.run(['rustc','--edition=2021','--crate-name','native_explicit_raise_tests',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=180)
                            self.assertEqual(build.returncode,0,build.stderr)
                            actual=subprocess.run([str(binary)],input=stdin,capture_output=True,text=True,timeout=15,env={**os.environ,'PATH':'/pytors-no-runtime-dependencies','PYTHONPATH':'/pytors-no-runtime-dependencies'})
                            self.assertEqual(actual.stdout,expected.stdout)
                            self.assertEqual(actual.returncode,expected.returncode,actual.stderr)
                            self.assertEqual(canonical_error(actual.stderr),canonical_error(expected.stderr))

def _execution(source,stdin,digest):
    def test(self):
        self.assertEqual(hashlib.sha256(source.encode()).hexdigest(),digest)
        self.exercise(source,stdin)
    return test


for _name,_source,_stdin,_digest in CASES:
    setattr(NativeRaiseExecutionTests,'test_'+_name,_execution(_source,_stdin,_digest))


UNICODE_REPR_CASES = [('single_string_raise',
  'raise ValueError("一つ")\n',
  '75314cf3bffa34437fc585af5a3d28ea26a6a891eb4486dca82033b7737941a5',
  False),
 ('stored_single_string_str',
  'error=ValueError("二つ")\nprint(str(error))\nraise error\n',
  'd832103bcfe7b64729ba9fe449c7c296cd5626c4903da21a8408998765adb1bc',
  False),
 ('explicit_repr',
  'error=ValueError("\\u200b")\nprint(repr(error))\nraise error\n',
  '99ca91c0bd9a28efd71985ea619402a0fe1c39b3b8b342d568376c8dfbb4b29b',
  True),
 ('container_repr',
  'error=ValueError("\\u200b")\nprint([error])\nraise error\n',
  '1c1e7dfec671cc9d48f4fb8da37536d26f9a1d0406d1686a61813d3174d9a09c',
  True),
 ('multiple_arguments',
  'raise TypeError("\\u200b",3)\n',
  'a5717bb8eb6cf9871beeed06780372b101612e6ad3a8fa6f693a16fbda82eb95',
  True),
 ('mutable_string_argument',
  'parts=["\\u200b"]\nerror=RuntimeError(parts)\nparts.append("ok")\nraise error\n',
  '71090e19a927217e7d36a85e739b9e9e5f7f8081af8f237e24c68d90ddb1b56b',
  True),
 ('separate_constructor_repr_demand',
  'first=ValueError("plain")\n'
  'second=TypeError("\\u200b")\n'
  'print(str(first),repr(second))\n'
  'raise first\n',
  '49775db0788305d14ce012a4f7e09f3fc49896b7fe295ce07df5701e9f08554e',
  True)]


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class NativeRaiseUnicodeExecutionTests(unittest.TestCase):
    exercise=NativeRaiseExecutionTests.exercise


def _unicode_execution(source,digest,needs_repr):
    def test(self):
        self.assertEqual(hashlib.sha256(source.encode()).hexdigest(),digest)
        self.exercise(source,"",string_mode="unicode",needs_unicode_repr=needs_repr)
    return test


for _name,_source,_digest,_needs_repr in UNICODE_REPR_CASES:
    setattr(NativeRaiseUnicodeExecutionTests,"test_"+_name,_unicode_execution(_source,_digest,_needs_repr))
