# -*- coding: utf-8 -*-
"""示例工具：真实项目里换成数据库/搜索/推荐接口即可。"""


def search_shops(city: str, keyword: str):
    return [
        {"name": "A 咖啡", "distance_min": 8, "tags": ["安静", "插座"]},
        {"name": "B 书店", "distance_min": 12, "tags": ["展览", "咖啡"]},
        {"name": "C 小馆", "distance_min": 15, "tags": ["人均40", "本地菜"]},
    ]


def merchant_metrics(merchant_id: str, week: str):
    return {"merchant_id": merchant_id, "week": week, "gmv": 58900, "orders": 1284,
            "aov": 46, "refund_rate": 0.012, "wow": 0.12}


def merchant_playbook(industry: str):
    return f"{industry}行业打法：工作日下午做套餐、周末做主题活动、每月一次会员日；配 3 张实拍图转化最高。"


def compliance_rules():
    return ("禁止：最好/第一/绝对/保证/100%/永久；禁止承诺收益；禁止诱导私下交易；"
            "医疗、金融、教育类需额外资质；未成年人相关内容需特别提示。")


def build_registry():
    from core import ToolRegistry
    reg = ToolRegistry()
    reg.register("search_shops", search_shops, "按城市/关键词搜附近商家")
    reg.register("merchant_metrics", merchant_metrics, "查商家周指标")
    reg.register("merchant_playbook", merchant_playbook, "查行业打法")
    reg.register("compliance_rules", compliance_rules, "查内容合规规则")
    return reg
