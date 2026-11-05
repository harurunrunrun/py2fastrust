"""Explicit compiler-only stack for suspended abstract transfer operations."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Request:
    target: object
    arguments: tuple


def run(request, *, stats=None):
    """Keep abstract DFS order without a host call frame per source call."""
    stack = [request.target(*request.arguments)]
    answer = None
    if stats is not None:
        stats['maximum_frames'] = 1
        stats['transfers'] = 0
    try:
        while stack:
            try:
                child = stack[-1].send(answer)
            except StopIteration as completed:
                stack.pop()
                answer = completed.value
                continue
            if not isinstance(child, Request):
                raise TypeError('abstract transfer yielded an invalid request')
            stack.append(child.target(*child.arguments))
            answer = None
            if stats is not None:
                stats['maximum_frames'] = max(stats['maximum_frames'], len(stack))
                stats['transfers'] += 1
        return answer
    finally:
        # Close every suspended context manager even if one close fails. An
        # analysis abort must not leave a parent effect/iteration scope open.
        pending = None
        while stack:
            try:
                stack.pop().close()
            except BaseException as failure:
                if pending is None:
                    pending = failure
        if pending is not None:
            raise pending
