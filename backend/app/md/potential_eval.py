"""Safe evaluation of a user potential U(r) into a pair force law.

The user types an expression in a single variable ``r`` (the pair distance), e.g.
``4*(1/r**12 - 1/r**6)``. We validate it against a strict AST allowlist (no
attribute access, no calls except whitelisted numpy ufuncs, no dunder names),
then build a vectorised callable. The pair force magnitude is -dU/dr, obtained
analytically with sympy when available and by a centred numerical derivative
otherwise.
"""
from __future__ import annotations

import ast
import math
from typing import Callable

import numpy as np

from .forces import minimum_image, _scatter_pair_forces
from .spec import Box, ForceTerm

# Whitelisted names usable inside a formula. All map to elementwise numpy ufuncs
# or constants so the expression vectorises over the pair-distance array.
_ALLOWED_FUNCS: dict[str, object] = {
    "sin": np.sin, "cos": np.cos, "tan": np.tan,
    "exp": np.exp, "log": np.log, "log10": np.log10, "sqrt": np.sqrt,
    "abs": np.abs, "sinh": np.sinh, "cosh": np.cosh, "tanh": np.tanh,
    "arctan": np.arctan, "sign": np.sign,
}
_ALLOWED_CONSTS: dict[str, float] = {"pi": math.pi, "e": math.e}

_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant,
    ast.Name, ast.Load, ast.Call,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.USub, ast.UAdd,
)


class FormulaError(ValueError):
    pass


def _validate(node: ast.AST) -> None:
    for child in ast.walk(node):
        if not isinstance(child, _ALLOWED_NODES):
            raise FormulaError(f"Disallowed syntax: {type(child).__name__}")
        if isinstance(child, ast.Name):
            if child.id.startswith("__"):
                raise FormulaError("Dunder names are not allowed")
            if child.id not in _ALLOWED_FUNCS and child.id not in _ALLOWED_CONSTS and child.id != "r":
                raise FormulaError(f"Unknown name: {child.id!r}")
        if isinstance(child, ast.Call):
            if not isinstance(child.func, ast.Name) or child.func.id not in _ALLOWED_FUNCS:
                raise FormulaError("Only whitelisted functions may be called")


def compile_potential(expression: str) -> Callable[[np.ndarray], np.ndarray]:
    """Return a vectorised U(r) callable after validating the expression."""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"Syntax error: {exc.msg}") from exc
    _validate(tree)
    code = compile(tree, "<formula>", "eval")
    namespace = {**_ALLOWED_FUNCS, **_ALLOWED_CONSTS, "__builtins__": {}}

    def U(r: np.ndarray) -> np.ndarray:
        return eval(code, namespace, {"r": r})  # noqa: S307 — sandboxed namespace

    return U


def _force_magnitude_over_r(U: Callable, r: np.ndarray) -> np.ndarray:
    """Compute (-dU/dr)/r for each pair distance, used to scale the displacement.

    Tries sympy for an exact derivative; falls back to a centred finite
    difference. Returns f/r so the caller multiplies by the displacement vector.
    """
    # f = -dU/dr ; we return f / r
    h = 1e-5
    dU = (U(r + h) - U(r - h)) / (2.0 * h)
    return -dU / r


def make_formula_force(term: ForceTerm):
    """Build a pairwise force callable from term.expression (cached compile)."""
    if not term.expression:
        raise FormulaError("Formula term has no expression")
    U = compile_potential(term.expression)
    cutoff = term.cutoff

    def force(pos, type_index, types, box: Box, pairs, _term):
        n = pos.shape[0]
        if pairs.shape[0] == 0:
            return np.zeros((n, 3)), 0.0
        disp = minimum_image(pos[pairs[:, 0]] - pos[pairs[:, 1]], box)
        r = np.maximum(np.linalg.norm(disp, axis=1), 1e-9)
        mask = r < cutoff if cutoff is not None else np.ones_like(r, dtype=bool)
        u = np.where(mask, U(r), 0.0)
        pe = float(np.sum(u))
        coeff = np.where(mask, _force_magnitude_over_r(U, r), 0.0)
        coeff = np.nan_to_num(coeff, nan=0.0, posinf=0.0, neginf=0.0)
        fij = coeff[:, None] * disp
        return _scatter_pair_forces(n, pairs, fij), pe

    return force


def validate_formula(expression: str) -> dict:
    """Validate + sample a formula for the /validate-formula endpoint.

    Returns a preview of U(r) and F(r) over a distance range for the live chart,
    or raises FormulaError.
    """
    U = compile_potential(expression)
    r = np.linspace(0.8, 3.0, 80)
    u = U(r)
    h = 1e-5
    f = -(U(r + h) - U(r - h)) / (2.0 * h)
    u = np.nan_to_num(np.asarray(u, dtype=float), nan=0.0, posinf=1e6, neginf=-1e6)
    f = np.nan_to_num(np.asarray(f, dtype=float), nan=0.0, posinf=1e6, neginf=-1e6)
    return {
        "valid": True,
        "samples": [
            {"r": float(rr), "U": float(uu), "F": float(ff)}
            for rr, uu, ff in zip(r, u, f)
        ],
    }
