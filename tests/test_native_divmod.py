"""Canonical divmod preserves quotient rules, captured calls and error frames."""
import unittest
import subprocess
import test_native_class_iterators as execution
import test_native_union_ordering as scalar_execution
from py2fastrust import transpile, TranspileOptions

CASES = {'booleans': 'print(divmod(True,True),divmod(False,True),divmod(7,True),divmod(True,3))\n',
 'builtins_alias': 'from builtins import divmod as quotient_remainder\n'
                   'print(quotient_remainder(17,-5))\n',
 'bytes_type': 'print(divmod(17,b"3"))\n',
 'callee_before_arguments': 'def replacement(a,b):return a+b\n'
                            'def change():\n'
                            ' global divmod\n'
                            ' divmod=replacement\n'
                            ' print("change")\n'
                            ' return 7\n'
                            'print(divmod(19,change()),divmod(19,7))\n',
 'captured_argument': 'def work(operation,a,b):return operation(a,b)\nprint(work(divmod,-19,7))\n',
 'class_field': 'class Box:\n'
                ' def __init__(self):self.operation=divmod\n'
                ' def split(self,a,b):return self.operation(a,b)\n'
                'box=Box()\n'
                'print(box.split(-29,6))\n',
 'empty': 'divmod()\n',
 'error_frame': 'def split(a,b):return divmod(a,b)\nprint(split(7,0))\n',
 'excess': 'def value(n):print(n);return n\nprint(divmod(value(1),value(2),value(3)))\n',
 'excess_keyword': 'def value(n):print(n);return n\n'
                   'print(divmod(value(1),value(2),value(3),bad=value(4)))\n',
 'float_pairs': 'for a in [-7.5,-0.0,0.0,7.5]:\n for b in [-2.0,2.0]:\n  print(divmod(a,b))\n',
 'float_zero': 'print(divmod(1.0,-0.0))\n',
 'keyword': 'def value(n):print(n);return n\nprint(divmod(value(1),y=value(2)))\n',
 'list_type': 'print(divmod([17],3))\n',
 'missing': 'def value():print("argument");return 3\nprint(divmod(value()))\n',
 'mixed_float': 'print(divmod(17,2.5),divmod(-7.5,2),divmod(True,0.5))\n',
 'none_type': 'print(divmod(None,3))\n',
 'saved_builtin': 'original=divmod\ndef divmod(a,b):return a+b\nprint(original(17,5),divmod(17,5))\n',
 'seeded_integers': 'rows=[(422993094198896, -92592298), (923911713524020, 95445054), '
                    '(-508012336259542, 98772793), (-243200571355271, 10367366), (-810034313036713, '
                    '-84822021), (-135113029652845, -59287634), (-985206499866172, -33787657), '
                    '(930172568163848, -98412554), (885593329143243, -3008328), (817836210025484, '
                    '90868111), (974885088925655, 53042394), (-414159791086558, 1585124), '
                    '(-80084585787512, -37613062), (-452345674959634, -7579735), (468461493250700, '
                    '4232416), (436404247614898, 92416042), (829916502423837, -47369798), '
                    '(-328155385303603, -42709216), (255176692359447, 67842633), (-863596597116221, '
                    '-69973241), (763359457717021, -61299750), (944877515257730, 34423170), '
                    '(-183750660639550, -28560556), (731861693396728, 47086145), (216107867333065, '
                    '71440556), (-49042976746611, 50249211), (460753423449578, 7803146), '
                    '(394729915789807, -47989728), (764253355725716, -33665756), (-512364417395181, '
                    '-22372103), (454206525093270, 22718199), (77249081264642, -32675386), '
                    '(-655456005431317, 66073218), (384013451223950, 31325655), (-113471124985736, '
                    '1746723), (926066705120980, -2489310), (354071613759218, -53758993), '
                    '(881156725701237, 95554843), (-413397826227492, 2178198), (-461798813378440, '
                    '-24328200), (364562595089081, 22392940), (876064283805164, -66644163), '
                    '(-578566643986637, -85753257), (-11038008239199, 95601321), (264228382909097, '
                    '-98350403), (753824298535240, -13590917), (-635037553022892, -80634053), '
                    '(-254410013387639, -16357130), (818055643597947, -9823153), (684919931272184, '
                    '92302104), (-867652256933780, 50714147), (-381831259357379, 19142994), '
                    '(-7437496706057, -12200457), (884515723651149, 69050468), (688977885641039, '
                    '-85138428), (-919480626500817, 62002777), (-921271712018706, 88597965), '
                    '(261806304253596, 14393076), (-393596672975666, 45184655), (458478713542150, '
                    '5150591), (685915646398282, 96592374), (139224038359733, 81990538), '
                    '(204828244914185, -54832730), (303459035943798, -49791502), (543352599687727, '
                    '69459297), (832110508273282, -17431958), (277777114038161, 89480295), '
                    '(-975119718919206, -65338592), (-334450995297965, -85120099), (538921699816410, '
                    '58836933), (-756967927075346, -67899372), (-19977453759549, -46805434), '
                    '(962450226096027, -73969005), (-156300145670106, 97011237), (-571628250945961, '
                    '20745168), (-388143062714016, -13273299), (-658773482239070, -64900967), '
                    '(992959539316196, -66905799), (-57064028366753, -59497570), (-587701847927161, '
                    '90181959), (588319694908117, -81786984), (-127682696027293, -49489356), '
                    '(-292168835889484, 82837267), (-883398240977090, -34015803), (-609526074758779, '
                    '29921022), (229271970605148, 99343315), (825240460853564, 30079257), '
                    '(-746930355227049, 46914054), (-490406398872631, 1209009), (-408049040518227, '
                    '53244000), (-399758375436452, -34573048), (-384263653600545, -76183862), '
                    '(896561940692328, -39499320), (544871955865919, 50535472), (-105500045258825, '
                    '44775360), (-925912977216344, -3470065), (-37279435563394, -52800210), '
                    '(-143963596328553, 91303109), (339355624221316, -21309137), (-127672700869691, '
                    '8822408), (-699677196802181, -58798568), (765777289179133, 74922321), '
                    '(401455596510167, -57060785), (-465807975015238, -74411830), (467607953404781, '
                    '22703033), (401337566235385, 19078638), (-617698274520359, -86778745), '
                    '(804117250700392, 71964392), (164305202310202, 1471519), (-438765699372090, '
                    '30001256), (-234255731113115, -28709114), (-563708461330871, -81153251), '
                    '(-452586381648717, 46117877), (869846603788590, -19349418), (-664242744479267, '
                    '-72537491), (878200664827488, -3177596), (-576429613129, 14435681), '
                    '(-868985191201832, 69067033), (595416566211277, 46562500), (-982108055710361, '
                    '-50234089), (-99987212318110, 98689870), (532649565415793, 11003721), '
                    '(-848133684821004, 47892738), (854833597946227, 92613219), (167481985806878, '
                    '2414602), (-259237073055151, 93139158), (695389847210348, 41574887), '
                    '(394132387649845, -23239624), (820008273624987, -10944236), (-599815212733684, '
                    '-95073411), (-858294965851243, 51351228), (580692640882844, -27745995), '
                    '(512414715356193, 39597287), (-173524259789199, -32577128), (-21804244756151, '
                    '67039609), (495028480487626, 27485573), (532731334750475, 49915406), '
                    '(376066469285386, -74591852), (215237450525886, -85594533), (881604763872448, '
                    '92016910), (642046303037441, 26244919), (237648822216890, -89921856), '
                    '(47808894442563, 42759902), (208794243703071, 83457016), (-368661305796133, '
                    '23116219), (-186531777349154, -28916264), (721502584581793, 24511072), '
                    '(144443054857470, -37915491), (-519757046889661, 83459947), (-59792668196040, '
                    '-80764422), (884212423488819, -11430919), (-738496489975829, -55671593), '
                    '(81934408287001, 40789816), (906991383970971, 74487017), (-192334649449932, '
                    '-3555647), (-357610940930658, -49517195), (828614148796955, -81536040), '
                    '(-331586311906591, 96660234), (-279381984595780, 17711670), (-26755219018289, '
                    '-64676476), (-686746234190049, -65453218), (-824046195506840, 97808013), '
                    '(107308769458736, -51229408), (647839544946161, -6808308), (-592164321048788, '
                    '29337954), (-451584253788762, 82118940), (90903160751785, -27528021), '
                    '(216433457795510, 14556330), (-994942698799768, 58113615), (193356921406307, '
                    '-47390307), (718131618545017, -59432654), (-299062793646344, -44967673), '
                    '(847300525029517, 51123730), (-347870089617707, 83465264), (-143114433510358, '
                    '56297678), (-392816048955507, -91153555), (-130834579600963, 97191804), '
                    '(-253407974266913, 32418153), (-815872063698050, -38563523), (980262253105697, '
                    '76327170)]\n'
                    'for a,b in rows:print(divmod(a,b))\n',
 'signed': 'for a in [-19,-1,0,1,19]:\n for b in [-7,-1,1,7]:\n  print(a,b,divmod(a,b))\n',
 'text_type': 'print(divmod("17",3))\n',
 'tuple_result_identity': 'answer=divmod(19,7)\n'
                          'alias=answer\n'
                          'print(answer,answer is alias,answer[0],answer[1])\n',
 'tuple_unpack_and_store': 'def split(a,b):return divmod(a,b)\n'
                           'q,r=split(100,9)\n'
                           'rows=[split(17,5),split(-17,5)]\n'
                           'print(q,r,rows)\n',
 'union_error': 'def split(a):return divmod(a,3)\nprint(split(17))\nprint(split(None))\n',
 'union_numeric': 'def split(a,b):return divmod(a,b)\nprint(split(17,5),split(True,2),split(-7,True))\n',
 'zero': 'print("before")\nprint(divmod(9,0))\n',
 'zero_bool': 'print(divmod(9,False))\n'}

class NativeDivmodTests(unittest.TestCase):
    cases = CASES
    check = execution.IteratorExecutionTests.check

    def test_integer_results_and_captured_calls(self):
        for name in ('signed','booleans','captured_argument','saved_builtin','builtins_alias',
                     'callee_before_arguments','class_field','tuple_unpack_and_store','union_numeric','seeded_integers'):
            with self.subTest(name=name):self.check(name)

    def test_binding_and_operand_errors_follow_argument_evaluation(self):
        for name in ('union_error','zero','zero_bool','error_frame','none_type','text_type',
                     'bytes_type','list_type','missing','empty','excess','keyword','excess_keyword'):
            with self.subTest(name=name):self.check(name)

    def test_float_pairs_in_every_integer_mode(self):
        for name in ('float_pairs','float_zero'):
            with self.subTest(name=name):self.check(name)

    def test_unimplemented_identity_and_bigint_float_protocols_are_positioned(self):
        for name,modes in (('tuple_result_identity',('i64','i128','bigint')),('mixed_float',('bigint',))):
            for mode in modes:
                with self.subTest(name=name,mode=mode):
                    result=transpile(CASES[name],TranspileOptions(integer=mode,filename='divmod_protocol.py'))
                    self.assertFalse(result.success)
                    self.assertEqual(result.diagnostics[0].code,'E006')
                    self.assertGreater(result.diagnostics[0].line,0)
                    self.assertEqual(result.diagnostics[0].filename,'divmod_protocol.py')
                    self.assertIn("comparison 'is'"if name=='tuple_result_identity'else'BigInt',result.diagnostics[0].message)

class NativeMixedDivmodTests(unittest.TestCase):
    setUpClass=classmethod(scalar_execution.NativeUnionOrderingTests.setUpClass.__func__)
    tearDownClass=classmethod(scalar_execution.NativeUnionOrderingTests.tearDownClass.__func__)
    compile=scalar_execution.NativeUnionOrderingTests.compile
    exercise=scalar_execution.NativeUnionOrderingTests.exercise

    def test_selected_width_normalizes_each_pair_component(self):
        rows=[((1<<190)+7,(1<<64)+3),(-(1<<63),-1),(-(1<<127),-1),(-((1<<180)+9),-17)]
        source='rows='+repr(rows)+'\nfor a,b in rows:print(divmod(a,b))\n'
        def normalized(value,bits):return (value+(1<<(bits-1)))%(1<<bits)-(1<<(bits-1))if bits else value
        for mode,bits in (('i64',64),('i128',128),('bigint',0)):
            pairs=[divmod(normalized(a,bits),normalized(b,bits))for a,b in rows]
            expected=''.join(str(tuple(normalized(x,bits)for x in pair))+'\n'for pair in pairs)
            for release in (False,True):
                with self.subTest(mode=mode,release=release):
                    _,binary,_=self.compile(source,mode,release)
                    actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10,env={'PATH':'/unavailable'})
                    self.assertEqual((actual.returncode,actual.stdout,actual.stderr),(0,expected,''))

    def test_mixed_float_fixed_width_modes(self):
        self.exercise(CASES['mixed_float'],('',),modes=('i64','i128'))

if __name__=='__main__':unittest.main()
