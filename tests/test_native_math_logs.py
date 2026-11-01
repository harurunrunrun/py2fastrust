"""Real logarithms, arbitrary integer scaling and Python domain errors."""
import ast
import shutil
import unittest
from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import build_program
from tests import test_native_frame_splits as text_helpers


class MathLogCapabilityTests(unittest.TestCase):
    def test_original_ast_and_scope_nodes_are_retained(self):
        from py2fastrust.native_linked_frames import generate_linked
        source="import math\nclass Box:\n def run(self,value,base):return math.log(value,base)\nprint(Box().run(8,2))\n"
        program=build_program(source,'main.py');unit=program.main
        before=ast.dump(unit.tree,include_attributes=True);nodes=tuple(ast.walk(unit.tree))
        self.assertIsNotNone(generate_linked(program,'i64'))
        self.assertEqual(ast.dump(unit.tree,include_attributes=True),before)
        self.assertEqual(tuple(ast.walk(unit.tree)),nodes)

    def test_static_numeric_paths_are_retained(self):
        from py2fastrust.native_frame_selection import select_frames
        for integer in ('i64','i128','bigint'):
            source="import math\nprint(math.gcd(24,18),math.floor(7))\n"
            self.assertFalse(select_frames(build_program(source,'main.py').main,integer=integer).required)
        source="import math\nprint(math.log2(8))\n"
        for integer in ('i64','i128'):
            self.assertFalse(select_frames(build_program(source,'main.py').main,integer=integer).required)

    def test_custom_float_protocol_is_explicit(self):
        source="import math\nclass Number:\n def __float__(self):return 2.0\nprint(math.log2(Number()))\n"
        for integer in ('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=integer))
            self.assertFalse(result.success)
            self.assertEqual(result.diagnostics[0].code,'E006')
            self.assertGreater(result.diagnostics[0].line,0)
            self.assertIn('__float__',result.diagnostics[0].message)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class MathLogExecutionTests(unittest.TestCase):
    exercise=text_helpers.SplitExecutionTests.exercise

    def test_ordinary_logs(self):
        self.exercise('import math\nprint(math.log(1),math.log(2),math.log2(8),math.log10(1000),math.log(8,2))\n')

    def test_framed_integer_logs(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  for value in [True,1,2,3,7,8,9,10,1024,(1<<53)-1,1<<53,(1<<53)+1,(1<<63)-1]:print(math.log(value),math.log2(value),math.log10(value))\nBox().run()\n')

    def test_framed_float_logs(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  for value in [1.0,2.0,0.5,0.1,5e-324,1e-300,1e300,1.7976931348623157e308,1e999,1e999-1e999]:print(math.log(value),math.log2(value),math.log10(value))\nBox().run()\n')

    def test_log_bases(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  for value in [1,2,10,27]:\n   for base in [2,3,10,0.5,1e999]:print(math.log(value,base))\nBox().run()\n')

    def test_finite_callables(self):
        self.exercise('import math\nclass Box:\n def call(self,function,value):return function(value)\nb=Box()\nprint(b.call(math.log,2))\nprint(b.call(math.log2,8))\nprint(b.call(math.log10,1000))\n')

    def test_local_alias(self):
        self.exercise('class Box:\n def run(self,value):\n  from math import log2 as binary_log\n  return binary_log(value)\nprint(Box().run(8))\n')

    def test_huge_positive_integer(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  value=(1<<2000)+1\n  print(math.log(value),math.log2(value),math.log10(value))\nBox().run()\n',expected_by_integer={'i64': ('0.0 0.0 0.0\n', '', 0), 'i128': ('0.0 0.0 0.0\n', '', 0)})

    def test_max_finite_rounding_boundary(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  value=(1<<1024)-(1<<971)+1\n  print(math.log(value),math.log2(value),math.log10(value))\nBox().run()\n',expected_by_integer={'i64': ('0.0 0.0 0.0\n', '', 0), 'i128': ('0.0 0.0 0.0\n', '', 0)})

    def test_overflow_frexp_rounding_boundary(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  value=(1<<1024)-(1<<970)+1\n  print(math.log(value),math.log2(value),math.log10(value))\nBox().run()\n',expected_by_integer={'i64': ('0.0 0.0 0.0\n', '', 0), 'i128': ('0.0 0.0 0.0\n', '', 0)})

    def test_operand_capture_order(self):
        self.exercise('import math\ndef mark(label,value):\n print(label)\n return value\nprint(math.log(mark("value",8),mark("base",2)))\n')

    def test_domain_before_base_conversion(self):
        self.exercise('import math\ndef mark(label,value):\n print(label)\n return value\nprint(math.log(mark("value",-1),mark("base","bad")))\n')

    def test_user_log_method(self):
        self.exercise('class Box:\n def log(self,value):return value+1\n def log2(self,value):return value+2\n def log10(self,value):return value+3\nb=Box()\nprint(b.log(2),b.log2(2),b.log10(2))\n')

    def test_log_zero_int(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log(0))\nBox().run()\n')

    def test_log_negative_int(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log(-1))\nBox().run()\n')

    def test_log_false(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log(False))\nBox().run()\n')

    def test_log_zero_float(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log(0.0))\nBox().run()\n')

    def test_log_negative_zero(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log(-0.0))\nBox().run()\n')

    def test_log_negative_float(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log(-1.5))\nBox().run()\n')

    def test_log_none(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log(None))\nBox().run()\n')

    def test_log_text(self):
        self.exercise("import math\nclass Box:\n def run(self):\n  print(math.log('2'))\nBox().run()\n")

    def test_log_empty(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log())\nBox().run()\n')

    def test_log_extra(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log(1,2,3))\nBox().run()\n')

    def test_log_keyword(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log(x=2))\nBox().run()\n')

    def test_log2_zero_int(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log2(0))\nBox().run()\n')

    def test_log2_negative_int(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log2(-1))\nBox().run()\n')

    def test_log2_false(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log2(False))\nBox().run()\n')

    def test_log2_zero_float(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log2(0.0))\nBox().run()\n')

    def test_log2_negative_zero(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log2(-0.0))\nBox().run()\n')

    def test_log2_negative_float(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log2(-1.5))\nBox().run()\n')

    def test_log2_none(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log2(None))\nBox().run()\n')

    def test_log2_text(self):
        self.exercise("import math\nclass Box:\n def run(self):\n  print(math.log2('2'))\nBox().run()\n")

    def test_log2_empty(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log2())\nBox().run()\n')

    def test_log2_extra(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log2(1,2,3))\nBox().run()\n')

    def test_log2_keyword(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log2(x=2))\nBox().run()\n')

    def test_log10_zero_int(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log10(0))\nBox().run()\n')

    def test_log10_negative_int(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log10(-1))\nBox().run()\n')

    def test_log10_false(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log10(False))\nBox().run()\n')

    def test_log10_zero_float(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log10(0.0))\nBox().run()\n')

    def test_log10_negative_zero(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log10(-0.0))\nBox().run()\n')

    def test_log10_negative_float(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log10(-1.5))\nBox().run()\n')

    def test_log10_none(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log10(None))\nBox().run()\n')

    def test_log10_text(self):
        self.exercise("import math\nclass Box:\n def run(self):\n  print(math.log10('2'))\nBox().run()\n")

    def test_log10_empty(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log10())\nBox().run()\n')

    def test_log10_extra(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log10(1,2,3))\nBox().run()\n')

    def test_log10_keyword(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log10(x=2))\nBox().run()\n')

    def test_log_one_base(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log(2,1))\nBox().run()\n')

    def test_log_float_one_base(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log(2,1.0))\nBox().run()\n')

    def test_log_zero_base(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log(2,0))\nBox().run()\n')

    def test_log_negative_base(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log(2,-1))\nBox().run()\n')

    def test_log_negative_float_base(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log(2,-1.0))\nBox().run()\n')

    def test_log_none_base(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log(2,None))\nBox().run()\n')

    def test_log_nan_one_base(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.log(1e999-1e999,1))\nBox().run()\n')

    def test_random_binary64_logs(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  for value in [1.0517003679231416e-78, 4.108162418894793e-175, 1.5980726229611725e-300, 2.252899525136347e+89, 2.5403285071504204e+37, 9.886533447209438e+205, 9.672464755514315e-214, 1.2536321343648322e+71, 6.787161351088125e-109, 2.324881872590944e+227, 8.869165305761954e+88, 1.5892258171523104e-178, 141181.01210310796, 2.5278236248032547e-178, 6.703434916043447e+272, 1.0492520439147625e+104, 1.784059694160217e-54, 3.405197632135218e+301, 1.3667552938574038e+113, 1.0620322918639214e-91, 1.2920303951646206e-45, 2.462742990934097e-160, 51815897963.65557, 9.083208143177705e-240, 2.8004061862770803e+189, 4.3522928663983556e-154, 4.153962774715088e-79, 5.300253215558968e+305, 1.0202538225313342e+53, 0.00011642085363829553, 8.287532299601056e+77, 7.864378934962338e+247, 9.458141641449492e-44, 1.0372327319668765e+21, 5.011486603796395e+57, 1.6458160435712934e+19, 4.0980032598571816e-182, 1.1164992957849922e+219, 1.8994629520211375e+56, 1.1583499248436818e+288, 2.7591197465146377e+284, 4.624568357965466e+91, 6.782957186696964e+97, 4.174117794121373e-116, 5.88722946431115e-264, 1.008861373609969e+228, 1.9260575118949987e+120, 1.9648461393315827e-267, 1.021561722514812e+167, 2.0065270244720534e-76, 6.006606002525807e+115, 9.666452566633202e-265, 3.5842995343655667e-141, 5.035448212835318e+90, 1.0406713738258615e-250, 2.8711084400168258e-279, 1.6310506984827638e+16, 2.7478513975224165e-294, 1.2065718201689226e+57, 1.5108696412998674e-194, 2.280038241255224e+247, 1.5862143860253563e+37, 1.3268761587824504e+298, 0.26010092917970745, 1.4698499681480241e-83, 4.422083583407782e+304, 1.18239472463309e+183, 7.87478344854935e-193, 7.876346708139497e+176, 2.401430982217037e-46, 1.8482848030418217e-236, 16013844553.657595, 1.4786730966258555e-85, 2.733226983926974e-164, 1.3886851066972753e+47, 1.9830020874393515e-50, 3.1181246771751536e-183, 4.036968647671714e+196, 2.695952674183861e-263, 6.262730950503594e-201, 1.3617266870316575e+121, 5.3888954627467064e+222, 7.684278243971003e-234, 1.5673222716165208e+209, 1.5445867191758673e-36, 1.407129456586951e-211, 5.887644505555056e-45, 1.105224745800056e-152, 3.230712617898171e-222, 1.4759514527058728e+210, 2.565307667992685e+300, 2.7413789672723444e-135, 43.054894917927555, 29360.764233023085, 7.217132383349888e+83, 4.307428637794609e+57, 5.175977250928331e+238, 3.750169380881441e+244, 8.736342473875869e+271, 9.52713171207551e-57, 1.71777875394169e+84, 3.92775020968519e-191, 2.693101356979262e-61, 1.79545567559317e+289, 7.852312055703699e-223, 1.0191762254352798e-203, 1.5093641527558266, 6.954471315631184e-31, 2.108818521916061e+215, 2.9389314891762315e-118, 4.840829445580847e+225, 2.2712346408496905e-61, 2.23560365779393e-154, 6.497552580512778e-122, 0.0008671403803814291, 2.5402668594623187e-281, 1.3183625827376315e-288, 1.1585774292553341e+304, 2.707800288975456e-273, 2.7993492438129195e-128]:print(math.log(value),math.log2(value),math.log10(value))\nBox().run()\n')

    def test_random_scaled_bigints(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  for mantissa,shift in [(7901319097231866, 1354), (6404346089378284, 1615), (7514661120177224, 860), (7617944235023297, 463), (5644081739532107, 331), (6480245544362214, 460), (7410887976076296, 808), (7171589543427259, 2168), (7145253200685697, 1479), (4775083365931624, 2148), (6810328008547658, 242), (8200913018220983, 836), (8527343415404560, 1137), (4795716796315428, 245), (6398330714031554, 1177), (6430682635745836, 566), (6620079752065078, 1665), (4783475729561983, 1301), (8802585772762327, 912), (6832219059846639, 474), (6640882027407302, 2003), (7189047241328299, 2041), (5711750022369279, 1303), (8036046466676949, 1786), (6520183625770331, 685), (5180865753366955, 1881), (8523546427635775, 774), (7397441727511252, 449), (6923485362149839, 740), (7950988592676284, 1445), (5264121246303067, 1756), (8340475601979966, 662), (5964462002164200, 373), (4660768045562690, 1196), (5118273308693435, 630), (5196614559187541, 1006), (5222613768540313, 324), (6745534292789397, 1910), (4765461648421472, 2008), (7397911584039626, 1634), (5290770062550849, 1614), (6006746364688701, 1772), (7154304698221502, 974), (7563637397948562, 1174), (5057447948671796, 906), (8284507163533332, 1920), (8692499675017736, 1239), (7233313131067651, 632), (4947755028586864, 1815), (7870772009626610, 917), (8304803815704192, 373), (7743619466395777, 613), (8674719570725396, 1688), (7292667976792712, 899), (4635823454937330, 1285), (7949995611502844, 2148), (5964902066581052, 436), (8525689418333343, 1574), (5292810844229823, 153), (7476284160472203, 632), (6065578792442774, 1349), (8198540076837218, 1611), (8631010010756146, 1760), (4571913432669069, 670), (6968805532012547, 1117), (5039812111752048, 2195), (7454871957205955, 1572), (7834379550589241, 1118), (6175962767833038, 264), (5813471986123459, 210), (6291847904415903, 1747), (5637675431410746, 206), (7193199966076374, 943), (4763489187650970, 957), (6288531369701336, 684), (4639583400319731, 1794), (4543595185385015, 1569), (5288064650416358, 1824), (4519291734874664, 1185), (4758695586058136, 384)]:\n   value=(mantissa<<shift)+1\n   print(math.log(value),math.log2(value),math.log10(value))\nBox().run()\n',expected_by_integer={'i64': ('0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n', '', 0), 'i128': ('0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n0.0 0.0 0.0\n', '', 0)})

    def test_mixed_integer_float_domains(self):
        self.exercise('import math\nclass Box:\n def run(self,value):return math.log2(value)\nb=Box()\nprint(b.run(2))\nprint(b.run(2.0))\nprint(b.run(0))\n')

    def test_mixed_float_integer_domains(self):
        self.exercise('import math\nclass Box:\n def run(self,value):return math.log2(value)\nb=Box()\nprint(b.run(2))\nprint(b.run(2.0))\nprint(b.run(0.0))\n')

    def test_negative_huge_integer(self):
        self.exercise('import math\nclass Box:\n def run(self):return math.log2(-(1<<2000)-1)\nprint(Box().run())\n')

    def test_captured_member_rebinding(self):
        self.exercise('import math\nold=math.log2\nmath.log2=lambda value:7\nprint(old(8),math.log2(8))\n')

    def test_nan_base(self):
        self.exercise('import math\nclass Box:\n def run(self):return math.log(2,1e999-1e999)\nprint(Box().run())\n')

    def test_negative_zero_base(self):
        self.exercise('import math\nclass Box:\n def run(self):return math.log(2,-0.0)\nprint(Box().run())\n')

    def test_false_base(self):
        self.exercise('import math\nclass Box:\n def run(self):return math.log(2,False)\nprint(Box().run())\n')
