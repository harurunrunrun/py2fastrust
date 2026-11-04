"""Immediate classmethod calls retain lookup order and stored method identity."""
import shutil
import unittest
import test_native_lambda_callbacks as helpers

CASES={'class_and_instance': 'class Gauge:\n scale=7\n @classmethod\n def score(cls,x=2):return cls.scale*x\ndef main():\n g=Gauge()\n alias=Gauge\n print(Gauge.score(),g.score(3),alias.score(4))\nmain()\n', 'receiver_effect_before_arguments': "events=[]\nclass Meter:\n @classmethod\n def put(cls,x):\n  events.append('body')\n  return x+8\ndef receiver():\n events.append('receiver')\n return Meter()\ndef argument():\n events.append('argument')\n return 5\nprint(receiver().put(argument()),events)\n", 'class_rebind_after_lookup': 'class First:\n factor=6\n @classmethod\n def score(cls,x):return cls.factor*x\nclass Later:\n factor=31\ndef argument():\n global First\n First=Later\n return 3\nprint(First.score(argument()),First.factor)\n', 'stored_identity_and_immediate_calls': 'class Meter:\n @classmethod\n def run(cls,x):return x+4\nm=Meter()\na=Meter.run\nb=m.run\nsame=a\nprint(a==b,a is b,a is same,Meter.run is Meter.run)\nprint(Meter.run(2),m.run(5),a(8),b(11))\n', 'mutable_class_storage_and_recursion': 'class Ledger:\n values=[]\n @classmethod\n def record(cls,n):\n  cls.values.append(n)\n  if n:return cls.record(n-1)+n\n  return 0\nprint(Ledger.record(4),Ledger.values)\n', 'defaults_and_keyword_effects': "events=[]\ndef mark(label,value):\n events.append(label)\n return value\nclass Scale:\n @classmethod\n def score(cls,x=mark('default',4),/,y=5,*,z=6):return x+y+z\nprint(Scale.score(),Scale().score(mark('x',7),z=mark('z',9)),events)\n", 'missing_argument_after_effect': "class Scale:\n @classmethod\n def score(cls,x,y):return x+y\ndef mark():\n print('argument evaluated')\n return 4\nScale.score(mark())\n", 'duplicate_argument_after_effect': "class Scale:\n @classmethod\n def score(cls,x):return x\ndef mark():\n print('keyword evaluated')\n return 9\nScale().score(3,x=mark())\n", 'body_exception_frames': "class Scale:\n @classmethod\n def score(cls,x):return 23//x\ndef main():\n print('calling')\n Scale.score(0)\nmain()\n", 'spread_call_retains_regular_path': 'class Scale:\n @classmethod\n def score(cls,*values,offset=2):return sum(values)+offset\nprint(Scale.score(*[3,7],offset=11),Scale().score(5,9))\n', 'different_class_targets': 'class East:\n @classmethod\n def value(cls,x):return x+3\nclass West:\n @classmethod\n def value(cls,x):return 5*x\ndef call(function):return function(7)\nprint(call(East.value),call(West().value),East.value(2),West.value(4))\n'}

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class ImmediateClassMethodTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    exercise=helpers.NativeLambdaCallbackTests.exercise


def install(name,source):
    def test(self):self.exercise(source)
    setattr(ImmediateClassMethodTests,'test_'+name,test)

for name,source in CASES.items():install(name,source)
