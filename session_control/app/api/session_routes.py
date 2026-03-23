from fastapi import APIRouter

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("")
async def create_session() -> dict:
    return {
        "message": "session endpoint scaffolded",
        "implemented": False,
    }