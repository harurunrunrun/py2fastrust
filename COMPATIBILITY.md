# 対応範囲

基準はPython 3.14です。以下は実装の対応状況です。CPythonの内部実装や全標準ライブラリの互換性を示す一覧ではありません。

## 言語・実行時機能

| 分類 | 対応 |
|---|---|
| 値 | None、bool、選択幅のint、float、str、bytes、list、tuple、dict、set、slice、range |
| 変数 | 型変更、共有参照、多重・アンパック代入、global/nonlocal、未束縛エラー |
| 制御 | if、while、for、break/continue、else、短絡演算、比較連鎖 |
| 関数 | 既定値、位置専用・キーワード専用引数、可変長引数、再帰、lambda、クロージャ |
| コンテナ式 | 内包表記、ジェネレータ式、展開、負の添字、スライス |
| 例外 | raise、except、else、finally、assert、例外対象変数の後始末 |
| クラス | 継承、C3 MRO、descriptor、property、staticmethod/classmethod、super、メタクラス |
| 名前空間 | 任意mappingを返す__prepare__、内部一時変数の分離、Python 3.14関数localsのsnapshot |
| その他 | with、ジェネレータ、f-string、match/case |
| 動的実行 | compile/eval/exec、静的コードとの相互呼び出し、遅延評価する関数アノテーション |
| メモリ | オブジェクト同一性、循環参照、フレーム・一時値をルートとするmark-and-sweep GC、__del__と復活 |

通常の関数再帰はヒープ上のフレームで処理します。プロトコルや組込み関数からの再入にはRust側の呼び出しが使われる経路もあります。

## 標準モジュール

| モジュール | 対象 |
|---|---|
| math | Python 3.14の全公開関数とpi/e/tau/inf/nan |
| heapq | CPythonの純Python実装。最大ヒープを含む公開API |
| bisect | CPythonの純Python実装。key・lo/hiを含む公開API |
| itertools | 公開API。無限イテレータ、tee、groupbyを含む遅延実行 |
| functools | 公開API。cache/lru_cache、partial、decorator、dispatch、cached_property |
| collections | deque、defaultdict、Counter、namedtuple、OrderedDict |
| sys | 標準入出力、argv、exit、再帰制限設定 |
| gc | collectなど、ランタイムのGC制御 |

mathの浮動小数点特殊関数は精度テストを行いますが、OSやCPythonのlibmによる結果と常にbit単位で一致することは保証しません。

純Pythonモジュールも、そのコードが対応する構文・組込み関数・モジュールの範囲にあることが必要です。
APIごとの名前は [API_SUPPORT.md](API_SUPPORT.md) を参照してください。

## 既知の制約

- async/await、except*、t-string、type文、型パラメータの構文は未対応です。
- complex、未対のUnicodeサロゲートなど、基本値にも未対応範囲があります。
- 実行時パーサではUnicodeの名前付きエスケープなどに制約があります。実行時パーサは公式CPythonパーサの移植ではありません。
- annotationlibの全format、型パラメータ、型エイリアスの評価は未対応です。
- モジュール・クラスの変数アノテーションから__annotations__を生成する処理は未対応です。
- 実行時に名前が決まるimport、外部C拡張、ネットワーク、スレッド、asyncio、CPython固有の内部APIは対象外です。
- inspect、pickle、weakrefなど、一覧にない標準モジュールのAPIは提供していません。
- namedtupleの呼出元moduleの推定、空の関数defaultsの表示、辞書subclassの基底descriptor操作には互換性の差が残っています。
- 辞書の変更中の反復では、サイズが戻った場合にも保守的にRuntimeErrorを送出する場合があります。
- 動的な関数・クラスを含むコードのネイティブ特殊化には制約があり、汎用実行へ戻る場合があります。

構文・モジュールの未対応は変換時の診断、動的な未対応操作は元ソース位置を含む実行時例外として報告します。

## 整数モード

i64/i128は各整数値・演算結果を選択幅へ正規化します。例えばi64の `2**63` は `-2**63` です。
この範囲超過の動作は、無制限整数を使うCPythonとは異なります。
BigIntモードでは任意精度整数として処理します。

負数の `//` と `%`、負指数の剰余累乗、負数のビット演算、巨大なシフト、整数とfloatの比較を個別に扱います。
長さ・添字・確保サイズ・rangeの進行は、ユーザーの整数演算とは別に検査します。
