# -*- coding: utf-8 -*-
"""多 Agent 编排 Demo。

用法：
  python main.py --mock "帮我看下本周商家数据，给一条运营建议"
  DEEPSEEK_API_KEY=sk-xxx python main.py "帮我看下本周商家数据"
"""
import argparse
import json
import os
import sys

from core import AgentSpec, Budget, Orchestrator, Tracer
from llm import MockLLM, OpenAICompatLLM
from tools import build_registry

HERE = os.path.dirname(os.path.abspath(__file__))


def load_agents(path):
    with open(path, encoding="utf-8") as fh:
        config = json.load(fh)
    agents = [AgentSpec(**a) for a in config["agents"]]
    return agents, config.get("pricing")


def main():
    parser = argparse.ArgumentParser(description="多 Agent 编排 Demo")
    parser.add_argument("task", nargs="*", help="要处理的任务")
    parser.add_argument("--mock", action="store_true", help="不调真实模型")
    parser.add_argument("--trace", default="", help="把追踪日志写到 JSON 文件")
    parser.add_argument("--max-tokens", type=int, default=20000)
    parser.add_argument("--max-steps", type=int, default=8)
    args = parser.parse_args()

    task = " ".join(args.task).strip() or "帮我看下本周商家数据，给一条运营建议"
    agents, pricing = load_agents(os.path.join(HERE, "agents.json"))
    llm = MockLLM() if args.mock else OpenAICompatLLM()
    tracer = Tracer(echo=True)
    orch = Orchestrator(
        agents=agents,
        llm=llm,
        tools=build_registry(),
        budget=Budget(max_tokens=args.max_tokens, max_steps=args.max_steps),
        tracer=tracer,
        pricing=pricing,
    )

    context = {"city": "杭州", "merchant_id": "m_001", "week": "2026-W45", "industry": "餐饮"}
    results = orch.run(task, context)

    print("\n===== 最终结果 =====")
    for name, text in results:
        print(f"\n[{name}]\n{text}")
    print(f"\n用量：{orch.budget.steps} 步 / {orch.budget.used_tokens} tokens")
    if args.trace:
        tracer.dump(args.trace)
        print(f"追踪日志：{args.trace}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
