"""Bundled ACL source discovery uses official ASTs and preserves import roots."""
import builtins
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust.diagnostics import CompilationError
from py2fastrust.frontend import build_program


PUBLIC_MODULES=('dsu','fenwicktree','segtree','lazysegtree','scc','twosat',
                'maxflow','mincostflow','math','modint','string','convolution')


class ACLResolutionTests(unittest.TestCase):
    def test_all_library_modules_resolve_without_installation_or_module_paths(self):
        original_import=builtins.__import__
        def no_host_acl(name,*args,**kwargs):
            if name=='atcoder' or name.startswith('atcoder.'):
                raise AssertionError('The converter executed an ACL import')
            return original_import(name,*args,**kwargs)
        with tempfile.TemporaryDirectory(prefix='pytors-acl-resolution-')as directory:
            for name in PUBLIC_MODULES:
                source=f'from atcoder.{name} import *\n'
                with self.subTest(module=name),patch('builtins.__import__',side_effect=no_host_acl):
                    program=build_program(source,str(Path(directory)/'main.py'))
                    module=next(item for item in program.modules if item.name=='atcoder.'+name)
                    self.assertEqual(module.origin,'vendored')
                    self.assertEqual(module.filename,f'<pytors-ac-library-python>/atcoder/{name}.py')
                    unit=next(item for item in program.units if item.name==module.name)
                    self.assertEqual(unit.source,files('py2fastrust').joinpath(*module.resource).read_text(encoding='utf-8'))
                    self.assertTrue(unit.is_module_scope(0))
                    self.assertEqual(program.main.source,source)

    def test_package_aliases_and_transitive_dependencies_are_recorded(self):
        program=build_program('from atcoder import lazysegtree as trees\nimport atcoder.twosat as sat\nimport atcoder.convolution\n')
        names={item.name for item in program.modules}
        self.assertTrue({'atcoder','atcoder.lazysegtree','atcoder._bit','atcoder.twosat',
                         'atcoder._scc','atcoder.convolution','atcoder.modint','atcoder._math'}<=names)
        self.assertEqual(program.main.imports[0].children,('atcoder.lazysegtree',))
        self.assertEqual(program.main.imports[1].module,'atcoder.twosat')
        for name in names:self.assertEqual(sum(item.name==name for item in program.modules),1)

    def test_function_local_and_repeated_imports_share_source_units(self):
        source='from atcoder.dsu import DSU\ndef load():\n import atcoder.dsu\n from atcoder import fenwicktree\n'
        program=build_program(source)
        self.assertEqual(sum(unit.name=='atcoder.dsu'for unit in program.units),1)
        self.assertIn('atcoder.fenwicktree',{unit.name for unit in program.units})
        self.assertEqual(len(program.main.imports),3)

    def test_explicit_user_package_shadows_the_bundled_package(self):
        with tempfile.TemporaryDirectory(prefix='pytors-acl-shadow-')as directory:
            root=Path(directory);package=root/'atcoder';package.mkdir()
            (package/'__init__.py').write_text('marker=7\n')
            (package/'dsu.py').write_text('value=9\n')
            program=build_program('import atcoder.dsu\n',str(root/'main.py'))
            self.assertTrue(all(item.origin=='user'for item in program.modules))
            self.assertEqual(next(unit for unit in program.units if unit.name=='atcoder.dsu').source,'value=9\n')
            self.assertNotIn('atcoder.dsu',program.main.native_imports)

    def test_missing_child_of_user_package_does_not_mix_bundled_sources(self):
        with tempfile.TemporaryDirectory(prefix='pytors-acl-isolation-')as directory:
            root=Path(directory);package=root/'atcoder';package.mkdir()
            (package/'__init__.py').write_text('marker=7\n')
            with self.assertRaises(CompilationError)as caught:
                build_program('import atcoder.dsu\n',str(root/'main.py'))
            self.assertEqual(caught.exception.diagnostic.code,'E003')
            self.assertIn('atcoder.dsu',caught.exception.diagnostic.message)

    def test_missing_bundled_child_is_a_positioned_diagnostic(self):
        with self.assertRaises(CompilationError)as caught:
            build_program('import atcoder.missing_module\n','entry.py')
        self.assertEqual((caught.exception.diagnostic.filename,caught.exception.diagnostic.line,
                          caught.exception.diagnostic.column,caught.exception.diagnostic.code),('entry.py',1,1,'E003'))

    def test_bundled_bytes_match_the_pinned_upstream_git_blobs(self):
        root=files('py2fastrust').joinpath('vendor','ac_library_python')
        manifest=json.loads(root.joinpath('UPSTREAM.json').read_text())
        self.assertEqual(manifest['repository'],'not522/ac-library-python')
        self.assertEqual(manifest['commit'],'27fdbb71cd0d566bdeb12746db59c9d908c6b5d5')
        self.assertEqual(len(manifest['files']),18)
        for name,wanted in manifest['files'].items():
            data=root.joinpath(*name.split('/')).read_bytes()
            self.assertEqual(hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest(),wanted,name)
        self.assertTrue(root.joinpath('LICENSE').read_text().startswith('CC0 1.0 Universal'))
