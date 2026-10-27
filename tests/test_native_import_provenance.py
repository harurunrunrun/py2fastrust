"""Native lowering trusts resolved standard modules, never their spelling."""
from pathlib import Path
import tempfile
import unittest

from py2fastrust.compiler import Compiler


class NativeImportProvenanceTests(unittest.TestCase):
    def test_builtin_module_resolution_records_provenance(self):
        compiler = Compiler("main.py", (), ())
        compiler.compile("import sys\nimport math\n")
        self.assertEqual(compiler.native_imports, {"__future__", "sys", "math"})

    def test_local_module_shadows_standard_module_without_native_trust(self):
        with tempfile.TemporaryDirectory(prefix="pytors-native-import-") as directory:
            root = Path(directory)
            (root / "sys.py").write_text("value=7\n")
            (root / "collections.py").write_text("value=8\n")
            compiler = Compiler(str(root / "main.py"), (root,), ())
            compiler.compile("import sys\nimport collections\n")
            self.assertNotIn("sys", compiler.native_imports)
            self.assertNotIn("collections", compiler.native_imports)
            self.assertTrue({"sys", "collections"} <= set(compiler.module_ids))

    def test_vendored_module_provenance_is_still_recorded(self):
        compiler = Compiler("main.py", (), ())
        compiler.compile("from collections import deque\n")
        self.assertEqual(compiler.native_imports, {"__future__", "sys", "collections"})


if __name__ == "__main__":
    unittest.main()
