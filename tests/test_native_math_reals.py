"""Canonical real math members, exact integer conversion and Python errors."""
import ast
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import build_program
from tests import test_native_frame_splits as text_helpers


class MathRealCapabilityTests(unittest.TestCase):
    def test_original_ast_and_scope_nodes_are_retained(self):
        from py2fastrust.native_linked_frames import generate_linked
        source="import math\nclass Box:\n def run(self,value):return math.sqrt(value)\nprint(Box().run(9))\n"
        program=build_program(source,'main.py');unit=program.main
        before=ast.dump(unit.tree,include_attributes=True);nodes=tuple(ast.walk(unit.tree))
        self.assertIsNotNone(generate_linked(program,'i64'))
        self.assertEqual(ast.dump(unit.tree,include_attributes=True),before)
        self.assertEqual(tuple(ast.walk(unit.tree)),nodes)

    def test_existing_integer_math_and_fixed_float_paths_keep_static_selection(self):
        from py2fastrust.native_frame_selection import select_frames
        for integer in ('i64','i128','bigint'):
            for source in ["import math\nprint(math.gcd(24,18))\n",
                           "import math\nprint(math.floor(7))\n"]:
                self.assertFalse(select_frames(build_program(source,'main.py').main,integer=integer).required)
        source="import math\nprint(math.sqrt(9))\n"
        for integer in ('i64','i128'):
            self.assertFalse(select_frames(build_program(source,'main.py').main,integer=integer).required)

    def check_custom_protocol(self,name,protocol):
        result=2.0 if name=='sqrt'else 2
        source='import math\nclass Number:\n def '+protocol+'(self):return '+repr(result)+'\nprint(math.'+name+'(Number()))\n'
        for integer in ('i64','i128','bigint'):
            converted=transpile(source,TranspileOptions(integer=integer))
            self.assertFalse(converted.success)
            self.assertEqual(converted.diagnostics[0].code,'E006')
            self.assertGreater(converted.diagnostics[0].line,0)
            self.assertIn(protocol,converted.diagnostics[0].message)

    def test_custom_sqrt_protocol_is_explicit(self):self.check_custom_protocol('sqrt','__float__')
    def test_custom_floor_protocol_is_explicit(self):self.check_custom_protocol('floor','__floor__')
    def test_custom_ceil_protocol_is_explicit(self):self.check_custom_protocol('ceil','__ceil__')
    def test_custom_trunc_protocol_is_explicit(self):self.check_custom_protocol('trunc','__trunc__')


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class MathRealExecutionTests(unittest.TestCase):
    exercise=text_helpers.SplitExecutionTests.exercise

    def test_unpruned_integer_math_support_uses_reached_kernels(self):
        source="import math\ndef divisor(value):return math.gcd(value,6)\nprint(divisor(8))\n"
        with tempfile.TemporaryDirectory(prefix='pytors-math-unpruned-')as directory:
            root=Path(directory)
            for integer in ('i64','i128','bigint'):
                converted=transpile(source,TranspileOptions(integer=integer,optimize=False))
                self.assertTrue(converted.success,converted.diagnostics)
                rust=root/(integer+'.rs');rust.write_text(converted.rust_source)
                for optimized in (False,True):
                    binary=root/(integer+str(optimized))
                    built=subprocess.run(['rustc','--edition=2021','--crate-name','math_unpruned',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=180)
                    self.assertEqual(built.returncode,0,built.stderr)
                    actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=15)
                    self.assertEqual((actual.stdout,actual.stderr,actual.returncode),('2\n','',0))

    def test_ordinary_sqrt(self):
        self.exercise('import math\nprint(math.sqrt(2),math.sqrt(9),math.sqrt(True),math.sqrt(False))\n')

    def test_framed_sqrt(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  for value in [0,1,2,4,9,1024,(1<<53)-1,1<<53,(1<<53)+1,(1<<63)-1]:print(math.sqrt(value))\nBox().run()\n')

    def test_round_integers(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  for value in [False,True,0,1,-1,27,-27,(1<<63)-1,-(1<<63)]:print(math.floor(value),math.ceil(value),math.trunc(value))\nBox().run()\n')

    def test_round_floats(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  for value in [0.0,-0.0,1.0,-1.0,1.1,-1.1,1.999,-1.999,1e-300,-1e-300,5e-324,-5e-324]:print(math.floor(value),math.ceil(value),math.trunc(value))\nBox().run()\n')

    def test_ordinary_round(self):
        self.exercise('from math import floor,ceil,trunc\nprint(floor(1.9),ceil(-1.9),trunc(-1.9))\n')

    def test_signed_zero_sqrt(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.sqrt(-0.0),math.sqrt(0.0))\nBox().run()\n')

    def test_nan_sqrt(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.sqrt(1e999-1e999))\nBox().run()\n')

    def test_positive_infinity_sqrt(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.sqrt(1e999))\nBox().run()\n')

    def test_negative_infinity_sqrt(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.sqrt(-1e999))\nBox().run()\n')

    def test_negative_sqrt(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.sqrt(-1))\nBox().run()\n')

    def test_finite_callables(self):
        self.exercise('import math\nclass Box:\n def apply(self,function,value):return function(value)\nb=Box()\nprint(b.apply(math.sqrt,9))\nprint(b.apply(math.floor,-1.9))\nprint(b.apply(math.ceil,1.1))\nprint(b.apply(math.trunc,-1.9))\n')

    def test_local_import_alias(self):
        self.exercise('class Box:\n def run(self,value):\n  from math import sqrt as root\n  return root(value)\nprint(Box().run(2))\n')

    def test_captured_alias(self):
        self.exercise('import math as m\nroot=m.sqrt\nfloor=m.floor\nclass Box:\n def run(self):print(root(2),floor(-1.5))\nBox().run()\n')

    def test_argument_order(self):
        self.exercise('import math\ndef first():\n print("first")\n return 9\ndef other():\n print("other")\n return 2\nmath.sqrt(first(),ignored=other())\n')

    def test_huge_integer_round(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  value=(1<<200)+(1<<100)+1\n  print(math.floor(value),math.ceil(value),math.trunc(value))\nBox().run()\n',expected_by_integer={'i64': ('1 1 1\n', '', 0), 'i128': ('1267650600228229401496703205377 1267650600228229401496703205377 1267650600228229401496703205377\n', '', 0)})

    def test_huge_integer_sqrt(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.sqrt(1<<2000))\nBox().run()\n',expected_by_integer={'i64': ('0.0\n', '', 0), 'i128': ('0.0\n', '', 0)})

    def test_float_result_wrap(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.floor(1e100),math.ceil(-1e100),math.trunc(1e100))\nBox().run()\n',expected_by_integer={'i64': ('0 0 0\n', '', 0), 'i128': ('0 0 0\n', '', 0)})

    def test_user_method_names(self):
        self.exercise('class Box:\n def sqrt(self,value):return value+2\n def floor(self,value):return value+3\nb=Box()\nprint(b.sqrt(4),b.floor(8))\n')

    def test_sqrt_none(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.sqrt(None))\nBox().run()\n')

    def test_sqrt_text(self):
        self.exercise("import math\nclass Box:\n def run(self):\n  print(math.sqrt('1.5'))\nBox().run()\n")

    def test_sqrt_bytes(self):
        self.exercise("import math\nclass Box:\n def run(self):\n  print(math.sqrt(b'1.5'))\nBox().run()\n")

    def test_sqrt_list(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.sqrt([1]))\nBox().run()\n')

    def test_sqrt_empty(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.sqrt())\nBox().run()\n')

    def test_sqrt_extra(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.sqrt(1,2))\nBox().run()\n')

    def test_sqrt_keyword(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.sqrt(x=1))\nBox().run()\n')

    def test_floor_none(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.floor(None))\nBox().run()\n')

    def test_floor_text(self):
        self.exercise("import math\nclass Box:\n def run(self):\n  print(math.floor('1.5'))\nBox().run()\n")

    def test_floor_bytes(self):
        self.exercise("import math\nclass Box:\n def run(self):\n  print(math.floor(b'1.5'))\nBox().run()\n")

    def test_floor_list(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.floor([1]))\nBox().run()\n')

    def test_floor_empty(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.floor())\nBox().run()\n')

    def test_floor_extra(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.floor(1,2))\nBox().run()\n')

    def test_floor_keyword(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.floor(x=1))\nBox().run()\n')

    def test_floor_inf(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.floor(1e999))\nBox().run()\n')

    def test_floor_negative_inf(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.floor(-1e999))\nBox().run()\n')

    def test_floor_nan(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.floor(1e999-1e999))\nBox().run()\n')

    def test_ceil_none(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.ceil(None))\nBox().run()\n')

    def test_ceil_text(self):
        self.exercise("import math\nclass Box:\n def run(self):\n  print(math.ceil('1.5'))\nBox().run()\n")

    def test_ceil_bytes(self):
        self.exercise("import math\nclass Box:\n def run(self):\n  print(math.ceil(b'1.5'))\nBox().run()\n")

    def test_ceil_list(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.ceil([1]))\nBox().run()\n')

    def test_ceil_empty(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.ceil())\nBox().run()\n')

    def test_ceil_extra(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.ceil(1,2))\nBox().run()\n')

    def test_ceil_keyword(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.ceil(x=1))\nBox().run()\n')

    def test_ceil_inf(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.ceil(1e999))\nBox().run()\n')

    def test_ceil_negative_inf(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.ceil(-1e999))\nBox().run()\n')

    def test_ceil_nan(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.ceil(1e999-1e999))\nBox().run()\n')

    def test_trunc_none(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.trunc(None))\nBox().run()\n')

    def test_trunc_text(self):
        self.exercise("import math\nclass Box:\n def run(self):\n  print(math.trunc('1.5'))\nBox().run()\n")

    def test_trunc_bytes(self):
        self.exercise("import math\nclass Box:\n def run(self):\n  print(math.trunc(b'1.5'))\nBox().run()\n")

    def test_trunc_list(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.trunc([1]))\nBox().run()\n')

    def test_trunc_empty(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.trunc())\nBox().run()\n')

    def test_trunc_extra(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.trunc(1,2))\nBox().run()\n')

    def test_trunc_keyword(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.trunc(x=1))\nBox().run()\n')

    def test_trunc_inf(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.trunc(1e999))\nBox().run()\n')

    def test_trunc_negative_inf(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.trunc(-1e999))\nBox().run()\n')

    def test_trunc_nan(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  print(math.trunc(1e999-1e999))\nBox().run()\n')

    def test_random_binary64_rounding(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  for value in [0.0, -0.0, 5e-324, -5e-324, 1.7976931348623157e+308, -1.7976931348623157e+308, -2.944415043012378e+114, 4.453425330150812e-258, 1.3070174877765882e-294, -6.447378014418746e+107, 4.6115153212833074e-48, 2.0127198565948864e-43, -2.729640634240175e-79, 4.498462156404264e-148, -1.2633426906141469e+51, 6.621160863785768e-225, 5.517021899078096e-254, 7.240092934290292e-259, -7.397145343091727e-36, 1.3358493734207472e-226, 6.255550241293485e+108, 4.5944702461491825e-56, -1.1840469102847866e-90, 2.6049539360560254e-65, -2.193992956552661e-10, -4.358435503060484e-41, -1.6341097122087675e-268, 9.874209335892916e-251, 2.793434097866367e+209, -2.7450073841458585e-120, 5.8535777263669604e-176, 2.053377847547986e+39, 1.7769385528826033e+42, -8.328444602375975e+142, -7.496333698587712e+235, -4.88798754164058e+111, 3.9481778070772023e-271, -1.720804630750491e+118, -1.2495786384401158e-141, 1.2474879095795994e-107, -1.610095048059241e+38, -2.325560297217044e+98, -1.914402848258532e+305, -0.09019712737154671, 3.054288165680212e-249, -1.0551384863389198e+118, 8.097391838606549e-50, -2.5640141811370037e+40, 2.6448199396406635e-276, 6.662540623187414e+71, 1.4359744535260425e-30, 2.8600499351601664e+243, 3.3649828317834707e-304, -4.066192682326616e+79, -5.119276375373789e-29, -1.5565851488956682e-50, 1.070826040617365e+172, 1.0460632187406394e+61, -1.6089167685002238e+274, -6.071004204843998e-215, 4.2151547063428564e-238, 1.0825600703715748e+152, -2.1198416189868018e+142, 4.288226077882111e+225, 4.099976268779853e-33, 5.090862791067927e-305, 1.909147762116211e+36, 1.7842435011589424e-261, 5.635175556475313e+80, -1.6283243441387526e-23, -1.787821422581933e-232, 2.162568235562016e+279, -7.782297586702262e-269, 5.639155028287126e+135, -7.279030180411534e-265, -9.39000235706046e+247, -6.809819095745409e+190, 7.983350259371693e+157, -4.092316343269057e-286, 4.603702056908016e-201, -5.250310978788932e-244, 1.4653591377999597e-175, -595.5106224102336, -5.105249472552565e+140, 5.64735579726758e+101, 2.6273496839148517e-253, 1.7624997983923418e+109, 1.475572356221833e-80, 0.006423895249661323, 1.92794472276738e-128, 1.304648267803604e+94, -6.829377119324579e+239, -312.7134063016791, -8.914622659905977e-194, 4.1184313042739644e+198, 2.0036417497060835e+152, 1.776649756267296e+203, 5.2545380518047335e-76, 1.4253815307174668e-266, 2.3810172829096048e-240]:print(math.floor(value),math.ceil(value),math.trunc(value))\nBox().run()\n',expected_by_integer={'i64': ('0 0 0\n0 0 0\n0 1 0\n-1 0 0\n0 0 0\n0 0 0\n0 0 0\n0 1 0\n0 1 0\n0 0 0\n0 1 0\n0 1 0\n-1 0 0\n0 1 0\n0 0 0\n0 1 0\n0 1 0\n0 1 0\n-1 0 0\n0 1 0\n0 0 0\n0 1 0\n-1 0 0\n0 1 0\n-1 0 0\n-1 0 0\n-1 0 0\n0 1 0\n0 0 0\n-1 0 0\n0 1 0\n0 0 0\n0 0 0\n0 0 0\n0 0 0\n0 0 0\n0 1 0\n0 0 0\n-1 0 0\n0 1 0\n0 0 0\n0 0 0\n0 0 0\n-1 0 0\n0 1 0\n0 0 0\n0 1 0\n0 0 0\n0 1 0\n0 0 0\n0 1 0\n0 0 0\n0 1 0\n0 0 0\n-1 0 0\n-1 0 0\n0 0 0\n0 0 0\n0 0 0\n-1 0 0\n0 1 0\n0 0 0\n0 0 0\n0 0 0\n0 1 0\n0 1 0\n0 0 0\n0 1 0\n0 0 0\n-1 0 0\n-1 0 0\n0 0 0\n-1 0 0\n0 0 0\n-1 0 0\n0 0 0\n0 0 0\n0 0 0\n-1 0 0\n0 1 0\n-1 0 0\n0 1 0\n-596 -595 -595\n0 0 0\n0 0 0\n0 1 0\n0 0 0\n0 1 0\n0 1 0\n0 1 0\n0 0 0\n0 0 0\n-313 -312 -312\n-1 0 0\n0 0 0\n0 0 0\n0 0 0\n0 1 0\n0 1 0\n0 1 0\n', '', 0), 'i128': ('0 0 0\n0 0 0\n0 1 0\n-1 0 0\n0 0 0\n0 0 0\n0 0 0\n0 1 0\n0 1 0\n0 0 0\n0 1 0\n0 1 0\n-1 0 0\n0 1 0\n35224541888300270631950887097429131264 35224541888300270631950887097429131264 35224541888300270631950887097429131264\n0 1 0\n0 1 0\n0 1 0\n-1 0 0\n0 1 0\n0 0 0\n0 1 0\n-1 0 0\n0 1 0\n-1 0 0\n-1 0 0\n-1 0 0\n0 1 0\n0 0 0\n-1 0 0\n0 1 0\n11683646022355176291579152914985254912 11683646022355176291579152914985254912 11683646022355176291579152914985254912\n-15967178537344282410763069475692478464 -15967178537344282410763069475692478464 -15967178537344282410763069475692478464\n0 0 0\n0 0 0\n0 0 0\n0 1 0\n0 0 0\n-1 0 0\n0 1 0\n-161009504805924103368591634374246531072 -161009504805924103368591634374246531072 -161009504805924103368591634374246531072\n0 0 0\n0 0 0\n-1 0 0\n0 1 0\n0 0 0\n0 1 0\n-118964292299652514143792021976136024064 -118964292299652514143792021976136024064 -118964292299652514143792021976136024064\n0 1 0\n0 0 0\n0 1 0\n0 0 0\n0 1 0\n0 0 0\n-1 0 0\n-1 0 0\n0 0 0\n0 0 0\n0 0 0\n-1 0 0\n0 1 0\n0 0 0\n0 0 0\n0 0 0\n0 1 0\n0 1 0\n1909147762116210901961902623559778304 1909147762116210901961902623559778304 1909147762116210901961902623559778304\n0 1 0\n0 0 0\n-1 0 0\n-1 0 0\n0 0 0\n-1 0 0\n0 0 0\n-1 0 0\n0 0 0\n0 0 0\n0 0 0\n-1 0 0\n0 1 0\n-1 0 0\n0 1 0\n-596 -595 -595\n0 0 0\n0 0 0\n0 1 0\n0 0 0\n0 1 0\n0 1 0\n0 1 0\n0 0 0\n0 0 0\n-313 -312 -312\n-1 0 0\n0 0 0\n0 0 0\n0 0 0\n0 1 0\n0 1 0\n0 1 0\n', '', 0)})

    def test_random_integer_sqrt(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  for value in [4382428564111758555, 5208378676991279040, 1884382938316311064, 8323306181678470835, 7428098376758135767, 2653973011786955884, 8121436637397692700, 8916908244999079884, 8794382223826297806, 8072862384343086520, 8723626564463000444, 1422590924598903476, 5318620909266788247, 3983788685540235069, 9091712192578278081, 5677797102972566741, 2236031823300069678, 500203759145725217, 4583104234498418514, 500637914216009176, 8864618106111530057, 4287573100417764016, 413779453414464751, 6076077411851440072, 2951976877250014934, 2063618588980043786, 8215087780561977038, 8823836966952813654, 7280713682717029250, 8389789905118086949, 4009701754104199624, 1222014013256689280, 7074540840916149623, 3300709976951285715, 5365758446943900564, 3530662899459816453, 8218336112172398424, 6981010935406449195, 8431732710110738525, 5536730295876871462, 5605476437450007540, 1355894213694492127, 3402407230222210972, 3278659931762909271, 6877381199705408984, 4825062408335343689, 1815969394612419054, 8894141378405039231, 5134914565419700212, 8443558026858289443, 5138981530266811175, 6872287241090514756, 8928555139782470837, 887243820356703025, 9031863757377085233, 1506624730445867312, 1729350952786791788, 5639924101647158237, 5245577661410432135, 2681697409330762547, 2840620743701282141, 4015708976298870300, 4822691466093498423, 8253636036418430924, 1456013232060287942, 2746212803009266497, 4495899627331952072, 5466122517293481888, 6307604395095116741, 4918699355115046540, 5887010079354158281, 1244805897583468027, 4686453108566104129, 7257227528800735623, 7594517604422875558, 3921859197153610141, 543797577585306686, 3576676474235625345, 2997753031512915867, 7883030351614152295, 586498217548592993, 6619832137735878152, 6675117434634024257, 2986641954221034493, 8257874005242793251, 6096891909006184657, 1854043683967343376, 995860336153911845, 5999321553308414117, 3033656714738682129, 8147164287508683530, 3019258497195794309, 4951852554435523256, 8568400407958471865, 5886279191899925941, 3348791642571065935, 6780840007056370378, 8034241820829274518, 546446211292476748, 7017545181799437264, 9209601951121047730, 5711049890645052322, 3282120536442032881, 2754099159552111434, 4196377048883671244, 5544090770674997272, 7019437702625788779, 7454576154857804539, 2498456306273333381, 4576328217069369020, 5176611977784216321, 6531552485227661981, 6239725699193241888, 4722522807794402618, 2048278305112581326, 2070896142332527208, 551491621846453493, 8482884851176684954, 4351533160501543338, 1266222997457448237]:print(math.sqrt(value))\nBox().run()\n')

    def test_max_float_integer_sqrt(self):
        self.exercise('import math\nclass Box:\n def run(self):return math.sqrt((1<<1024)-(1<<971))\nprint(Box().run())\n',expected_by_integer={'i64': ('0.0\n', '', 0), 'i128': ('0.0\n', '', 0)})

    def test_negative_huge_integer_sqrt(self):
        self.exercise('import math\nclass Box:\n def run(self):return math.sqrt(-(1<<2000))\nprint(Box().run())\n',expected_by_integer={'i64': ('0.0\n', '', 0), 'i128': ('0.0\n', '', 0)})

    def test_closed_callable_error(self):
        self.exercise('import math\nclass Box:\n def run(self):return math.sqrt(math.floor)\nprint(Box().run())\n')

    def test_closed_tuple_error(self):
        self.exercise('import math\nclass Box:\n def run(self):return math.trunc((1,2))\nprint(Box().run())\n')

    def test_closed_dict_error(self):
        self.exercise('import math\nclass Box:\n def run(self):return math.ceil({1:2})\nprint(Box().run())\n')

    def test_builtin_alias_rebinding(self):
        self.exercise('import math\nclass Box:\n def run(self):\n  function=math.sqrt\n  print(function(9))\n  function=math.floor\n  print(function(-1.5))\nBox().run()\n')

    def test_member_captured_old_member(self):
        self.exercise('import math\nold=math.sqrt\nmath.sqrt=lambda value:7\nprint(old(9),math.sqrt(9))\n')

    def test_member_late_module_read(self):
        self.exercise('import math\ndef run(value):return math.sqrt(value)\nmath.sqrt=lambda value:7\nprint(run(9))\n')

    def test_member_callee_before_argument_effect(self):
        self.exercise('import math\ndef change():\n math.sqrt=lambda value:7\n return 9\nprint(math.sqrt(change()))\nprint(math.sqrt(9))\n')

    def test_member_restore_captured_member(self):
        self.exercise('import math\nold=math.sqrt\nmath.sqrt=lambda value:7\nprint(math.sqrt(9))\nmath.sqrt=old\nprint(math.sqrt(9))\n')
