from fastapi import APIRouter
from app.api.routes import chat, ingest, history

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(chat.router)
api_router.include_router(ingest.router)
api_router.include_router(history.router)
