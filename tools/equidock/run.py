#!/usr/bin/env python3
"""EquiDock subprocess entry point. Reads JSON from stdin, writes JSON to stdout."""
import json
import os
import sys
import tempfile
from pathlib import Path

TOOL_DIR = Path(__file__).parent
REPO_DIR = TOOL_DIR / "repo"
sys.path.insert(0, str(REPO_DIR))
os.environ["DGLBACKEND"] = "pytorch"

# DGL 1.x renamed copy_edge → copy_e; patch for equidock which uses the old name
import dgl.function as _dgl_fn
if not hasattr(_dgl_fn, "copy_edge") and hasattr(_dgl_fn, "copy_e"):
    _dgl_fn.copy_edge = _dgl_fn.copy_e

_CKPT_DIPS = (
    REPO_DIR / "checkpts"
    / "oct20_Wdec_0.0001#ITS_lw_10.0#Hdim_64#Nlay_8#shrdLay_F#ln_LN#lnX_0#Hnrm_0#NattH_50#skH_0.75#xConnI_0.0#LkySl_0.01#pokOTw_1.0#fine_F#"
    / "dips_model_best.pth"
)
_CKPT_DB5 = (
    REPO_DIR / "checkpts"
    / "oct20_Wdec_0.001#ITS_lw_10.0#Hdim_64#Nlay_5#shrdLay_T#ln_LN#lnX_0#Hnrm_0#NattH_50#skH_0.5#xConnI_0.0#LkySl_0.01#pokOTw_1.0#fine_F#"
    / "db5_model_best.pth"
)


_MAX_RECEPTOR_RESIDUES = 600   # memory limit for EquiDock on CPU


def _progress(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _trim_pdb_to_best_chain(pdb_text: str, max_residues: int = _MAX_RECEPTOR_RESIDUES) -> str:
    """
    If the receptor has more than max_residues residues, extract the single chain
    that is closest in size to the target range (50–max_residues).  Returns the
    PDB text for that chain (ATOM records only).  Warns to stderr so the user
    sees it in the terminal.
    """
    from collections import defaultdict
    chains: dict[str, list[str]] = defaultdict(list)
    residues_per_chain: dict[str, set] = defaultdict(set)

    for line in pdb_text.splitlines():
        if line.startswith("ATOM"):
            chain = line[21] if len(line) > 21 else " "
            try:
                res_num = int(line[22:26])
            except ValueError:
                res_num = 0
            chains[chain].append(line)
            residues_per_chain[chain].add(res_num)

    total_residues = sum(len(v) for v in residues_per_chain.values())
    if total_residues <= max_residues:
        return pdb_text

    _progress(
        f"⚠ Receptor has ~{total_residues} residues — EquiDock is limited to "
        f"{max_residues} to avoid OOM. Auto-selecting best chain."
    )

    # Pick the chain with most residues that is ≤ max_residues; else pick smallest
    candidates = sorted(residues_per_chain.items(), key=lambda x: len(x[1]), reverse=True)
    chosen = None
    for ch, res in candidates:
        if len(res) <= max_residues:
            chosen = ch
            break
    if chosen is None:
        # All chains are too big — use the smallest one and warn
        chosen = min(residues_per_chain, key=lambda c: len(residues_per_chain[c]))
        _progress(
            f"⚠ All chains exceed {max_residues} residues. Using chain {chosen!r} "
            f"({len(residues_per_chain[chosen])} res). Consider providing a binding domain only."
        )

    _progress(
        f"→ Using receptor chain {chosen!r} "
        f"({len(residues_per_chain[chosen])} residues, "
        f"dropped {total_residues - len(residues_per_chain[chosen])} residues from other chains)"
    )
    return "\n".join(chains[chosen]) + "\nEND\n"


# ── Functions inlined from inference_rigid.py (avoid module-level import side-effects) ──

def _get_residues(pdb_filename):
    from biopandas.pdb import PandasPdb
    df = PandasPdb().read_pdb(pdb_filename).df["ATOM"]
    df.rename(columns={"chain_id": "chain", "residue_number": "residue",
                        "residue_name": "resname", "x_coord": "x", "y_coord": "y",
                        "z_coord": "z", "element_symbol": "element"}, inplace=True)
    return list(df.groupby(["chain", "residue", "resname"]))


def _G_fn(protein_coords, x, sigma):
    import torch
    e = torch.exp(
        -torch.sum((protein_coords.view(1, -1, 3) - x.view(-1, 1, 3)) ** 2, dim=2)
        / float(sigma)
    )
    return -sigma * torch.log(1e-3 + e.sum(dim=1))


def _body_intersection_loss(lig_coors, rec_coors, sigma=8.0, surface_ct=8.0):
    import torch
    return (
        torch.mean(torch.clamp(surface_ct - _G_fn(rec_coors, lig_coors, sigma), min=0))
        + torch.mean(torch.clamp(surface_ct - _G_fn(lig_coors, rec_coors, sigma), min=0))
    )


def _get_rot_mat(euler_angles):
    import torch
    roll, yaw, pitch = euler_angles[0], euler_angles[1], euler_angles[2]
    z = torch.zeros([])
    o = torch.ones([])
    RX = torch.stack([torch.stack([o, z, z]),
                      torch.stack([z, torch.cos(roll), -torch.sin(roll)]),
                      torch.stack([z, torch.sin(roll),  torch.cos(roll)])]).reshape(3, 3)
    RY = torch.stack([torch.stack([torch.cos(pitch), z, torch.sin(pitch)]),
                      torch.stack([z, o, z]),
                      torch.stack([-torch.sin(pitch), z, torch.cos(pitch)])]).reshape(3, 3)
    RZ = torch.stack([torch.stack([torch.cos(yaw), -torch.sin(yaw), z]),
                      torch.stack([torch.sin(yaw),  torch.cos(yaw), z]),
                      torch.stack([z, z, o])]).reshape(3, 3)
    return torch.mm(torch.mm(RZ, RY), RX)


def _run(inputs: dict) -> dict:
    import numpy as np
    import torch
    from biopandas.pdb import PandasPdb

    ligand_pdb   = str(inputs.get("ligand", "")).strip()
    receptor_pdb = str(inputs.get("receptor", "")).strip()
    dataset      = str(inputs.get("dataset", "dips")).strip().lower()
    rm_clashes   = bool(inputs.get("remove_clashes", True))

    if not ligand_pdb:
        raise ValueError("ligand PDB is required")
    if not receptor_pdb:
        raise ValueError("receptor PDB is required")

    # Trim large receptors (multi-chain complexes, full spike, etc.) to avoid OOM
    receptor_pdb = _trim_pdb_to_best_chain(receptor_pdb)
    if dataset not in ("dips", "db5"):
        raise ValueError("dataset must be 'dips' or 'db5'")

    ckpt_path = _CKPT_DIPS if dataset == "dips" else _CKPT_DB5
    if not ckpt_path.exists():
        raise FileNotFoundError(
            f"Checkpoint not found: {ckpt_path}\n"
            "Run tools/equidock/setup.sh first."
        )

    from src.utils.protein_utils import preprocess_unbound_bound, protein_to_graph_unbound_bound
    from src.utils.train_utils import batchify_and_create_hetero_graphs_inference, create_model

    device = torch.device("cuda:0") if torch.cuda.is_available() else torch.device("cpu")
    _progress(f"Device: {device} | model: {dataset}")

    log = _progress  # equidock uses log() like print()

    with tempfile.TemporaryDirectory() as tmpdir:
        lig_path = os.path.join(tmpdir, "pair_l_b.pdb")
        rec_path = os.path.join(tmpdir, "pair_r_b_COMPLEX.pdb")
        Path(lig_path).write_text(ligand_pdb)
        Path(rec_path).write_text(receptor_pdb)

        # All-atom ligand coordinates (before transformation)
        ppdb_lig = PandasPdb().read_pdb(lig_path)
        lig_all_atoms = (
            ppdb_lig.df["ATOM"][["x_coord", "y_coord", "z_coord"]]
            .to_numpy().squeeze().astype(np.float32)
        )

        # All-atom receptor coordinates (for clash removal)
        ppdb_rec = PandasPdb().read_pdb(rec_path)
        rec_all_atoms = torch.from_numpy(
            ppdb_rec.df["ATOM"][["x_coord", "y_coord", "z_coord"]]
            .to_numpy().squeeze().astype(np.float32)
        )

        # ── Load model from checkpoint ──────────────────────────────────────────
        _progress("Loading checkpoint…")
        checkpoint = torch.load(str(ckpt_path), map_location=device)
        args: dict = {}
        for k, v in checkpoint["args"].items():
            args[k] = v
        args["debug"] = False
        args["device"] = device
        args["n_jobs"] = 1
        args["worker"] = 0

        # ── Build residue graphs ────────────────────────────────────────────────
        _progress("Building residue graphs…")
        (unbound_lig, unbound_rec,
         bound_lig_nodes, bound_rec_nodes) = preprocess_unbound_bound(
            _get_residues(lig_path),
            _get_residues(rec_path),
            graph_nodes=args.get("graph_nodes", "residues"),
            pos_cutoff=args.get("pocket_cutoff", 8.0),
            inference=True,
        )

        ligand_graph, receptor_graph = protein_to_graph_unbound_bound(
            unbound_lig, unbound_rec,
            bound_lig_nodes, bound_rec_nodes,
            graph_nodes=args.get("graph_nodes", "residues"),
            cutoff=args.get("graph_cutoff", 30.0),
            max_neighbor=args.get("graph_max_neighbor", 10),
            one_hot=False,
            residue_loc_is_alphaC=args.get("graph_residue_loc_is_alphaC", False),
        )

        # Must be set before batching, and must be set before create_model
        args["input_edge_feats_dim"] = ligand_graph.edata["he"].shape[1]
        ligand_graph.ndata["new_x"] = ligand_graph.ndata["x"]

        model = create_model(args, log)
        model.load_state_dict(checkpoint["state_dict"])
        model = model.to(device)
        model.eval()

        batch_graph = batchify_and_create_hetero_graphs_inference(ligand_graph, receptor_graph)
        batch_graph = batch_graph.to(device)

        # ── Run inference ───────────────────────────────────────────────────────
        _progress("Running EquiDock inference…")
        with torch.no_grad():
            (_, _, _, all_rotation_list, all_translation_list) = model(batch_graph, epoch=0)

        rotation    = all_rotation_list[0].detach().cpu().numpy()
        translation = all_translation_list[0].detach().cpu().numpy()

        # Apply rigid body transform to all ligand atoms
        unbound_ligand_new_pos = (rotation @ lig_all_atoms.T).T + translation

        # ── Optional clash removal (manual gradient descent, as in original) ────
        if rm_clashes:
            _progress("Removing clashes (gradient descent)…")
            euler = torch.zeros([3], requires_grad=True)
            t_fine = torch.zeros([3], requires_grad=True)
            lig_th = (_get_rot_mat(euler) @ torch.from_numpy(unbound_ligand_new_pos).T).T + t_fine

            non_int_loss_item = 100.0
            it = 0
            while non_int_loss_item > 0.5 and it < 2000:
                non_int_loss = _body_intersection_loss(lig_th, rec_all_atoms)
                non_int_loss_item = non_int_loss.item()
                eta = 1e-3
                if non_int_loss_item < 2.0:
                    eta = 1e-4
                if it > 1500:
                    eta = 1e-2
                if it % 200 == 0:
                    _progress(f"  clash iter {it}: loss={non_int_loss_item:.3f}")
                non_int_loss.backward()
                with torch.no_grad():
                    t_fine_new = (t_fine - eta * t_fine.grad).clone().detach()
                    euler_new  = (euler  - eta * euler.grad).clone().detach()
                t_fine = t_fine_new.requires_grad_(True)
                euler  = euler_new.requires_grad_(True)
                lig_th = (_get_rot_mat(euler) @ torch.from_numpy(unbound_ligand_new_pos).T).T + t_fine
                it += 1

            final_pos = lig_th.detach().numpy()
        else:
            final_pos = unbound_ligand_new_pos

        # ── Write combined complex (docked ligand + original receptor) ──────────
        ppdb_lig.df["ATOM"][["x_coord", "y_coord", "z_coord"]] = final_pos
        out_lig = os.path.join(tmpdir, "docked_ligand.pdb")
        ppdb_lig.to_pdb(path=out_lig, records=["ATOM"], gz=False)

        rec_atom_lines = [
            l for l in receptor_pdb.splitlines()
            if l.startswith("ATOM") or l.startswith("HETATM")
        ]
        complex_pdb = Path(out_lig).read_text().rstrip()
        complex_pdb += "\n" + "\n".join(rec_atom_lines) + "\nEND\n"

    _progress("EquiDock done.")
    n_lig_res = int(ppdb_lig.df["ATOM"]["residue_number"].nunique())
    return {
        "best_complex": complex_pdb,
        "metadata": {
            "dataset": dataset,
            "remove_clashes": rm_clashes,
            "ligand_residues": n_lig_res,
            "translation_magnitude_A": round(float(np.linalg.norm(translation)), 2),
        },
    }


if __name__ == "__main__":
    inputs = json.load(sys.stdin)
    try:
        outputs = _run(inputs)
    except Exception as exc:
        json.dump({"error": str(exc)}, sys.stdout)
        sys.stdout.flush()
        sys.exit(1)
    json.dump(outputs, sys.stdout)
    sys.stdout.flush()
