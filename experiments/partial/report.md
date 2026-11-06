## A/B 结果（同任务、同模型、同预算）

| 臂 | 样本 | 成功率 | 95% CI | token/任务 | calls/任务 | 平均步数 |
|---|---|---|---|---|---|---|
| no_memory__baseline | 36 | 83.3% (30/36) | 69.4%–94.4% | 16428 | 11.5 | 10.5 |
| memory__baseline | 26 | 76.9% (20/26) | 61.5%–92.3% | 20923 | 12.3 | 11.3 |
| memory__optimized | 13 | 76.9% (10/13) | 53.8%–100.0% | 14320 | 10.5 | 10.5 |

### 配对 McNemar

- no_memory__baseline vs memory__baseline: n=26，不一致 3 (A 赢 2 / B 赢 1)，p=1.000，该样本量可检测的最小差异≈38.8%
- no_memory__baseline vs memory__optimized: n=13，不一致 3 (A 赢 2 / B 赢 1)，p=1.000，该样本量可检测的最小差异≈54.9%
- memory__baseline vs memory__optimized: n=13，不一致 2 (A 赢 1 / B 赢 1)，p=1.000，该样本量可检测的最小差异≈54.9%

### 按任务族（成功数 · 平均 token · 平均步数）

| 任务族 | memory__baseline | memory__optimized | no_memory__baseline |
|---|---|---|---|
| boundary | - | - | 2/2 · 13.2k · 9步 |
| boundary+parsing | 2/4 · 23.5k · 12步 | 1/3 · 20.7k · 14步 | 4/6 · 22.4k · 13步 |
| cache_state | 4/4 · 14.4k · 9步 | 2/2 · 7.3k · 6步 | 4/4 · 9.5k · 7步 |
| mutable_default | 1/1 · 11.4k · 8步 | - | 4/4 · 7.3k · 7步 |
| mutable_default+recursion | 1/1 · 26.9k · 14步 | - | 4/4 · 18.3k · 12步 |
| paging+types | 4/8 · 25.3k · 12步 | 3/4 · 18.4k · 13步 | 4/8 · 23.6k · 13步 |
| parsing | 4/4 · 24.6k · 12步 | 4/4 · 8.9k · 7步 | 4/4 · 15.7k · 10步 |
| recursion | 4/4 · 13.4k · 10步 | - | 4/4 · 9.6k · 8步 |

### 记忆的净效果（相对无记忆臂，按任务族）


**memory__baseline**

| 任务族 | 记忆臂 胜 | 记忆臂 负 | 持平 | 净变化 |
|---|---|---|---|---|
| boundary+parsing | 0 | 1 | 3 | -1 |
| paging+types | 1 | 1 | 6 | +0 |

**memory__optimized**

| 任务族 | 记忆臂 胜 | 记忆臂 负 | 持平 | 净变化 |
|---|---|---|---|---|
| boundary+parsing | 0 | 2 | 1 | -2 |
| paging+types | 1 | 0 | 3 | +1 |

### 记忆臂失败 / 无记忆臂成功的任务（归因）

| 臂 | 任务 | 失败模式 | 步数 | 注入 | 归因 | 证据 |
|---|---|---|---|---|---|---|
| memory__baseline | multi-paging-last_page-x-types-format_price | wrong_fix | 14 | 0 | 无注入（与记忆无关） | 检索未命中任何教训 |
| memory__baseline | multi-boundary-search_rotated-x-parsing-parse_range | wrong_fix | 14 | 1 | 上下文稀释 | 每调用 token 2290 vs 基线 1551（+48%） |
| memory__optimized | multi-boundary-peak_index-x-parsing-parse_kv | wrong_fix | 14 | 0 | 无注入（与记忆无关） | 检索未命中任何教训 |
| memory__optimized | multi-boundary-search_rotated-x-parsing-parse_range | wrong_fix | 14 | 0 | 无注入（与记忆无关） | 检索未命中任何教训 |

- `multi-boundary-search_rotated-x-parsing-parse_range` 注入的教训原文：
  - 不得修改 tests；修复 src 所有缺陷并验证后调用 finish。

### 回滚可观测性（自然任务）

| 臂 | 进入回滚判定次数 | 真正执行回滚 | 哈希校验通过 |
|---|---|---|---|
| no_memory__baseline | 4 | 0 | 0 |
| memory__baseline | 6 | 0 | 0 |
| memory__optimized | 1 | 0 | 0 |
