"""RAG LangGraph 파이프라인 — 할루시네이션 방지 + LLM 라우팅 + 부서 필터 (RAG-F13/F17/F20)"""

from dataclasses import dataclass
from typing import Optional

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.core.config import settings
from app.core.llm_router import TaskTier, llm_router
from app.rag.state import RAGState
from app.rag.vector_store import get_vector_store

# ── 상수 ────────────────────────────────────────────────────

NO_ANSWER_RESPONSE = (
    "제공된 문서에서 해당 정보를 찾을 수 없습니다. "
    "관련 부서 담당자에게 문의해 주세요."
)

SYSTEM_PROMPT = """\
당신은 호텔 운영 전문 AI 어시스턴트입니다.

[중요 규칙]
1. 반드시 아래 제공된 컨텍스트 문서만을 근거로 답변하세요.
2. 컨텍스트에 없는 정보는 절대 생성하지 마세요.
3. 컨텍스트에서 답을 찾을 수 없다면 정확히 이렇게 답하세요:
   "{no_answer}"
4. 답변 말미에 참고한 문서명(출처)을 반드시 언급하세요.
5. 친절하고 명확한 한국어로 답변하세요.

[컨텍스트 문서]
{{context}}
""".format(no_answer=NO_ANSWER_RESPONSE)


# ── 소스 디테일 ───────────────────────────────────────────────

@dataclass
class SourceDetail:
    """RAG-F11: 출처 문서 상세 정보"""
    source: str
    page: Optional[int] = None
    section: Optional[str] = None
    chunk_preview: str = ""
    doc_type: Optional[str] = None
    department_id: Optional[str] = None


def build_source_detail(doc: Document) -> SourceDetail:
    """Document 객체를 SourceDetail로 변환 (RAG-F11)"""
    meta = doc.metadata or {}
    preview = doc.page_content[:120].strip()
    if len(doc.page_content) > 120:
        preview += "..."
    return SourceDetail(
        source=meta.get("source", ""),
        page=meta.get("page"),
        section=meta.get("section"),
        chunk_preview=preview,
        doc_type=meta.get("doc_type"),
        department_id=meta.get("department_id"),
    )


# ── 쿼리 복잡도 분류 ──────────────────────────────────────────

def classify_query_complexity(query: str, retrieved_docs: list[Document]) -> TaskTier:
    """RAG-F17: 쿼리 복잡도 기반 LLM 티어 결정.

    단순 쿼리 (단일 소스 + 짧은 질문) → LOCAL_FIRST (로컬 LLM)
    복합 쿼리 (다중 소스 or 긴 질문) → CLOUD_FIRST
    """
    if len(retrieved_docs) <= 1 and len(query) < 50:
        return TaskTier.LOCAL_FIRST
    return TaskTier.CLOUD_FIRST


# ── 검색기 빌더 ───────────────────────────────────────────────

def _build_retriever(department_ids: list[int] | None = None):
    """RAG-F20~22: 부서 필터 적용 검색기 생성"""
    vs = get_vector_store()
    search_kwargs: dict = {"k": settings.top_k_results}

    if department_ids:
        dept_strs = [str(d) for d in department_ids]
        search_kwargs["filter"] = {"department_id": {"$in": dept_strs}}

    return vs.as_retriever(search_kwargs=search_kwargs)


# ── 그래프 빌더 ───────────────────────────────────────────────

_memory = MemorySaver()
_graph = None


def _build_graph():
    def retrieve(state: RAGState) -> dict:
        question = state["messages"][-1].content
        dept_ids = state.get("department_filter")
        retriever = _build_retriever(department_ids=dept_ids)
        docs = retriever.invoke(question)
        return {"context": docs}

    def generate(state: RAGState) -> dict:
        docs = state.get("context", [])
        context_text = "\n\n".join(
            f"[{doc.metadata.get('source', '문서')}] {doc.page_content}"
            for doc in docs
        )
        system_msg = SystemMessage(
            content=SYSTEM_PROMPT.replace("{context}", context_text or "관련 문서 없음")
        )

        # RAG-F17: 쿼리 복잡도 기반 LLM 선택
        question = state["messages"][-1].content
        tier = classify_query_complexity(question, docs)
        llm = llm_router.get_llm(tier)

        response = llm.invoke([system_msg] + list(state["messages"]))
        return {"messages": [response]}

    graph = StateGraph(RAGState)
    graph.add_node("retrieve", retrieve)
    graph.add_node("generate", generate)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", END)
    return graph.compile(checkpointer=_memory)


def get_graph():
    global _graph
    if _graph is None:
        _graph = _build_graph()
    return _graph


# ── 공개 인터페이스 ───────────────────────────────────────────

def chat(
    session_id: str,
    question: str,
    department_ids: list[int] | None = None,
) -> tuple[str, list[SourceDetail]]:
    """RAG-F11/F13/F17/F20: 세션 대화, 소스 디테일 반환, 부서 필터 지원"""
    initial_state: dict = {
        "messages": [HumanMessage(content=question)],
        "department_filter": department_ids,
    }
    result = get_graph().invoke(
        initial_state,
        config={"configurable": {"thread_id": session_id}},
    )
    answer = result["messages"][-1].content
    raw_docs = result.get("context", [])
    source_details = [build_source_detail(doc) for doc in raw_docs]
    return answer, source_details
