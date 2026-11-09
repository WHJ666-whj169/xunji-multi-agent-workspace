# -*- coding: utf-8 -*-
"""LLM 适配层：mock 模式零依赖；真实模式走 OpenAI 兼容接口（DeepSeek/通义/Kimi 均可）。"""
import json
import os
import urllib.request


class MockLLM:
    """不联网，按 Agent 角色返回固定但合理的文本，用于跑通编排。"""

    def complete(self, system: str, user: str, model: str = "light") -> str:
        if "内容审核" in system:
            banned = [w for w in ("最好", "第一", "绝对", "保证", "100%", "永久") if w in user]
            return ("BLOCK: 含绝对化/承诺性用语 " + "、".join(banned)) if banned else "PASS"
        if "数据分析" in system:
            return ("结论：本周 GMV 环比 +12%，增量主要来自周六；客单价持平，复购率 +3pp。"
                    "依据：订单 1,284 单，客单 ¥46，退款率 1.2%。")
        if "商家运营" in system:
            return ("建议 1：周二至周四 14:00–17:00 上「双人下午茶套餐」，限时 7 天，定价 ¥68。"
                    "建议 2：把套餐同步到用户端「附近」页，配 3 张实拍图。")
        if "用户助手" in system:
            return "附近 3 个去处：A 咖啡（步行 8 分钟，安静）、B 书店（12 分钟，有展）、C 小馆（15 分钟，人均 ¥40）。"
        return "（mock 回复）"


class OpenAICompatLLM:
    """真实调用：export DEEPSEEK_API_KEY=sk-xxx 后去掉 --mock。"""

    def __init__(self, api_key=None, base_url="https://api.deepseek.com", model="deepseek-chat"):
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.model = model

    def complete(self, system: str, user: str, model: str = None) -> str:
        if not self.api_key:
            raise RuntimeError("缺少 DEEPSEEK_API_KEY；先用 --mock 跑通")
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": 0.3,
            "max_tokens": 800,
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"].strip()
