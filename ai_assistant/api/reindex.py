from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from db import get_session
from rag.retriever import reindex
from schemas import ReindexResponse

router = APIRouter()


@router.post("/reindex", response_model=ReindexResponse)
async def reindex_endpoint(db: AsyncSession = Depends(get_session)):
    try:
        count = await reindex(db)
        return ReindexResponse(status="success", documents_indexed=count)
    except Exception as e:
        return ReindexResponse(status=f"error: {str(e)[:200]}", documents_indexed=0)
