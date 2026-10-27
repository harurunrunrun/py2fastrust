"""Finite type sets shared by control-flow proofs and native lowering."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TypeSet:
    kinds: frozenset[str] = frozenset()
    maybe_unbound: bool = False
    unknown: bool = False

    @classmethod
    def from_kind(cls, kind):
        return cls(frozenset({"int", "bool"}) if kind == "int_bool" else frozenset({kind}))

    def join(self, other):
        return TypeSet(self.kinds | other.kinds, self.maybe_unbound or other.maybe_unbound,
                       self.unknown or other.unknown)

    @property
    def native_kind(self):
        if self.maybe_unbound or self.unknown:
            return None
        if self.kinds == {"int", "bool"}:
            return "int_bool"
        return next(iter(self.kinds)) if len(self.kinds) == 1 else None
