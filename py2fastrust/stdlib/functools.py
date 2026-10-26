"""Function tools backed by the transpiler's native callable primitives."""

from _py2fastrust_functools import Placeholder, cache, lru_cache, partial, reduce

__all__ = [
    "update_wrapper", "wraps", "WRAPPER_ASSIGNMENTS", "WRAPPER_UPDATES",
    "total_ordering", "cache", "cmp_to_key", "lru_cache", "reduce", "partial",
    "partialmethod", "singledispatch", "singledispatchmethod", "cached_property",
    "Placeholder",
]

WRAPPER_ASSIGNMENTS = (
    "__module__", "__name__", "__qualname__", "__doc__", "__annotate__", "__type_params__",
)
WRAPPER_UPDATES = ("__dict__",)


def update_wrapper(wrapper, wrapped, assigned=WRAPPER_ASSIGNMENTS, updated=WRAPPER_UPDATES):
    for attribute in assigned:
        try:
            value = getattr(wrapped, attribute)
        except AttributeError:
            continue
        setattr(wrapper, attribute, value)
    for attribute in updated:
        getattr(wrapper, attribute).update(getattr(wrapped, attribute, {}))
    wrapper.__wrapped__ = wrapped
    return wrapper


def wraps(wrapped, assigned=WRAPPER_ASSIGNMENTS, updated=WRAPPER_UPDATES):
    return partial(update_wrapper, wrapped=wrapped, assigned=assigned, updated=updated)


def _comparison(root, operation):
    def method(self, other):
        result = getattr(type(self), root)(self, other)
        if result is NotImplemented:
            return NotImplemented
        if root == "__lt__":
            if operation == "__le__":
                return result or self == other
            if operation == "__gt__":
                return not result and self != other
            return not result
        if root == "__le__":
            if operation == "__lt__":
                return result and self != other
            if operation == "__gt__":
                return not result
            return not result or self == other
        if root == "__gt__":
            if operation == "__lt__":
                return not result and self != other
            if operation == "__le__":
                return not result
            return result or self == other
        if operation == "__lt__":
            return not result
        if operation == "__le__":
            return not result or self == other
        return result and self != other
    method.__name__ = operation
    return method


def total_ordering(cls):
    operations = ("__lt__", "__le__", "__gt__", "__ge__")
    roots = [name for name in operations if getattr(cls, name, None) is not getattr(object, name, None)]
    if not roots:
        raise ValueError("must define at least one ordering operation: < > <= >=")
    root = max(roots)
    for operation in operations:
        if operation not in roots:
            setattr(cls, operation, _comparison(root, operation))
    return cls


def cmp_to_key(comparison):
    class KeyWrapper:
        __hash__ = None
        def __init__(self, obj):
            self.obj = obj
        def __lt__(self, other):
            return comparison(self.obj, other.obj) < 0
        def __le__(self, other):
            return comparison(self.obj, other.obj) <= 0
        def __gt__(self, other):
            return comparison(self.obj, other.obj) > 0
        def __ge__(self, other):
            return comparison(self.obj, other.obj) >= 0
        def __eq__(self, other):
            return comparison(self.obj, other.obj) == 0
        def __ne__(self, other):
            return comparison(self.obj, other.obj) != 0
    return KeyWrapper


class cached_property:
    def __init__(self, func):
        self.func = func
        self.attrname = None
        self.__doc__ = getattr(func, "__doc__", None)
        self.__module__ = getattr(func, "__module__", None)

    def __set_name__(self, owner, name):
        if self.attrname is None:
            self.attrname = name
        elif name != self.attrname:
            raise TypeError("Cannot assign the same cached_property to two different names")

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        if self.attrname is None:
            raise TypeError("Cannot use cached_property instance without calling __set_name__ on it")
        try:
            namespace = instance.__dict__
        except AttributeError:
            raise TypeError("No '__dict__' attribute on instance to cache property")
        if self.attrname not in namespace:
            namespace[self.attrname] = self.func(instance)
        return namespace[self.attrname]


class partialmethod:
    def __init__(self, func, /, *args, **keywords):
        if not callable(func) and not hasattr(func, "__get__"):
            raise TypeError("the first argument must be callable or a descriptor")
        if args and args[-1] is Placeholder:
            raise TypeError("trailing Placeholders are not allowed")
        if any(value is Placeholder for value in keywords.values()):
            raise TypeError("Placeholder cannot be passed as a keyword argument")
        if isinstance(func, partialmethod):
            self.func = func.func
            combined = []
            position = 0
            for value in func.args:
                if value is Placeholder and position < len(args):
                    value = args[position]
                    position += 1
                combined.append(value)
            combined.extend(args[position:])
            self.args = tuple(combined)
            self.keywords = {**func.keywords, **keywords}
        else:
            self.func = func
            self.args = args
            self.keywords = keywords

    def __get__(self, obj, cls=None):
        get = getattr(self.func, "__get__", None)
        if get is not None:
            new_func = get(obj, cls)
            if new_func is not self.func:
                result = partial(new_func, *self.args, **self.keywords)
                try:
                    result.__self__ = new_func.__self__
                except AttributeError:
                    pass
                return result
        def method(receiver, /, *args, **keywords):
            bound = partial(self.func, receiver, *self.args, **self.keywords)
            return bound(*args, **keywords)
        method.__isabstractmethod__ = self.__isabstractmethod__
        method._partialmethod = self
        return method.__get__(obj, cls)

    @property
    def __isabstractmethod__(self):
        return getattr(self.func, "__isabstractmethod__", False)


class _RegistryProxy:
    def __init__(self, registry):
        self._registry = registry
    def __getitem__(self, key):
        return self._registry[key]
    def __setitem__(self, key, value):
        raise TypeError("mappingproxy object does not support item assignment")
    def __delitem__(self, key):
        raise TypeError("mappingproxy object does not support item deletion")
    def __iter__(self):
        return iter(self._registry)
    def __len__(self):
        return len(self._registry)
    def get(self, key, default=None):
        return self._registry.get(key, default)
    def keys(self):
        return self._registry.keys()
    def values(self):
        return self._registry.values()
    def items(self):
        return self._registry.items()


def singledispatch(func):
    registry = {object: func}
    dispatch_cache = {}

    def dispatch(cls):
        if cls in dispatch_cache:
            return dispatch_cache[cls]
        if cls in registry:
            implementation = registry[cls]
        else:
            implementation = None
            for base in cls.__mro__:
                if base is not object and base in registry:
                    implementation = registry[base]
                    break
            if implementation is None:
                chosen = None
                for candidate in registry:
                    if candidate is object or not issubclass(cls, candidate):
                        continue
                    if chosen is None or issubclass(candidate, chosen):
                        chosen = candidate
                    elif not issubclass(chosen, candidate):
                        raise RuntimeError("Ambiguous dispatch")
                implementation = registry[chosen] if chosen is not None else registry[object]
        dispatch_cache[cls] = implementation
        return implementation

    def register(cls, implementation=None):
        if implementation is None:
            if isinstance(cls, type):
                def decorator(function):
                    return register(cls, function)
                return decorator
            implementation = cls
            annotations = getattr(implementation, "__annotations__", {})
            cls = None
            for name in annotations:
                if name != "return":
                    cls = annotations[name]
                    break
            if isinstance(cls, str):
                cls = eval(cls, implementation.__globals__)
            if not isinstance(cls, type):
                raise TypeError("Invalid first argument to register(): use an explicit class or an annotated function")
        if not isinstance(cls, type):
            raise TypeError("Invalid first argument to register(): expected a class")
        registry[cls] = implementation
        dispatch_cache.clear()
        return implementation

    def wrapper(*args, **keywords):
        if not args:
            raise TypeError("singledispatch function requires at least one positional argument")
        return dispatch(type(args[0]))(*args, **keywords)

    wrapper.register = register
    wrapper.dispatch = dispatch
    wrapper.registry = _RegistryProxy(registry)
    wrapper._clear_cache = dispatch_cache.clear
    update_wrapper(wrapper, func)
    return wrapper


class singledispatchmethod:
    def __init__(self, func):
        if not callable(func) and not hasattr(func, "__get__"):
            raise TypeError("the first argument must be callable or a descriptor")
        self.dispatcher = singledispatch(func)
        self.func = func

    def register(self, cls, method=None):
        return self.dispatcher.register(cls, method)

    def __get__(self, obj, cls=None):
        def method(*args, **keywords):
            if not args:
                raise TypeError("singledispatchmethod requires at least one positional argument")
            implementation = self.dispatcher.dispatch(type(args[0]))
            return implementation.__get__(obj, cls)(*args, **keywords)
        method.__isabstractmethod__ = self.__isabstractmethod__
        method.register = self.register
        update_wrapper(method, self.func)
        return method

    @property
    def __isabstractmethod__(self):
        return getattr(self.func, "__isabstractmethod__", False)
