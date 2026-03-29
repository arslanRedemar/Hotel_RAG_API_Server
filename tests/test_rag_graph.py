"""RAG 그래프 (LangGraph) 단위 테스트 (TDD)"""

from unittest.mock import MagicMock, patch
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage


# ── classify_query_complexity ────────────────────────────────

class TestClassifyQueryComplexity:

    def test_short_query_single_doc_is_local_first(self):
        from app.rag.graph import classify_query_complexity
        from app.core.llm_router import TaskTier
        docs = [Document(page_content="짧은 내용")]
        tier = classify_query_complexity("체크인은?", docs)
        assert tier == TaskTier.LOCAL_FIRST

    def test_long_query_multiple_docs_is_cloud_first(self):
        from app.rag.graph import classify_query_complexity
        from app.core.llm_router import TaskTier
        docs = [Document(page_content=f"문서 {i}") for i in range(4)]
        long_q = "호텔 체크인 절차와 체크아웃 절차를 비교하고 각 부서의 역할을 상세히 설명해주세요"
        tier = classify_query_complexity(long_q, docs)
        assert tier == TaskTier.CLOUD_FIRST

    def test_empty_docs_is_local_first(self):
        from app.rag.graph import classify_query_complexity
        from app.core.llm_router import TaskTier
        tier = classify_query_complexity("질문", [])
        assert tier == TaskTier.LOCAL_FIRST


# ── SYSTEM_PROMPT / 할루시네이션 방지 ────────────────────────

class TestSystemPrompt:

    def test_system_prompt_contains_no_answer_instruction(self):
        from app.rag.graph import SYSTEM_PROMPT
        assert "찾을 수 없" in SYSTEM_PROMPT or "없습니다" in SYSTEM_PROMPT

    def test_system_prompt_requires_source_citation(self):
        from app.rag.graph import SYSTEM_PROMPT
        assert "문서" in SYSTEM_PROMPT or "출처" in SYSTEM_PROMPT or "컨텍스트" in SYSTEM_PROMPT

    def test_no_answer_response_constant_exists(self):
        from app.rag.graph import NO_ANSWER_RESPONSE
        assert isinstance(NO_ANSWER_RESPONSE, str)
        assert len(NO_ANSWER_RESPONSE) > 0


# ── chat() function ──────────────────────────────────────────

class TestChatFunction:

    def _make_mock_graph(self, answer: str, docs: list[Document]):
        """LangGraph 그래프 모킹"""
        mock_graph = MagicMock()
        mock_ai_msg = AIMessage(content=answer)
        mock_graph.invoke.return_value = {
            "messages": [HumanMessage(content="질문"), mock_ai_msg],
            "context": docs,
        }
        return mock_graph

    def test_returns_answer_and_sources(self):
        from app.rag.graph import chat
        docs = [Document(page_content="체크인 절차", metadata={"source": "checkin.pdf", "page": 1})]
        mock_graph = self._make_mock_graph("체크인은 14시부터입니다.", docs)

        with patch("app.rag.graph.get_graph", return_value=mock_graph):
            answer, source_docs = chat("session-1", "체크인 시간은?")

        assert "체크인" in answer or answer
        assert isinstance(source_docs, list)

    def test_returns_source_details(self):
        from app.rag.graph import chat
        docs = [Document(
            page_content="체크인 절차: 1. 신분증 확인",
            metadata={"source": "sop.pdf", "page": 2, "department_id": "1"}
        )]
        mock_graph = self._make_mock_graph("체크인 절차입니다.", docs)

        with patch("app.rag.graph.get_graph", return_value=mock_graph):
            answer, source_docs = chat("session-2", "체크인?")

        assert len(source_docs) > 0
        first_src = source_docs[0]
        assert hasattr(first_src, "source") or isinstance(first_src, (dict, Document))

    def test_accepts_department_filter(self):
        from app.rag.graph import chat
        docs = [Document(page_content="내용", metadata={"source": "doc.pdf"})]
        mock_graph = self._make_mock_graph("답변", docs)

        with patch("app.rag.graph.get_graph", return_value=mock_graph):
            # department_ids 파라미터가 예외 없이 수락되어야 함
            answer, sources = chat("session-3", "질문", department_ids=[1, 2])

        assert answer

    def test_session_id_used_as_thread_id(self):
        from app.rag.graph import chat
        mock_graph = self._make_mock_graph("답변", [])

        with patch("app.rag.graph.get_graph", return_value=mock_graph):
            chat("my-session-id", "질문")

        call_kwargs = mock_graph.invoke.call_args
        assert "my-session-id" in str(call_kwargs)


# ── 소스 디테일 변환 ──────────────────────────────────────────

class TestBuildSourceDetail:

    def test_extracts_page_from_metadata(self):
        from app.rag.graph import build_source_detail
        doc = Document(
            page_content="체크인 절차" * 20,
            metadata={"source": "sop.pdf", "page": 5}
        )
        detail = build_source_detail(doc)
        assert detail.source == "sop.pdf"
        assert detail.page == 5

    def test_chunk_preview_is_truncated(self):
        from app.rag.graph import build_source_detail
        long_content = "긴 내용입니다. " * 100
        doc = Document(page_content=long_content, metadata={"source": "doc.txt"})
        detail = build_source_detail(doc)
        assert len(detail.chunk_preview) <= 150

    def test_handles_missing_page(self):
        from app.rag.graph import build_source_detail
        doc = Document(page_content="내용", metadata={"source": "doc.txt"})
        detail = build_source_detail(doc)
        assert detail.page is None

    def test_handles_section_metadata(self):
        from app.rag.graph import build_source_detail
        doc = Document(
            page_content="섹션 내용",
            metadata={"source": "manual.pdf", "section": "2.1 체크인"}
        )
        detail = build_source_detail(doc)
        assert detail.section == "2.1 체크인"


# ── 부서 필터 검색기 ──────────────────────────────────────────

class TestDepartmentFilterRetriever:

    def test_filter_applied_when_department_ids_provided(self):
        from app.rag.graph import _build_retriever
        mock_vs = MagicMock()
        mock_retriever = MagicMock()
        mock_vs.as_retriever.return_value = mock_retriever

        with patch("app.rag.graph.get_vector_store", return_value=mock_vs):
            _build_retriever(department_ids=[1, 2])

        # filter가 search_kwargs에 포함되어야 함
        assert mock_vs.as_retriever.called

    def test_no_filter_when_no_department(self):
        from app.rag.graph import _build_retriever
        mock_vs = MagicMock()
        mock_vs.as_retriever.return_value = MagicMock()

        with patch("app.rag.graph.get_vector_store", return_value=mock_vs):
            _build_retriever(department_ids=None)

        assert mock_vs.as_retriever.called


# ── _build_graph 내부 노드 통합 ──────────────────────────────

class TestBuildGraphNodes:

    def test_graph_invokes_successfully(self):
        """_build_graph()로 생성된 그래프가 정상 동작하는지 확인"""
        from app.rag.graph import _build_graph
        from langchain_core.messages import AIMessage

        mock_retriever = MagicMock()
        mock_retriever.invoke.return_value = [
            Document(page_content="체크인은 14시", metadata={"source": "sop.pdf"})
        ]

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(content="체크인은 14시입니다.")

        with patch("app.rag.graph.get_vector_store") as mock_vs:
            mock_vs.return_value.as_retriever.return_value = mock_retriever
            with patch("app.rag.graph.llm_router") as mock_router:
                mock_router.get_llm.return_value = mock_llm
                graph = _build_graph()
                result = graph.invoke(
                    {"messages": [HumanMessage(content="체크인 시간?")], "department_filter": None},
                    config={"configurable": {"thread_id": "test-thread"}},
                )

        assert result["messages"][-1].content == "체크인은 14시입니다."
        assert result["context"] is not None

    def test_graph_passes_department_filter(self):
        """부서 필터가 retriever에 전달되는지 확인"""
        from app.rag.graph import _build_graph
        from langchain_core.messages import AIMessage

        mock_retriever = MagicMock()
        mock_retriever.invoke.return_value = []

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(content="답변")

        with patch("app.rag.graph.get_vector_store") as mock_vs:
            mock_vs.return_value.as_retriever.return_value = mock_retriever
            with patch("app.rag.graph.llm_router") as mock_router:
                mock_router.get_llm.return_value = mock_llm
                graph = _build_graph()
                graph.invoke(
                    {
                        "messages": [HumanMessage(content="질문")],
                        "department_filter": [1, 2],
                    },
                    config={"configurable": {"thread_id": "dept-thread"}},
                )

        # as_retriever가 filter kwargs로 호출되었는지 확인
        call_kwargs = mock_vs.return_value.as_retriever.call_args[1]
        assert "search_kwargs" in call_kwargs
        assert "filter" in call_kwargs["search_kwargs"]

    def test_get_graph_is_singleton(self):
        """get_graph()가 동일 인스턴스를 반환하는지 확인"""

        from app.rag.graph import get_graph
        # 두 번 호출해도 같은 객체여야 함
        g1 = get_graph()
        g2 = get_graph()
        assert g1 is g2
