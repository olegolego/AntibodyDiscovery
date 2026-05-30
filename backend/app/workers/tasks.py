from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext

# Maps tool id → adapter class (lazy-imported to avoid loading all deps at startup)
_ADAPTER_MAP = {
    "sequence_input": ("app.tools.adapters.echo", "EchoAdapter"),
    "sequence_db":    ("app.tools.adapters.sequence_db", "SequenceDbAdapter"),
    "dataset":        ("app.tools.adapters.dataset_tool", "DatasetToolAdapter"),
    "target_input": ("app.tools.adapters.echo", "EchoAdapter"),
    "echo": ("app.tools.adapters.echo", "EchoAdapter"),
    "immunebuilder": ("app.tools.adapters.immunebuilder", "ImmuneBuilderAdapter"),
    "alphafold_monomer": ("app.tools.adapters.alphafold", "AlphaFoldAdapter"),
    "esmfold": ("app.tools.adapters.esmfold", "ESMFoldAdapter"),
    "abmap": ("app.tools.adapters.abmap", "AbMAPAdapter"),
    "rfdiffusion": ("app.tools.adapters.rfdiffusion", "RFdiffusionAdapter"),
    "proteinmpnn": ("app.tools.adapters.proteinmpnn", "ProteinMPNNAdapter"),
    "haddock3":          ("app.tools.adapters.haddock3",  "HADDOCK3Adapter"),
    "biophi":            ("app.tools.adapters.biophi",    "BioPhiAdapter"),
    "ablang":            ("app.tools.adapters.ablang",    "AbLangAdapter"),
    "equidock":          ("app.tools.adapters.equidock",  "EquiDockAdapter"),
    "equifold":          ("app.tools.adapters.equifold",  "EquiFoldAdapter"),
    "megadock":          ("app.tools.adapters.megadock",  "MEGADOCKAdapter"),
    "gromacs_mmpbsa":    ("app.tools.adapters.gromacs",   "GROMACSAdapter"),
    "pdbfixer":          ("app.tools.adapters.pdbfixer",  "PDBFixerAdapter"),
    "superwater":        ("app.tools.adapters.superwater","SuperWaterAdapter"),
    "compute":           ("app.tools.adapters.compute",   "ComputeAdapter"),
    "loop":              ("app.tools.adapters.loop",      "LoopAdapter"),
    "loop_start":        ("app.tools.adapters.loop_start", "LoopStartAdapter"),
    "loop_end":          ("app.tools.adapters.loop_end",   "LoopEndAdapter"),
    "loop_objective":    ("app.tools.adapters.loop_objective", "LoopObjectiveAdapter"),
    "custom_dnn":        ("app.tools.adapters.custom_dnn", "CustomDNNAdapter"),
    "diffusion_design":  ("app.tools.adapters.toolbox",   "ToolboxAdapter"),
    "cdr_mutator":       ("app.tools.adapters.cdr_mutator", "CDRMutatorAdapter"),
    "esm_embedding":       ("app.tools.adapters.esm_embedding",      "ESMEmbeddingAdapter"),
    "cheap_embedding":     ("app.tools.adapters.cheap_embedding",    "CHEAPEmbeddingAdapter"),
    "aa_chem_embedding":   ("app.tools.adapters.aa_chem_embedding",  "AAChemEmbeddingAdapter"),
    "aa_onehot_embedding": ("app.tools.adapters.aa_onehot_embedding","AAOneHotEmbeddingAdapter"),
    "iglm":              ("app.tools.adapters.iglm",            "IgLMAdapter"),
    "progen2":           ("app.tools.adapters.progen2",         "ProGen2Adapter"),
    "liability_scanner": ("app.tools.adapters.liability_scanner", "LiabilityScannerAdapter"),
    "deepsp":            ("app.tools.adapters.deepsp",            "DeepSPAdapter"),
    "netsolp":           ("app.tools.adapters.netsolp",           "NetSolPAdapter"),
    "rcc_mlde":          ("app.tools.adapters.rcc_mlde",          "RCCMLDEAdapter"),
    "dnn_mlde":          ("app.tools.adapters.dnn_mlde",          "DNNMLDEAdapter"),
    "rl_designer":       ("app.tools.adapters.rl_designer",       "RLDesignerAdapter"),
    "developability_filter": ("app.tools.adapters.developability_filter", "DevelopabilityFilterAdapter"),
    # BioPipelines tools
    "dna_encoder":        ("app.tools.adapters.dna_encoder",        "DNAEncoderAdapter"),
    "fuse":               ("app.tools.adapters.fuse",               "FuseAdapter"),
    "mutation_profiler":  ("app.tools.adapters.mutation_profiler",  "MutationProfilerAdapter"),
    "mutation_composer":  ("app.tools.adapters.mutation_composer",  "MutationComposerAdapter"),
    "distance_selector":  ("app.tools.adapters.distance_selector",  "DistanceSelectorAdapter"),
    "compound_library":   ("app.tools.adapters.compound_library",   "CompoundLibraryAdapter"),
    "boltz2":             ("app.tools.adapters.boltz2",             "Boltz2Adapter"),
    "ligand_mpnn":        ("app.tools.adapters.ligand_mpnn",        "LigandMPNNAdapter"),
    # design operations
    "choose":            ("app.tools.adapters.choose",            "ChooseAdapter"),
    "filter":            ("app.tools.adapters.filter_op",         "FilterAdapter"),
    "rank":              ("app.tools.adapters.rank_op",           "RankAdapter"),
    "evaluate":          ("app.tools.adapters.evaluate_op",       "EvaluateAdapter"),
}


async def dispatch_tool(
    spec: ToolSpec, inputs: dict[str, Any], ctx: RunContext
) -> dict[str, Any]:
    entry = _ADAPTER_MAP.get(spec.id)
    if entry is None:
        raise ValueError(f"No adapter registered for tool '{spec.id}'")

    module_path, class_name = entry
    import importlib
    module = importlib.import_module(module_path)
    adapter_cls = getattr(module, class_name)
    adapter = adapter_cls(spec)
    return await adapter.invoke(inputs, ctx)
