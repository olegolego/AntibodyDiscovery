from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def list_artifacts():
    # Placeholder — implement with storage backend in Phase 3+
    return []
