"""LLM 客户端：OpenAI 兼容 / Ollama 两种后端，统一返回文本与真实 usage。"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from .config import LLMConfig


class LLMError(RuntimeError):
    pass


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    calls: int = 0

    def add(self, other: "Usage") -> None:
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.cached_tokens += other.cached_tokens
        self.calls += other.calls

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LLMClient:
    def __init__(self, cfg: LLMConfig | None = None):
        self.cfg = cfg or LLMConfig()

    def _post(self, path: str, payload: dict) -> dict:
        url = self.cfg.base_url.rstrip("/") + path
        headers = {"Content-Type": "application/json"}
        if self.cfg.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=self.cfg.timeout_s) as resp:
            return json.loads(resp.read().decode())

    def chat(self, messages: list[dict], max_tokens: int | None = None) -> tuple[str, Usage]:
        """返回 (文本, usage)。429/5xx/超时做指数退避重试，重试耗尽抛 LLMError。"""
        max_tokens = max_tokens or self.cfg.max_output_tokens
        last_err: Exception | None = None
        for attempt in range(self.cfg.max_retries):
            try:
                if self.cfg.provider == "ollama":
                    # Ollama 原生接口
                    payload = {
                        "model": self.cfg.model,
                        "messages": messages,
                        "stream": False,
                        "options": {"temperature": self.cfg.temperature, "num_predict": max_tokens},
                    }
                    raw = self._post("/api/chat", payload)
                    text = raw["message"]["content"]
                    usage = Usage(
                        prompt_tokens=int(raw.get("prompt_eval_count", 0)),
                        completion_tokens=int(raw.get("eval_count", 0)),
                        calls=1,
                    )
                    return text, usage

                payload = {
                    "model": self.cfg.model,
                    "messages": messages,
                    "temperature": self.cfg.temperature,
                    "max_tokens": max_tokens,
                }
                raw = self._post("/chat/completions", payload)
                msg = raw["choices"][0]["message"]
                text = msg.get("content") or ""
                # 部分模型把内容放在 reasoning_content，仅在 content 为空时兜底
                if not text.strip() and msg.get("reasoning_content"):
                    text = msg["reasoning_content"]
                u = raw.get("usage") or {}
                details = u.get("prompt_tokens_details") or {}
                usage = Usage(
                    prompt_tokens=int(u.get("prompt_tokens", 0)),
                    completion_tokens=int(u.get("completion_tokens", 0)),
                    cached_tokens=int(details.get("cached_tokens", 0) or 0),
                    calls=1,
                )
                return text, usage
            except urllib.error.HTTPError as e:
                body = ""
                try:
                    body = e.read().decode()[:200]
                except Exception:
                    pass
                last_err = LLMError(f"HTTP {e.code}: {body}")
                if e.code in (429, 500, 502, 503, 504):
                    time.sleep(min(2 ** attempt, 8))
                    continue
                raise last_err
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_err = LLMError(f"网络错误: {e}")
                time.sleep(min(2 ** attempt, 8))
            except (KeyError, json.JSONDecodeError) as e:
                last_err = LLMError(f"响应解析失败: {e}")
                time.sleep(1)
        raise LLMError(f"重试 {self.cfg.max_retries} 次仍失败: {last_err}")

    def health(self) -> dict:
        """探测端点可用性，只返回模型名与延迟，不返回任何密钥。"""
        t = time.time()
        text, usage = self.chat([{"role": "user", "content": "Reply with PONG"}], max_tokens=16)
        return {
            "provider": self.cfg.provider,
            "model": self.cfg.model,
            "base_url": self.cfg.base_url,
            "latency_s": round(time.time() - t, 2),
            "reply": text.strip()[:40],
            "usage": usage.__dict__,
        }
