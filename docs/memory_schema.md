# 记忆条目 schema（v2 类别作用域 / v3 具体性闸门）

本文件定义反思记忆的存储字段与检索规则。代码实现见 `agent/memory.py`、`agent/loop.py`。

## 1. 为什么从函数名换到 bug 类别

v1 的记忆条目用 `scope`（函数名/文件名）做**硬过滤**：教训锁定的函数在当前仓库不存在时，
直接不注入。这个设计在 64 题主实验里表现为：

- 记忆臂 64 题**注入 0 次**。检索被硬过滤全部挡掉，机制没有生效；
- 因此 55/64 vs 54/64 的差异不能解释为“记忆无效”，只能记为“不可测”；
- 加闸门前（`experiments/archive_pre_fix/`）则相反：84 次注入、57 题命中，其中跨任务无关教训
  直接把 6 个任务带错。

结论：以函数名为作用域，要么因为同名/不存在而全挡（不可测），要么因为词面相似而误注入（有害）。
真正可迁移的是**缺陷类别**——`lower_bound` 的 off-by-one 与 `insert_position_desc` 的
off-by-one 是同一类修复模式，agent 应该能复用；而函数名只是“这条教训来自哪个实例”的线索，
不该作为准入条件。

v2 因此改为：

- `bug_category` 决定“是否同类”；
- `symptom` 与当前失败信号的相似度决定“是否值得看”；
- 函数名（`scope`）只作为**排序加分**，不再做任何硬过滤。

## 2. 类别枚举

| 类别 | 中文 | 对应任务族 |
|---|---|---|
| `boundary_compare` | 边界比较 / off-by-one | boundary |
| `paging_index` | 分页 / 切片索引 | paging |
| `reduce_init` | 归约初值 / 比较器 | reduce_init |
| `mutable_default` | 可变默认参数 / 共享状态 | mutable_default |
| `cache_state` | 缓存 / 状态失效 | cache_state |
| `parsing_robustness` | 解析容错 | parsing |
| `recursion_base` | 递归终止 / 基例 | recursion |
| `type_conversion` | 类型转换 / 空值 | types |

组合任务（`multi-*`）有主类别 `bug_category`（可见测试覆盖的 A 模块）与
`bug_categories`（A+B）。记忆检索只使用 Agent 可观察信号推断出的类别集合。

## 3. 字段

存储为 append-only JSONL：`{"type":"add","lesson":{...}}` / `{"type":"feedback","id":...,"outcome":...}`。

| 字段 | 类型 | 必填 | 含义 |
|---|---|---|---|
| `id` | str | 是 | 教训 id，`L<毫秒时间戳>` |
| `bug_category` | str | v2 是 | 上述 8 类之一 |
| `symptom` | str | v2 是 | 可观察症状：测试怎么失败、期望/实际、异常文本 |
| `root_cause` | str | 是 | 根因，指向具体代码行为（不是“要仔细”） |
| `fix_pattern` | str | 是 | 下次遇到同类症状的具体做法 |
| `language_constraints` | str | 否 | 适用语言/库约束，如“Python3 纯标准库”“仅标准库 re” |
| `family` | str | 兼容 | 任务族名（v1 兼容、统计用） |
| `scenario` | str | 兼容 | v1 场景描述；v2 缺省等于 `symptom` |
| `error_type` | str | 兼容 | v1 错误类别；v2 缺省等于 `bug_category` |
| `rule` | str | 兼容 | v1 规则句；v2 缺省等于 `fix_pattern` |
| `source_task` | str | 是 | 产生该教训的任务 id（不参与检索） |
| `scope` | list[str] | 否 | 教训提到的当前仓库函数/文件名，**只做排序加分** |
| `created_at` | str | 是 | 创建时间 |
| `hits` | int | 是 | 被检索命中次数 |
| `success_after` / `fail_after` | int | 是 | 注入后该任务成功/失败次数（反馈） |
| `dedup_hits` | int | 是 | 被合并去重次数 |

写入侧闸门：

- `is_usable`：`root_cause` ≥ 10 字，`fix_pattern`（或 `rule`）≥ 8 字，非占位符、非 prompt 复述；
- v2 不要求函数锚点；`bug_category` 缺失时按 `family` 归一化，仍无法归类则 `reject("no_category")`；
- 同类（`bug_category`）且根因 Jaccard ≥ 0.82 的教训合并，不重复堆文本。

## 4. 检索打分（v2）

Agent 可观察信号（不含 ground-truth）：

- `prompt`
- `retrieval_hint`：src 文件名、可见测试名、src 内函数/类名（读源码即可获得）
- `visible_failure`：episode 开始前跑一次可见测试的失败输出
- `observed_categories`：由 `infer_categories(text)` 从上述文本推断的类别集合（关键词词典，见
  `CATEGORY_KEYWORDS`）

对每条教训：

```
score = 3.0 * [bug_category ∈ observed_categories]
      + 2.0 * jaccard(tokens(symptom + root_cause), tokens(query))
      + 0.4 * jaccard(scope, current_identifiers)
      - 0.3 * [fail_after > success_after]
```

- `score ≥ 0.5` 进入候选，按分数、类别命中、创建时间取前 `k` 条；
- **没有任何函数名/同族硬过滤**；
- 隔离规则保留：`fail_after ≥ 2 且 success_after == 0` 的教训不再注入（已被证伪）。

## 5. v3：具体性闸门 + 只注入 top-1

v2 检索通了（234/250 题命中、681 次注入），但成功率 +2.4pp（p=0.451）、token +21.5%。
v3 只改注入策略，不改存储字段：

**闸门（三条必须同时满足，缺一不注入）**

| 条件 | 实现 | 例子 |
|---|---|---|
| (a) 点名具体符号/函数/参数/条件 | `has_specific_symbol()`：非泛化标识符（≥3 字符）、单字母比较变量、或条件词（空列表/负数/越界/None/last_page…） | `clamp`、`hi`、`n <= 0`、`空列表` |
| (b) 可验证判据 | `has_verifiable_check()`：出现“应返回/期望/assert/==/→”等判据，且后面 40 字内有具体值/标识符 | `last_page(0) 应返回 0`、`parse_kv('') 应返回 None` |
| (c) 类别匹配 | `bug_category ∈ observed_categories` | `paging_index` |

- 候选按 v2 分数排序，逐条过闸门，**只取第一条通过者**；全部不通过则不注入。
- 单条渲染硬截断 200 字；单题注入预算 220 字（`V3_ENTRY_CHARS` / `V3_MAX_CHARS`）。
- 渲染顺序：先 `fix_pattern`（含可验证判据），剩余空间再补根因前 60 字。
- 闸门拒收按原因计数（`no_category` / `no_symbol` / `no_check`），写入 `state()["gate"]`。

**成本口径**

- 预注册：mem_v3 平均 token/任务相对 no_memory ≤ +10%；
- 压缩手段只有两个：top-3 → top-1、注入文本 900 字 → 220 字；
- 若仍超限，继续压缩注入文本，并在报告写明砍掉了哪些字段（本版砍掉整段 `symptom`、
  `language_constraints` 和根因全文，只保留判据 + 根因摘要）。

**判死线（与 README 同步，运行前锁定）**

65 族变体聚类 bootstrap（20000 次）p>0.05 或净差 <+2pp ⇒ 关闭文本教训注入这条线；
v1/v2/v3 全部保留为对照。

## 6. 与 v1 的兼容

- `ReflectionMemory(path, version="v1")` 保留旧检索逻辑（同族 + 函数硬过滤），用于对照组；
- 旧 JSONL 无需迁移：加载时 `bug_category` 由 `family` 归一化补全；
- CSV 中 `memory_injected` / `memory_injected_count` 记录每条 episode 实际注入的教训 id 与条数。

## 6. 局限（必须与结果一起读）

1. 类别推断是关键词词典，不是语义分类器；函数名仍是主要线索之一，因此“跨函数”泛化的上限
   受词典覆盖影响。
2. 反射阶段由 LLM 输出 `bug_category`，存在归类噪声；归一化失败会拒收，不静默改类。
3. 组合任务复用 65 个变体：任务数从 97 扩到 250，但**独立变体数不变**。名义 n 提升不等于
   统计功效提升，报告中的显著性必须同时给出“按变体聚类”的口径。
4. 记忆库在线累积，早期任务没有可注入教训；注入率必须按“实际命中题数/条数”报告，
   不能把 0 注入写成“无差异”。
