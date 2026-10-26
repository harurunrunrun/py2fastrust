"""Collections implemented in Python and compiled into the standalone runtime.

Copyright (c) 2026 py2fastrust contributors. MIT License.
"""

import sys as _sys

__all__ = ["deque", "defaultdict", "Counter", "namedtuple", "OrderedDict"]


def _index(value):
    if isinstance(value, int):
        return int(value)
    if hasattr(value, "__index__"):
        result = value.__index__()
        if isinstance(result, int):
            return int(result)
        raise TypeError("__index__ returned non-int")
    raise TypeError("an integer is required")


def _deque_size(value):
    value = _index(value)
    if value > 9223372036854775807 or value < -9223372036854775808:
        raise OverflowError("Python int too large to convert to C ssize_t")
    return value


class _DequeIterator:
    def __init__(self, queue, reverse=False):
        self.queue = queue
        self.version = queue._version
        self.reverse = reverse
        self.index = len(queue) - 1 if reverse else 0

    def __iter__(self):
        return self

    def __next__(self):
        if self.version != self.queue._version:
            raise RuntimeError("deque mutated during iteration")
        if self.index < 0 or self.index >= len(self.queue):
            raise StopIteration
        value = self.queue[self.index]
        self.index += -1 if self.reverse else 1
        return value


class deque:
    def __init__(self, iterable=(), maxlen=None):
        if maxlen is not None:
            if not isinstance(maxlen, int):
                raise TypeError("an integer is required")
            maxlen = _deque_size(maxlen)
            if maxlen < 0:
                raise ValueError("maxlen must be non-negative")
        self._maxlen = maxlen
        self._data = [None] * 8
        self._head = 0
        self._size = 0
        self._version = 0
        self._repr_running = False
        self.extend(iterable)

    @property
    def maxlen(self):
        return self._maxlen

    def __len__(self):
        return self._size

    def __iter__(self):
        return _DequeIterator(self)

    def __reversed__(self):
        return _DequeIterator(self, True)

    def _grow(self):
        if self._size == len(self._data):
            self._data = list(self) + [None] * len(self._data)
            self._head = 0

    def _position(self, index):
        index = _index(index)
        if index < 0:
            index += self._size
        if index < 0 or index >= self._size:
            raise IndexError("deque index out of range")
        return (self._head + index) % len(self._data)

    def __getitem__(self, index):
        return self._data[self._position(index)]

    def __setitem__(self, index, value):
        self._data[self._position(index)] = value

    def __delitem__(self, index):
        index = _index(index)
        self._position(index)
        values = list(self)
        del values[index]
        self.clear()
        self.extend(values)

    def append(self, value):
        if self._maxlen == 0:
            self._version += 1
            return
        if self._maxlen is not None and self._size == self._maxlen:
            self.popleft()
        self._grow()
        self._data[(self._head + self._size) % len(self._data)] = value
        self._size += 1
        self._version += 1

    def appendleft(self, value):
        if self._maxlen == 0:
            self._version += 1
            return
        if self._maxlen is not None and self._size == self._maxlen:
            self.pop()
        self._grow()
        self._head = (self._head - 1) % len(self._data)
        self._data[self._head] = value
        self._size += 1
        self._version += 1

    def pop(self):
        if not self._size:
            raise IndexError("pop from an empty deque")
        self._size -= 1
        index = (self._head + self._size) % len(self._data)
        value = self._data[index]
        self._data[index] = None
        self._version += 1
        return value

    def popleft(self):
        if not self._size:
            raise IndexError("pop from an empty deque")
        value = self._data[self._head]
        self._data[self._head] = None
        self._head = (self._head + 1) % len(self._data)
        self._size -= 1
        self._version += 1
        return value

    def clear(self):
        if not self._size:
            return
        self._data = [None] * 8
        self._head = 0
        self._size = 0
        self._version += 1

    def extend(self, iterable):
        if iterable is self:
            iterable = list(self)
        if self._maxlen == 0:
            for value in iterable:
                pass
            return
        for value in iterable:
            self.append(value)

    def extendleft(self, iterable):
        if iterable is self:
            iterable = list(self)
        if self._maxlen == 0:
            for value in iterable:
                pass
            return
        for value in iterable:
            self.appendleft(value)

    def rotate(self, n=1):
        n = _deque_size(n)
        if self._size > 1:
            self._version += 1
            n %= self._size
            if n > self._size // 2:
                n -= self._size
            while n > 0:
                self.appendleft(self.pop())
                n -= 1
            while n < 0:
                self.append(self.popleft())
                n += 1

    def reverse(self):
        for i in range(self._size // 2):
            self[i], self[-i-1] = self[-i-1], self[i]

    def count(self, value):
        return sum(item is value or item == value for item in self)

    def index(self, value, start=0, stop=None):
        start = _index(start)
        if start < 0:
            start = max(0, self._size + start)
        if stop is None:
            stop = self._size
        else:
            stop = _index(stop)
            if stop < 0:
                stop += self._size
        version = self._version
        for i in range(start, min(stop, self._size)):
            equal = self[i] is value or self[i] == value
            if equal:
                return i
            if version != self._version:
                raise RuntimeError("deque mutated during iteration")
        raise ValueError("value is not in deque")

    def insert(self, index, value):
        index = _deque_size(index)
        if self._maxlen is not None and self._size == self._maxlen:
            raise IndexError("deque already at its maximum size")
        values = list(self)
        values.insert(index, value)
        self.clear()
        self.extend(values)

    def remove(self, value):
        version = self._version
        for index in range(self._size):
            equal = self[index] is value or self[index] == value
            if version != self._version:
                raise IndexError("deque mutated during iteration")
            if equal:
                del self[index]
                return
        raise ValueError("value is not in deque")

    def copy(self):
        return type(self)(self, self._maxlen)

    __copy__ = copy

    def __contains__(self, value):
        return any(item is value or item == value for item in self)

    def __repr__(self):
        if self._repr_running:
            return "[...]"
        self._repr_running = True
        try:
            suffix = "" if self._maxlen is None else ", maxlen=" + str(self._maxlen)
            return type(self).__name__ + "(" + repr(list(self)) + suffix + ")"
        finally:
            self._repr_running = False

    def __eq__(self, other):
        if not isinstance(other, deque):
            return NotImplemented
        return list(self) == list(other)

    def __lt__(self, other):
        if not isinstance(other, deque):
            return NotImplemented
        return list(self) < list(other)

    def __le__(self, other):
        return self == other or self < other

    def __gt__(self, other):
        return other < self

    def __ge__(self, other):
        return self == other or other < self

    def __add__(self, other):
        if not isinstance(other, deque):
            return NotImplemented
        result = self.copy()
        result.extend(other)
        return result

    def __iadd__(self, other):
        self.extend(other)
        return self

    def __mul__(self, count):
        return type(self)(list(self) * count, self._maxlen)

    __rmul__ = __mul__

    def __imul__(self, count):
        values = list(self) * count
        self.clear()
        self.extend(values)
        return self


class _Mapping(dict):
    def __init__(self, *args, **kwargs):
        if not hasattr(self, "_data"):
            self._data = {}
            self._version = 0
            self._repr_running = False
        self.update(*args, **kwargs)

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        if key not in self._data:
            self._version += 1
        self._data[key] = value

    def __delitem__(self, key):
        del self._data[key]
        self._version += 1

    def __iter__(self):
        return _MappingIterator(self)

    def __reversed__(self):
        return _MappingIterator(self, reverse=True)

    def __len__(self):
        return len(self._data)

    def __contains__(self, key):
        return key in self._data

    def keys(self):
        return _OrderedKeysView(self) if isinstance(self, OrderedDict) else _DictKeysView(self)

    def values(self):
        return _OrderedValuesView(self) if isinstance(self, OrderedDict) else _DictValuesView(self)

    def items(self):
        return _OrderedItemsView(self) if isinstance(self, OrderedDict) else _DictItemsView(self)

    def get(self, key, default=None):
        return self._data.get(key, default)

    def pop(self, key, *default):
        if len(default) > 1:
            raise TypeError("pop expected at most 2 arguments")
        if key in self._data:
            value = self._data[key]
            del self[key]
            return value
        if default:
            return default[0]
        raise KeyError(key)

    def popitem(self):
        if not self._data:
            raise KeyError("popitem(): dictionary is empty")
        key = list(self._data)[-1]
        return key, self.pop(key)

    def clear(self):
        if self._data:
            self._data.clear()
            self._version += 1

    def setdefault(self, key, default=None):
        if key not in self._data:
            self[key] = default
        return self._data[key]

    def update(self, *args, **kwargs):
        if len(args) > 1:
            raise TypeError("update expected at most 1 argument")
        if args:
            source = args[0]
            if hasattr(source, "keys"):
                for key in source.keys():
                    self[key] = source[key]
            else:
                for key, value in source:
                    self[key] = value
        for key, value in kwargs.items():
            self[key] = value

    @classmethod
    def fromkeys(cls, iterable, value=None):
        result = cls()
        for key in iterable:
            result[key] = value
        return result

    def copy(self):
        return type(self)(self._data)

    __copy__ = copy

    def __eq__(self, other):
        if isinstance(other, _Mapping):
            other = other._data
        return self._data == other

    def __repr__(self):
        return repr(self._data)


class defaultdict(_Mapping):
    def __init__(self, default_factory=None, /, *args, **kwargs):
        if default_factory is not None and not callable(default_factory):
            raise TypeError("first argument must be callable or None")
        self.default_factory = default_factory
        _Mapping.__init__(self, *args, **kwargs)

    def __missing__(self, key):
        if self.default_factory is None:
            raise KeyError(key)
        value = self.default_factory()
        self[key] = value
        return value

    def __getitem__(self, key):
        if key in self._data:
            return self._data[key]
        return self.__missing__(key)

    def copy(self):
        return type(self)(self.default_factory, self._data)

    __copy__ = copy

    def __repr__(self):
        prefix = type(self).__name__ + "(" + repr(self.default_factory) + ", "
        if self._repr_running:
            return prefix + "{...})"
        self._repr_running = True
        try:
            return prefix + repr(self._data) + ")"
        finally:
            self._repr_running = False

    def __or__(self, other):
        if not isinstance(other, dict):
            return NotImplemented
        result = self.copy()
        result.update(other)
        return result

    def __ror__(self, other):
        if not isinstance(other, dict):
            return NotImplemented
        result = type(self)(self.default_factory, other)
        result.update(self)
        return result

    def __ior__(self, other):
        self.update(other)
        return self


class Counter(_Mapping):
    def __init__(self, iterable=None, /, **kwargs):
        if not hasattr(self, "_data"):
            self._data = {}
            self._version = 0
            self._repr_running = False
        self.update(iterable, **kwargs)

    def __missing__(self, key):
        return 0

    def __getitem__(self, key):
        return self._data.get(key, 0)

    def update(self, iterable=None, /, **kwargs):
        if iterable is not None:
            if hasattr(iterable, "keys"):
                if not self:
                    _Mapping.update(self, iterable)
                else:
                    for key in iterable.keys():
                        self[key] = iterable[key] + self.get(key, 0)
            else:
                for key in iterable:
                    self[key] = self.get(key, 0) + 1
        if kwargs:
            self.update(kwargs)

    def subtract(self, iterable=None, /, **kwargs):
        if iterable is not None:
            if hasattr(iterable, "keys"):
                for key in iterable.keys():
                    self[key] = self.get(key, 0) - iterable[key]
            else:
                for key in iterable:
                    self[key] = self.get(key, 0) - 1
        for key, value in kwargs.items():
            self[key] = self.get(key, 0) - value

    def total(self):
        return sum(self._data.values())

    def most_common(self, n=None):
        values = sorted(self._data.items(), key=lambda item: item[1], reverse=True)
        return values if n is None else values[:max(n, 0)]

    def elements(self):
        def repeat_elements(items):
            for key, count in items:
                for _ in range(_deque_size(count)):
                    yield key
        return repeat_elements(iter(self.items()))

    @classmethod
    def fromkeys(cls, iterable, value=None):
        raise NotImplementedError("Counter.fromkeys() is undefined")

    def __repr__(self):
        if not self._data:
            return type(self).__name__ + "()"
        try:
            counts = dict(self.most_common())
        except TypeError:
            counts = dict(self)
        return type(self).__name__ + "(" + repr(counts) + ")"

    def __eq__(self, other):
        if not isinstance(other, Counter):
            if isinstance(other, dict):
                return _Mapping.__eq__(self, other)
            return NotImplemented
        return all(self[key] == other[key] for key in list(self) + list(other))

    def __le__(self, other):
        if not isinstance(other, Counter):
            return NotImplemented
        return all(self[key] <= other[key] for key in list(self) + list(other))

    def __lt__(self, other):
        return self <= other and self != other

    def __ge__(self, other):
        return other <= self

    def __gt__(self, other):
        return other < self

    def _combine(self, other, operation):
        if not isinstance(other, Counter):
            return NotImplemented
        result = Counter()
        seen = set()
        for key in list(self) + list(other):
            if key in seen:
                continue
            seen.add(key)
            a, b = self[key], other[key]
            if operation == "+":
                value = a + b
            elif operation == "-":
                value = a - b
            elif operation == "&":
                value = min(a, b)
            else:
                value = max(a, b)
            if value > 0:
                result[key] = value
        return result

    def __add__(self, other):
        return self._combine(other, "+")

    def __sub__(self, other):
        return self._combine(other, "-")

    def __and__(self, other):
        return self._combine(other, "&")

    def __or__(self, other):
        return self._combine(other, "|")

    def __pos__(self):
        return self + Counter()

    def __neg__(self):
        return Counter() - self

    def _inplace(self, other, operation):
        if operation == "&":
            for key in self:
                self[key] = min(self[key], other[key])
        else:
            for key, value in other.items():
                if operation == "+":
                    self[key] = self[key] + value
                elif operation == "-":
                    self[key] = self[key] - value
                elif value > self[key]:
                    self[key] = value
        for key in list(self):
            if self[key] <= 0:
                del self[key]
        return self

    def __iadd__(self, other):
        return self._inplace(other, "+")

    def __isub__(self, other):
        return self._inplace(other, "-")

    def __iand__(self, other):
        return self._inplace(other, "&")

    def __ior__(self, other):
        return self._inplace(other, "|")


class OrderedDict(_Mapping):
    def move_to_end(self, key, last=True):
        keys = list(self._data)
        if key not in self._data:
            raise KeyError(key)
        boundary = keys[-1 if last else 0]
        if boundary is key or boundary == key:
            return
        value = self._data.pop(key)
        if last:
            self._data[key] = value
        else:
            pairs = list(self._data.items())
            self._data.clear()
            self._data[key] = value
            for old_key, old_value in pairs:
                self._data[old_key] = old_value
        self._version += 1

    def popitem(self, last=True):
        if not self._data:
            raise KeyError("dictionary is empty")
        key = list(self._data)[-1 if last else 0]
        value = self.pop(key)
        return key, value

    def __eq__(self, other):
        if isinstance(other, OrderedDict):
            return list(self.items()) == list(other.items())
        return _Mapping.__eq__(self, other)

    def __repr__(self):
        if not self._data:
            return type(self).__name__ + "()"
        if self._repr_running:
            return "..."
        self._repr_running = True
        try:
            return type(self).__name__ + "(" + repr(self._data) + ")"
        finally:
            self._repr_running = False

    def __or__(self, other):
        if not isinstance(other, dict):
            return NotImplemented
        result = self.copy()
        result.update(other)
        return result

    def __ror__(self, other):
        if not isinstance(other, dict):
            return NotImplemented
        result = type(self)(other)
        result.update(self)
        return result

    def __ior__(self, other):
        self.update(other)
        return self

    @classmethod
    def fromkeys(cls, iterable, value=None):
        result = cls()
        for key in iterable:
            result[key] = value
        return result


class _MappingIterator:
    def __init__(self, owner, kind="keys", reverse=False):
        self.owner = owner
        self.kind = kind
        self.version = owner._version
        self.keys = list(owner._data)
        if reverse:
            self.keys.reverse()
        self.index = 0
        self.exhausted = False

    def __iter__(self):
        return self

    def __next__(self):
        if self.exhausted:
            raise StopIteration
        if self.version != self.owner._version:
            message = "OrderedDict mutated during iteration" if isinstance(self.owner, OrderedDict) else "dictionary changed size during iteration"
            raise RuntimeError(message)
        if self.index == len(self.keys):
            self.exhausted = True
            raise StopIteration
        key = self.keys[self.index]
        self.index += 1
        if self.kind == "values":
            return self.owner[key]
        if self.kind == "items":
            return key, self.owner[key]
        return key


class _MappingProxy:
    def __init__(self, owner):
        self._owner = owner

    def __getitem__(self, key):
        return self._owner[key]

    def __contains__(self, key):
        return key in self._owner

    def __len__(self):
        return len(self._owner)

    def __iter__(self):
        return iter(self._owner)

    def __reversed__(self):
        return reversed(self._owner)

    def get(self, key, default=None):
        return self._owner.get(key, default)

    def keys(self):
        return self._owner.keys()

    def values(self):
        return self._owner.values()

    def items(self):
        return self._owner.items()

    def copy(self):
        return self._owner.copy()

    def __eq__(self, other):
        if isinstance(other, _MappingProxy):
            other = other._owner
        return self._owner == other

    def __or__(self, other):
        if isinstance(other, _MappingProxy):
            other = other._owner
        return self._owner | other

    def __ror__(self, other):
        if isinstance(other, _MappingProxy):
            other = other._owner
        return other | self._owner

    def __repr__(self):
        return "mappingproxy(" + repr(self._owner) + ")"


class _MappingView:
    _kind = "keys"
    _name = "dict_keys"

    def __init__(self, owner):
        self._owner = owner

    @property
    def mapping(self):
        return _MappingProxy(self._owner)

    def __len__(self):
        return len(self._owner)

    def __iter__(self):
        return _MappingIterator(self._owner, self._kind)

    def __reversed__(self):
        return _MappingIterator(self._owner, self._kind, True)

    def __contains__(self, item):
        if self._kind == "keys":
            return item in self._owner
        if self._kind == "values":
            return any(value is item or value == item for value in self)
        return (isinstance(item, tuple) and len(item) == 2 and item[0] in self._owner
                and (self._owner[item[0]] is item[1] or self._owner[item[0]] == item[1]))

    def __repr__(self):
        return self._name + "(" + repr(list(self)) + ")"


class _SetView(_MappingView):
    def isdisjoint(self, other):
        return not any(item in self for item in other)

    def __eq__(self, other):
        if not isinstance(other, _SET_VIEW_TYPES):
            return NotImplemented
        return len(self) == len(other) and all(item in other for item in self)

    def __le__(self, other):
        if not isinstance(other, _SET_VIEW_TYPES):
            return NotImplemented
        return len(self) <= len(other) and all(item in other for item in self)

    def __lt__(self, other):
        if not isinstance(other, _SET_VIEW_TYPES):
            return NotImplemented
        return len(self) < len(other) and all(item in other for item in self)

    def __ge__(self, other):
        if not isinstance(other, _SET_VIEW_TYPES):
            return NotImplemented
        return len(self) >= len(other) and all(item in self for item in other)

    def __gt__(self, other):
        if not isinstance(other, _SET_VIEW_TYPES):
            return NotImplemented
        return len(self) > len(other) and all(item in self for item in other)

    def __and__(self, other):
        result = set()
        for item in other:
            if item in self:
                result.add(item)
        return result

    __rand__ = __and__

    def __or__(self, other):
        return set(self) | set(other)

    __ror__ = __or__

    def __sub__(self, other):
        return set(self) - set(other)

    def __rsub__(self, other):
        return set(other) - set(self)

    def __xor__(self, other):
        if isinstance(other, _SetView):
            result = set()
            for item in self:
                if item not in other:
                    result.add(item)
            for item in other:
                if item not in self:
                    result.add(item)
            return result
        return set(self) ^ set(other)

    __rxor__ = __xor__


_SET_VIEW_TYPES = (_SetView, set, frozenset, type({}.keys()), type({}.items()))


class _DictKeysView(_SetView):
    pass


class _DictValuesView(_MappingView):
    _kind = "values"
    _name = "dict_values"


class _DictItemsView(_SetView):
    _kind = "items"
    _name = "dict_items"


class _OrderedKeysView(_DictKeysView):
    _name = "odict_keys"


class _OrderedValuesView(_DictValuesView):
    _name = "odict_values"


class _OrderedItemsView(_DictItemsView):
    _name = "odict_items"


for _view_class in (_DictKeysView, _DictValuesView, _DictItemsView, _OrderedKeysView, _OrderedValuesView, _OrderedItemsView):
    _view_class.__name__ = _view_class._name
    _view_class.__qualname__ = _view_class._name
    _view_class.__module__ = "builtins"
_MappingProxy.__name__ = "mappingproxy"
_MappingProxy.__qualname__ = "mappingproxy"
_MappingProxy.__module__ = "builtins"


def namedtuple(typename, field_names, *, rename=False, defaults=None, module=None):
    keywords = {"False", "None", "True", "and", "as", "assert", "async", "await", "break", "class", "continue", "def", "del", "elif", "else", "except", "finally", "for", "from", "global", "if", "import", "in", "is", "lambda", "nonlocal", "not", "or", "pass", "raise", "return", "try", "while", "with", "yield"}
    def valid(name):
        return (isinstance(name, str) and bool(name) and (name[0] == "_" or name[0].isalpha())
                and all(char == "_" or char.isalnum() for char in name) and name not in keywords)
    typename = str(typename)
    if not valid(typename):
        raise ValueError("Type names and field names must be valid identifiers")
    fields = field_names.replace(",", " ").split() if isinstance(field_names, str) else list(field_names)
    fields = [str(field) for field in fields]
    seen = set()
    for index, field in enumerate(fields):
        if not valid(field) or field.startswith("_") or field in seen:
            if not rename:
                raise ValueError("Invalid or duplicate field name: " + field)
            fields[index] = "_" + str(index)
        seen.add(fields[index])
    fields = tuple(fields)
    default_values = () if defaults is None else tuple(defaults)
    if len(default_values) > len(fields):
        raise TypeError("Got more default values than field names")
    field_defaults = dict(zip(fields[len(fields)-len(default_values):], default_values)) if default_values else {}
    parameters = ", ".join(fields)
    arguments = "(" + parameters + ("," if len(fields) == 1 else "") + ")"
    signature = "_cls" + (", " + parameters if fields else "")
    new = eval("lambda " + signature + ": _tuple_new(_cls, " + arguments + ")",
               {"_tuple_new": tuple.__new__, "__name__": "namedtuple_" + typename})
    new.__name__ = "__new__"
    new.__qualname__ = typename + ".__new__"
    new.__defaults__ = None if defaults is None else default_values
    new.__doc__ = "Create new instance of " + typename + "(" + parameters + ("," if len(fields) == 1 else "") + ")"

    class NamedTuple(tuple):
        __slots__ = ()
        __new__ = new
        _fields = fields
        _field_defaults = field_defaults
        __match_args__ = fields

        def __repr__(self):
            values = [field + "=" + repr(value) for field, value in zip(fields, self)]
            return type(self).__name__ + "(" + ", ".join(values) + ")"

        def __eq__(self, other):
            if not isinstance(other, tuple):
                return NotImplemented
            return tuple(self) == tuple(other)

        def __lt__(self, other):
            if not isinstance(other, tuple):
                return NotImplemented
            return tuple(self) < tuple(other)

        def __le__(self, other):
            if not isinstance(other, tuple):
                return NotImplemented
            return tuple(self) <= tuple(other)

        def __gt__(self, other):
            if not isinstance(other, tuple):
                return NotImplemented
            return tuple(self) > tuple(other)

        def __ge__(self, other):
            if not isinstance(other, tuple):
                return NotImplemented
            return tuple(self) >= tuple(other)

        def __hash__(self):
            return hash(tuple(self))

        def __add__(self, other):
            return tuple(self) + other

        def __mul__(self, count):
            return tuple(self) * count

        __rmul__ = __mul__

        def count(self, value):
            return tuple(self).count(value)

        def index(self, value, *bounds):
            return tuple(self).index(value, *bounds)

        def _asdict(self):
            return dict(zip(fields, self))

        def _replace(self, **kwargs):
            values = [kwargs.pop(field) if field in kwargs else value for field, value in zip(fields, self)]
            if kwargs:
                raise TypeError("unexpected field names")
            return self._make(values)

        __replace__ = _replace

        def __getnewargs__(self):
            return tuple(self)

        @classmethod
        def _make(cls, iterable):
            result = tuple.__new__(cls, iterable)
            if len(result) != len(fields):
                raise TypeError("Expected a different number of arguments")
            return result

    for index, field in enumerate(fields):
        setattr(NamedTuple, field, property(lambda self, index=index: self[index]))
    NamedTuple.__name__ = typename
    NamedTuple.__qualname__ = typename
    if module is None:
        try:
            module = _sys._getframemodulename(1) or "__main__"
        except AttributeError:
            module = "__main__"
    NamedTuple.__module__ = module
    NamedTuple.__doc__ = typename + "(" + parameters + ("," if len(fields) == 1 else "") + ")"
    return NamedTuple
