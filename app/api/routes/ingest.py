from fastapi import APIRouter, HTTPException

from app.models.schemas import IngestRequest, IngestResponse
from app.rag.ingest import ingest_documents

router = APIRouter(prefix="/ingest", tags=["Ingest"])


@router.post("", response_model=IngestResponse)
async def ingest(request: IngestRequest = IngestRequest()):
    try:
        result = ingest_documents(collection_name=request.collection_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    chunk_count = result.get("chunk_count", 0) if isinstance(result, dict) else int(result)
    return IngestResponse(
        message="문서 인제스트 완료",
        doc_count=chunk_count,
    )
