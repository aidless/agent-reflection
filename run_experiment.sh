#!/usr/bin/env bash
# 一条命令复现 250 题主实验：构造任务集 -> 自检 -> 四臂跑批 -> 完整性校验 -> 出统计。
# 模型端点只从环境变量读取，脚本内不含任何密钥。
#   AGENT_BASE_URL  OpenAI 兼容端点，默认 http://127.0.0.1:3425/v1
#   AGENT_MODEL     模型名，默认 opencode-go/deepseek-v4.1-flash
#   AGENT_PROVIDER  openai | ollama，默认 openai
#   AGENT_API_KEY   可选，仅从环境变量读
#
# 用法:
#   ./run_experiment.sh              # 250 任务、四臂串行（耗时取决于端点）
#   PARALLEL=1 ./run_experiment.sh   # 四臂并行
#   LIMIT=5 ./run_experiment.sh      # 先跑 5 个/臂打通链路
#   TASK_SET=main ./run_experiment.sh # 64 题试点集
set -euo pipefail

cd "$(dirname "$0")"
LIMIT="${LIMIT:-0}"
PARALLEL="${PARALLEL:-0}"
TASK_SET="${TASK_SET:-all}"
MAX_STEPS="${MAX_STEPS:-12}"
SEED="${SEED:-7}"
ARMS=("no_memory__baseline" "mem_v1__baseline" "mem_v2__baseline" "mem_v3__baseline")

echo "== 0. 环境 =="
python3 - <<'PY'
from agent.config import LLMConfig
c = LLMConfig()
print("provider:", c.provider, "| model:", c.model, "| base_url:", c.base_url,
      "| api_key:", "已设置" if c.api_key else "未设置(走本地代理)")
PY

echo "== 1. 构造任务集（可重复，无网络依赖） =="
python3 -m bench.tasks
python3 -m bench.verify_tasks

echo "== 2. 跑批（$TASK_SET，limit=$LIMIT，max_steps=$MAX_STEPS） =="
mkdir -p logs experiments/v2 experiments/v3
rm -f experiments/v2/no_memory.csv experiments/v2/mem_v1.csv \
      experiments/v2/mem_v2.csv experiments/v3/mem_v3.csv
run_arm() {
  local arm="$1" name="${1%%__*}" dir="experiments/v2"
  [[ "$name" == *"v3"* ]] && dir="experiments/v3"
  mkdir -p "$dir"
  python3 -m bench.runner --arms "$arm" --task-set "$TASK_SET" --shuffle --seed "$SEED" \
    --limit "$LIMIT" --max-steps "$MAX_STEPS" --reset-memory \
    --csv "${dir}/${name}.csv" --work-dir "${dir}/work" \
    --trace-dir "${dir}/traces" --memory-dir "${dir}/memory" \
    2>&1 | tee "logs/${arm}.log"
}
if [ "$PARALLEL" = "1" ]; then
  for arm in "${ARMS[@]}"; do run_arm "$arm" & done
  wait
else
  for arm in "${ARMS[@]}"; do run_arm "$arm"; done
fi

echo "== 3. 完整性校验 =="
python3 -m bench.check_runs experiments/v2/no_memory.csv \
  experiments/v2/mem_v1.csv experiments/v2/mem_v2.csv experiments/v3/mem_v3.csv

echo "== 4. 统计 =="
python3 -m bench.analyze_memory --csv experiments/v2/no_memory.csv \
  experiments/v2/mem_v1.csv experiments/v2/mem_v2.csv experiments/v3/mem_v3.csv \
  --names no_memory mem_v1 mem_v2 mem_v3 \
  --memory-dir experiments/v2/memory experiments/v3/memory \
  --out experiments/v3/phase3.md
echo "完成：experiments/v3/phase3.md"
