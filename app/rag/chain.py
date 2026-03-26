from langchain_openai import ChatOpenAI
from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough

from app.core.config import settings
from app.rag.vector_store import get_vector_store


SYSTEM_PROMPT = """당신은 호텔 안내 AI 어시스턴트입니다.
아래 컨텍스트를 바탕으로 고객의 질문에 친절하고 정확하게 답변해 주세요.
컨텍스트에 없는 정보는 모른다고 답하세요.

컨텍스트:
{context}
"""

prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    MessagesPlaceholder(variable_name="chat_history"),
    ("human", "{question}"),
])


def _format_docs(docs):
    return "\n\n".join(doc.page_content for doc in docs)


def build_rag_chain(collection_name: str = "hotel_docs"):
    llm = ChatOpenAI(
        model=settings.llm_model,
        openai_api_key=settings.openai_api_key,
        temperature=0.2,
    )
    retriever = get_vector_store(collection_name).as_retriever(
        search_kwargs={"k": settings.top_k_results}
    )
    chain = (
        RunnablePassthrough.assign(context=lambda x: _format_docs(retriever.invoke(x["question"])))
        | prompt
        | llm
        | StrOutputParser()
    )
    return chain, retriever


# 세션별 chain + history 캐시
_sessions: dict[str, dict] = {}


def get_session(session_id: str = "default") -> dict:
    if session_id not in _sessions:
        chain, retriever = build_rag_chain()
        _sessions[session_id] = {
            "chain": chain,
            "retriever": retriever,
            "history": [],
        }
    return _sessions[session_id]


def chat(session_id: str, question: str) -> tuple[str, list]:
    session = get_session(session_id)
    history = session["history"]

    result = session["chain"].invoke({
        "question": question,
        "chat_history": history,
    })

    # 소스 문서 별도 조회
    source_docs = session["retriever"].invoke(question)

    history.append(HumanMessage(content=question))
    history.append(AIMessage(content=result))
    # 최근 10개 메시지만 유지
    if len(history) > 10:
        session["history"] = history[-10:]

    return result, source_docs
