.PHONY: help setup tasks verify test smoke repro experiment probe report clean

PY ?= python3
ARMS ?= no_memory__baseline,mem_v1__baseline,mem_v2__baseline,mem_v3__baseline
REPRO_ARMS ?= no_memory__baseline,mem_v2__baseline

help:
	@echo "make setup      安装依赖"
	@echo "make tasks      生成 250 个基准任务并自检"
	@echo "make test       跑单元测试（不调用 LLM）"
	@echo "make repro      5 题 smoke（两臂，共 10 个 episode，需要 LLM 端点）"
	@echo "make experiment 全量 A/B 实验（250 任务 x 4 臂，耗时取决于端点）"
	@echo "make probe      回滚能力探针（有/无回滚对比）"
	@echo "make report     从 250 题 CSV 生成四臂统计（含 v3 判死线检查）"

setup:
	$(PY) -m pip install -r requirements.txt

tasks:
	$(PY) -m bench.tasks
	$(PY) -m bench.verify_tasks

verify:
	$(PY) -m bench.verify_tasks

test:
	$(PY) -m pytest tests -q

repro:
	rm -f experiments/smoke.csv
	$(PY) -m bench.runner --arms $(REPRO_ARMS) --task-set main --limit 5 \
		--csv experiments/smoke.csv --max-steps 14 --reset-memory \
		--work-dir experiments/smoke_work --trace-dir experiments/smoke_traces \
		--memory-dir experiments/smoke_memory
	$(PY) -m bench.report --csv experiments/smoke.csv --out experiments/smoke

experiment:
	./run_experiment.sh

probe:
	$(PY) -m bench.rollback_probe --out experiments/rollback_probe.csv

report:
	$(PY) -m bench.analyze_memory --csv experiments/v2/no_memory.csv \
		experiments/v2/mem_v1.csv experiments/v2/mem_v2.csv experiments/v3/mem_v3.csv \
		--names no_memory mem_v1 mem_v2 mem_v3 \
		--memory-dir experiments/v2/memory experiments/v3/memory \
		--out experiments/v3/phase3.md

clean:
	rm -rf experiments/work experiments/traces experiments/*.csv
