import os
from pathlib import Path

import yaml

from app.models.tool_spec import ToolSpec

_BACKEND_DIR = Path(__file__).parents[2]

# Large file defaults (PDB, FASTA) are stored here, NOT in the PortSpec.
# This keeps the /api/tools response small (~5 KB instead of ~230 KB).
# Keys: "{tool_id}.{port_name}"
_large_defaults: dict[str, str] = {}

_SENTINEL_PREFIX = "__default_file__:"


def get_large_default(tool_id: str, port_name: str) -> str | None:
    return _large_defaults.get(f"{tool_id}.{port_name}")


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def load(self, tools_root: Path | None = None) -> None:
        if tools_root is None:
            tools_root = Path(__file__).parents[3] / "tools"
        for yaml_path in tools_root.rglob("tool.yaml"):
            with open(yaml_path) as f:
                data = yaml.safe_load(f)
            spec = ToolSpec.model_validate(data)
            for port in spec.inputs:
                if port.default_file:
                    resolved = _BACKEND_DIR / port.default_file
                    if resolved.exists():
                        # Store the content server-side only
                        _large_defaults[f"{spec.id}.{port.name}"] = resolved.read_text()
                        # Return a small sentinel in the API response
                        port.default = f"{_SENTINEL_PREFIX}{resolved.name}"
                    else:
                        import warnings
                        warnings.warn(f"[registry] default_file not found: {resolved}")
            self._tools[spec.id] = spec

    def get(self, tool_id: str) -> ToolSpec | None:
        return self._tools.get(tool_id)

    def all(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)


tool_registry = ToolRegistry()
