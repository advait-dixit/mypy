from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Final, Optional, Tuple
from typing_extensions import TypeAlias as _TypeAlias

from mypy.nodes import (
    LITERAL_NO,
    LITERAL_TYPE,
    LITERAL_YES,
    AssertTypeExpr,
    AssignmentExpr,
    AwaitExpr,
    BytesExpr,
    CallExpr,
    CastExpr,
    ComparisonExpr,
    ComplexExpr,
    ConditionalExpr,
    DictExpr,
    DictionaryComprehension,
    EllipsisExpr,
    EnumCallExpr,
    Expression,
    FloatExpr,
    GeneratorExpr,
    IndexExpr,
    IntExpr,
    LambdaExpr,
    ListComprehension,
    ListExpr,
    MemberExpr,
    NamedTupleExpr,
    NameExpr,
    NewTypeExpr,
    OpExpr,
    ParamSpecExpr,
    PromoteExpr,
    RevealExpr,
    SetComprehension,
    SetExpr,
    SliceExpr,
    StarExpr,
    StrExpr,
    SuperExpr,
    TempNode,
    TupleExpr,
    TypeAliasExpr,
    TypeApplication,
    TypedDictExpr,
    TypeVarExpr,
    TypeVarTupleExpr,
    UnaryExpr,
    Var,
    YieldExpr,
    YieldFromExpr,
)
from mypy.visitor import ExpressionVisitor

# [Note Literals and literal_hash]
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
#
# Mypy uses the term "literal" to refer to any expression built out of
# the following:
#
# * Plain literal expressions, like `1` (integer, float, string, etc.)
#
# * Compound literal expressions, like `(lit1, lit2)` (list, dict,
#   set, or tuple)
#
# * Operator expressions, like `lit1 + lit2`
#
# * Variable references, like `x`
#
# * Member references, like `lit.m`
#
# * Index expressions, like `lit[0]`
#
# A typical "literal" looks like `x[(i,j+1)].m`.
#
# An expression that is a literal has a `literal_hash`, with the
# following properties.
#
# * `literal_hash` is a Key: a tuple containing basic data types and
#   possibly other Keys. So it can be used as a key in a dictionary
#   that will be compared by value (as opposed to the Node itself,
#   which is compared by identity).
#
# * Two expressions have equal `literal_hash`es if and only if they
#   are syntactically equal expressions. (NB: Actually, we also
#   identify as equal expressions like `3` and `3.0`; is this a good
#   idea?)
#
# * The elements of `literal_hash` that are tuples are exactly the
#   subexpressions of the original expression (e.g. the base and index
#   of an index expression, or the operands of an operator expression).


def literal(e: Expression) -> int:
    if isinstance(e, ComparisonExpr):
        return min(literal(o) for o in e.operands)

    elif isinstance(e, OpExpr):
        return min(literal(e.left), literal(e.right))

    elif isinstance(e, (MemberExpr, UnaryExpr, StarExpr)):
        return literal(e.expr)

    elif isinstance(e, AssignmentExpr):
        return literal(e.target)

    elif isinstance(e, IndexExpr):
        if literal(e.index) == LITERAL_YES:
            return literal(e.base)
        else:
            return LITERAL_NO

    elif isinstance(e, NameExpr):
        if isinstance(e.node, Var) and e.node.is_final and e.node.final_value is not None:
            return LITERAL_YES
        return LITERAL_TYPE

    if isinstance(e, (IntExpr, FloatExpr, ComplexExpr, StrExpr, BytesExpr)):
        return LITERAL_YES

    if literal_hash(e):
        return LITERAL_YES

    return LITERAL_NO


Key: _TypeAlias = Tuple[Any, ...]


def subkeys(key: Key) -> Iterable[Key]:
    return [elt for elt in key if isinstance(elt, tuple)]


def literal_hash(e: Expression) -> Key | None:
    return e.accept(_hasher)


def extract_var_from_literal_hash(key: Key) -> Var | None:
    """If key refers to a Var node, return it.

    Return None otherwise.
    """
    if len(key) == 2 and key[0] == "Var" and isinstance(key[1], Var):
        return key[1]
    return None


class _Hasher(ExpressionVisitor[Optional[Key]]):
    def visit_int_expr(self, e: IntExpr) -> Key:
        return ("Literal", e.value)

    def visit_str_expr(self, e: StrExpr) -> Key:
        return ("Literal", e.value)

    def visit_bytes_expr(self, e: BytesExpr) -> Key:
        return ("Literal", e.value)

    def visit_float_expr(self, e: FloatExpr) -> Key:
        return ("Literal", e.value)

    def visit_complex_expr(self, e: ComplexExpr) -> Key:
        return ("Literal", e.value)

    def visit_star_expr(self, e: StarExpr) -> Key:
        return ("Star", literal_hash(e.expr))

    def visit_name_expr(self, e: NameExpr) -> Key:
        if isinstance(e.node, Var) and e.node.is_final and e.node.final_value is not None:
            return ("Literal", e.node.final_value)
        # N.B: We use the node itself as the key, and not the name,
        # because using the name causes issues when there is shadowing
        # (for example, in list comprehensions).
        return ("Var", e.node)

    def visit_member_expr(self, e: MemberExpr) -> Key:
        return ("Member", literal_hash(e.expr), e.name)

    def visit_op_expr(self, e: OpExpr) -> Key:
        return ("Binary", e.op, literal_hash(e.left), literal_hash(e.right))

    def visit_comparison_expr(self, e: ComparisonExpr) -> Key:
        rest: tuple[str | Key | None, ...] = tuple(e.operators)
        rest += tuple(literal_hash(o) for o in e.operands)
        return ("Comparison",) + rest

    def visit_unary_expr(self, e: UnaryExpr) -> Key:
        return ("Unary", e.op, literal_hash(e.expr))

    def seq_expr(self, e: ListExpr | TupleExpr | SetExpr, name: str) -> Key | None:
        if all(literal(x) == LITERAL_YES for x in e.items):
            rest: tuple[Key | None, ...] = tuple(literal_hash(x) for x in e.items)
            return (name,) + rest
        return None

    def visit_list_expr(self, e: ListExpr) -> Key | None:
        return self.seq_expr(e, "List")

    def visit_dict_expr(self, e: DictExpr) -> Key | None:
        if all(a and literal(a) == literal(b) == LITERAL_YES for a, b in e.items):
            rest: tuple[Key | None, ...] = tuple(
                (literal_hash(a) if a else None, literal_hash(b)) for a, b in e.items
            )
            return ("Dict",) + rest
        return None

    def visit_tuple_expr(self, e: TupleExpr) -> Key | None:
        return self.seq_expr(e, "Tuple")

    def visit_set_expr(self, e: SetExpr) -> Key | None:
        return self.seq_expr(e, "Set")

    def visit_index_expr(self, e: IndexExpr) -> Key | None:
        if literal(e.index) == LITERAL_YES:
            return ("Index", literal_hash(e.base), literal_hash(e.index))
        return None

    def visit_assignment_expr(self, e: AssignmentExpr) -> Key | None:
        return literal_hash(e.target)

    def visit_call_expr(self, e: CallExpr) -> None:
        return None

    def visit_slice_expr(self, e: SliceExpr) -> None:
        return None

    def visit_cast_expr(self, e: CastExpr) -> None:
        return None

    def visit_assert_type_expr(self, e: AssertTypeExpr) -> None:
        return None

    def visit_conditional_expr(self, e: ConditionalExpr) -> None:
        return None

    def visit_ellipsis(self, e: EllipsisExpr) -> None:
        return None

    def visit_yield_from_expr(self, e: YieldFromExpr) -> None:
        return None

    def visit_yield_expr(self, e: YieldExpr) -> None:
        return None

    def visit_reveal_expr(self, e: RevealExpr) -> None:
        return None

    def visit_super_expr(self, e: SuperExpr) -> None:
        return None

    def visit_type_application(self, e: TypeApplication) -> None:
        return None

    def visit_lambda_expr(self, e: LambdaExpr) -> None:
        return None

    def visit_list_comprehension(self, e: ListComprehension) -> None:
        return None

    def visit_set_comprehension(self, e: SetComprehension) -> None:
        return None

    def visit_dictionary_comprehension(self, e: DictionaryComprehension) -> None:
        return None

    def visit_generator_expr(self, e: GeneratorExpr) -> None:
        return None

    def visit_type_var_expr(self, e: TypeVarExpr) -> None:
        return None

    def visit_paramspec_expr(self, e: ParamSpecExpr) -> None:
        return None

    def visit_type_var_tuple_expr(self, e: TypeVarTupleExpr) -> None:
        return None

    def visit_type_alias_expr(self, e: TypeAliasExpr) -> None:
        return None

    def visit_namedtuple_expr(self, e: NamedTupleExpr) -> None:
        return None

    def visit_enum_call_expr(self, e: EnumCallExpr) -> None:
        return None

    def visit_typeddict_expr(self, e: TypedDictExpr) -> None:
        return None

    def visit_newtype_expr(self, e: NewTypeExpr) -> None:
        return None

    def visit__promote_expr(self, e: PromoteExpr) -> None:
        return None

    def visit_await_expr(self, e: AwaitExpr) -> None:
        return None

    def visit_temp_node(self, e: TempNode) -> None:
        return None


_hasher: Final = _Hasher()
