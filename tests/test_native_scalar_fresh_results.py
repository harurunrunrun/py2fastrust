"""Fresh-result evidence distinguishes construction from shared input returns."""
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions
from py2fastrust import native_scalar_constructor_data as constructors
from py2fastrust.native_scalar_fresh_results import Registry


SOURCE='''saved = []
class Number:
    def __init__(self, value):
        self.value = value
    def increase(self):
        self.value += 1
def build(value):
    return Number(value)
def forward(value):
    return build(value)
def factory(value):
    item = Number(0)
    item.value += value
    return item
def add(left, right):
    return Number(left.value + right.value)
def alias(value):
    return value
def publish(value):
    item = Number(value)
    saved.append(item)
    return item
def conditional(value, flag):
    if flag:
        return build(value)
    else:
        return forward(value + 1)
def sometimes_alias(value, flag):
    if flag:
        return Number(value.value)
    return value
def mutate_then_create(value):
    value.value += 3
    return Number(value.value)
def known_guard(left, right):
    if isinstance(right, Number):
        return Number(left.value + right.value)
    else:
        return Number(left.value + right)
n = int(input())
left = build(n)
left.increase()
right = forward(n + 1)
other = factory(n + 2)
published = publish(n + 3)
choice = conditional(n, bool(n % 2))
maybe_alias = sometimes_alias(left, bool(n % 2))
mutated = mutate_then_create(left)
print(add(left, right).value, alias(left).value, other.value, published.value,
      choice.value, maybe_alias.value, mutated.value, saved[0].value,
      known_guard(left, right).value)
'''


class NativeScalarFreshResultTests(unittest.TestCase):
    def test_existing_references_and_publications_are_not_fresh(self):
        for mode in ('i64','i128'):
            models=[]
            original=constructors.prepare
            def prepare(model):
                original(model)
                models.append(model)
            with patch.object(constructors,'prepare',prepare):
                result=transpile(SOURCE,TranspileOptions(integer=mode,license='none'))
            self.assertTrue(result.success,result.diagnostics)
            registry=Registry(models[-1])
            names={info.plan.node.name for info in registry.results.values()}
            self.assertTrue({'build','forward','factory','add','conditional','mutate_then_create','known_guard'}<=names)
            self.assertFalse({'alias','publish','sometimes_alias'}&names)
            factory=next(info for info in registry.results.values()if info.plan.node.name=='factory')
            self.assertEqual(factory.locals,{'item'})
            self.assertTrue(factory.fields)


if __name__=='__main__':
    unittest.main()
