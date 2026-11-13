"""Pool only controlled diagnostic filename references in retained Rust code."""
import re


# Minted names are ASCII. Conservatively exclude Unicode-adjacent names too,
# rather than matching a fragment of a valid Unicode Rust identifier.
_IDENTIFIER=re.compile(r"(?<![A-Za-z_0-9'#\x80-\U0010ffff])[A-Za-z_][A-Za-z_0-9]*(?![A-Za-z_0-9\x80-\U0010ffff])")


class SourceFilenames:
    def __init__(self):
        self.entries={}

    def reference(self,filename):
        from .native import _string
        previous=self.entries.get(filename)
        if previous is not None:return previous[0]
        literal=_string(filename)
        symbol='PYTORS_FILE_'+str(len(self.entries))
        # A literal no longer than its reference cannot benefit from pooling.
        if len(literal.encode())<=len(symbol):return literal
        self.entries[filename]=symbol,literal
        return symbol

    def finish(self,source):
        if not self.entries:return source
        from .aot import rust_mask
        known={symbol:literal for symbol,literal in self.entries.values()}
        counts={symbol:0 for symbol in known}
        uses=[]
        for match in _IDENTIFIER.finditer(rust_mask(source)):
            symbol=match.group()
            if symbol in known:
                counts[symbol]+=1
                uses.append((match.start(),match.end(),symbol))
        replacements={};definitions=[]
        for symbol,literal in self.entries.values():
            count=counts[symbol]
            if not count:continue
            definition=f"const {symbol}:&'static str={literal};"
            inline_bytes=count*len(literal.encode())
            pooled_bytes=count*len(symbol)+len(definition.encode())+1
            if pooled_bytes<inline_bytes:
                definitions.append(definition)
                replacements[symbol]=symbol
            else:replacements[symbol]=literal
        if not uses:return source
        pieces=[];cursor=0
        for start,end,symbol in uses:
            pieces.extend((source[cursor:start],replacements[symbol]));cursor=end
        pieces.append(source[cursor:])
        result=''.join(pieces)
        # Appending module items preserves any leading crate inner attributes.
        if definitions:
            definitions='\n'.join(definitions)
            result+=(definitions+'\n'if result.endswith('\n')else'\n'+definitions)
        return result


def reference(model,filename):
    pool=getattr(model,'source_filenames',None)
    if pool is None:pool=model.source_filenames=SourceFilenames()
    return pool.reference(filename)


def finish(model,source):
    pool=getattr(model,'source_filenames',None)
    return source if pool is None else pool.finish(source)
