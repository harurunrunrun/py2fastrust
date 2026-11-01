"""Native fallible less-than sorting follows CPython's observable comparisons."""
from importlib.resources import files


def kernel(*,asynchronous=False):
    resources=files('py2fastrust').joinpath('runtime')
    source=resources.joinpath('native_cmp_sort.rs').read_text(encoding='utf-8')
    methods=resources.joinpath('native_cmp_sort_methods.rs').read_text(encoding='utf-8')
    substitutions={'@ASYNC@':'async 'if asynchronous else'',
                   '@SUFFIX@':'_async'if asynchronous else'',
                   '@BOUND@':('std::ops::AsyncFnMut'if asynchronous else'FnMut')+'(usize,usize)->Result<bool,E>',
                   '@AWAIT@':'.await'if asynchronous else'',
                   '@ASYNC_BLOCK@':'async 'if asynchronous else'(||',
                   '@BLOCK_END@':'.await'if asynchronous else')()'}
    for name,value in substitutions.items():methods=methods.replace(name,value)
    return source+'\n'+methods
