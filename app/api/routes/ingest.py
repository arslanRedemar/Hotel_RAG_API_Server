from fastapi import APIRouter, HTTPException

from app.models.schemas import IngestRequest, IngestResponse
from app.rag.ingest import ingest_documents

router = APIRouter(prefix="/ingest", tags=["Ingest"])


@router.post("", response_model=IngestResponse)
async def ingest(request: IngestRequest = IngestRequest()):
    try:
        count = ingest_documents(collection_name=request.collection_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return IngestResponse(
        message="문서 인제스트 완료",
        doc_count=count,
    )
