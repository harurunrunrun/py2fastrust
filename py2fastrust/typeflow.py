"""Finite type sets shared by control-flow proofs and native lowering."""

from dataclasses import dataclass
from .native_types import alternatives,join_types


@dataclass(frozen=True)
class TypeSet:
    kinds: frozenset[object] = frozenset()
    maybe_unbound: bool = False
    unknown: bool = False

    @classmethod
    def from_kind(cls, kind):
        if kind=="unknown":return cls(frozenset({kind}),unknown=True)
        values=set()
        for value in alternatives(kind):
            values.update({"int","bool"} if value=="int_bool" else {value})
        return cls(frozenset(values))

    def join(self, other):
        return TypeSet(self.kinds | other.kinds, self.maybe_unbound or other.maybe_unbound,
                       self.unknown or other.unknown)

    @property
    def native_kind(self):
        if self.maybe_unbound or self.unknown:
            return None
        result=None
        from .native_types import kind_tag
        for kind in sorted(self.kinds,key=kind_tag):
            result=kind if result is None else join_types(result,kind)
            if result is None:return None
        return result
