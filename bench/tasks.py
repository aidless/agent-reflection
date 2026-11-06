"""基准任务集：由 8 个缺陷族 × 8 个变体生成单缺陷任务，再组合成多缺陷任务。

每个任务目录：
  workspace/src/<module>.py     有缺陷的源码
  workspace/tests/test_visible.py  可见测试（只读）
  task.json                     元数据 + 参考解 + 隐藏测试
"""
from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .families_a import F_BOUNDARY, F_MUTABLE, F_PAGING, F_REDUCE
from .families_b import F_PARSING, F_RECURSION, F_STATE, F_TYPES

FAMILIES = [F_BOUNDARY, F_PAGING, F_REDUCE, F_MUTABLE, F_STATE, F_PARSING, F_RECURSION, F_TYPES]

# 每个缺陷族对应的 bug 类别（v2 记忆的检索作用域）
CATEGORY_OF = {
    "boundary": "boundary_compare",
    "paging": "paging_index",
    "reduce_init": "reduce_init",
    "mutable_default": "mutable_default",
    "cache_state": "cache_state",
    "parsing": "parsing_robustness",
    "recursion": "recursion_base",
    "types": "type_conversion",
}

DATA_DIR = Path(__file__).resolve().parent / "data" / "tasks"
TARGET_TASKS = 250


def buggy_source(correct: str, old: str, new: str) -> str:
    if old not in correct:
        raise ValueError(f"注入点不存在: {old[:60]!r}")
    return correct.replace(old, new, 1)


def _imports_and_tests(src: str) -> tuple[list[str], list[tuple[str, str]]]:
    """拆分隐藏测试文件：导入行 + [(函数名, 源码)]。"""
    tree = ast.parse(src)
    imports = []
    tests = []
    lines = src.splitlines()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append("\n".join(lines[node.lineno - 1: node.end_lineno]))
        elif isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            tests.append((node.name, "\n".join(lines[node.lineno - 1: node.end_lineno])))
    return imports, tests


def _test_passes(module_src: str, imports: list[str], func_src: str, extra_env: dict | None = None) -> bool:
    with tempfile.TemporaryDirectory(prefix="probe-") as td:
        tmp = Path(td)
        (tmp / "src").mkdir()
        (tmp / "src" / "mod_probe.py").write_text(module_src)
        (tmp / "tests").mkdir()
        body = "\n".join(imports) + "\n\n" + func_src
        (tmp / "tests" / "test_probe.py").write_text(body)
        env = dict(os.environ)
        env["PYTHONPATH"] = str(tmp / "src")
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
            cwd=str(tmp), capture_output=True, text=True, timeout=20, env=env,
        )
        return proc.returncode == 0


def compose_visible(module: str, broken: str, visible_src: str, hidden_src: str) -> tuple[str, str]:
    """从隐藏用例中挑一条在缺陷版上失败的用例，追加进可见测试。

    这样每个任务都有真实失败信号；隐藏测试仍保留全集用于判定。
    返回 (visible_src, first_failing_name)。
    """
    imports, tests = _imports_and_tests(hidden_src)
    # 探针里模块名固定为 mod_probe，需把 import 行里的真实模块名替换
    probe_imports = [ln.replace(f"import {module}", "import mod_probe").replace(
        f"from {module}", "from mod_probe") for ln in imports]
    first_fail = None
    for name, src in tests:
        if not _test_passes(broken, probe_imports, src):
            first_fail = (name, src)
            break
    if first_fail is None:
        # 隐藏用例都没覆盖到这个 bug，退而使用可见测试自身的失败信号
        v_imports, v_tests = _imports_and_tests(visible_src)
        v_probe = [ln.replace(f"import {module}", "import mod_probe").replace(
            f"from {module}", "from mod_probe") for ln in v_imports]
        for name, src in v_tests:
            if not _test_passes(broken, v_probe, src):
                return visible_src, name
        raise ValueError(f"缺陷版上没有任何测试失败: {module}")
    needed = []
    existing = set(visible_src.splitlines())
    for ln in imports:
        if ln not in existing and ln not in needed:
            needed.append(ln)
    visible = visible_src.rstrip("\n") + "\n\n" + "\n".join(needed) + "\n\n" + first_fail[1] + "\n"
    return visible, first_fail[0]



def _write_repo(data_dir: Path, tid: str, sources: dict[str, str], visible_src: str) -> Path:
    ws = data_dir / tid / "workspace"
    (ws / "src").mkdir(parents=True, exist_ok=True)
    (ws / "tests").mkdir(parents=True, exist_ok=True)
    for rel, content in sources.items():
        (ws / rel).write_text(content)
    (ws / "tests" / "test_visible.py").write_text(visible_src)
    return ws


def build_variants() -> dict[tuple[str, str], dict]:
    """为每个变体预计算缺陷源码、可见测试、隐藏测试。"""
    out = {}
    for fam in FAMILIES:
        for v in fam["variants"]:
            broken = buggy_source(v["correct"], v["bug"][0], v["bug"][1]).lstrip("\n")
            visible_src, fail_name = compose_visible(v["module"], broken, v["visible"], v["hidden"])
            out[(fam["name"], v["name"])] = {
                "family": fam, "variant": v, "broken": broken,
                "visible": visible_src, "fail_name": fail_name,
            }
    return out


HARD_PAIRS = [
    ("boundary", "parsing"), ("paging", "types"),
    ("reduce_init", "cache_state"), ("mutable_default", "recursion"),
]


def build_tasks(data_dir: Path = DATA_DIR, clean: bool = True) -> list[dict]:
    if clean and data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    variants = build_variants()
    tasks: list[dict] = []

    # 单缺陷任务
    for (fname, vname), art in variants.items():
        v, fam = art["variant"], art["family"]
        tid = f"{fname}-{vname}"
        src_rel = f"src/{v['module']}.py"
        _write_repo(data_dir, tid, {src_rel: art["broken"]}, art["visible"])
        prompt = (
            f"仓库工作区里 {src_rel} 存在缺陷，tests/test_visible.py 中有失败的测试。\n"
            f"请定位并修复 {src_rel} 的根因，使可见测试通过，并通过未公开的隐藏测试（覆盖边界情况）。\n"
            f"tests/ 目录只读，不能修改测试。修好后调用 finish。"
        )
        meta = {
            "id": tid, "kind": "single", "family": fname,
            "bug_category": CATEGORY_OF[fname],
            "bug_class": fam["bug_class"],
            "bug_desc": v["bug_desc"], "module": v["module"], "src_path": src_rel,
            "prompt": prompt, "visible_failing_test": art["fail_name"],
            "reference": {src_rel: v["correct"].lstrip("\n")},
            "hidden_tests": v["hidden"].lstrip("\n"),
        }
        (data_dir / tid / "task.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
        tasks.append(meta)

    # 多缺陷任务：可见测试只覆盖 A，隐藏测试同时覆盖 B（B 必须自己读源码发现）
    by_family: dict[str, list[str]] = {}
    for fname, vname in variants:
        by_family.setdefault(fname, []).append(vname)
    seen_pairs: set[frozenset] = set()

    def add_multi(fam_a: str, va_name: str, fam_b: str, vb_name: str) -> bool:
        a = variants[(fam_a, va_name)]
        b = variants[(fam_b, vb_name)]
        va, vb = a["variant"], b["variant"]
        tid = f"multi-{fam_a}-{va['name']}-x-{fam_b}-{vb['name']}"
        if (data_dir / tid).exists():
            return False
        src_a, src_b = f"src/{va['module']}.py", f"src/{vb['module']}.py"
        _write_repo(data_dir, tid, {src_a: a["broken"], src_b: b["broken"]}, a["visible"])
        prompt = (
            f"仓库 src/ 下可能存在多处缺陷，tests/test_visible.py 只覆盖其中一处（{src_a}）。\n"
            f"隐藏测试会检查 src/ 下所有模块，请通读源码修复全部缺陷，并自行构造边界用例验证。\n"
            f"tests/ 目录只读，不能修改测试。修好后调用 finish。"
        )
        hidden = a["variant"]["hidden"].lstrip("\n") + "\n\n" + vb["hidden"].lstrip("\n")
        meta = {
            "id": tid, "kind": "multi",
            "family": f"{fam_a}+{fam_b}",
            "bug_category": CATEGORY_OF[fam_a],
            "bug_categories": [CATEGORY_OF[fam_a], CATEGORY_OF[fam_b]],
            "bug_class": f"{a['family']['bug_class']} + {b['family']['bug_class']}",
            "bug_desc": f"{va['bug_desc']}；{vb['bug_desc']}",
            "module": f"{va['module']}+{vb['module']}",
            "src_path": f"{src_a},{src_b}",
            "prompt": prompt, "visible_failing_test": a["fail_name"],
            "reference": {src_a: va["correct"].lstrip("\n"), src_b: vb["correct"].lstrip("\n")},
            "hidden_tests": hidden,
        }
        (data_dir / tid / "task.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
        tasks.append(meta)
        seen_pairs.add(frozenset({(fam_a, va_name), (fam_b, vb_name)}))
        return True

    # 1) 原有 4 组固定配对（保持历史对照不变）
    for fam_a, fam_b in HARD_PAIRS:
        names_a, names_b = sorted(by_family[fam_a]), sorted(by_family[fam_b])
        for i in range(min(len(names_a), len(names_b))):
            add_multi(fam_a, names_a[i], fam_b, names_b[i])

    # 2) 扩样本：按 primary bug_category 均衡补齐到 TARGET_TASKS。
    #    这些组合题仍复用 64 个变体，名义 n 变大但独立变体数不变（报告里必须写明）。
    families = sorted(by_family)
    need = TARGET_TASKS - len(tasks)
    per_family = need // len(families)
    extra = need % len(families)
    for fi, fam_a in enumerate(families):
        quota = per_family + (1 if fi < extra else 0)
        partners = [f for f in families if f != fam_a]
        partners = partners[fi % len(partners):] + partners[: fi % len(partners)]
        made = 0
        for pidx, fam_b in enumerate(partners):
            for i in range(len(by_family[fam_a])):
                j = (i + pidx) % len(by_family[fam_b])
                key = frozenset({(fam_a, by_family[fam_a][i]), (fam_b, by_family[fam_b][j])})
                if key in seen_pairs:
                    continue
                if add_multi(fam_a, by_family[fam_a][i], fam_b, by_family[fam_b][j]):
                    made += 1
                if made >= quota:
                    break
            if made >= quota:
                break
    return tasks


def load_tasks(data_dir: Path = DATA_DIR, limit: int | None = None) -> list[dict]:
    if not data_dir.exists():
        build_tasks(data_dir)
    items = []
    for d in sorted(data_dir.iterdir()):
        f = d / "task.json"
        if f.exists():
            items.append(json.loads(f.read_text()))
    return items[:limit] if limit else items


def workspace_of(task_id: str, data_dir: Path = DATA_DIR) -> Path:
    return data_dir / task_id / "workspace"


def select_main(tasks: list[dict], per_family: int = 4, seed: int = 0) -> list[dict]:
    """主实验集：全部多缺陷任务 + 每族前 N 个单缺陷任务，固定种子交错排序。"""
    import random

    singles, multis = [], []
    counts: dict[str, int] = {}
    for t in tasks:
        if t["kind"] == "multi":
            multis.append(t)
        else:
            counts[t["family"]] = counts.get(t["family"], 0)
            if counts[t["family"]] < per_family:
                singles.append(t)
                counts[t["family"]] += 1
    out, i = [], 0
    while i < max(len(singles), len(multis)):
        if i < len(multis):
            out.append(multis[i])
        if i < len(singles):
            out.append(singles[i])
        i += 1
    rng = random.Random(seed)
    # 保持多/单交替的宏观节奏：按块打乱，块内顺序固定
    blocks = [out[j:j + 8] for j in range(0, len(out), 8)]
    fixed = [b for b in blocks if b and b[0]["kind"] == "single"]
    mixed = [b for b in blocks if b and b[0]["kind"] != "single"]
    rng.shuffle(mixed)
    return [t for b in mixed + fixed for t in b]


if __name__ == "__main__":
    ts = build_tasks()
    print(f"生成 {len(ts)} 个任务 -> {DATA_DIR}")
    for t in ts[:5]:
        print(" ", t["id"])
