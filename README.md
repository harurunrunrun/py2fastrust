# py2fastrust

Python 3.14のプログラムを、外部crate不要の単一Rustファイルへ変換します。
型ヒントや入力コードの書き換えは不要です。

現在はalpha版です。対応範囲と制約は [COMPATIBILITY.md](COMPATIBILITY.md) を参照してください。
標準ライブラリの名前ごとの実装状況は [API_SUPPORT.md](API_SUPPORT.md) に記載しています。

## 使い方

変換時にはPython 3.14以降、生成コードのコンパイルにはRust 1.85以降が必要です。
生成した実行ファイルにはPython環境も追加のソースファイルも不要です。

```bash
python3 -m pip install -e .
py2fastrust examples/sum.py -o /tmp/main.rs
rustc --edition=2021 -O /tmp/main.rs -o /tmp/main
printf '4\n1 2 3 4\n' | /tmp/main
```

インストールせず、リポジトリのルートから実行することもできます。

```bash
python3 -m py2fastrust examples/sum.py -o /tmp/main.rs
```

整数モードは生成単位全体で選びます。`eval/exec` にも同じモードが適用されます。

```bash
py2fastrust main.py -o main.rs                 # i64（既定）
py2fastrust main.py -o main.rs --int i128
py2fastrust main.py -o main.rs --int bigint
```

i64/i128は、整数リテラル・変換・整数演算の結果を符号付きの選択幅へ折り返します。
Pythonの無制限整数と同じ結果が必要な場合は `--int bigint` を指定してください。
BigIntも自作ランタイムを生成ファイルに含めるため、Cargoや追加crateは不要です。
rangeの終端判定・添字・確保サイズには、折り返しとは別の検査付き処理を使います。

## モジュール

固定名のimportと、純Pythonモジュール・パッケージの同梱に対応します。
既定の検索先は入力ファイルのディレクトリです。

```bash
py2fastrust main.py --module-path ./lib -o main.rs
py2fastrust main.py --include-module helpers -o main.rs
```

`--include-module` は、`eval/exec` 内でimportするモジュールなど、通常のソースから参照されないものを事前に含める指定です。
生成した実行ファイルは、同梱したコードと対応済み標準モジュールを使います。

## Python API

```python
from py2fastrust import TranspileOptions, transpile

result = transpile(
    'n = int(input())\nprint(n * n)\n',
    TranspileOptions(integer="i128", filename="solution.py"),
)
if result.success:
    print(result.rust_source)
else:
    for diagnostic in result.diagnostics:
        print(diagnostic)
```

`source_map` はコード単位・命令位置から元のファイル、行、列への対応です。
`backend` は `native` または `vm` です。`TranspileOptions(optimize=False)` と
CLIの `--no-optimize` で汎用ランタイムを選択できます。
`--check` はRustファイルを書かずに変換可否を検証します。

## 実行方式と速度

通常の入力には公式の `ast` と `symtable` を使い、スコープと評価順を解析します。
型と束縛を証明できるi64/i128の整数・一次元整数配列・整数辞書・ループは、通常のRust整数と
`Vec<T>`、`HashMap`、`HashSet`、制御構文へ変換します。`list(map(int, input().split()))`、整数のアンパック入力、
整数リストのappend・extend・sort、整数辞書の集計と挿入順の反復にも対応します。
整数集合は構築・追加・削除・membership・sumを扱い、反復順や共有の影響を観測するコードは汎用実行を使います。
判定できないプログラムは、共通の動的ランタイムで実行します。

ランタイムは共有オブジェクト、GC、関数フレーム、例外、クラス、クロージャを扱います。
例外グループと `except*` は、部分グループの処理・再送出・未処理部分の再結合を行います。
実行時の `eval/exec` はRust製の字句解析器と、CPython 3.14.4の公式文法から生成した
PEG規則を使い、その構文木から同じ命令形式へ直接変換します。実行処理に未対応の構文は診断を出します。
`__future__` の指定と動的コンパイルへの継承、Unicode識別子のNFKC正規化にも対応します。
型パラメータ、遅延評価する型エイリアス、GenericAliasの型変数置換も、静的コードと動的コードで共用します。
t-stringはTemplateとInterpolationへ変換し、式の値と変換・整形の指定を保持します。
複素数のリテラル・演算・変換と、実行時の `compile(optimize=1/2)` にも対応します。

ベンチマークは正解一致を確認した後に実行時間の中央値と最大RSSを測定します。
変換・コンパイル時間は別に記録します。

```bash
python3 benchmarks/run.py --case arithmetic --size 1000000
python3 benchmarks/run.py --case list --size 1000000
python3 benchmarks/run.py --case dp --size 1000000
python3 benchmarks/run.py --case dict --size 1000000
python3 benchmarks/run.py --case bfs --size 2000
```

測定対象は算術、入出力、配列、sort、辞書、BFS、DP、BigIntです。
算術では手書きRustとも比較し、PyPyが利用可能なら同じ入力で測定します。
動的機能を使うプログラムの速度は、ネイティブ化されるプログラムと異なります。
汎用ランタイムのdict/setは現在、線形検索を使います。ネイティブ化できる整数辞書ではHashMapによる検索を使います。
dequeの両端操作は償却O(1)ですが、OrderedDictの先頭移動はO(n)です。

## 検証

```bash
python3 -m unittest discover -s tests -v
python3 tests/test_native.py --benchmark-native
python3 tools/check_standalone.py
```

CPython 3.14との実行差分、固定幅整数の参照モデル、BigIntの乱数演算、GC、動的コードと
AOTコードの相互呼び出しを検証しています。CIはRust 1.85とstableを対象とします。
`check_standalone.py` は全整数モードのデバッグ・最適化ビルドを実行し、生成物をPythonが見つからないPATHでも検証します。
`--wheel path/to/package.whl` で配布物を検証し、`--output directory` で生成ソース・実行ファイル・測定結果を保存できます。

## ライセンス

本体と自作ランタイムはMITです。生成ファイルにも必要な表示を含みます。
CPython由来の標準ライブラリ・数値アルゴリズムとUnicodeデータについては
[THIRD_PARTY.md](THIRD_PARTY.md) と同梱のPSF・Unicodeライセンスを参照してください。
