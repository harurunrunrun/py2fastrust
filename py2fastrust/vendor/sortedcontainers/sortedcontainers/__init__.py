"""Sorted containers for native conversion (independent implementation).

This module provides SortedList, SortedSet and SortedDict with the observable
behavior of the sortedcontainers 2.4 public API for values without a key
function: ordering, positional access, bisection, error messages and repr.
Values are kept in sorted chunks with a Fenwick tree over chunk sizes, so
insertion, deletion and positional lookup take logarithmic time plus a chunk
move. Key functions are not part of this implementation; passing one is a
conversion-time argument error.
"""
from bisect import bisect_left, bisect_right, insort_right

_LOAD = 1000


class SortedList:
    """Sorted mutable sequence of comparable values."""

    def __init__(self, iterable=None):
        self._lists = []
        self._maxes = []
        self._tree = []
        self._len = 0
        if iterable is not None:
            values = list(iterable)
            values.sort()
            self._reset(values)

    # Internal structure -------------------------------------------------

    def _reset(self, values):
        self._lists = [values[start:start + _LOAD] for start in range(0, len(values), _LOAD)]
        self._maxes = [chunk[-1] for chunk in self._lists]
        self._len = len(values)
        self._rebuild()

    def _rebuild(self):
        tree = [len(chunk) for chunk in self._lists]
        size = len(tree)
        for index in range(size):
            parent = index | (index + 1)
            if parent < size:
                tree[parent] += tree[index]
        self._tree = tree

    def _grow(self, index, delta):
        tree = self._tree
        size = len(tree)
        while index < size:
            tree[index] += delta
            index |= index + 1

    def _prefix(self, index):
        total = 0
        tree = self._tree
        while index > 0:
            total += tree[index - 1]
            index &= index - 1
        return total

    def _locate(self, index):
        tree = self._tree
        size = len(tree)
        position = 0
        step = 1
        while step * 2 <= size:
            step *= 2
        while step:
            following = position + step
            if following <= size and tree[following - 1] <= index:
                index -= tree[following - 1]
                position = following
            step //= 2
        return position, index

    def _delete(self, position, offset):
        chunk = self._lists[position]
        del chunk[offset]
        self._len -= 1
        if chunk:
            self._maxes[position] = chunk[-1]
            self._grow(position, -1)
        else:
            del self._lists[position]
            del self._maxes[position]
            self._rebuild()

    def _normalize(self, index):
        if index < 0:
            index += self._len
        return index

    # Public API -----------------------------------------------------------

    def add(self, value):
        maxes = self._maxes
        if not maxes:
            self._lists.append([value])
            maxes.append(value)
            self._len = 1
            self._rebuild()
            return
        position = bisect_right(maxes, value)
        if position == len(maxes):
            position -= 1
            self._lists[position].append(value)
            maxes[position] = value
        else:
            insort_right(self._lists[position], value)
        self._len += 1
        chunk = self._lists[position]
        if len(chunk) > 2 * _LOAD:
            half = chunk[_LOAD:]
            del chunk[_LOAD:]
            maxes[position] = chunk[-1]
            self._lists.insert(position + 1, half)
            maxes.insert(position + 1, half[-1])
            self._rebuild()
        else:
            self._grow(position, 1)

    def update(self, iterable):
        values = list(iterable)
        values.sort()
        if not values:
            return
        if self._len:
            merged = [value for chunk in self._lists for value in chunk]
            merged.extend(values)
            merged.sort()
            self._reset(merged)
        else:
            self._reset(values)

    def clear(self):
        self._lists = []
        self._maxes = []
        self._tree = []
        self._len = 0

    def discard(self, value):
        maxes = self._maxes
        if not maxes:
            return
        position = bisect_left(maxes, value)
        if position == len(maxes):
            return
        chunk = self._lists[position]
        offset = bisect_left(chunk, value)
        if chunk[offset] == value:
            self._delete(position, offset)

    def remove(self, value):
        maxes = self._maxes
        if maxes:
            position = bisect_left(maxes, value)
            if position != len(maxes):
                chunk = self._lists[position]
                offset = bisect_left(chunk, value)
                if chunk[offset] == value:
                    self._delete(position, offset)
                    return
        raise ValueError(repr(value) + " not in list")

    def pop(self, index=-1):
        if not self._len:
            raise IndexError("pop index out of range")
        index = self._normalize(index)
        if index < 0 or index >= self._len:
            raise IndexError("list index out of range")
        position, offset = self._locate(index)
        value = self._lists[position][offset]
        self._delete(position, offset)
        return value

    def bisect_left(self, value):
        maxes = self._maxes
        if not maxes:
            return 0
        position = bisect_left(maxes, value)
        if position == len(maxes):
            return self._len
        return self._prefix(position) + bisect_left(self._lists[position], value)

    def bisect_right(self, value):
        maxes = self._maxes
        if not maxes:
            return 0
        position = bisect_right(maxes, value)
        if position == len(maxes):
            return self._len
        return self._prefix(position) + bisect_right(self._lists[position], value)

    def bisect(self, value):
        return self.bisect_right(value)

    def count(self, value):
        return self.bisect_right(value) - self.bisect_left(value)

    def index(self, value, start=None, stop=None):
        length = self._len
        if not length:
            raise ValueError(repr(value) + " is not in list")
        if start is None:
            start = 0
        if start < 0:
            start += length
        if start < 0:
            start = 0
        if stop is None:
            stop = length
        if stop < 0:
            stop += length
        if stop > length:
            stop = length
        if stop <= start:
            raise ValueError(repr(value) + " is not in list")
        maxes = self._maxes
        position = bisect_left(maxes, value)
        if position == len(maxes):
            raise ValueError(repr(value) + " is not in list")
        chunk = self._lists[position]
        offset = bisect_left(chunk, value)
        if chunk[offset] != value:
            raise ValueError(repr(value) + " is not in list")
        stop -= 1
        left = self._prefix(position) + offset
        if start <= left:
            if left <= stop:
                return left
        elif start <= self.bisect_right(value) - 1:
            return start
        raise ValueError(repr(value) + " is not in list")

    def irange(self, minimum=None, maximum=None, inclusive=(True, True), reverse=False):
        low = 0
        high = self._len
        if minimum is not None:
            low = self.bisect_left(minimum) if inclusive[0] else self.bisect_right(minimum)
        if maximum is not None:
            high = self.bisect_right(maximum) if inclusive[1] else self.bisect_left(maximum)
        return self._range(low, high, reverse)

    def islice(self, start=None, stop=None, reverse=False):
        length = self._len
        low = 0 if start is None else start
        high = length if stop is None else stop
        if low < 0:
            low += length
        if high < 0:
            high += length
        low = max(0, min(low, length))
        high = max(0, min(high, length))
        return self._range(low, high, reverse)

    def _range(self, low, high, reverse):
        if reverse:
            index = high - 1
            while index >= low:
                yield self[index]
                index -= 1
        else:
            index = low
            while index < high:
                yield self[index]
                index += 1

    def copy(self):
        return SortedList(self)

    def __len__(self):
        return self._len

    def __getitem__(self, index):
        index = self._normalize(index)
        if index < 0 or index >= self._len:
            raise IndexError("list index out of range")
        position, offset = self._locate(index)
        return self._lists[position][offset]

    def __delitem__(self, index):
        index = self._normalize(index)
        if index < 0 or index >= self._len:
            raise IndexError("list index out of range")
        position, offset = self._locate(index)
        self._delete(position, offset)

    def __contains__(self, value):
        maxes = self._maxes
        if not maxes:
            return False
        position = bisect_left(maxes, value)
        if position == len(maxes):
            return False
        chunk = self._lists[position]
        return chunk[bisect_left(chunk, value)] == value

    def __iter__(self):
        for chunk in self._lists:
            for value in chunk:
                yield value

    def __reversed__(self):
        position = len(self._lists) - 1
        while position >= 0:
            chunk = self._lists[position]
            offset = len(chunk) - 1
            while offset >= 0:
                yield chunk[offset]
                offset -= 1
            position -= 1

    def __repr__(self):
        return "SortedList(" + repr([value for chunk in self._lists for value in chunk]) + ")"

    def _sequence(self, other):
        return list(other) if isinstance(other, (SortedList, list, tuple)) else None

    def __eq__(self, other):
        values = self._sequence(other)
        if values is None:
            return NotImplemented
        return list(self) == values

    def __ne__(self, other):
        values = self._sequence(other)
        if values is None:
            return NotImplemented
        return list(self) != values

    def __lt__(self, other):
        values = self._sequence(other)
        if values is None:
            return NotImplemented
        return list(self) < values

    def __le__(self, other):
        values = self._sequence(other)
        if values is None:
            return NotImplemented
        return list(self) <= values

    def __gt__(self, other):
        values = self._sequence(other)
        if values is None:
            return NotImplemented
        return list(self) > values

    def __ge__(self, other):
        values = self._sequence(other)
        if values is None:
            return NotImplemented
        return list(self) >= values


class SortedSet:
    """Sorted mutable set of hashable comparable values."""

    def __init__(self, iterable=None):
        self._set = set()
        self._list = SortedList()
        if iterable is not None:
            self.update(iterable)

    def add(self, value):
        if value not in self._set:
            self._set.add(value)
            self._list.add(value)

    def update(self, iterable):
        fresh = [value for value in list(iterable) if value not in self._set]
        if fresh:
            self._set.update(fresh)
            self._list.update(set(fresh))
        return self

    def clear(self):
        self._set.clear()
        self._list.clear()

    def discard(self, value):
        if value in self._set:
            self._set.remove(value)
            self._list.remove(value)

    def remove(self, value):
        self._set.remove(value)
        self._list.remove(value)

    def pop(self, index=-1):
        value = self._list.pop(index)
        self._set.remove(value)
        return value

    def copy(self):
        return SortedSet(self._set)

    def count(self, value):
        return 1 if value in self._set else 0

    def bisect_left(self, value):
        return self._list.bisect_left(value)

    def bisect_right(self, value):
        return self._list.bisect_right(value)

    def bisect(self, value):
        return self._list.bisect_right(value)

    def index(self, value, start=None, stop=None):
        return self._list.index(value, start, stop)

    def irange(self, minimum=None, maximum=None, inclusive=(True, True), reverse=False):
        return self._list.irange(minimum, maximum, inclusive, reverse)

    def islice(self, start=None, stop=None, reverse=False):
        return self._list.islice(start, stop, reverse)

    def union(self, other):
        result = SortedSet(self._set)
        result.update(other)
        return result

    def intersection(self, other):
        values = set(other)
        return SortedSet([value for value in self._set if value in values])

    def difference(self, other):
        values = set(other)
        return SortedSet([value for value in self._set if value not in values])

    def symmetric_difference(self, other):
        return SortedSet(self._set ^ set(other))

    def isdisjoint(self, other):
        return self._set.isdisjoint(other)

    def issubset(self, other):
        return self._set.issubset(other)

    def issuperset(self, other):
        return self._set.issuperset(other)

    def __or__(self, other):
        return self.union(other)

    def __and__(self, other):
        return self.intersection(other)

    def __sub__(self, other):
        return self.difference(other)

    def __xor__(self, other):
        return self.symmetric_difference(other)

    def __len__(self):
        return len(self._set)

    def __contains__(self, value):
        return value in self._set

    def __getitem__(self, index):
        return self._list[index]

    def __delitem__(self, index):
        value = self._list[index]
        self._list.remove(value)
        self._set.remove(value)

    def __iter__(self):
        return iter(self._list)

    def __reversed__(self):
        return reversed(self._list)

    def _other_set(self, other):
        if isinstance(other, SortedSet):
            return other._set
        if isinstance(other, (set, frozenset)):
            return other
        return None

    def __eq__(self, other):
        values = self._other_set(other)
        if values is None:
            return NotImplemented
        return self._set == values

    def __ne__(self, other):
        values = self._other_set(other)
        if values is None:
            return NotImplemented
        return self._set != values

    def __le__(self, other):
        values = self._other_set(other)
        if values is None:
            return NotImplemented
        return self._set <= values

    def __lt__(self, other):
        values = self._other_set(other)
        if values is None:
            return NotImplemented
        return self._set < values

    def __ge__(self, other):
        values = self._other_set(other)
        if values is None:
            return NotImplemented
        return self._set >= values

    def __gt__(self, other):
        values = self._other_set(other)
        if values is None:
            return NotImplemented
        return self._set > values

    def __repr__(self):
        return "SortedSet(" + repr(list(self._list)) + ")"


class SortedDict:
    """Mapping whose keys iterate in sorted order."""

    def __init__(self, mapping=None):
        self._dict = {}
        self._list = SortedList()
        if mapping is not None:
            self.update(mapping)

    def update(self, mapping):
        pairs = list(mapping.items()) if isinstance(mapping, (dict, SortedDict)) else list(mapping)
        for key, value in pairs:
            self[key] = value

    def __setitem__(self, key, value):
        if key not in self._dict:
            self._list.add(key)
        self._dict[key] = value

    def __getitem__(self, key):
        return self._dict[key]

    def __delitem__(self, key):
        del self._dict[key]
        self._list.remove(key)

    def __contains__(self, key):
        return key in self._dict

    def __len__(self):
        return len(self._dict)

    def __iter__(self):
        return iter(self._list)

    def __reversed__(self):
        return reversed(self._list)

    def __eq__(self, other):
        if isinstance(other, SortedDict):
            return self._dict == other._dict
        if isinstance(other, dict):
            return self._dict == other
        return NotImplemented

    def __ne__(self, other):
        if isinstance(other, SortedDict):
            return self._dict != other._dict
        if isinstance(other, dict):
            return self._dict != other
        return NotImplemented

    def clear(self):
        self._dict.clear()
        self._list.clear()

    def copy(self):
        result = SortedDict()
        for key in self._list:
            result[key] = self._dict[key]
        return result

    def get(self, key, default=None):
        return self._dict.get(key, default)

    def setdefault(self, key, default=None):
        if key in self._dict:
            return self._dict[key]
        self[key] = default
        return default

    def pop(self, key, *default):
        if key in self._dict:
            self._list.remove(key)
            return self._dict.pop(key)
        if default:
            return default[0]
        # dict.pop raises KeyError(key) for the missing key.
        return self._dict.pop(key)

    def popitem(self, index=-1):
        if not self._dict:
            # dict.popitem raises KeyError('popitem(): dictionary is empty').
            return self._dict.popitem()
        key = self._list.pop(index)
        return key, self._dict.pop(key)

    def peekitem(self, index=-1):
        key = self._list[index]
        return key, self._dict[key]

    def index(self, key, start=None, stop=None):
        return self._list.index(key, start, stop)

    def bisect_left(self, key):
        return self._list.bisect_left(key)

    def bisect_right(self, key):
        return self._list.bisect_right(key)

    def bisect(self, key):
        return self._list.bisect_right(key)

    def irange(self, minimum=None, maximum=None, inclusive=(True, True), reverse=False):
        return self._list.irange(minimum, maximum, inclusive, reverse)

    def islice(self, start=None, stop=None, reverse=False):
        return self._list.islice(start, stop, reverse)

    def keys(self):
        return SortedKeysView(self)

    def values(self):
        return SortedValuesView(self)

    def items(self):
        return SortedItemsView(self)

    def __repr__(self):
        return "SortedDict({" + ", ".join(repr(key) + ": " + repr(self._dict[key]) for key in self._list) + "})"


class SortedKeysView:
    def __init__(self, mapping):
        self._mapping = mapping

    def __len__(self):
        return len(self._mapping._dict)

    def __getitem__(self, index):
        return self._mapping._list[index]

    def __iter__(self):
        return iter(self._mapping._list)

    def __reversed__(self):
        return reversed(self._mapping._list)

    def __contains__(self, key):
        return key in self._mapping._dict

    def index(self, key, start=None, stop=None):
        return self._mapping._list.index(key, start, stop)

    def count(self, key):
        return 1 if key in self._mapping._dict else 0

    def __repr__(self):
        return "SortedKeysView(" + repr(self._mapping) + ")"


class SortedValuesView:
    def __init__(self, mapping):
        self._mapping = mapping

    def __len__(self):
        return len(self._mapping._dict)

    def __getitem__(self, index):
        return self._mapping._dict[self._mapping._list[index]]

    def __iter__(self):
        for key in self._mapping._list:
            yield self._mapping._dict[key]

    def __reversed__(self):
        for key in reversed(self._mapping._list):
            yield self._mapping._dict[key]

    def __contains__(self, value):
        for key in self._mapping._list:
            if self._mapping._dict[key] == value:
                return True
        return False

    def __repr__(self):
        return "SortedValuesView(" + repr(self._mapping) + ")"


class SortedItemsView:
    def __init__(self, mapping):
        self._mapping = mapping

    def __len__(self):
        return len(self._mapping._dict)

    def __getitem__(self, index):
        key = self._mapping._list[index]
        return key, self._mapping._dict[key]

    def __iter__(self):
        for key in self._mapping._list:
            yield key, self._mapping._dict[key]

    def __reversed__(self):
        for key in reversed(self._mapping._list):
            yield key, self._mapping._dict[key]

    def __repr__(self):
        return "SortedItemsView(" + repr(self._mapping) + ")"
