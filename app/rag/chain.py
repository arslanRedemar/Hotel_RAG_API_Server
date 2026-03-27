# LangGraph 기반 구현으로 이전되었습니다.
# 하위 호환성을 위해 graph.py의 chat 함수를 재내보냅니다.
from app.rag.graph import chat, get_graph

__all__ = ["chat", "get_graph"]
