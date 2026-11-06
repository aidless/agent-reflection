## A/B 结果（同任务、同模型、同预算）

| 臂 | 样本 | 成功率 | 95% CI | token/任务 | calls/任务 | 平均步数 |
|---|---|---|---|---|---|---|
| no_memory__baseline | 5 | 80.0% (4/5) | 40.0%–100.0% | 15395 | 12.0 | 11.0 |
| mem_v2__baseline | 5 | 60.0% (3/5) | 20.0%–100.0% | 16654 | 11.4 | 10.4 |

### 配对 McNemar

- no_memory__baseline vs mem_v2__baseline: n=5，不一致 1 (A 赢 1 / B 赢 0)，p=1.000，该样本量可检测的最小差异≈88.5%

### 按任务族（成功数 · 平均 token · 平均步数）

| 任务族 | mem_v2__baseline | no_memory__baseline |
|---|---|---|
| boundary+cache_state | 0/1 · 17.3k · 11步 | 1/1 · 11.5k · 9步 |
| boundary+mutable_default | 1/1 · 15.0k · 10步 | 1/1 · 20.5k · 14步 |
| boundary+parsing | 0/1 · 27.6k · 14步 | 0/1 · 19.4k · 12步 |
| paging | 2/2 · 11.7k · 8步 | 2/2 · 12.8k · 10步 |

### 记忆的净效果（相对无记忆臂，按任务族）


**mem_v2__baseline**

| 任务族 | 记忆臂 胜 | 记忆臂 负 | 持平 | 净变化 |
|---|---|---|---|---|
| boundary+cache_state | 0 | 1 | 0 | -1 |

### 记忆臂失败 / 无记忆臂成功的任务（归因）

| 臂 | 任务 | 失败模式 | 步数 | 注入 | 归因 | 证据 |
|---|---|---|---|---|---|---|
| mem_v2__baseline | multi-boundary-lower_bound-x-cache_state-counter_reset | wrong_fix | 11 | 0 | 无注入（与记忆无关） | 检索未命中任何教训 |

### 回滚可观测性（自然任务）

| 臂 | 进入回滚判定次数 | 真正执行回滚 | 哈希校验通过 | 平均 run_tests/任务 | test_runs≥2 的任务 |
|---|---|---|---|---|---|
| no_memory__baseline | 0 | 0 | 0 | 1.0 | 0 |
| mem_v2__baseline | 1 | 0 | 0 | 1.2 | 1 |

> 回滚只在“测试失败（写操作后）→ 编辑 → 再测试，且失败测试集合完全一致”时触发。自然任务集里 Agent 平均只跑 1.x 次测试就耗尽步数，这是回滚次数为 0 的结构性原因；分支本身由 `bench/rollback_probe.py` 的受控任务验证可执行（见 README）。
