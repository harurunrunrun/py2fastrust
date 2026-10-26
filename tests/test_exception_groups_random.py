"""Independent tree/handler combinations against CPython's except* semantics."""

import random
import shutil
import unittest

import test_exception_groups_dynamic


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class ExceptionGroupTreeTests(unittest.TestCase):
    maxDiff = None
    helpers = test_exception_groups_dynamic.DynamicExceptionGroupTests.helpers
    setUpClass = classmethod(test_exception_groups_dynamic.DynamicExceptionGroupTests.setUpClass.__func__)
    check_source = test_exception_groups_dynamic.DynamicExceptionGroupTests.check_source

    def test_seeded_nested_trees_reraises_and_new_errors(self):
        generator = random.Random(654314)

        def tree(depth):
            if depth == 0 or generator.randrange(4) == 0:
                return generator.randrange(5)
            return (f"tree{depth}", [tree(depth - 1) for _ in range(generator.randrange(1, 5))])

        cases = [(tree(3), [generator.randrange(5) for _ in range(3)])
                 for _ in range(120)]
        source = 'cases = ' + repr(cases) + '\n' + '''
import gc
def describe(error):
    if isinstance(error, BaseExceptionGroup):
        return type(error).__name__, error.message, tuple(describe(child) for child in error.exceptions)
    return type(error).__name__, str(error)
def build(specification, leaves):
    if isinstance(specification, int):
        return leaves[specification]
    return BaseExceptionGroup(specification[0], [build(child, leaves) for child in specification[1]])
def bare_reraise():
    raise
for index, (specification, actions) in enumerate(cases):
    leaves = [ValueError("v"), TypeError("t"), OSError("o"), KeyError("k"), SystemExit(3)]
    original = build(specification, leaves)
    events = []
    try:
        try:
            raise original
        except* ValueError as matched:
            events.append(("v", describe(matched)))
            if actions[0] == 1: bare_reraise()
            if actions[0] == 2: raise matched
            if actions[0] == 3: raise RuntimeError("new-v")
            if actions[0] == 4:
                matched.__cause__ = LookupError("cause-v")
                raise
        except* TypeError as matched:
            events.append(("t", describe(matched)))
            gc.collect()
            if actions[1] == 1: bare_reraise()
            if actions[1] == 2: raise matched
            if actions[1] == 3: raise RuntimeError("new-t")
            if actions[1] == 4:
                matched.__context__ = LookupError("context-t")
                raise
        except* (OSError, KeyError) as matched:
            events.append(("other", describe(matched)))
            if actions[2] == 1: bare_reraise()
            if actions[2] == 2: raise matched
            if actions[2] == 3: raise RuntimeError("new-other")
            if actions[2] == 4:
                matched.__traceback__ = None
                raise
    except BaseException as result:
        print(index, events, describe(result))
    else:
        print(index, events, None)
'''
        self.check_source(source)


if __name__ == "__main__":
    unittest.main()
