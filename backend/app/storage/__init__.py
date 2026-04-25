from app.config import settings


def get_storage():
    if settings.storage_backend == "local":
        from app.storage.local import LocalStorage
        return LocalStorage()
    raise NotImplementedError(f"Storage backend '{settings.storage_backend}' not implemented yet")
