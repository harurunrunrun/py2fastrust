"""All native emitters consume one validated source representation."""
import ast
import builtins
from dataclasses import FrozenInstanceError, asdict
import json
from pathlib import Path
import shutil
import subprocess
import symtable
import sys
import tempfile
import typing
import unittest
from unittest.mock import patch

from py2fastrust import TranspileOptions, transpile
from py2fastrust.compiler import Compiler
from py2fastrust.diagnostics import CompilationError
from py2fastrust.frontend import build_program, parse_source
from py2fastrust.native import try_generate_native
from py2fastrust.native_bigint import try_generate_bigint
from py2fastrust.native_classes import try_generate_classes


SCALAR = "def twice(value):\n return value*2\nprint(twice(7))\n"
CLASSES = "class Box:\n def __init__(self,n):self.n=n\n def read(self):return self.n\nprint(Box(9).read())\n"


class SharedFrontendTests(unittest.TestCase):
    def test_public_source_map_annotations_resolve_independently_of_legacy_ir(self):
        from py2fastrust.api import TranspileResult
        from py2fastrust.source_locations import SourceLocation
        hints=typing.get_type_hints(TranspileResult)
        self.assertEqual(hints["source_map"],tuple[SourceLocation,...])
        from py2fastrust.ir import SourceLocation as legacy_location
        self.assertIs(legacy_location,SourceLocation)

    def test_public_frontend_never_constructs_vm_ir_or_runs_general_compilation(self):
        with patch.object(Compiler,"compile",side_effect=AssertionError("legacy compiler entered")), \
             patch("py2fastrust.ir.Instruction",side_effect=AssertionError("VM instruction created")), \
             patch("py2fastrust.ir_flow.analyze_program",side_effect=AssertionError("VM analysis entered")), \
             patch("py2fastrust.codegen.generate",side_effect=AssertionError("general backend entered")):
            for source in (SCALAR,CLASSES):
                for mode in ("i64","i128","bigint"):
                    for optimize in (False,True):
                        with self.subTest(source=source,mode=mode,optimize=optimize):
                            result=transpile(source,TranspileOptions(integer=mode,optimize=optimize))
                            self.assertTrue(result.success,result.diagnostics)
                            self.assertEqual(result.backend,"native")
                            self.assertTrue(result.source_map)

    def test_each_public_source_is_parsed_scoped_and_contextually_compiled_once(self):
        original_parse,original_scope,original_compile=ast.parse,symtable.symtable,builtins.compile
        for source in (SCALAR,CLASSES):
            for mode in ("i64","i128","bigint"):
                with self.subTest(source=source,mode=mode), \
                     patch("ast.parse",wraps=original_parse)as parse, \
                     patch("symtable.symtable",wraps=original_scope)as scope, \
                     patch("builtins.compile",wraps=original_compile)as validate:
                    result=transpile(source,TranspileOptions(integer=mode))
                    self.assertTrue(result.success,result.diagnostics)
                    self.assertEqual(parse.call_count,1,parse.call_args_list)
                    self.assertEqual(scope.call_count,1)
                    validations=[call for call in validate.call_args_list if isinstance(call.args[0],ast.AST)]
                    self.assertEqual(len(validations),1)
                    self.assertTrue(validations[0].kwargs["dont_inherit"])

    def test_supplied_unit_drives_all_entrypoints_without_reparsing(self):
        for source in (SCALAR,CLASSES):
            unit=build_program(source,"shared.py").main
            original=ast.dump(unit.tree,include_attributes=True)
            with patch("ast.parse",side_effect=AssertionError("reparsed source")), \
                 patch("symtable.symtable",side_effect=AssertionError("reparsed scope")):
                for mode in ("i64","i128","bigint"):
                    self.assertIsNotNone(try_generate_native(source,"shared.py",mode,unit=unit))
                if source==SCALAR:
                    self.assertIsNotNone(try_generate_bigint(source,"shared.py",unit=unit))
                else:
                    for mode in ("i64","i128","bigint"):
                        self.assertIsNotNone(try_generate_classes(source,"shared.py",mode,unit=unit))
            self.assertEqual(ast.dump(unit.tree,include_attributes=True),original)

    def test_contextual_syntax_and_scope_errors_keep_official_positions(self):
        for source in ("return 1\n","break\n","continue\n","yield 1\n",
                       "def f():\n nonlocal absent\n", "def f(x,x):pass\n",
                       "from math import *\ndef f():\n from math import *\n"):
            with self.subTest(source=source),patch.object(Compiler,"compile",side_effect=AssertionError("legacy")):
                result=transpile(source,TranspileOptions(filename="invalid.py"))
                self.assertFalse(result.success)
                self.assertEqual(result.diagnostics[0].code,"E001")
                self.assertEqual(result.diagnostics[0].filename,"invalid.py")
                self.assertGreaterEqual(result.diagnostics[0].line,1)

    def test_read_only_tree_scopes_and_metadata(self):
        unit=parse_source(CLASSES)
        with self.assertRaises((FrozenInstanceError,AttributeError)):unit.filename="changed"
        with self.assertRaises(TypeError):unit.tree.body.append(ast.Pass())
        with self.assertRaises(TypeError):unit.tree.body[0].name="Changed"
        with self.assertRaises(TypeError):unit.node_ordinals[0]=1
        self.assertTrue(unit.scopes)
        self.assertTrue(unit.nodes)
        self.assertTrue(unit.bindings)
        method=unit.tree.body[0].body[0]
        symbols={symbol.name for symbol in unit.scope_for(method).symbols if symbol.has("parameter")}
        self.assertEqual(symbols,{"self","n"})

    def test_source_mapping_is_stable_and_uses_contiguous_scope_ordinals(self):
        first=transpile(CLASSES,TranspileOptions(filename="source.py",optimize=False))
        second=transpile(CLASSES,TranspileOptions(filename="source.py",optimize=True))
        self.assertTrue(first.success,first.diagnostics)
        self.assertEqual(first.source_map,second.source_map)
        program=build_program(CLASSES,"source.py")
        self.assertEqual(program.source_map,first.source_map)
        by_scope={}
        for location in program.source_map:
            self.assertEqual(location.filename,"source.py")
            self.assertGreaterEqual(location.line,1)
            self.assertGreaterEqual(location.column,1)
            by_scope.setdefault(location.code,[]).append(location.instruction)
        for instructions in by_scope.values():self.assertEqual(instructions,list(range(len(instructions))))
        self.assertGreater(len(by_scope),1)

    def test_fresh_float_class_path_does_not_import_general_compiler_or_profile(self):
        package=Path(__file__).resolve().parents[1]
        driver=r'''import ast,json,sys
from unittest.mock import patch
sys.path.insert(0,sys.argv[1])
from py2fastrust import transpile
source="class Box:\n def __init__(self):self.value=1.25\nprint(Box().value)\n"
with patch("ast.parse",wraps=ast.parse)as parse:
 result=transpile(source)
print(json.dumps({"success":result.success,"parses":parse.call_count,"forbidden":[name for name in ["py2fastrust.compiler","py2fastrust.codegen","py2fastrust.python_profile","py2fastrust.ir","py2fastrust.ir_flow"]if name in sys.modules]}))
'''
        run=subprocess.run([sys.executable,"-I","-c",driver,str(package)],capture_output=True,text=True,timeout=15)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertEqual(json.loads(run.stdout),{"success":True,"parses":1,"forbidden":[]})

    def test_reserved_namespace_import_aliases_disable_default_assumptions(self):
        sources=(
            "import sys as __name__\ndef f():print(7)\nif __name__=='__main__':f()\n",
            "import sys as __builtins__\ndef f():print(7)\nf()\n",
            "import sys as __name__\nclass C:pass\nif __name__=='__main__':print(7)\n",
            "def f():\n global __name__\n __name__='changed'\nf()\n",
        )
        with patch.object(Compiler,"compile",side_effect=AssertionError("legacy")), \
             patch("py2fastrust.codegen.generate",side_effect=AssertionError("general")):
            for source in sources:
                for mode in ("i64","i128","bigint"):
                    result=transpile(source,TranspileOptions(integer=mode))
                    self.assertFalse(result.success)
                    self.assertEqual(result.diagnostics[0].code,"E006")
                    self.assertIn("rebinding",result.diagnostics[0].message)
        # A normal local parameter does not replace the module namespace.
        result=transpile("def f(__name__):return __name__\nprint(f('local'))\n")
        self.assertTrue(result.success,result.diagnostics)

    def test_empty_source_does_not_load_future_or_parse_dormant_modules(self):
        with patch("ast.parse",wraps=ast.parse)as parse:
            program=build_program("print(1)\n")
        self.assertEqual(parse.call_count,1)
        self.assertEqual(program.modules,())
        self.assertEqual(len(program.units),1)
        self.assertEqual(program.native_imports,frozenset())
        requested=build_program("from __future__ import annotations\n")
        self.assertEqual(requested.module("__future__").origin,"vendored")
        self.assertGreater(requested.main.future_flags,0)

    def test_resolver_records_actual_modules_and_function_imports(self):
        program=build_program("def work():\n import sys\n from collections import deque\n return 1\n")
        self.assertTrue({"sys","collections"}<=program.native_imports)
        self.assertEqual(program.module("sys").origin,"builtin")
        self.assertEqual(program.module("collections").origin,"vendored")
        self.assertEqual(program.module("collections").filename,"<pytors-stdlib>/collections.py")
        self.assertEqual(len(program.main.imports),2)
        self.assertNotIn("__future__",program.native_imports)

    def test_local_module_shadowing_never_grants_native_trust(self):
        with tempfile.TemporaryDirectory(prefix="pytors-frontend-shadow-")as directory:
            root=Path(directory)
            (root/"sys.py").write_text("value=9\n")
            program=build_program("import sys\n",str(root/"main.py"),(root,))
            self.assertEqual(program.module("sys").origin,"user")
            self.assertNotIn("sys",program.native_imports)
            result=transpile("import sys\nread=sys.stdin.readline\nprint(read())\n",TranspileOptions(filename=str(root/"main.py"),module_paths=(root,)))
            self.assertFalse(result.success)
            self.assertEqual(result.diagnostics[0].code,"E006")
            # A standard module depending on a shadowed module is also unsafe
            # to replace with a builtin helper that skips those user effects.
            dependent=build_program("from collections import deque\n",str(root/"main.py"),(root,))
            self.assertEqual(dependent.module("collections").origin,"vendored")
            self.assertNotIn("collections",dependent.native_imports)

    def test_recursive_packages_relative_imports_and_cycles(self):
        with tempfile.TemporaryDirectory(prefix="pytors-frontend-package-")as directory:
            root=Path(directory);package=root/"helpers";package.mkdir()
            (package/"__init__.py").write_text("from . import util\n")
            (package/"util.py").write_text("from . import cycle\ndef work():\n import math\n return 4\n")
            (package/"cycle.py").write_text("from . import util\n")
            source="def run():\n from helpers import util\n return 3\n"
            program=build_program(source,str(root/"main.py"),(root,))
            self.assertEqual({unit.name for unit in program.units},{"__main__","helpers","helpers.util","helpers.cycle"})
            self.assertEqual(program.module("helpers").filename,str(package/"__init__.py"))
            self.assertEqual(program.module("helpers.util").filename,str(package/"util.py"))
            self.assertIn("math",program.native_imports)
            self.assertTrue(any(location.filename==str(package/"util.py")for location in program.source_map))

    def test_package_initializer_importing_requested_child_parses_it_once(self):
        with tempfile.TemporaryDirectory(prefix="pytors-frontend-cycle-")as directory:
            root=Path(directory);package=root/"pkg";package.mkdir()
            (package/"__init__.py").write_text("from . import child\n")
            (package/"child.py").write_text("value=3\n")
            with patch("ast.parse",wraps=ast.parse)as parse:
                program=build_program("import pkg.child\n",module_paths=(root,))
            self.assertEqual(parse.call_count,3)
            self.assertEqual(len(program.units),3)

    def test_recursive_missing_module_and_module_syntax_errors_point_to_their_source(self):
        with tempfile.TemporaryDirectory(prefix="pytors-frontend-errors-")as directory:
            root=Path(directory);module=root/"helper.py"
            module.write_text("def work():\n import not_available_frontend_test\n")
            result=transpile("import helper\n",TranspileOptions(filename=str(root/"main.py"),module_paths=(root,)))
            self.assertEqual((result.diagnostics[0].code,result.diagnostics[0].filename,result.diagnostics[0].line),("E003",str(module),2))
            self.assertIn("could not be found",result.diagnostics[0].message)
            module.write_text("return 2\n")
            result=transpile("import helper\n",TranspileOptions(filename=str(root/"main.py"),module_paths=(root,)))
            self.assertEqual((result.diagnostics[0].code,result.diagnostics[0].filename),("E001",str(module)))
            result=transpile("from . import missing\n",TranspileOptions(filename=str(root/"main.py")))
            self.assertEqual(result.diagnostics[0].code,"E003")
            self.assertIn("relative import beyond top-level package",result.diagnostics[0].message)

    def test_imported_source_encoding_errors_are_positioned_diagnostics(self):
        with tempfile.TemporaryDirectory(prefix="pytors-frontend-encoding-")as directory:
            root=Path(directory);module=root/"broken.py"
            module.write_bytes(b"# coding: unknown_frontend_codec\nvalue=1\n")
            result=transpile("import broken\n",TranspileOptions(filename=str(root/"main.py"),module_paths=(root,)))
            self.assertFalse(result.success)
            self.assertEqual((result.diagnostics[0].code,result.diagnostics[0].filename),("E001",str(module)))

    def test_user_package_resolution_uses_its_selected_search_path(self):
        with tempfile.TemporaryDirectory(prefix="pytors-frontend-roots-")as directory:
            root=Path(directory);first=root/"first";second=root/"second"
            for base in (first,second):
                (base/"pkg").mkdir(parents=True)
                (base/"pkg"/"__init__.py").write_text("")
            (second/"pkg"/"child.py").write_text("value=3\n")
            with self.assertRaises(CompilationError)as caught:
                build_program("import pkg.child\n",module_paths=(first,second))
            self.assertEqual(caught.exception.diagnostic.code,"E003")

    def test_bindings_use_official_private_names_and_defaults_outer_scope(self):
        unit=build_program("limit=3\nclass Box:\n def read(self,__value=limit):\n  return __value\n").main
        value=next(binding for binding in unit.bindings if binding.name=="_Box__value"and binding.role=="parameter")
        self.assertEqual(value.owner,value.scope)
        default=next(binding for binding in unit.bindings if binding.name=="limit"and binding.role=="load")
        self.assertEqual(unit.scopes[default.scope].kind,"class")

    def test_attributes_parameters_and_call_keywords_follow_lexical_mangling(self):
        source="class C:\n def method(self,__value):\n  return other.__value\n def call(self):return self.method(__value=3)\n"
        unit=build_program(source).main
        method=unit.tree.body[0].body[0]
        self.assertEqual(unit.name_for(method.args.args[1]),"_C__value")
        attribute=method.body[0].value
        self.assertEqual(unit.name_for(attribute),"_C__value")
        keyword=unit.tree.body[0].body[1].body[0].value.keywords[0]
        self.assertEqual(unit.name_for(keyword),"__value")
        self.assertIn("_C__value",{symbol.name for symbol in unit.scope_for(method).symbols})

    def test_free_binding_owner_skips_a_shadowing_class_namespace(self):
        source="def outer():\n value=1\n class Inner:\n  value=2\n  def read(self):return value\n return Inner\n"
        unit=build_program(source).main
        binding=next(binding for binding in unit.bindings if binding.name=="value" and binding.role=="load")
        self.assertEqual(unit.scopes[binding.scope].name,"read")
        self.assertEqual(unit.scopes[binding.owner].name,"outer")

    def test_relocated_standard_library_keeps_logical_source_maps(self):
        with tempfile.TemporaryDirectory(prefix="pytors-frontend-relocation-")as directory:
            root=Path(directory);copies=[root/"one",root/"two"]
            import py2fastrust
            package=Path(py2fastrust.__file__).parent
            for copy in copies:
                shutil.copytree(package,copy/"py2fastrust",ignore=shutil.ignore_patterns("__pycache__","*.pyc",".env*"))
            driver='''import json,sys
from dataclasses import asdict
sys.path.insert(0,sys.argv[1])
from py2fastrust.frontend import build_program
p=build_program("from collections import deque\\n", "main.py", (sys.argv[2],))
print(json.dumps({"maps":[asdict(v)for v in p.source_map],"files":[u.filename for u in p.units],"trusted":sorted(p.native_imports)}))
'''
            results=[]
            for copy in copies:
                run=subprocess.run([sys.executable,"-I","-c",driver,str(copy),str(root/"empty")],capture_output=True,text=True,timeout=20)
                self.assertEqual(run.returncode,0,run.stderr)
                results.append(json.loads(run.stdout))
            self.assertEqual(results[0],results[1])
            self.assertIn("<pytors-stdlib>/collections.py",results[0]["files"])
            self.assertNotIn("<pytors-stdlib>/__future__.py",results[0]["files"])


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class SharedFrontendExecutionTests(unittest.TestCase):
    def test_class_private_attributes_use_lexical_owner_in_every_integer_mode(self):
        valid="""class Other:
 def __init__(self):
  self._C__value=7
  self.__value=19
class C:
 def __init__(self,__value):self.__value=__value
 def read(self,other):return other.__value
c=C(_C__value=3)
print(c._C__value,c.read(Other()))
"""
        cases=(valid,valid+"print(c.__value)\n", """class Other:
 def __init__(self):self.__value=19
class C:
 def read(self,other):return other.__value
print(C().read(Other()))
""")
        with tempfile.TemporaryDirectory(prefix="pytors-private-frontend-")as directory:
            root=Path(directory)
            for source in cases:
                expected=subprocess.run([sys.executable,"-c",source],capture_output=True,text=True,timeout=5)
                for mode in ("i64","i128","bigint"):
                    result=transpile(source,TranspileOptions(integer=mode))
                    self.assertTrue(result.success,result.diagnostics)
                    path=root/"program.rs";path.write_text(result.rust_source)
                    built=subprocess.run(["rustc","--edition=2021",str(path),"-o",str(root/"program")],capture_output=True,text=True,timeout=60)
                    self.assertEqual(built.returncode,0,built.stderr)
                    actual=subprocess.run([str(root/"program")],capture_output=True,text=True,timeout=5)
                    self.assertEqual((actual.returncode,actual.stdout),(expected.returncode,expected.stdout),actual.stderr)
                    if expected.returncode:self.assertIn("AttributeError:",actual.stderr)

    def test_float_class_literals_compile_without_general_codegen_helpers(self):
        source="class Box:\n def __init__(self):self.value=1.25\nprint(Box().value)\n"
        with tempfile.TemporaryDirectory(prefix="pytors-frontend-float-")as directory:
            root=Path(directory)
            for mode in ("i64","i128"):
                result=transpile(source,TranspileOptions(integer=mode))
                self.assertTrue(result.success,result.diagnostics)
                path=root/"program.rs";path.write_text(result.rust_source)
                built=subprocess.run(["rustc","--edition=2021",str(path),"-o",str(root/"program")],capture_output=True,text=True,timeout=60)
                self.assertEqual(built.returncode,0,built.stderr)
                actual=subprocess.run([str(root/"program")],capture_output=True,text=True,timeout=5)
                self.assertEqual((actual.returncode,actual.stdout),(0,"1.25\n"),actual.stderr)

    def test_local_reserved_names_use_official_scope_ownership(self):
        sources=("def f():\n __name__='local'\n __builtins__=3\n return __name__\nprint(f())\n",
                 "class C:\n def f(self):\n  __name__='local'\n  __builtins__=3\n  return __name__\nprint(C().f())\n",
                 "class C:\n def f(self):\n  print(__name__)\n  __name__='local'\nC().f()\n")
        with tempfile.TemporaryDirectory(prefix="pytors-frontend-local-names-")as directory:
            root=Path(directory)
            for source in sources:
                expected=subprocess.run([sys.executable,"-c",source],capture_output=True,text=True,timeout=5)
                for mode in ("i64","i128","bigint"):
                    result=transpile(source,TranspileOptions(integer=mode))
                    self.assertTrue(result.success,result.diagnostics)
                    path=root/"program.rs";path.write_text(result.rust_source)
                    built=subprocess.run(["rustc","--edition=2021",str(path),"-o",str(root/"program")],capture_output=True,text=True,timeout=60)
                    self.assertEqual(built.returncode,0,built.stderr)
                    actual=subprocess.run([str(root/"program")],capture_output=True,text=True,timeout=5)
                    self.assertEqual((actual.returncode,actual.stdout),(expected.returncode,expected.stdout),actual.stderr)
                    if expected.returncode:self.assertIn("UnboundLocalError:",actual.stderr)

    def test_all_native_emitters_execute_after_removing_legacy_frontend(self):
        with tempfile.TemporaryDirectory(prefix="pytors-frontend-execute-")as directory:
            root=Path(directory)
            for mode in ("i64","i128","bigint"):
                for source,expected in ((SCALAR,"14\n"),(CLASSES,"9\n")):
                    with patch.object(Compiler,"compile",side_effect=AssertionError("legacy compiler")), \
                         patch("py2fastrust.codegen.generate",side_effect=AssertionError("general backend")):
                        result=transpile(source,TranspileOptions(integer=mode))
                    self.assertTrue(result.success,result.diagnostics)
                    path=root/"program.rs";path.write_text(result.rust_source)
                    built=subprocess.run(["rustc","--edition=2021",str(path),"-o",str(root/"program")],capture_output=True,text=True,timeout=60)
                    self.assertEqual(built.returncode,0,built.stderr)
                    run=subprocess.run([str(root/"program")],capture_output=True,text=True,timeout=5)
                    self.assertEqual((run.returncode,run.stdout),(0,expected),run.stderr)


if __name__=="__main__":unittest.main()
