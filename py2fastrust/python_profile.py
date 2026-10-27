"""Observe Python 3.14 bug-fix behavior using fixed, trusted probes.

The standalone runtime carries these choices into dynamic compilation as well.
Submitted source is never executed to determine its compatibility profile.
"""
import ast
from types import CodeType


TSTRING_PRESERVES_TRAILING_WHITESPACE = (
    ast.parse('t"{ x }"', mode="eval").body.values[0].str == " x "
)

_code = compile("def _pytors_profile(value: int): pass\n", "<pytors-profile>",
                "exec", dont_inherit=True)
ANN_QUALNAME_USES_OWNER = next(
    item.co_qualname for item in _code.co_consts
    if isinstance(item, CodeType) and item.co_name == "__annotate__"
) == "_pytors_profile.__annotate__"
del _code


class _ProfileExceptionGroup(ExceptionGroup):
    def __new__(cls, message, exceptions, marker):
        return ExceptionGroup.__new__(cls, message, exceptions)


EG_REPR_USES_EXCEPTIONS_TUPLE = repr(
    _ProfileExceptionGroup("pytors-profile", [ValueError()], None)
) == "_ProfileExceptionGroup('pytors-profile', (ValueError(),))"
del _ProfileExceptionGroup


def profile():
    return {
        "tstring_preserves_trailing_whitespace": TSTRING_PRESERVES_TRAILING_WHITESPACE,
        "annotation_qualname_uses_owner": ANN_QUALNAME_USES_OWNER,
        "exception_group_repr_checks_argument_count": EG_REPR_USES_EXCEPTIONS_TUPLE,
    }
