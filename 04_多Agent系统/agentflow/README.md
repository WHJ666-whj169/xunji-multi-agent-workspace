# agentflow · 多 Agent 编排脚手架

零第三方依赖，只用 Python 标准库。用来跑通「路由 → 专业 Agent → 审核 → 预算/日志」的最小闭环。

## 运行

```bash
cd 04_多Agent系统/agentflow
python main.py --mock "帮我看下本周商家数据，给一条运营建议"
```

真实模型：

```bash
# Windows PowerShell
$env:DEEPSEEK_API_KEY="sk-xxxx"
python main.py "帮我看下本周商家数据"
```

## 结构

| 文件 | 作用 |
|---|---|
| `main.py` | 入口：加载配置、组装编排器、打印结果 |
| `core.py` | 编排核心：路由、预算、工具注册、追踪、审核收尾 |
| `llm.py` | LLM 适配：mock + OpenAI 兼容接口 |
| `tools.py` | 示例工具：搜店、商家指标、行业打法、合规规则 |
| `agents.json` | Agent 定义：名称、模型档位、工具、系统提示词 |

## 接进你的后端

1. 把 `tools.py` 里的函数换成你自己的服务调用（数据库、搜索、推荐）。
2. 把 `agents.json` 的系统提示词改成你的业务话术。
3. 在 `/agent/chat` 接口里 new 一个 `Orchestrator`，传入用户问题和上下文。
4. 生产环境务必：
   - 用 Redis 存会话与缓存；
   - 每次请求带 `trace_id` 并落日志；
   - 设 `max_tokens` / `max_steps` / 每用户日限额；
   - 审核 Agent 作为必经节点；
   - 写操作（退款/封号/发券）走人工确认。

## 成本估算

`core.py` 里按 60% 输入 / 40% 输出、light ¥0.5/¥1、flagship ¥2/¥8 每百万 token 估算，仅用于演示。真实计费以厂商账单为准。
