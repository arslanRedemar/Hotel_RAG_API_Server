from typing import Annotated, Optional
from typing_extensions import TypedDict
from langchain_core.documents import Document
from langgraph.graph.message import add_messages


class RAGState(TypedDict):
    messages: Annotated[list, add_messages]       # 대화 이력 (자동 누적)
    context: list[Document]                       # 검색된 문서 청크
    department_filter: Optional[list[int]]        # RAG-F20: 부서 필터
