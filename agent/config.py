"""运行配置：全部从环境变量读取，不硬编码路径与密钥。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


@dataclass
class LLMConfig:
    # 默认指向本机 OpenAI 兼容代理；也可用 AGENT_BASE_URL 指向任意兼容端点
    base_url: str = field(default_factory=lambda: _env("AGENT_BASE_URL", "http://127.0.0.1:3425/v1"))
    api_key: str = field(default_factory=lambda: _env("AGENT_API_KEY", ""))
    model: str = field(default_factory=lambda: _env("AGENT_MODEL", "opencode-go/deepseek-v4.1-flash"))
    # openai: /chat/completions；ollama: /api/chat
    provider: str = field(default_factory=lambda: _env("AGENT_PROVIDER", "openai"))
    temperature: float = 0.0
    timeout_s: int = field(default_factory=lambda: int(_env("AGENT_TIMEOUT", "90")))
    max_retries: int = 3

    def label(self) -> str:
        return f"{self.provider}:{self.model}"


@dataclass
class Budget:
    max_steps: int = 12
    wall_timeout_s: int = 240
    max_total_tokens: int = 90000
    max_output_tokens: int = 1200


@dataclass
class CostMode:
    """实验开关：baseline 为朴素实现，optimized 打开全部降本手段。"""

    name: str = "baseline"
    obs_max_chars: int = 4000          # 工具输出截断长度
    test_failures_only: bool = False   # 测试输出只保留失败摘要
    memoize_tools: bool = False        # 相同 (工具, 参数) 直接复用结果
    diff_observation: bool = False     # 编辑后只回传 diff，不回传全文
    memory_topk: int = 3               # 注入的教训条数
    memory_max_chars: int = 900        # 注入教训总长度上限
    auto_finish_on_pass: bool = False  # 测试通过即自动结束，省一次模型调用
    planner_skip_max_files: int = 0    # 源文件数 <= N 时跳过规划调用
    history_window: int = 0            # 0 表示保留全部历史
    max_output_tokens: int = 1200

    def as_dict(self) -> dict:
        return asdict(self)


def cost_mode(name: str) -> CostMode:
    if name == "optimized":
        return CostMode(
            name="optimized",
            obs_max_chars=1200,
            test_failures_only=True,
            memoize_tools=True,
            diff_observation=True,
            memory_topk=2,
            memory_max_chars=480,
            auto_finish_on_pass=True,
            planner_skip_max_files=2,
            history_window=10,
            max_output_tokens=500,
        )
    if name == "aggressive":
        # 只用于回答"能不能再砍一半"：历史窗口 4、输出 800 字、单条记忆 280 字。
        return CostMode(
            name="aggressive",
            obs_max_chars=800,
            test_failures_only=True,
            memoize_tools=True,
            diff_observation=True,
            memory_topk=1,
            memory_max_chars=280,
            auto_finish_on_pass=True,
            planner_skip_max_files=4,
            history_window=4,
            max_output_tokens=300,
        )
    return CostMode(name="baseline")
