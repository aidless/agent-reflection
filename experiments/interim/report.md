## A/B 结果（同任务、同模型、同预算）

| 臂 | 样本 | 成功率 | 95% CI | token/任务 | calls/任务 | 平均步数 |
|---|---|---|---|---|---|---|
| no_memory__baseline | 31 | 80.6% (25/31) | 64.5%–93.5% | 18462 | 12.9 | 11.9 |
| memory__baseline | 27 | 77.8% (21/27) | 63.0%–92.6% | 20323 | 13.2 | 12.2 |
| memory__optimized | 40 | 70.0% (28/40) | 55.0%–82.5% | 12941 | 10.1 | 10.1 |

### 配对 McNemar

- no_memory__baseline vs memory__baseline: n=27，不一致 1 (A 赢 1 / B 赢 0)，p=1.000，该样本量可检测的最小差异≈38.1%
- no_memory__baseline vs memory__optimized: n=31，不一致 5 (A 赢 4 / B 赢 1)，p=0.375，该样本量可检测的最小差异≈35.6%
- memory__baseline vs memory__optimized: n=27，不一致 3 (A 赢 3 / B 赢 0)，p=0.250，该样本量可检测的最小差异≈38.1%

### 按任务族（成功数 · 平均 token · 平均步数）

| 任务族 | memory__baseline | memory__optimized | no_memory__baseline |
|---|---|---|---|
| boundary | - | 3/4 · 12.7k · 10步 | - |
| boundary+parsing | 3/4 · 24.7k · 14步 | 3/8 · 18.5k · 13步 | 3/4 · 23.1k · 14步 |
| cache_state | 4/4 · 13.9k · 10步 | 3/4 · 11.5k · 9步 | 4/4 · 13.4k · 10步 |
| mutable_default | 1/1 · 15.5k · 12步 | 4/4 · 5.3k · 6步 | 3/3 · 7.8k · 7步 |
| mutable_default+recursion | 1/2 · 18.5k · 12步 | 3/4 · 14.8k · 12步 | 3/4 · 17.2k · 12步 |
| paging+types | 4/8 · 24.5k · 14步 | 4/8 · 16.5k · 12步 | 4/8 · 22.2k · 14步 |
| parsing | 4/4 · 23.9k · 13步 | 4/4 · 9.5k · 8步 | 4/4 · 26.7k · 14步 |
| recursion | 4/4 · 12.6k · 10步 | 4/4 · 5.6k · 6步 | 4/4 · 12.4k · 10步 |

### 记忆的净效果（相对无记忆臂，按任务族）


**memory__baseline**

| 任务族 | 记忆臂 胜 | 记忆臂 负 | 持平 | 净变化 |
|---|---|---|---|---|
| mutable_default+recursion | 0 | 1 | 1 | -1 |

**memory__optimized**

| 任务族 | 记忆臂 胜 | 记忆臂 负 | 持平 | 净变化 |
|---|---|---|---|---|
| boundary+parsing | 0 | 2 | 2 | -2 |
| cache_state | 0 | 1 | 3 | -1 |
| mutable_default+recursion | 1 | 1 | 2 | +0 |

### 记忆臂失败 / 无记忆臂成功的任务（归因）

| 臂 | 任务 | 失败模式 | 步数 | 注入 | 归因 | 证据 |
|---|---|---|---|---|---|---|
| memory__baseline | multi-mutable_default-Stack-x-recursion-count_nodes | wrong_fix | 14 | 0 | 无注入（与记忆无关） | 检索未命中任何教训 |
| memory__optimized | multi-boundary-lower_bound-x-parsing-parse_float_list | wrong_fix | 14 | 0 | 无注入（与记忆无关） | 检索未命中任何教训 |
| memory__optimized | multi-boundary-peak_index-x-parsing-parse_kv | wrong_fix | 14 | 0 | 无注入（与记忆无关） | 检索未命中任何教训 |
| memory__optimized | cache_state-counter_reset | wrong_fix | 14 | 0 | 无注入（与记忆无关） | 检索未命中任何教训 |
| memory__optimized | multi-mutable_default-Stack-x-recursion-count_nodes | wrong_fix | 14 | 0 | 无注入（与记忆无关） | 检索未命中任何教训 |

### 回滚可观测性（自然任务）

| 臂 | 进入回滚判定次数 | 真正执行回滚 | 哈希校验通过 | 平均 run_tests/任务 | test_runs≥2 的任务 |
|---|---|---|---|---|---|
| no_memory__baseline | 4 | 0 | 0 | 0.9 | 5 |
| memory__baseline | 3 | 0 | 0 | 0.9 | 5 |
| memory__optimized | 1 | 0 | 0 | 0.8 | 2 |

> 回滚只在“测试失败（写操作后）→ 编辑 → 再测试，且失败测试集合完全一致”时触发。自然任务集里 Agent 平均只跑 1.x 次测试就耗尽步数，这是回滚次数为 0 的结构性原因；分支本身由 `bench/rollback_probe.py` 的受控任务验证可执行（见 README）。
