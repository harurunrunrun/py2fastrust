"""Interim proof for compile-unit frozen-constant insertion histories.

CP's constant cache spans nested code and can retain a constant from code later
removed as unreachable. Do not infer its origin from final bytecode positions.
Identical typed operand histories are equivalent under every target hash seed;
different possible histories require the still-open constant-origin adapter.
"""
import ast,dis
from dataclasses import dataclass

from .native_cpython_set_context import PolicyProbe,copy_ast,construction_plan,_compile,_classify


@dataclass(frozen=True)
class OperandFact:
    state:str
    value:object=None
    reason:str|None=None


@dataclass(frozen=True)
class InventoryIssue:
    node:ast.AST
    reason:str


@dataclass(frozen=True)
class Inventory:
    groups:dict
    issues:tuple


def constant_operand(node,integer):
    try:
        tree=copy_ast(node)
        if integer!='bigint':tree=PolicyProbe(integer).visit(tree)
        ast.fix_missing_locations(tree)
        items=list(dis.get_instructions(compile(ast.Expression(tree),'<pytors-set-constant-fact>','eval',optimize=0)))
    except (SyntaxError,TypeError,ValueError)as error:
        return OperandFact('incomplete',reason='constant operand metadata probe failed ('+type(error).__name__+'): '+str(error))
    items=[item for item in items if item.opname not in {'RESUME','RETURN_VALUE'}]
    if len(items)==1 and items[0].opname in {'LOAD_CONST','LOAD_SMALL_INT','RETURN_CONST'}:return OperandFact('constant',items[0].argval)
    return OperandFact('nonconstant')


def typed_key(value):
    """An order-free overapproximation of CP's typed constant-cache key.

Float/complex constants matter in unused source too: a later equal numeric
duplicate can leave an integer representative in a frozen constant. NaN keys
may conservatively collide here, yielding a diagnostic rather than admission.
No host hashes, secret, or physical frozenset traversal is emitted.
"""
    if value is None:return ('none',)
    if value is Ellipsis:return ('ellipsis',)
    if type(value)is bool:return ('bool',value)
    if type(value)is int:return ('int',value)
    if type(value)is float:return ('float',value.hex())
    if type(value)is complex:return ('complex',value.real.hex(),value.imag.hex())
    if type(value)is str:return ('str',value)
    if type(value)is bytes:return ('bytes',value)
    if type(value)is tuple:return ('tuple',tuple(typed_key(item)for item in value))
    if type(value)is frozenset:return ('frozenset',frozenset(typed_key(item)for item in value))
    raise TypeError('nonconstant key')


def history(values):
    try:
        # Iteration only forms an unordered analysis key. It never determines
        # insertion order or any generated value; source operands do that.
        key=frozenset(typed_key(value)for value in frozenset(values))
        return key,tuple(typed_key(value)for value in values)
    except TypeError:return None


class ConstantOrigins:
    def __init__(self,model,parents):self.model=model;self.parents=parents;self.units={};self.operands={}

    def values(self,elements,*,issues=None):
        facts=[]
        for element in elements:
            if id(element)not in self.operands:self.operands[id(element)]=constant_operand(element,self.model.integer)
            facts.append((element,self.operands[id(element)]))
        # One proved runtime operand prevents this entire constant run from
        # becoming a frozen constant, even if another operand's probe failed.
        if any(fact.state=='nonconstant'for _,fact in facts):return None
        incomplete=[InventoryIssue(element,fact.reason)for element,fact in facts if fact.state=='incomplete']
        if incomplete:
            if issues is not None:issues.extend(incomplete)
            return None
        return [fact.value for _,fact in facts]

    def source_unit(self,node):
        unit=self.model.unit
        return unit.original_unit(node)if hasattr(unit,'original_unit')else unit

    def inventory(self,unit):
        from .native_classes import ClassUnsupported
        groups={};issues=[]
        for original in ast.walk(unit.tree):
            if not isinstance(original,ast.Set):continue
            starred=any(isinstance(element,ast.Starred)for element in original.elts)
            if not starred:
                segments=[original.elts]
                if len(original.elts)<3:
                    try:plan=construction_plan(self.model,original,self.parents)
                    except ClassUnsupported:plan=None
                    if plan is not None and plan not in {'frozen_direct','frozen_bulk'}:continue
            else:
                # Constant runs in an unexecuted starred literal may contribute
                # compiler-generated frozen constants too. Conservatively keep
                # every eligible run; do not admit a source expansion adapter.
                segments=[[]]
                for element in original.elts:
                    if isinstance(element,ast.Starred):segments.append([])
                    else:segments[-1].append(element)
                segments=[segment for segment in segments if len(segment)>=3]
            for segment in segments:
                if not segment:continue
                values=self.values(segment,issues=issues)
                if values is None:continue
                probe=ast.copy_location(ast.Set(elts=segment),original)
                try:plans=_classify(_compile(probe,'iteration',self.model.integer),probe)
                except (SyntaxError,TypeError,ValueError)as error:
                    issues.append(InventoryIssue(original,'constant construction metadata probe failed ('+type(error).__name__+'): '+str(error)))
                    continue
                if not plans:
                    issues.append(InventoryIssue(original,'constant construction metadata has no proved instruction plan'))
                    continue
                if not plans.intersection({'frozen_direct','frozen_bulk'}):continue
                item=history(values)
                if item is None:
                    issues.append(InventoryIssue(original,'typed constant insertion history cannot be represented'))
                    continue
                key,ordered=item
                groups.setdefault(key,[]).append((ordered,original))
        return Inventory(groups,tuple(issues))

    def issue_detail(self,unit,issue):
        return str(unit.filename)+':'+str(issue.node.lineno)+':'+str(issue.node.col_offset+1)+': '+issue.reason

    def certify(self,node,*,order_irrelevant=None):
        from .native_classes import ClassUnsupported
        unit=self.source_unit(node)
        if id(unit)not in self.units:self.units[id(unit)]=self.inventory(unit)
        own_issues=[]
        values=self.values(node.elts,issues=own_issues);item=history(values)if values is not None else None
        if item is None:
            detail='; '+self.issue_detail(unit,own_issues[0])if own_issues else''
            raise ClassUnsupported(node,'this frozen set literal has no proved typed constant operand history'+detail,proof='compile-unit frozen-set constant origin')
        inventory=self.units[id(unit)]
        if inventory.issues:
            if order_irrelevant is not None and order_irrelevant():return
            raise ClassUnsupported(node,'the compile-unit frozen-set constant inventory is incomplete; '+self.issue_detail(unit,inventory.issues[0])+'; the native constant-pool origin adapter cannot prove this observable family without every possible contributor',proof='complete original-source constant inventory or closed order erasure')
        key,ordered=item
        choices=inventory.groups.get(key,())
        conflicts=[other for candidate,other in choices if candidate!=ordered]
        if choices and conflicts and order_irrelevant is not None and order_irrelevant():return
        if not choices or conflicts:
            detail=('; another possible constant history occurs at line '+str(conflicts[0].lineno))if conflicts else''
            raise ClassUnsupported(node,'equal frozen set constants can be interned across this original compilation unit with different insertion histories'+detail+'; the native compile-unit constant-pool origin adapter is not implemented yet',proof='identical typed frozen-constant histories across dead, nested and unused source')
