"""Cross-feature contracts shared by the merged runtime implementations."""

import textwrap
import unittest

import test_runtime


class CompatibilityWaveTests(unittest.TestCase):
    def compare_both(self, source):
        source=textwrap.dedent(source)
        test_runtime.RuntimeTests().run_source(source+"\nexec("+repr(source)+", {})\n")

    def test_inline_comprehension_keeps_frame_builtins_while_eval_recaptures(self):
        self.compare_both('''
            import builtins
            old = dict(vars(builtins))
            new = dict(vars(builtins))
            old['stamp'] = lambda: 'old'
            new['stamp'] = lambda: 'new'
            namespace = {'__builtins__': old}
            def switch(): namespace['__builtins__'] = new
            namespace['switch'] = switch
            exec("def f(): return [(switch(), stamp(), eval('stamp()'))[1:] for x in [1, 2]]", namespace)
            print(namespace['f']())
            print(namespace['f'].__builtins__ is old)
        ''')

    def test_namedtuple_inline_callers_and_base_views_keep_module_and_gc_roots(self):
        self.compare_both('''
            import builtins
            import gc
            from collections import namedtuple, OrderedDict
            class Key(str):
                __hash__ = str.__hash__
                def __eq__(self, other):
                    gc.collect()
                    return str.__eq__(self, other)
            namespace = {Key('__name__'): 'wave', '__builtins__': dict(vars(builtins))}
            exec("from collections import namedtuple, OrderedDict\\n"
                 "values = [namedtuple('Point', 'x')(i) for i in [1, 2]]\\n"
                 "mapping = OrderedDict((value.x, value) for value in values)\\n"
                 "mapping.move_to_end(1)\\n", namespace)
            values = namespace['values']
            mapping = namespace['mapping']
            print([type(value).__module__ for value in values])
            print(list(mapping), list(dict.keys(mapping)))
            print([(gc.collect(), value.x)[1] for value in dict.values(mapping)])
            print([type(value).__module__ for value in dict.values(mapping)])
        ''')
