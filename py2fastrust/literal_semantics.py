"""Immutable literal meaning shared by direct Rust lowering implementations."""
import ast
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class IntegerPolicy:
    bits: int

    def __post_init__(self):
        if self.bits not in {0,64,128}:
            raise ValueError("integer width must be 0, 64, or 128")

    def normalize(self,value):
        value=int(value)
        if not self.bits:return value
        value%=1<<self.bits
        return value-(1<<self.bits) if value>=(1<<(self.bits-1)) else value

    def rust_literal(self,value,quote):
        value=self.normalize(value)
        if self.bits:
            return "NativeInt::MIN" if value==-(1<<(self.bits-1)) else f"({value}_i128 as NativeInt)"
        if -(1<<127)<value<(1<<127):return f"Int::from_i128({value}_i128)"
        if value==-(1<<127):return "Int::from_i128(i128::MIN)"
        return f"Int::parse({quote(str(value))},10).unwrap()"


_POLICIES={bits:IntegerPolicy(bits)for bits in (0,64,128)}


def integer_policy(bits):
    return _POLICIES[bits]


def float_literal(value):
    return ("f64::NAN" if math.isnan(value) else
            "f64::INFINITY" if value==math.inf else
            "f64::NEG_INFINITY" if value==-math.inf else repr(value)+"_f64")


@dataclass(frozen=True)
class Literal:
    kind: str
    value: object

    @classmethod
    def from_ast(cls,node):
        if not isinstance(node,ast.Constant):return None
        return cls.from_value(node.value)

    @classmethod
    def from_value(cls,value):
        kind={int:"int",bool:"bool",float:"float",str:"str",bytes:"bytes",type(None):"none"}.get(type(value))
        if kind is None:return None
        if kind=="str" and any(0xD800<=ord(character)<=0xDFFF for character in value):return None
        return cls(kind,value)

    def rust_atom(self,integer_literal,quote):
        if self.kind=="int":return integer_literal(self.value)
        if self.kind=="bool":return str(self.value).lower()
        if self.kind=="float":return float_literal(self.value)
        if self.kind=="str":return f"String::from({quote(self.value)})"
        if self.kind=="bytes":return "vec!["+",".join(f"{byte}_u8"for byte in self.value)+"]"
        if self.kind=="none":return "()"
        raise ValueError("unsupported literal kind")
