"""Generator error effects follow real callable identities and lexical scopes."""
import unittest
from py2fastrust.frontend import parse_source
from py2fastrust.native_constraints import analyze
from py2fastrust.native_generator_effects import may_stop
CASES={'direct_next': ('print(list(next(iter(()))for _ in range(1)))\n', True),
 'alias_next': ('pull=next\nprint(list(pull(iter(()))for _ in range(1)))\n',
                True),
 'callee_transitive': ('def a():return b()\n'
                       'def b():return next(iter(()))\n'
                       'print(sum(a()for _ in range(1)))\n',
                       True),
 'next_default': ('print(list(next(iter(()),7)for _ in range(2)))\n', False),
 'outer_source_next': ('print(list(x for x in range(next(iter(())))))\n',
                       False),
 'shadowed_next': ('def next(value):return 9\n'
                   'print(list(next(0)for _ in range(2)))\n',
                   False),
 'list_pop_is_not_stop': ('values=["a","b"]\n'
                          'print("".join(values.pop()for _ in range(2)))\n',
                          False),
 'listcomp_inside_generator': ('print(list([next(iter(()))for _ in '
                               'range(1)]for j in range(1)))\n',
                               True),
 'expanded_next_default': ('print(list(next(*(iter(()),7))for _ in '
                           'range(2)))\n',
                           False),
 'expanded_next': ('print(list(next(*(iter(()),))for _ in range(1)))\n', True)}
class GeneratorEffects(unittest.TestCase):
    def test_canonical_calls_and_scope_boundaries(self):
        for name,(source,expected)in CASES.items():
            with self.subTest(name=name):
                unit=parse_source(source,"generator_effect.py")
                self.assertEqual(bool(may_stop(unit,analyze(unit))),expected)
