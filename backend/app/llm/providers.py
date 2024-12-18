"""Provider-independent LLM integration layer.

Supported providers (all optional; the platform is fully
functional offline):
  - openai            (ChatGPT-family / GPT models)
  - anthropic         (Claude API)
  - openrouter        (multi-model gateway)
  - ollama            (local OpenAI-compatible server)
  - openai_compatible (any OpenAI-compatible endpoint: vLLM,
                       LiteLLM, Azure, Groq, Together, ...)
  - offline           (deterministic heuristics; default)

Safety properties:
- Content from evaluation tasks is NEVER sent unless
  ``llm_allow_evaluation_content`` is explicitly enabled.
- Requests are bounded by token caps, timeouts, retries, and
  a configurable daily cost budget.
- API keys are Fernet-encrypted at rest and masked in API
  responses; they are never logged.
- All AI outputs are labelled AI-generated and require human
  approval before any rubric/disposition change.

NOTE on billing: OpenAI API usage is billed separately from a
ChatGPT Plus/Pro subscription; a ChatGPT plan does NOT grant
API access. Anthropic and OpenRouter have their own billing.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import settings
from app.models import AIProviderSetting, LLMUsageLog
from app.security import decrypt_secret, encrypt_secret, redact_text

log = logging.getLogger(__name__)

PROVIDERS = ("openai", "anthropic", "openrouter", "openai_compatible", "ollama", "offline")

# Process-wide sliding window so the per-minute guard applies across the
# short-lived LLMClient instances created per request.
_RATE_WINDOW: list[float] = []

# Rough USD-per-1K-token list prices for cost estimation
DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o": (0.0025, 0.01),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4-turbo": (0.01, 0.03),
    "claude-3-5-sonnet-20241022": (0.003, 0.015),
    "claude-3-5-haiku-20241022": (0.0008, 0.004),
    "claude-3-opus-20240229": (0.015, 0.075),
}


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str | None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float = 0.0
    offline: bool = False
    warnings: list[str] = field(default_factory=list)


class LLMError(RuntimeError):
    pass


class ProviderConfig:
    """Persisted provider configuration (API keys encrypted)."""

    def __init__(self, db, owner_id: str | None = None):
        self.db = db
        self.owner_id = owner_id

    def get_active(self) -> dict[str, Any] | None:
        row = self.db.query(AIProviderSetting).filter(AIProviderSetting.is_active.is_(True)).first()
        if row is None:
            # fall back to env-based configuration
            if settings.llm_provider:
                return self._env_config()
            return None
        cfg: dict[str, Any] = {
            "provider": row.provider,
            "base_url": row.base_url,
            "model": row.model,
            "label": row.label,
        }
        if row.encrypted_api_key:
            cfg["api_key"] = decrypt_secret(row.encrypted_api_key)
        cfg.update(row.extra_json or {})
        return cfg

    def _env_config(self) -> dict[str, Any]:
        return {
            "provider": settings.llm_provider,
            "base_url": settings.llm_base_url,
            "model": settings.llm_model,
            "api_key": settings.llm_api_key,
        }

    def save(
        self,
        provider: str,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        label: str | None = None,
        extra: dict | None = None,
        activate: bool = True,
    ) -> AIProviderSetting:
        if provider not in PROVIDERS:
            raise LLMError(f"Unknown provider: {provider}")
        row = AIProviderSetting(
            owner_id=self.owner_id or "system",
            provider=provider,
            label=label,
            base_url=base_url,
            model=model,
            extra_json=extra,
            is_active=activate,
        )
        if api_key:
            row.encrypted_api_key = encrypt_secret(api_key)
        if activate:
            self.db.query(AIProviderSetting).update({"is_active": False})
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def mask(self) -> dict[str, Any] | None:
        cfg = self.get_active()
        if cfg is None:
            return None
        key = cfg.get("api_key")
        if key:
            cfg["api_key"] = f"{key[:2]}…{key[-4:]}" if len(key) > 6 else "****"
        cfg.pop("extra_json", None)
        return cfg


class LLMClient:
    def __init__(self, db, config: dict[str, Any] | None = None):
        self.db = db
        self.cfg = config or {}
        self.provider = self.cfg.get("provider") or "offline"

    # ---------------- public helpers ----------------
    def test_connection(self) -> dict[str, Any]:
        if self.provider == "offline" or not self.provider:
            return {"ok": True, "provider": "offline", "detail": "Offline deterministic mode."}
        try:
            # Health-check ping intentionally bypasses the LLM_ENABLED master
            # switch so admins can verify credentials/endpoints before turning
            # live evaluation assistance on. It sends no evaluation content.
            result = self._dispatch("Reply with OK.", 8, "You are a connectivity health check.")
            return {
                "ok": True,
                "provider": self.provider,
                "model": result.model,
                "detail": f"Connected. {result.completion_tokens} tokens used.",
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "provider": self.provider, "detail": str(exc)}

    def complete(self, prompt: str, max_tokens: int | None = None, system: str | None = None) -> LLMResult:
        if not settings.llm_enabled or not self.provider or self.provider == "offline":
            return LLMResult(
                text="",
                provider="offline",
                model=None,
                offline=True,
                warnings=["LLM assistance is disabled or not configured."],
            )
        self._check_budget()
        self._check_rate_limit()
        max_tokens = min(max_tokens or settings.llm_max_tokens, settings.llm_max_tokens)
        start = time.time()
        result = self._dispatch(prompt, max_tokens, system)
        self._log_usage(prompt, result, time.time() - start)
        return result

    # ---------------- dispatch ----------------
    def _dispatch(self, prompt: str, max_tokens: int, system: str | None) -> LLMResult:
        if self.provider in ("openai", "openai_compatible", "ollama"):
            return self._openai_compatible(prompt, max_tokens, system)
        if self.provider == "anthropic":
            return self._anthropic(prompt, max_tokens, system)
        if self.provider == "openrouter":
            return self._openrouter(prompt, max_tokens, system)
        raise LLMError(f"Unsupported provider: {self.provider}")

    def _openai_compatible(self, prompt, max_tokens, system) -> LLMResult:
        base = self.cfg.get("base_url") or "https://api.openai.com/v1"
        key = self.cfg.get("api_key")
        model = self.cfg.get("model") or "gpt-4o-mini"
        url = base.rstrip("/")
        if not url.endswith("/chat/completions"):
            url = url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.2,
        }
        return self._request(url, headers, payload, model)

    def _anthropic(self, prompt, max_tokens, system) -> LLMResult:
        url = (self.cfg.get("base_url") or "https://api.anthropic.com/v1").rstrip("/") + "/messages"
        key = self.cfg.get("api_key")
        model = self.cfg.get("model") or "claude-3-5-haiku-20241022"
        headers = {
            "x-api-key": key or "",
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            payload["system"] = system
        return self._request(url, headers, payload, model, anthropic=True)

    def _openrouter(self, prompt, max_tokens, system) -> LLMResult:
        cfg = dict(self.cfg)
        cfg["base_url"] = cfg.get("base_url") or "https://openrouter.ai/api/v1"
        client = LLMClient(self.db, cfg)
        return client._openai_compatible(prompt, max_tokens, system)

    def _request(self, url, headers, payload, model, anthropic=False) -> LLMResult:
        timeout = settings.llm_timeout_seconds
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = httpx.post(url, json=payload, headers=headers, timeout=timeout)
                if resp.status_code == 429:
                    wait = 2**attempt
                    log.warning("LLM rate-limited; retrying in %ss", wait)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                if anthropic:
                    text = "".join(b.get("text", "") for b in data.get("content", []))
                    usage = data.get("usage", {})
                    return LLMResult(
                        text=text,
                        provider="anthropic",
                        model=model,
                        prompt_tokens=usage.get("input_tokens", 0),
                        completion_tokens=usage.get("output_tokens", 0),
                        estimated_cost_usd=self._cost(
                            model, usage.get("input_tokens", 0), usage.get("output_tokens", 0)
                        ),
                    )
                choice = data.get("choices") or [{}]
                text = choice[0].get("message", {}).get("content", "")
                usage = data.get("usage", {})
                return LLMResult(
                    text=text,
                    provider=self.provider,
                    model=model,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    estimated_cost_usd=self._cost(
                        model, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
                    ),
                )
            except httpx.HTTPError as exc:
                last_exc = exc
                time.sleep(0.5 * (attempt + 1))
        raise LLMError(f"LLM request failed after retries: {last_exc}")

    # ---------------- guards ----------------
    def _check_budget(self):
        rows = (
            self.db.query(LLMUsageLog)
            .filter(
                LLMUsageLog.created_at
                >= dt.datetime.now(dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)
            )
            .all()
        )
        spent = sum(r.estimated_cost_usd for r in rows)
        if spent >= settings.llm_max_cost_usd:
            raise LLMError(f"Daily LLM budget of ${settings.llm_max_cost_usd:.2f} exhausted.")

    def _check_rate_limit(self):
        now = time.time()
        _RATE_WINDOW[:] = [t for t in _RATE_WINDOW if now - t < 60]
        if len(_RATE_WINDOW) >= settings.llm_max_requests_per_minute:
            raise LLMError("LLM rate limit reached; try again shortly.")
        _RATE_WINDOW.append(now)

    def _cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        # Local Ollama inference has no per-token API cost.
        if self.provider == "ollama":
            return 0.0
        in_price, out_price = DEFAULT_PRICES.get(model, (0.001, 0.002))
        return round(
            in_price * prompt_tokens / 1000 + out_price * completion_tokens / 1000,
            6,
        )

    def _log_usage(self, prompt: str, result: LLMResult, elapsed: float):
        row = LLMUsageLog(
            provider=result.provider or self.provider,
            model=result.model,
            endpoint="chat/completions",
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            estimated_cost_usd=result.estimated_cost_usd,
            status="ok" if not result.offline else "skipped_offline",
        )
        self.db.add(row)
        try:
            self.db.commit()
        except Exception:  # noqa: BLE001
            self.db.rollback()
        # Never log prompts verbatim (may contain evaluation content).
        log.debug(
            "llm call provider=%s model=%s elapsed=%.2fs cost=$%.5f",
            redact_text(result.provider or ""),
            result.model,
            elapsed,
            result.estimated_cost_usd,
        )


# ---------------- offline deterministic analysis ----------------


def summarize_disagreement_case(
    prompt: str,
    response: str,
    ratings: list[dict[str, Any]],
    rationales: dict[str, str],
) -> dict[str, Any]:
    """Deterministic offline 'AI-assisted' case summary.

    Extracts the divergent categories, score gaps, and the most
    divergent rationale phrases without any external API.
    """
    summary_points = []
    divergences = []
    keys = set()
    for r in ratings:
        keys |= set((r.get("scores") or {}).keys())
    for key in sorted(keys):
        vals = [r["scores"][key] for r in ratings if key in (r.get("scores") or {})]
        if not vals:
            continue
        try:
            numeric = [float(v) for v in vals]
            gap = max(numeric) - min(numeric)
        except (TypeError, ValueError):
            numeric = None
            distinct = {str(v) for v in vals}
            gap = len(distinct) - 1 if len(distinct) > 1 else 0
        if gap > 0:
            divergences.append(
                {
                    "category": key,
                    "values": [str(v) for v in vals],
                    "spread": gap,
                }
            )
    for r in ratings:
        rat = (rationales.get(r.get("reviewer_id", ""), "") or "").strip()
        if not rat:
            continue
        sentences = [s.strip() for s in re.split(r"[.!?]+", rat) if len(s.strip()) > 20]
        if sentences:
            # extractive pick: longest sentence (heuristic for detail)
            summary_points.append(
                {
                    "reviewer_id": r.get("reviewer_id"),
                    "key_sentence": max(sentences, key=len)[:300],
                }
            )
    return {
        "method": "deterministic_offline",
        "ai_generated": False,
        "divergent_categories": divergences,
        "key_evidence_points": summary_points,
        "note": (
            "Offline deterministic summary. Configure an LLM provider " "for richer narrative analysis."
        ),
    }


def suggest_rubric_wording(category_name: str, definition: str | None) -> dict[str, Any]:
    """Deterministic rubric-improvement suggestions (offline)."""
    issues = []
    if not definition or len(definition.strip()) < 40:
        issues.append("Definition is missing or too short to guide consistent scoring.")
    vague_terms = ["good", "bad", "quality", "appropriate", "relevant"]
    if definition:
        found = [t for t in vague_terms if re.search(rf"\b{t}\b", definition.lower())]
        if found:
            issues.append(
                f"Vague evaluative terms detected ({', '.join(found)}); "
                "replace with observable, measurable criteria."
            )
    return {
        "method": "deterministic_offline",
        "ai_generated": False,
        "category": category_name,
        "identified_issues": issues,
        "suggested_improvements": [
            "Add a two-sentence operational definition with observable indicators",
            "Provide a labelled example at every scale point",
            "Define explicit boundary cases between adjacent levels",
        ],
    }


def cluster_explanations(rationales: list[str]) -> list[dict[str, Any]]:
    """Deterministic semantic-ish clustering of disagreement
    rationales via keyword signatures (TF over a fixed lexicon).
    Labelled as heuristic clustering."""
    themes = {
        "hallucination": ["hallucinat", "fabricat", "invented", "factual", "incorrect", "wrong fact"],
        "completeness": ["missing", "incomplete", "omitted", "did not mention", "lacks"],
        "style": ["tone", "style", "format", "structure", "verbose", "concise"],
        "safety": ["harmful", "unsafe", "bias", "offensive", "policy"],
        "relevance": ["irrelevant", "off-topic", "tangential", "did not answer"],
    }
    clusters: dict[str, list[str]] = {}
    for text in rationales:
        low = text.lower()
        hit = None
        best = 0
        for theme, terms in themes.items():
            count = sum(low.count(t) for t in terms)
            if count > best:
                best = count
                hit = theme
        if hit:
            clusters.setdefault(hit, []).append(text[:200])
        else:
            clusters.setdefault("other", []).append(text[:200])
    return [
        {"theme": theme, "count": len(items), "examples": items[:3]}
        for theme, items in sorted(clusters.items(), key=lambda kv: -len(kv[1]))
    ]


def build_client(db) -> LLMClient:
    cfg = ProviderConfig(db).get_active()
    return LLMClient(db, cfg or {"provider": "offline"})
