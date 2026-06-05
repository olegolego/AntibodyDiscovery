"""Vectorised O(N^2) pairwise force laws.

Every force law has the signature::

    f(pos, type_index, types, box, pairs, term) -> (forces[N,3], potential_energy)

``pairs`` is a precomputed ``(M,2)`` int array of i<j indices (so a cell-list can
later replace the all-pairs enumeration without touching the force code). Forces
are computed on the displacement r_ij = r_i - r_j with the minimum-image
convention applied when the box is periodic.
"""
from __future__ import annotations

import numpy as np

from .spec import Box, ForceTerm, ParticleType


def all_pairs(n: int) -> np.ndarray:
    """Return every unordered (i, j) pair with i < j as an (M, 2) int array."""
    if n < 2:
        return np.empty((0, 2), dtype=np.int64)
    i, j = np.triu_indices(n, k=1)
    return np.stack([i, j], axis=1).astype(np.int64)


def minimum_image(disp: np.ndarray, box: Box) -> np.ndarray:
    """Wrap displacement vectors into [-L/2, L/2) per periodic axis."""
    if box.boundary != "periodic":
        return disp
    L = np.asarray(box.lengths, dtype=np.float64)
    return disp - L * np.round(disp / L)


def _scatter_pair_forces(n: int, pairs: np.ndarray, fij: np.ndarray) -> np.ndarray:
    """Accumulate per-pair force vectors (force on i) back onto each particle.

    fij[k] is the force exerted on particle pairs[k,0] by pairs[k,1]; the
    reaction -fij is added to the partner.
    """
    forces = np.zeros((n, 3), dtype=np.float64)
    np.add.at(forces, pairs[:, 0], fij)
    np.add.at(forces, pairs[:, 1], -fij)
    return forces


def lennard_jones(pos, type_index, types, box, pairs, term: ForceTerm):
    """12-6 Lennard-Jones. U = 4 eps [(s/r)^12 - (s/r)^6].

    With a cutoff we use the *shifted-force* form so both U and F go smoothly to
    zero at rc — this is what keeps NVE energy conserved (a bare truncation leaves
    a force discontinuity that pumps energy as pairs cross the cutoff).
    """
    n = pos.shape[0]
    if pairs.shape[0] == 0:
        return np.zeros((n, 3)), 0.0
    eps, sig = float(term.epsilon), float(term.sigma)
    disp = minimum_image(pos[pairs[:, 0]] - pos[pairs[:, 1]], box)
    r2 = np.maximum(np.sum(disp * disp, axis=1), 1e-12)

    mask = np.ones_like(r2, dtype=bool)
    if term.cutoff is not None:
        rc = term.cutoff * sig
        mask = r2 < rc * rc

    inv_r2 = np.where(mask, sig * sig / r2, 0.0)
    inv_r6 = inv_r2 ** 3
    inv_r12 = inv_r6 ** 2
    r = np.sqrt(r2)

    # scalar force component along +r_hat (positive = repulsive) and its /r factor
    f_scalar = 24.0 * eps * (2.0 * inv_r12 - inv_r6) / r   # = -dU/dr
    u = 4.0 * eps * (inv_r12 - inv_r6)

    if term.cutoff is not None:
        rc = term.cutoff * sig
        sc6 = (sig / rc) ** 6
        sc12 = sc6 ** 2
        f_rc = 24.0 * eps * (2.0 * sc12 - sc6) / rc     # F(rc)
        u_rc = 4.0 * eps * (sc12 - sc6)                  # U(rc)
        # shifted-force: F_sf = F(r) - F(rc); U_sf = U(r) - U(rc) + F(rc)(r - rc)
        f_scalar = np.where(mask, f_scalar - f_rc, 0.0)
        u = np.where(mask, u - u_rc + f_rc * (r - rc), 0.0)

    pe = float(np.sum(u))
    coeff = f_scalar / r                  # vector force on i = coeff * disp
    fij = coeff[:, None] * disp
    return _scatter_pair_forces(n, pairs, fij), pe


def coulomb(pos, type_index, types, box, pairs, term: ForceTerm):
    """Coulomb 1/r between particle charges. U = k q_i q_j / r."""
    n = pos.shape[0]
    if pairs.shape[0] == 0:
        return np.zeros((n, 3)), 0.0
    charges = np.array([types[t].charge for t in type_index], dtype=np.float64)
    qq = charges[pairs[:, 0]] * charges[pairs[:, 1]]
    disp = minimum_image(pos[pairs[:, 0]] - pos[pairs[:, 1]], box)
    r2 = np.maximum(np.sum(disp * disp, axis=1), 1e-12)
    r = np.sqrt(r2)

    mask = np.ones_like(r2, dtype=bool)
    if term.coulomb_cutoff is not None:
        mask = r < term.coulomb_cutoff

    k = float(term.k_coulomb)
    pe = float(np.sum(np.where(mask, k * qq / r, 0.0)))
    # F = k q_i q_j / r^2 * r_hat = k q_i q_j / r^3 * disp
    coeff = np.where(mask, k * qq / (r2 * r), 0.0)
    fij = coeff[:, None] * disp
    return _scatter_pair_forces(n, pairs, fij), pe


def gravity(pos, type_index, types, box, pairs, term: ForceTerm):
    """Softened Newtonian gravity. U = -G m_i m_j / sqrt(r^2 + eps^2)."""
    n = pos.shape[0]
    if pairs.shape[0] == 0:
        return np.zeros((n, 3)), 0.0
    masses = np.array([types[t].mass for t in type_index], dtype=np.float64)
    mm = masses[pairs[:, 0]] * masses[pairs[:, 1]]
    disp = minimum_image(pos[pairs[:, 0]] - pos[pairs[:, 1]], box)
    soft2 = float(term.softening) ** 2
    r2 = np.sum(disp * disp, axis=1) + soft2
    r = np.sqrt(r2)
    G = float(term.g_constant)

    pe = float(np.sum(-G * mm / r))
    # F on i is attractive (toward j): -G m_i m_j / r^3 * disp
    coeff = -G * mm / (r2 * r)
    fij = coeff[:, None] * disp
    return _scatter_pair_forces(n, pairs, fij), pe


def harmonic_bond(pos, type_index, types, box, bonds_ij, bonds_r0, bonds_k):
    """Harmonic bonds over an explicit bond list. U = 1/2 k (r - r0)^2.

    Distinct signature from the pairwise laws: bonds are sparse and indexed
    explicitly rather than over all pairs.
    """
    n = pos.shape[0]
    if bonds_ij.shape[0] == 0:
        return np.zeros((n, 3)), 0.0
    disp = pos[bonds_ij[:, 0]] - pos[bonds_ij[:, 1]]   # bonds ignore PBC images
    r = np.maximum(np.linalg.norm(disp, axis=1), 1e-12)
    dr = r - bonds_r0
    pe = float(np.sum(0.5 * bonds_k * dr * dr))
    # F on i = -k (r - r0) * r_hat
    coeff = -bonds_k * dr / r
    fij = coeff[:, None] * disp
    return _scatter_pair_forces(n, bonds_ij, fij), pe


# Registry of pairwise force laws (harmonic_bond handled separately by the engine).
PAIRWISE = {
    "lennard_jones": lennard_jones,
    "coulomb": coulomb,
    "gravity": gravity,
}
