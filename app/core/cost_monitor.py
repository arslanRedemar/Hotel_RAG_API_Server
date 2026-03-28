"""LLM 토큰 사용량 및 비용 모니터링 (SYS-F72, SYS-F73)"""

import logging
from dataclasses import dataclass, field
from threading import Lock

logger = logging.getLogger(__name__)

# gpt-4o-mini: $0.15/1M input tokens, $0.60/1M output tokens
# gpt-4o:      $5.00/1M input tokens, $15.00/1M output tokens
_MODEL_PRICE: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (5.00, 15.00),
}


@dataclass
class _ModuleUsage:
    module: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    call_count: int = 0
    fallback_count: int = 0   # 로컬→클라우드 폴백 횟수


_store: dict[str, _ModuleUsage] = {}
_lock = Lock()


def record_usage(
    module: str,
    prompt_tokens: int,
    completion_tokens: int,
    model: str = "gpt-4o-mini",
    is_fallback: bool = False,
) -> None:
    """모듈별 클라우드 API 토큰 사용량 기록 (SYS-F72).

    Args:
        module: 호출 모듈명 e.g. "rag", "sop_extraction", "work_order"
        prompt_tokens: 입력 토큰 수
        completion_tokens: 출력 토큰 수
        model: OpenAI 모델 ID
        is_fallback: 로컬→클라우드 폴백 여부
    """
    in_price, out_price = _MODEL_PRICE.get(model, (0.15, 0.60))
    cost = (prompt_tokens * in_price + completion_tokens * out_price) / 1_000_000

    with _lock:
        if module not in _store:
            _store[module] = _ModuleUsage(module=module)
        u = _store[module]
        u.prompt_tokens += prompt_tokens
        u.completion_tokens += completion_tokens
        u.cost_usd += cost
        u.call_count += 1
        if is_fallback:
            u.fallback_count += 1

    _check_budget_alert()


def get_usage_summary() -> list[dict]:
    """대시보드용 모듈별 사용량 집계 반환 (SYS-F72)."""
    with _lock:
        return [
            {
                "module": u.module,
                "call_count": u.call_count,
                "fallback_count": u.fallback_count,
                "prompt_tokens": u.prompt_tokens,
                "completion_tokens": u.completion_tokens,
                "total_tokens": u.prompt_tokens + u.completion_tokens,
                "cost_usd": round(u.cost_usd, 4),
            }
            for u in _store.values()
        ]


def get_total_cost() -> float:
    with _lock:
        return sum(u.cost_usd for u in _store.values())


def _check_budget_alert() -> None:
    """월 예산 80% 초과 시 경고 로그 발생 (SYS-F73)."""
    from app.core.config import settings

    budget = settings.monthly_llm_budget_usd
    if budget <= 0:
        return

    total = get_total_cost()
    if total >= budget * 0.8:
        logger.warning(
            "[SYS-F73] LLM 월 예산 80%% 도달: $%.2f / $%.2f",
            total,
            budget,
        )
