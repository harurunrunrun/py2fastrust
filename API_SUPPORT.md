# 標準ライブラリAPIの実装一覧

以下は各名前を実装した一覧です。引数・型・特殊なプロトコルを含む完全なCPython互換性を保証するものではありません。
言語全体の制約は [COMPATIBILITY.md](COMPATIBILITY.md) を参照してください。

## math

| API | 状態 |
|---|---|
| `acos` | 実装済み |
| `acosh` | 実装済み |
| `asin` | 実装済み |
| `asinh` | 実装済み |
| `atan` | 実装済み |
| `atan2` | 実装済み |
| `atanh` | 実装済み |
| `cbrt` | 実装済み |
| `ceil` | 実装済み |
| `comb` | 実装済み |
| `copysign` | 実装済み |
| `cos` | 実装済み |
| `cosh` | 実装済み |
| `degrees` | 実装済み |
| `dist` | 実装済み |
| `e` | 実装済み |
| `erf` | 実装済み |
| `erfc` | 実装済み |
| `exp` | 実装済み |
| `exp2` | 実装済み |
| `expm1` | 実装済み |
| `fabs` | 実装済み |
| `factorial` | 実装済み |
| `floor` | 実装済み |
| `fma` | 実装済み |
| `fmod` | 実装済み |
| `frexp` | 実装済み |
| `fsum` | 実装済み |
| `gamma` | 実装済み |
| `gcd` | 実装済み |
| `hypot` | 実装済み |
| `inf` | 実装済み |
| `isclose` | 実装済み |
| `isfinite` | 実装済み |
| `isinf` | 実装済み |
| `isnan` | 実装済み |
| `isqrt` | 実装済み |
| `lcm` | 実装済み |
| `ldexp` | 実装済み |
| `lgamma` | 実装済み |
| `log` | 実装済み |
| `log10` | 実装済み |
| `log1p` | 実装済み |
| `log2` | 実装済み |
| `modf` | 実装済み |
| `nan` | 実装済み |
| `nextafter` | 実装済み |
| `perm` | 実装済み |
| `pi` | 実装済み |
| `pow` | 実装済み |
| `prod` | 実装済み |
| `radians` | 実装済み |
| `remainder` | 実装済み |
| `sin` | 実装済み |
| `sinh` | 実装済み |
| `sqrt` | 実装済み |
| `sumprod` | 実装済み |
| `tan` | 実装済み |
| `tanh` | 実装済み |
| `tau` | 実装済み |
| `trunc` | 実装済み |
| `ulp` | 実装済み |

## heapq

| API | 状態 |
|---|---|
| `heapify` | 実装済み |
| `heapify_max` | 実装済み |
| `heappop` | 実装済み |
| `heappop_max` | 実装済み |
| `heappush` | 実装済み |
| `heappush_max` | 実装済み |
| `heappushpop` | 実装済み |
| `heappushpop_max` | 実装済み |
| `heapreplace` | 実装済み |
| `heapreplace_max` | 実装済み |
| `merge` | 実装済み |
| `nlargest` | 実装済み |
| `nsmallest` | 実装済み |

## bisect

| API | 状態 |
|---|---|
| `bisect` | 実装済み |
| `bisect_left` | 実装済み |
| `bisect_right` | 実装済み |
| `insort` | 実装済み |
| `insort_left` | 実装済み |
| `insort_right` | 実装済み |

## itertools

| API | 状態 |
|---|---|
| `accumulate` | 実装済み |
| `batched` | 実装済み |
| `chain` | 実装済み |
| `combinations` | 実装済み |
| `combinations_with_replacement` | 実装済み |
| `compress` | 実装済み |
| `count` | 実装済み |
| `cycle` | 実装済み |
| `dropwhile` | 実装済み |
| `filterfalse` | 実装済み |
| `groupby` | 実装済み |
| `islice` | 実装済み |
| `pairwise` | 実装済み |
| `permutations` | 実装済み |
| `product` | 実装済み |
| `repeat` | 実装済み |
| `starmap` | 実装済み |
| `takewhile` | 実装済み |
| `tee` | 実装済み |
| `zip_longest` | 実装済み |

## functools

| API | 状態 |
|---|---|
| `Placeholder` | 実装済み |
| `WRAPPER_ASSIGNMENTS` | 実装済み |
| `WRAPPER_UPDATES` | 実装済み |
| `cache` | 実装済み |
| `cached_property` | 実装済み |
| `cmp_to_key` | 実装済み |
| `lru_cache` | 実装済み |
| `partial` | 実装済み |
| `partialmethod` | 実装済み |
| `reduce` | 実装済み |
| `singledispatch` | 実装済み |
| `singledispatchmethod` | 実装済み |
| `total_ordering` | 実装済み |
| `update_wrapper` | 実装済み |
| `wraps` | 実装済み |

functoolsのsingledispatch/singledispatchmethodはクラス登録に対応します。
union型による登録や未対応モジュールのABC連携には制約があります。
mathの特殊関数はCPythonのlibmと常にbit単位で一致するとは限りません。

## collections

| 型・生成関数 | 公開API |
|---|---|
| `deque` | append、appendleft、clear、copy、count、extend、extendleft、index、insert、pop、popleft、remove、reverse、rotate、maxlen |
| `defaultdict` | dictの操作、default_factory、copy、fromkeys |
| `Counter` | dictの操作、elements、most_common、subtract、total、update、加減算・集合演算・比較 |
| `namedtuple` | defaults/module/rename、_fields、_field_defaults、_make、_asdict、_replace、__match_args__ |
| `OrderedDict` | dictの操作、move_to_end、popitem(last=...)、順序を含む同型比較 |

Counter.fromkeysはCPythonと同じくNotImplementedErrorを送出します。
ChainMap、UserDict、UserList、UserStringは対象に含めていません。

## sys

| API | 状態 |
|---|---|
| `stdin`、`stdout`、`stderr` | text/binary bufferの入出力 |
| `argv` | 実行ファイルに渡された引数 |
| `exit` | SystemExit |
| `setrecursionlimit`、`getrecursionlimit` | 再帰制限の設定・取得 |

一覧にないsysのAPIはサポート対象に含めていません。

## 追加モジュール

| モジュール | 対応 |
|---|---|
| `__future__` | 全既知feature・compiler_flag・release metadata、future文の配置検証とcompile/eval/execへの継承 |
| `types.GenericAlias` | origin/args/parameters metadata、比較・hash・呼び出し、__class_getitem__、MRO接続。実TypeVar系の置換は未対応 |
