from fastapi import APIRouter
from app.api.routes import admin, auth, chat, documents, history, ingest, inspections, revenue, sops, work_orders

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(chat.router)
api_router.include_router(ingest.router)
api_router.include_router(history.router)
api_router.include_router(sops.router)
api_router.include_router(documents.router)
api_router.include_router(work_orders.router)
api_router.include_router(inspections.router)
api_router.include_router(revenue.router)
api_router.include_router(admin.router)
