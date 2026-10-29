"""Bundled Unicode arrays keep token values and nearby, complete attribution."""
from importlib.resources import files
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from py2fastrust import transpile,TranspileOptions
from py2fastrust.native_notices import retain_native_notices
from py2fastrust.native_unicode_tables import unicode_tables,compact_unicode_tables
from py2fastrust.rust_pruning import _lex


def token_values(source):
    return [(token.kind,token.text)for token in _lex(source)[0]]


class UnicodeTableLayoutTests(unittest.TestCase):
    def test_only_reserved_numeric_table_initializers_are_compacted(self):
        source='''// original comment must stay byte-identical
const OTHER:&[(u32,u32)]=&[
 (1,2),
 (3,4),
];
const NATIVE_PRED_TABLE_ALPHA:&[(u32,u32)]=&[
 (0x41,0x5A),
 (0x61,0x7A),
 (0x00C0,0x00D6),
];
const NATIVE_FIXED_INT_ZEROES:&[u32]=&[
 0x30,
 0x660u32,
 0x6f0,
];
fn main(){let text=r##"const RANGES:&[(u32,u32)]=&[
 (9,10),
 (11,12),
];"##;println!("{}",text);}
'''
        compact=compact_unicode_tables(source,width=80)
        self.assertEqual(token_values(source),token_values(compact))
        self.assertEqual(compact_unicode_tables(compact,width=80),compact)
        self.assertIn('const OTHER:&[(u32,u32)]=&[\n (1,2),\n (3,4),\n];',compact)
        self.assertIn('(0x41,0x5A), (0x61,0x7A), (0x00C0,0x00D6),',compact)
        self.assertIn('0x30, 0x660u32, 0x6f0,',compact)
        before_tokens,before_comments,_=_lex(source)
        after_tokens,after_comments,_=_lex(compact)
        self.assertEqual([token.text for token in before_tokens if token.kind=='literal'],
                         [token.text for token in after_tokens if token.kind=='literal'])
        self.assertEqual([source[a:b]for a,b,_ in before_comments],[compact[a:b]for a,b,_ in after_comments])

    def test_array_types_and_local_tables_preserve_tokens_and_width(self):
        source='fn main(){\n    const ZEROES:[u32;12]=[\n'+''.join('        '+str(i)+',\n'for i in range(12))+'    ];\n    const RANGES:&\'static [(u32,u32,)]=&[\n'+''.join('        ('+str(i)+','+str(i+1)+',),\n'for i in range(10))+'    ];\n}\n'
        compact=compact_unicode_tables(source,width=52)
        self.assertEqual(token_values(source),token_values(compact))
        self.assertTrue(all(len(line)<=52 for line in compact.splitlines()))
        self.assertLess(len(compact.splitlines()),len(source.splitlines()))
        self.assertEqual(len(unicode_tables(compact)),2)

    def test_unfamiliar_initializers_and_internal_comments_are_not_rewritten(self):
        source='''const ZEROES:&[u32]=&[lookup(3),4];
const RANGES:&[(u32,u32)]=&[(1,2),/* leave me */(3,4)];
const NATIVE_PRED_TABLE_ALPHA:&[u8]=&[
 1,
 2,
];
fn main(){}
'''
        self.assertEqual(compact_unicode_tables(source),source)

    def test_full_license_follows_first_table_and_identifies_noncontiguous_tables(self):
        source='''fn first()->u32{const ZEROES:&[u32]=&[0x30,0x660];ZEROES[0]}
fn unrelated(){let text="UNICODE LICENSE V3";println!("{}",text);}
fn second()->u32{const RANGES:&[(u32,u32)]=&[(1,2),(3,4)];RANGES[0].0}
fn main(){println!("{} {}",first(),second());}
'''
        result=retain_native_notices(source)
        self.assertEqual(token_values(result),token_values(source))
        notice=files('py2fastrust').joinpath('stdlib','UNICODE_LICENSE.txt').read_text()
        self.assertEqual(result.count('// UNICODE LICENSE V3'),1)
        for line in notice.splitlines():self.assertIn('// '+line,result)
        self.assertLess(result.index('// UNICODE LICENSE V3'),result.index('const ZEROES'))
        self.assertLess(result.index('const ZEROES'),result.index('fn unrelated'))
        self.assertIn('Unicode 16.0 data table 1: ZEROES.',result)
        self.assertIn('Unicode 16.0 data table 2: RANGES; license: table 1 (ZEROES) above.',result)
        self.assertLess(result.index('data table 2: RANGES'),result.index('const RANGES'))
        self.assertTrue(result.rstrip().endswith('}'))
        if shutil.which('rustc'):
            with tempfile.TemporaryDirectory(prefix='pytors-unicode-notice-')as directory:
                rust=Path(directory,'main.rs');rust.write_text(result);binary=rust.with_suffix('')
                compiled=subprocess.run(['rustc','--edition=2021',str(rust),'-o',str(binary)],text=True,capture_output=True)
                self.assertEqual(compiled.returncode,0,compiled.stderr)
                actual=subprocess.run([str(binary)],text=True,capture_output=True)
                self.assertEqual((actual.returncode,actual.stdout),(0,'48 1\n'))

    def test_license_shaped_literals_are_preserved_by_notice_selection(self):
        root=files("py2fastrust")
        blocks=[]
        for name in ("PYTHON_LICENSE.txt","UNICODE_LICENSE.txt"):
            blocks.append("\n".join("// "+line for line in root.joinpath("stdlib",name).read_text().splitlines()))
        blocks.append("/*\n"+root.joinpath("runtime","NOTICE.txt").read_text()+"\n*/\n")
        literal="\n".join(blocks)
        source='fn main(){let text=r####"'+literal+'"####;print!("{}",text);}'
        result=retain_native_notices(source)
        self.assertEqual(token_values(source),token_values(result))
        self.assertIn('r####"'+literal+'"####',result)

    def test_macro_and_attribute_token_trees_are_not_reformatted(self):
        source='''macro_rules! data {()=>{const ZEROES:&[u32]=&[
 1,
 2,
];};}
fn main(){let _=stringify!(const RANGES:&[(u32,u32)]=&[
 (1,2),
 (3,4),
]);}
'''
        self.assertEqual(compact_unicode_tables(source),source)
        result=retain_native_notices(source)
        self.assertLess(result.index('// UNICODE LICENSE V3'),result.index('macro_rules!'))
        self.assertNotIn('//',result[result.index('macro_rules!'):result.index('fn main')])
        self.assertEqual(token_values(source),token_values(result))
        attribute='#[tokens(const ZEROES:&[u32]=&[\n 1,\n 2,\n])]fn main(){}'
        self.assertEqual(compact_unicode_tables(attribute),attribute)

    def test_incomplete_or_other_constant_types_are_unchanged(self):
        for source in ('const ZEROES:', 'const ZEROES:&[u32]=&',
                       'const ZEROES:u32=3;', 'const OTHER:&[u32]=&[\n1,\n2,\n];'):
            self.assertEqual(compact_unicode_tables(source),source)

    def test_retained_real_tables_are_compact_and_notices_remain_adjacent(self):
        source='s=input()\nprint(s.isalpha(),int(input()))\n'
        for mode in ('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=mode,string_mode='unicode'))
            self.assertTrue(result.success,result.diagnostics)
            tables=unicode_tables(result.rust_source)
            self.assertTrue(tables)
            first=tables[0]
            self.assertLess(result.rust_source.index('// UNICODE LICENSE V3'),first.start)
            self.assertNotIn('fn ',result.rust_source[result.rust_source.index('// UNICODE LICENSE V3'):first.start])
            for table in tables:
                body=result.rust_source[table.body_start:table.body_end]
                self.assertTrue(all(len(line)<=100 for line in body.splitlines()))
                if table.elements and len(table.elements)>2:
                    self.assertLess(len(body.splitlines()),len(table.elements)+2)


if __name__=='__main__':unittest.main()
