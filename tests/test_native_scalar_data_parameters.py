"""Read-only data views retain live alias observations and reject publication."""
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions
import test_native_source_state as state_tests
from py2fastrust import native_scalar_data_parameters as views


SOURCE='''class Number:
    def __init__(self, value):
        self.value = value
    def increase(self):
        self.value += 1
    def read(self):
        return self.value
def combine(left, right):
    if isinstance(right, Number):
        return Number(left.value + right.value)
    return Number(left.value + right)
def mutate_between(left, right):
    before = left.value
    right.increase()
    return before + left.value
def alias(value):
    return value
def capture(value):
    def inner():
        return value.value
    return inner()
left = Number(3)
right = combine(left, Number(4))
print(left.read(), right.read(), mutate_between(left, left), alias(left).value, capture(left))
'''


class NativeScalarDataParameterTests(unittest.TestCase):
    def test_formals_use_concrete_views_only_when_the_binding_never_escapes(self):
        models=[]
        original=views.prepare
        def prepare(model):
            original(model)
            models.append(model)
        with patch.object(views,'prepare',prepare):
            result=transpile(SOURCE,TranspileOptions(license='none'))
        self.assertTrue(result.success,result.diagnostics)
        model=models[-1]
        selected={(plan.node.name,name)for plan in model.plans
                  for name in plan.runtime_parameters
                  if views.parameter(model,plan,name)is not None}
        self.assertTrue({('read','self'),('combine','left'),('mutate_between','left')}<=selected)
        self.assertFalse({('increase','self'),('alias','value'),('capture','value'),('mutate_between','right')}&selected)

    def test_live_aliases_are_read_after_source_mutation(self):
        with patch.dict(state_tests.SOURCES,{'scalar_parameter_views':SOURCE}):
            state_tests.NativeSourceStateExecutionTests.exercise(self,'scalar_parameter_views',('',))


if __name__=='__main__':unittest.main()
