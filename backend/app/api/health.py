from fastapi import APIRouter, Depends
from pymongo.database import Database

from app.database import get_database

router = APIRouter(tags=["health"])


@router.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok", "phase": "1"}


@router.get("/health/ready")
def ready(db: Database = Depends(get_database)) -> dict[str, str]:
    db.command("ping")
    return {"status": "ready", "database": "connected"}
