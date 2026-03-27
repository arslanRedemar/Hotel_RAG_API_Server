from langchain_openai import ChatOpenAI
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from app.core.config import settings
from app.rag.state import RAGState
from app.rag.vector_store import get_vector_store


SYSTEM_PROMPT = """당신은 호텔 안내 AI 어시스턴트입니다.
아래 컨텍스트를 바탕으로 고객의 질문에 친절하고 정확하게 답변해 주세요.
컨텍스트에 없는 정보는 모른다고 답하세요.

컨텍스트:
{context}
"""

# 앱 수명 동안 그래프와 메모리 인스턴스를 싱글톤으로 유지
_memory = MemorySaver()
_graph = None


def _build_graph():
    llm = ChatOpenAI(
        model=settings.llm_model,
        openai_api_key=settings.openai_api_key,
        temperature=0.2,
    )
    retriever = get_vector_store().as_retriever(
        search_kwargs={"k": settings.top_k_results}
    )

    # --- 노드 정의 ---

    def retrieve(state: RAGState) -> dict:
        """최신 사용자 메시지로 벡터 DB를 검색합니다."""
        question = state["messages"][-1].content
        docs = retriever.invoke(question)
        return {"context": docs}

    def generate(state: RAGState) -> dict:
        """검색된 컨텍스트와 대화 이력을 바탕으로 답변을 생성합니다."""
        context_text = "\n\n".join(doc.page_content for doc in state["context"])
        system_msg = SystemMessage(content=SYSTEM_PROMPT.format(context=context_text))
        response = llm.invoke([system_msg] + list(state["messages"]))
        return {"messages": [response]}

    # --- 그래프 구성 ---

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


def chat(session_id: str, question: str) -> tuple[str, list[Document]]:
    """세션 ID로 대화 이력을 유지하며 RAG 응답을 반환합니다."""
    result = get_graph().invoke(
        {"messages": [HumanMessage(content=question)]},
        config={"configurable": {"thread_id": session_id}},
    )
    answer = result["messages"][-1].content
    sources = result.get("context", [])
    return answer, sources
