"""C iterator boundaries retain exception payloads, ownership and source frames."""
import hashlib,unittest
import test_native_explicit_raise as raise_tests
CASES=[('payload_map_next',
  'def callback(value):\n'
  ' raise StopIteration(41)\n'
  'it=map(callback,[1,2])\n'
  'print(next(it))\n',
  '',
  '046562271cd6b420638f9b3106584cf167b4dee9451718d430b79d0ecca53845'),
 ('payload_map_default',
  'def callback(value):\n'
  ' raise StopIteration(41)\n'
  'it=map(callback,[1,2])\n'
  'print(next(it,"default"))\n',
  '',
  '4d51a5c2bdffcc83e4c710340b9e301b4bf64d380d367a18d58dc477467e5016'),
 ('payload_filter_next',
  'def callback(value):\n'
  ' raise StopIteration(41)\n'
  'it=filter(callback,[1,2])\n'
  'print(next(it))\n',
  '',
  '08aaea37b9e6f6d8bf98a014dfb1901c9a631f7e4ce28a8d0514f69d574f8f2d'),
 ('payload_enumerate_map_next',
  'def callback(value):\n'
  ' raise StopIteration(41)\n'
  'it=enumerate(map(callback,[1,2]))\n'
  'print(next(it))\n',
  '',
  'c78bcc04f49cb761bd09cdaf2eaa51b3fb7aff50d63fa587ab0530fb85150dde'),
 ('payload_map_map_next',
  'def callback(value):\n'
  ' raise StopIteration(41)\n'
  'it=map(int,map(callback,[1,2]))\n'
  'print(next(it))\n',
  '',
  '2edaa3b97c9857984d8c85e19800f09ab82c8f66ba739dbe5185b64fe2e67793'),
 ('payload_zip_map_next',
  'def callback(value):\n'
  ' raise StopIteration(41)\n'
  'it=zip(map(callback,[1,2]),[3,4])\n'
  'print(next(it))\n',
  '',
  'e5910571a0919b8f11021e7b4a494a645d3bcff74ca550110dc495769375a55a'),
 ('payload_chain_map_next',
  'def callback(value):\n'
  ' raise StopIteration(41)\n'
  'from itertools import chain\n'
  'it=chain(map(callback,[1,2]))\n'
  'print(next(it))\n',
  '',
  '4e88c033aa9bb3ee4b23c665a28b36b042e4eb435adefaaf344646ee08237dd4'),
 ('payload_filter_map_next',
  'def callback(value):\n'
  ' raise StopIteration(41)\n'
  'it=filter(None,map(callback,[1,2]))\n'
  'print(next(it))\n',
  '',
  '93cc09b8eb4d576a0c94b0c38b5958d901ea6c1c0b38f6298c49162ed82c9687'),
 ('carrier_map_next_uncaught_0',
  "error=StopIteration('saved')\n"
  'def word(value):raise error\n'
  'next(map(word,[1]))\n',
  '',
  '27663e8027810ec1ffde63f5c9a1050ba2a225224102831e7ebf9117125bbc68'),
 ('carrier_map_list_then_reraise_0',
  "error=StopIteration('saved')\n"
  'def word(value):raise error\n'
  'print(list(map(word,[1])))\n'
  'raise error\n',
  '',
  'd3ca3f6364e2be2a7c1ff90eaa564599a5587fb57528afa12fe0fd6ed82006c6'),
 ('carrier_map_next_default_then_reraise_0',
  "error=StopIteration('saved')\n"
  'def word(value):raise error\n'
  'print(next(map(word,[1]),9))\n'
  'raise error\n',
  '',
  '63530621f3b8cb93e2c44feed8fd1139152ac44fe785d4050ebcaba9ca15d10d'),
 ('carrier_filter_next_uncaught_0',
  "error=StopIteration('saved')\n"
  'def word(value):raise error\n'
  'next(filter(word,[1]))\n',
  '',
  'bc6ee3b7e746a346a8fe8070dc960b953148fcb87b260f7f7eff2f1d136f102e'),
 ('carrier_filter_list_then_reraise_0',
  "error=StopIteration('saved')\n"
  'def word(value):raise error\n'
  'print(list(filter(word,[1])))\n'
  'raise error\n',
  '',
  '7b15624eefcdafc72f77df9c5dcf5e55fde1fd1166e52f8d940cbd6869d26b47'),
 ('carrier_zip_next_uncaught_0',
  "error=StopIteration('saved')\n"
  'def word(value):raise error\n'
  'next(zip(map(word,[1]),[2],strict=bool(int(input()))))\n',
  '0\n',
  '6467fe626a9c8e6b10bd116c74b59e065ced9604d550a21349e57eb6225cb556'),
 ('carrier_zip_next_uncaught_1',
  "error=StopIteration('saved')\n"
  'def word(value):raise error\n'
  'next(zip(map(word,[1]),[2],strict=bool(int(input()))))\n',
  '1\n',
  '6467fe626a9c8e6b10bd116c74b59e065ced9604d550a21349e57eb6225cb556'),
 ('carrier_enumerate_next_uncaught_0',
  "error=StopIteration('saved')\n"
  'def word(value):raise error\n'
  'next(enumerate(map(word,[1])))\n',
  '',
  '7f3912de700c1da7f5bd853d6b6fb060ba461c4d9625471ad090bcb7adbb4fd1'),
 ('carrier_chain_next_uncaught_0',
  'from itertools import chain\n'
  "error=StopIteration('saved')\n"
  'def word(value):raise error\n'
  'next(chain(map(word,[1]),[2]))\n',
  '',
  '9cb009e875c6fce1f132ed1d98da5b6675d50d68fe0b02337acfa4c0b37951c5'),
 ('carrier_generator_source_map_stop_0',
  "error=StopIteration('saved')\n"
  'def word(value):raise error\n'
  'print(list(value for value in map(word,[1])))\n'
  'raise error\n',
  '',
  '705b581b324c1bfe9d2e929b3567b1c88c8f69020fb447dcc03585c0e96d6f30'),
 ('carrier_filter_source_map_next_0',
  "error=StopIteration('saved')\n"
  'def word(value):raise error\n'
  'next(filter(None,map(word,[1])))\n',
  '',
  '5b69ef184e724bfa66e55464ee06825e9e7f7afa721e1214cbf93b95e2d0a377'),
 ('continue_map_strict_callback_stop_payload',
  'error=StopIteration("saved")\n'
  'def word(a,b):raise error\n'
  'next(map(word,[2],[3],strict=True))\n',
  '',
  'f0d6d29efcb23319d6291c31f92ad1ef5f879ee2e3d2d21ede07135e05ecfc66'),
 ('continue_map_strict_source_stop_equal_empty',
  'error=StopIteration("saved")\n'
  'def word(value):\n'
  ' if value==2:raise error\n'
  ' return value\n'
  'source=map(word,[2])\n'
  'stream=map(lambda a,b:a+b,source,[],strict=True)\n'
  'print(list(stream))\n'
  'raise error\n',
  '',
  '0584ac368468a3108463d8d2f37fe9b428642822c2fe0395017a8a3b96d4ad43'),
 ('continue_zip_strict_source_stop_equal_empty',
  'error=StopIteration("saved")\n'
  'def word(value):\n'
  ' if value==2:raise error\n'
  ' return value\n'
  'source=map(word,[2])\n'
  'stream=zip(source,[],strict=True)\n'
  'print(list(stream))\n'
  'raise error\n',
  '',
  'c9447fe59250363c8e0e53ed45a237790f072d29fe6109e6a5eee9c6e7727ea5'),
 ('continue_zip_strict_both_stop_same_payload',
  'error=StopIteration("saved")\n'
  'def word(value):\n'
  ' if value==2:raise error\n'
  ' return value\n'
  'stream=zip(map(word,[2]),map(word,[2]),strict=True)\n'
  'print(list(stream))\n'
  'raise error\n',
  '',
  'ae14add92f518ef94709b2f5e25a0047bdaa379e8a92010ffaf6a74c0e0ce9a5'),
 ('continue_map_strict_source_stop_shorter',
  'error=StopIteration("saved")\n'
  'def word(value):\n'
  ' if value==2:raise error\n'
  ' return value\n'
  'next(map(lambda a,b:a+b,map(word,[2]),[1],strict=True))\n',
  '',
  'c42c5d64c7a3d05b2cc5c667e3df88cc8680410aecfb102d3d27bb0116f8eb94'),
 ('continue_map_strict_final_source_stop',
  'error=StopIteration("saved")\n'
  'def word(value):\n'
  ' if value==2:raise error\n'
  ' return value\n'
  'next(map(lambda a,b:a+b,[1],map(word,[2]),strict=True))\n',
  '',
  '933b91b1a0c218104c7765ddaf9d4554a37915ba85f318eefbdef4b45f10e16b'),
 ('continue_chain_stop_moves_to_next_source',
  'error=StopIteration("saved")\n'
  'def word(value):\n'
  ' if value==2:raise error\n'
  ' return value\n'
  'from itertools import chain\n'
  'source=map(word,[1,2,3])\n'
  'stream=chain(source,[8,9])\n'
  'print(list(stream),list(stream),list(source))\n'
  'raise error\n',
  '',
  '8ef20964742263b26da8ca8010c352edd9043f6d2b01fd1ab0aab7cce5c14aaa'),
 ('continue_islice_error_fuses_only_its_cursor',
  'error=StopIteration("saved")\n'
  'def word(value):\n'
  ' if value==2:raise error\n'
  ' return value\n'
  'from itertools import islice\n'
  'source=map(word,[1,2,3])\n'
  'stream=islice(source,5)\n'
  'print(list(stream),list(stream),list(source))\n'
  'raise error\n',
  '',
  'c1fe2c7a2056e02e77553654a669d7920be4357cf1b09801f5669ad780e7dbf6'),
 ('continue_pairwise_error_clears_previous_item',
  'error=StopIteration("saved")\n'
  'def word(value):\n'
  ' if value==2:raise error\n'
  ' return value\n'
  'from itertools import pairwise\n'
  'source=map(word,[1,2,3,4])\n'
  'stream=pairwise(source)\n'
  'print(list(stream),list(stream),list(source))\n'
  'raise error\n',
  '',
  'fd0621408494067fdb5029e37d7972c6aa9d3dc55d2dc92438c1ecada36281b8'),
 ('continue_accumulate_source_stop_can_resume',
  'error=StopIteration("saved")\n'
  'def word(value):\n'
  ' if value==2:raise error\n'
  ' return value\n'
  'from itertools import accumulate\n'
  'source=map(word,[1,2,3,4])\n'
  'stream=accumulate(source)\n'
  'print(list(stream),list(stream),list(stream))\n'
  'raise error\n',
  '',
  'dd0a0a50b89182d30aba1d71afe7b48c655d0ff325f6a2232d877ec196169226'),
 ('continue_accumulate_callback_stop_keeps_old_total',
  'from itertools import accumulate\n'
  'error=StopIteration("fold")\n'
  'def fold(a,b):\n'
  ' if b==2:raise error\n'
  ' return a+b\n'
  'stream=accumulate([1,2,3,4],fold)\n'
  'print(next(stream),next(stream,99),list(stream))\n'
  'raise error\n',
  '',
  'b1feeeae9d3e16a7e3ea06b0f4cda878c3016b82b9adfeb612d044121848bc72'),
 ('continue_filter_next_default_keeps_callback_frame',
  'error=StopIteration("saved")\n'
  'def word(value):\n'
  ' if value==2:raise error\n'
  ' return value\n'
  'stream=filter(word,[2,3])\n'
  'print(next(stream,99),next(stream))\n'
  'raise error\n',
  '',
  'b3dd118a064e390c2313b0d3d1cd42986691d53b08be1f412fafb9043cbcf945'),
 ('continue_next_as_direct_callback_has_no_python_frame',
  'print(sum(next(value) for value in map(iter,[[]])))\n',
  '',
  '56f647fd24bf5e5d4c1604c87a683d961a0e2769d28090427cc8d4da17562cb3'),
 ('continue_next_as_lambda_callback_has_real_frame',
  'print(sum((lambda value:next(value))(value)for value in map(iter,[[]])))\n',
  '',
  'e90beb5c30a6f70f4e05d10449ec2a8a7d9ba1bbf2ef43e3b8639032a940956b'),
 ('frames_direct_builtin_next_callback',
  'print(next(map(next,[iter(())])))\n',
  '',
  '29617e8725a2c359bcee1317a2dfecbdc5433d64aac07c6efa324fb1808bb498'),
 ('frames_direct_builtin_next_generator_cause',
  'print(sum(next(map(next,[iter(())]))for unused in range(1)))\n',
  '',
  '24628cbb32d848d7fa5dd81d2ec394604c0aa3551e56c9381aceb1a95d5a7b78'),
 ('frames_python_lambda_next_generator_cause',
  'print(sum(next(map(lambda it:next(it),[iter(())]))for unused in '
  'range(1)))\n',
  '',
  'aad0ac022779c1ccbd03f9e90c88a195701df6dcf2dd2808926fe0f342afc7d4'),
 ('frames_source_constructor_retained_stop',
  'error=StopIteration("ctor")\n'
  'class Item:\n'
  ' def __init__(self,value):raise error\n'
  'print(list(map(Item,[1])))\n'
  'raise error\n',
  '',
  '1e18f20647ccc1cc9bac5f9b9f355dabaec011d1ecc6e3f4b0139a50e9287f2d'),
 ('frames_direct_builtin_filter_next_callback',
  'print(next(filter(next,[iter(())])))\n',
  '',
  '8fc272450df5c105e296ba63eb898fc92256eee4039f7fee8b8a7fdc6df0b65f'),
 ('frames_recursive_callback_frames_retained',
  'error=StopIteration("recursive")\n'
  'def fail(depth):\n'
  ' if depth:return fail(depth-1)\n'
  ' raise error\n'
  'print(list(map(lambda value:fail(value),[2])))\n'
  'raise error\n',
  '',
  '24b87397bdcff3f441e40a5ef5ed91a626ad07a8c19e87fd8b7ecbf387424faa'),
 ('frames_same_line_distinct_lambda_frames',
  'print(sum((lambda it:(lambda:next(it))())(iter(()))for unused in '
  'range(1)))\n',
  '',
  'c32675513b5a4a0c23a8b7eb48105e89b8c2489cff26c35353025158fc3737bb')]
class IteratorStopPolicy(unittest.TestCase):
    exercise=raise_tests.NativeRaiseExecutionTests.exercise

def _test(source,stdin,digest):
    def method(self):
        self.assertEqual(hashlib.sha256(source.encode()).hexdigest(),digest)
        self.exercise(source,stdin)
    return method
GUARDED = {
    'frames_direct_builtin_filter_next_callback': 'IteratorType',
}
class IteratorStopPrerequisiteBoundaries(unittest.TestCase):
    def test_original_sources_name_independent_missing_protocols(self):
        from py2fastrust import transpile,TranspileOptions
        for name,source,stdin,digest in CASES:
            if name not in GUARDED:continue
            self.assertEqual(hashlib.sha256(source.encode()).hexdigest(),digest)
            for mode in ('i64','i128','bigint'):
                with self.subTest(name=name,integer=mode):
                    result=transpile(source,TranspileOptions(integer=mode,license='none'))
                    self.assertFalse(result.success)
                    self.assertTrue(any(d.code=='E006'and d.line>0 and GUARDED[name]in d.message for d in result.diagnostics),result.diagnostics)
for name,source,stdin,digest in CASES:
    if name not in GUARDED:setattr(IteratorStopPolicy,'test_'+name,_test(source,stdin,digest))
