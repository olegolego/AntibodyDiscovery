import hashlib
import os
from pathlib import Path

from app.config import settings


class LocalStorage:
    def __init__(self) -> None:
        self.root = Path(settings.local_artifact_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, content: bytes, suffix: str = "") -> str:
        digest = hashlib.sha256(content).hexdigest()
        filename = digest + suffix
        path = self.root / filename
        if not path.exists():
            path.write_bytes(content)
        return f"local://{filename}"

    def get(self, uri: str) -> bytes:
        filename = uri.removeprefix("local://")
        return (self.root / filename).read_bytes()
