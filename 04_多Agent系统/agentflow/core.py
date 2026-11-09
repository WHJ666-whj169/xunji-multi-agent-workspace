# -*- coding: utf-8 -*-
"""最小可用的多 Agent 编排核心：路由、预算、工具、追踪、审核兜底。"""
from dataclasses import dataclass, field
import json
import time


@dataclass
class Budget:
    max_tokens: int = 20000
    max_steps: int = 8
    used_tokens: int = 0
    steps: int = 0

    def charge(self, tokens: int) -> None:
        self.used_tokens += max(1, tokens)

    def take_step(self) -> None:
        self.steps += 1

    def exhausted(self) -> bool:
        return self.used_tokens >= self.max_tokens or self.steps >= self.max_steps


@dataclass
class AgentSpec:
    name: str
    title: str
    system: str
    tools: list = field(default_factory=list)
    model: str = "light"


class ToolRegistry:
    def __init__(self):
        self._tools = {}

    def register(self, name, fn, description=""):
        self._tools[name] = {"fn": fn, "description": description}

    def call(self, name, **kwargs):
        if name not in self._tools:
            return f"[工具缺失] {name}"
        try:
            return self._tools[name]["fn"](**kwargs)
        except Exception as exc:  # 工具失败不拖垮整条链路
            return f"[工具错误] {name}: {exc}"

    def names(self):
        return sorted(self._tools)


class Tracer:
    def __init__(self, echo=True):
        self.events = []
        self.echo = echo

    def log(self, **event):
        event["ts"] = time.strftime("%H:%M:%S")
        self.events.append(event)
        if self.echo:
            print(f"[{event['ts']}] {event.get('type','?'):<8} "
                  f"{event.get('agent',''):<15} {event.get('detail','')}")

    def dump(self, path):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.events, fh, ensure_ascii=False, indent=2)


class Orchestrator:
    """Supervisor 模式：按意图选 Agent，顺序执行，审核 Agent 收尾。"""

    ROUTES = [
        (("数据", "指标", "gmv", "周报", "环比", "分析"), ["analyst", "merchant_ops", "compliance"]),
        (("文案", "活动", "建议", "运营", "推广"), ["merchant_ops", "compliance"]),
        (("审核", "违规", "敏感", "合规"), ["compliance"]),
    ]

    def __init__(self, agents, llm, tools, budget=None, tracer=None, pricing=None):
        self.agents = {a.name: a for a in agents}
        self.llm = llm
        self.tools = tools
        self.budget = budget or Budget()
        self.tracer = tracer or Tracer()
        self.pricing = pricing or {"light": {"input": 0.5, "output": 1.0},
                                   "flagship": {"input": 2.0, "output": 8.0}}

    def route(self, task: str):
        low = task.lower()
        for keys, plan in self.ROUTES:
            if any(k.lower() in low for k in keys):
                return plan
        return ["user_assistant", "compliance"]

    def _tool_context(self, agent: AgentSpec, context: dict) -> str:
        if not agent.tools:
            return ""
        chunks = []
        for name in agent.tools:
            if name == "search_shops":
                chunks.append(str(self.tools.call(name, city=context.get("city", "杭州"),
                                                  keyword=context.get("keyword", "咖啡"))))
            elif name == "merchant_metrics":
                chunks.append(str(self.tools.call(name, merchant_id=context.get("merchant_id", "m_001"),
                                                  week=context.get("week", "2026-W45"))))
            elif name == "merchant_playbook":
                chunks.append(str(self.tools.call(name, industry=context.get("industry", "餐饮"))))
            elif name == "compliance_rules":
                chunks.append(str(self.tools.call(name)))
        return "\n".join(chunks)

    def _estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 2)

    def run_agent(self, agent: AgentSpec, task: str, context: dict, prior: list) -> str:
        if self.budget.exhausted():
            return "[预算耗尽] 已停止，请人工处理"

        if agent.name == "compliance":
            content = "\n".join(text for _, text in prior) or task
            user = f"请审核以下内容：\n{content}"
        else:
            tool_ctx = self._tool_context(agent, context)
            user = f"任务：{task}\n上下文：{json.dumps(context, ensure_ascii=False)}"
            if prior:
                user += "\n前置结论：\n" + "\n".join(f"- {n}: {t}" for n, t in prior)[-1200:]
            if tool_ctx:
                user += f"\n工具结果：\n{tool_ctx}"

        text = self.llm.complete(agent.system, user, model=agent.model)

        tokens = self._estimate_tokens(agent.system + user + text)
        self.budget.charge(tokens)
        self.budget.take_step()
        price = self.pricing.get(agent.model, self.pricing["light"])
        cost = (tokens * 0.6) / 1_000_000 * price["input"] + (tokens * 0.4) / 1_000_000 * price["output"]
        self.tracer.log(type="agent", agent=agent.name, detail=f"{tokens} tok / ¥{cost:.4f} | {text[:60]}")
        return text

    def run(self, task: str, context=None):
        context = context or {}
        plan = self.route(task)
        self.tracer.log(type="route", agent="supervisor", detail=" → ".join(plan))
        results = []
        for name in plan:
            if name not in self.agents:
                continue
            text = self.run_agent(self.agents[name], task, context, results)
            results.append((name, text))
            if text.startswith("[预算耗尽]"):
                break
        self.tracer.log(type="done", agent="supervisor",
                        detail=f"steps={self.budget.steps} tokens={self.budget.used_tokens}")
        return results
