# -*- coding: utf-8 -*-
"""任务台账 CLI（替代被 Windows 智能应用控制拦截的 Go 二进制）。

与 dsh-task-ledger 插件的数据面兼容：输出 list/stats/owners/history/show 的 JSON 形状。
存储：<repo>/ledger/ledger.json + <repo>/ledger/worklog/<id>.md
身份：~/.taskledger/identity.json
目录清单：~/.taskledger/dirs.json
"""
import argparse
import hashlib
import json
import os
import re
import secrets
import sys
from datetime import datetime, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

HOME = os.path.expanduser("~")
TL_HOME = os.path.join(HOME, ".taskledger")
IDENTITY = os.path.join(TL_HOME, "identity.json")
DIRS = os.path.join(TL_HOME, "dirs.json")
STALE_DAYS, OVERDUE_DAYS, BACKLOG_DAYS = 3, 14, 30


# ---------------- 基础 ----------------
def now():
    return datetime.now().replace(microsecond=0)


def fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else ""


def parse_dt(text):
    if not text:
        return None
    text = text.strip()
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def fail(message, code=1):
    print(message, file=sys.stderr)
    sys.exit(code)


def identity():
    data = read_json(IDENTITY, None)
    if not data or not data.get("uuid"):
        return None
    return data


def require_identity():
    who = identity()
    if who is None:
        fail("尚未初始化本机身份。请在终端运行：ledger.py init", 100)
    return who


def find_root(start):
    cur = os.path.abspath(start)
    if os.path.isdir(cur) and os.path.basename(cur) == "ledger":
        cur = os.path.dirname(cur)
    while True:
        if os.path.isdir(os.path.join(cur, "ledger")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def repo_of(args, must_exist=True):
    repo = getattr(args, "repo", None)
    if repo:
        repo = os.path.abspath(repo)
        if must_exist and not os.path.isdir(os.path.join(repo, "ledger")):
            fail(f"找不到台账：{repo} 下没有 ledger/ 目录")
        return repo
    found = find_root(os.getcwd())
    if found:
        return found
    if must_exist:
        fail("找不到台账：当前目录及上级都没有 ledger/")
    return os.path.abspath(os.getcwd())


def ledger_path(repo):
    return os.path.join(repo, "ledger", "ledger.json")


def load_ledger(repo):
    data = read_json(ledger_path(repo), None)
    if data is None:
        data = {"tasks": {}, "history": [], "owners": {}}
    data.setdefault("tasks", {})
    data.setdefault("history", [])
    data.setdefault("owners", {})
    return data


def save_ledger(repo, data):
    write_json(ledger_path(repo), data)


def dirs_list():
    return read_json(DIRS, [])


def dirs_save(rows):
    write_json(DIRS, rows)


def dirs_add(repo, name=""):
    rows = [r for r in dirs_list() if os.path.abspath(r.get("path", "")) != repo]
    rows.append({"path": repo, "name": name or os.path.basename(repo), "hidden": False})
    dirs_save(rows)


def slug(text):
    text = re.sub(r"[^\w\u4e00-\u9fa5-]+", "-", text.strip())
    return text.strip("-")[:12] or "task"


def new_id(title):
    return f"{now():%Y%m%d-%H%M}-{slug(title)}-{secrets.token_hex(2)}"


def tags_of(text):
    if not text:
        return []
    return [t.strip() for t in re.split(r"[,，、]", text) if t.strip()][:5]


def owners_view(data, me_uuid):
    out = {}
    for uuid, info in data.get("owners", {}).items():
        out[uuid] = {
            "file": f"{uuid}.json",
            "name": info.get("name", uuid),
            "joined": info.get("joined", ""),
            "mine": uuid == me_uuid,
        }
    return out


def name_of(data, uuid):
    if not uuid:
        return ""
    return data.get("owners", {}).get(uuid, {}).get("name", uuid)


# ---------------- 过程文档 ----------------
def worklog_path(repo, task_id):
    return os.path.join(repo, "ledger", "worklog", f"{task_id}.md")


def render_worklog(task, who):
    lines = [
        f"# {task['title']}",
        "",
        f"- **Tags**: {', '.join(task.get('tags') or [])}",
        f"- **Status**: {task['status']} · {task.get('updated') or task['created']} · @{who['name']} · {who['uuid']}",
        f"- **Created**: {task['created']} · @{name_of_current(task.get('creator'))} · {task.get('creator') or ''}",
    ]
    if task.get("finished"):
        lines.append(f"- **Sealed**: {task['finished']} · @{who['name']} · {who['uuid']}")
    lines += [
        "",
        "## Background",
        "",
        "（为什么做：触发它的原话 / 现象 / 链接）",
        "",
        "## To Do",
        "",
        "- [ ] ",
        "",
        "## Next",
        "",
        "（下一个具体动作：文件:行号 级别）",
        "",
        "## Process",
        "",
        "（踩坑与证据：带 revision + 文件:行号 或符号名）",
        "",
        "## Conclusion",
        "",
        "（做成了什么、留了什么坑；只写可验证事实）",
        "",
        "## Execution Log",
        "",
        "",
    ]
    return "\n".join(lines)


def name_of_current(uuid):
    data = _CURRENT_LEDGER.get("data") if _CURRENT_LEDGER else None
    if not data:
        return uuid or ""
    return name_of(data, uuid)


_CURRENT_LEDGER = {}


def ensure_worklog(repo, task, who):
    path = worklog_path(repo, task["id"])
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(render_worklog(task, who))
    return path


def append_log(repo, task, who, kind, note):
    path = ensure_worklog(repo, task, who)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"- {fmt(now())} · {kind} · @{who['name']} · {note}\n")


def set_header(repo, task, who):
    path = ensure_worklog(repo, task, who)
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("- **Tags**:"):
            lines[i] = f"- **Tags**: {', '.join(task.get('tags') or [])}"
        elif line.startswith("- **Status**:"):
            lines[i] = f"- **Status**: {task['status']} · {task.get('updated') or task['created']} · @{who['name']} · {who['uuid']}"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


# ---------------- 命令 ----------------
def cmd_root(args):
    target = os.path.abspath(args.dir or os.getcwd())
    is_root = os.path.isdir(os.path.join(target, "ledger"))
    repo = find_root(target)
    result = {
        "dir": target,
        "root": is_root,
        "repo": repo,
        "ledger": os.path.join(repo, "ledger") if repo else None,
        "reason": "直接含有 ledger/ 目录" if is_root else ("上级有台账" if repo else "不是台账根"),
    }
    print(json.dumps(result, ensure_ascii=False))


def cmd_whoami(args):
    who = identity()
    if who:
        print(json.dumps({"uuid": who["uuid"], "name": who["name"]}, ensure_ascii=False))
    else:
        print(json.dumps({"uuid": None, "name": None}, ensure_ascii=False))


def cmd_init(args):
    who = identity()
    if args.claim:
        print(json.dumps({"uuid": who["uuid"], "name": who["name"]} if who else {"uuid": None, "name": None}, ensure_ascii=False))
        return
    if args.new:
        if not args.name:
            fail("init --new 需要 --name")
        uuid = secrets.token_hex(8)
        data = {"uuid": uuid, "name": args.name}
        write_json(IDENTITY, data)
        print(json.dumps(data, ensure_ascii=False))
        return
    print("非交互环境：请用 init --new --name \"名字\" 或 init --claim <uuid>")


def default_name(repo):
    return os.path.basename(repo.rstrip("\\/"))


def cmd_dirs(args):
    rows = dirs_list()
    if args.add:
        repo = os.path.abspath(args.dir)
        if not os.path.isdir(os.path.join(repo, "ledger")):
            print(json.dumps({"dirs": rows, "added": False, "reason": "不是台账根"}, ensure_ascii=False))
            return
        dirs_add(repo, args.name or "")
        rows = dirs_list()
        print(json.dumps({"dirs": rows, "added": True, "reason": ""}, ensure_ascii=False))
        return
    if args.remove:
        repo = os.path.abspath(args.dir)
        dirs_save([r for r in rows if os.path.abspath(r.get("path", "")) != repo])
    elif args.hide or args.unhide:
        repo = os.path.abspath(args.dir)
        for r in rows:
            if os.path.abspath(r.get("path", "")) == repo:
                r["hidden"] = bool(args.hide)
        dirs_save(rows)
    elif args.rename is not None:
        repo = os.path.abspath(args.dir)
        for r in rows:
            if os.path.abspath(r.get("path", "")) == repo:
                r["name"] = args.rename
        dirs_save(rows)
    rows = dirs_list()
    if not args.all:
        rows = [r for r in rows if not r.get("hidden")]
    print(json.dumps({"dirs": rows}, ensure_ascii=False))


def cmd_new(args):
    who = require_identity()
    repo = repo_of(args, must_exist=False)
    os.makedirs(os.path.join(repo, "ledger", "worklog"), exist_ok=True)
    data = load_ledger(repo)
    task_id = args.id or new_id(args.title)
    if task_id in data["tasks"]:
        fail(f"任务号已存在：{task_id}")
    created = args.created or fmt(now())
    status = "doing" if args.self else "open"
    task = {
        "id": task_id,
        "title": args.title,
        "status": status,
        "creator": who["uuid"],
        "owner": who["uuid"] if args.self else None,
        "created": created,
        "started": created if args.self else None,
        "updated": created,
        "finished": None,
        "category": args.category or "",
        "tags": tags_of(args.tags),
        "worklog": f"worklog/{task_id}.md",
    }
    data["tasks"][task_id] = task
    data["owners"].setdefault(who["uuid"], {"name": who["name"], "joined": created})
    _CURRENT_LEDGER["data"] = data
    ensure_worklog(repo, task, who)
    append_log(repo, task, who, "new", f"建任务（{status}）")
    save_ledger(repo, data)
    dirs_add(repo)
    print(task_id)


def cmd_claim(args):
    who = require_identity()
    repo = repo_of(args)
    data = load_ledger(repo)
    task = data["tasks"].get(args.id)
    if not task:
        fail(f"找不到任务：{args.id}")
    if task.get("owner") and task["owner"] != who["uuid"]:
        fail("任务已在别人名下，不能认领")
    task["owner"] = who["uuid"]
    task["status"] = "doing"
    task["started"] = task.get("started") or fmt(now())
    task["updated"] = fmt(now())
    data["owners"].setdefault(who["uuid"], {"name": who["name"], "joined": fmt(now())})
    _CURRENT_LEDGER["data"] = data
    set_header(repo, task, who)
    append_log(repo, task, who, "claim", "认领，状态 doing")
    save_ledger(repo, data)
    print(f"已认领：{args.id}")


def cmd_set(args):
    who = require_identity()
    repo = repo_of(args)
    data = load_ledger(repo)
    task = data["tasks"].get(args.id)
    if not task:
        fail(f"找不到任务：{args.id}")
    if args.release:
        task["owner"] = None
        task["status"] = "open"
        task["started"] = None
        task["updated"] = fmt(now())
        append_log(repo, task, who, "release", "释放回公共池")
    elif args.tags is not None:
        task["tags"] = tags_of(args.tags)
        task["updated"] = fmt(now())
        _CURRENT_LEDGER["data"] = data
        set_header(repo, task, who)
        append_log(repo, task, who, "set", "更新标签")
    elif args.owner:
        fail("agent 不使用 --owner；请让对方自己 claim")
    else:
        fail("set 需要 --release 或 --tags")
    save_ledger(repo, data)
    print(f"已更新：{args.id}")


def cmd_log(args):
    who = require_identity()
    repo = repo_of(args)
    data = load_ledger(repo)
    task = data["tasks"].get(args.id)
    if not task:
        fail(f"找不到任务：{args.id}")
    if task.get("owner") != who["uuid"]:
        fail("只能给自己名下的任务记进展")
    task["updated"] = fmt(now())
    _CURRENT_LEDGER["data"] = data
    append_log(repo, task, who, "log", args.note)
    save_ledger(repo, data)
    print(f"已记录：{args.id}")


def cmd_close(args):
    who = require_identity()
    repo = repo_of(args)
    data = load_ledger(repo)
    task = data["tasks"].get(args.id)
    if not task:
        fail(f"找不到任务：{args.id}")
    if not task.get("owner") and not args.cancel:
        fail("公共池任务只能取消；想正常结案先 claim")
    if task.get("owner") and task["owner"] != who["uuid"]:
        fail("不能结别人名下的任务")
    finished = args.finished or fmt(now())
    result = "cancelled" if args.cancel else "done"
    record = dict(task)
    record.update({
        "result": result,
        "summary": args.summary or "",
        "finished": finished,
        "owner": who["uuid"],
        "owner_name": who["name"],
        "creator_name": name_of(data, task.get("creator")),
        "worklog": f"../worklog/{task['id']}.md",
    })
    data["history"].append(record)
    record["_src"] = f"history/{finished[:4]}{finished[5:7]}.md"
    record["_line"] = len(data["history"]) + 1
    record["_fingerprint"] = hashlib.sha1(
        json.dumps({k: v for k, v in record.items() if not k.startswith("_")},
                   ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:12]
    del data["tasks"][args.id]
    _CURRENT_LEDGER["data"] = data
    append_log(repo, task, who, "cancel" if args.cancel else "close", args.summary or result)
    save_ledger(repo, data)
    print(f"已{'取消' if args.cancel else '结案'}：{args.id}")


def cmd_delete(args):
    who = require_identity()
    repo = repo_of(args)
    data = load_ledger(repo)
    if args.id:
        if args.id not in data["tasks"]:
            fail(f"找不到任务：{args.id}")
        del data["tasks"][args.id]
        save_ledger(repo, data)
        print(f"已删除：{args.id}")
        return
    records = data["history"]
    if args.src:
        idx = None
        for i, rec in enumerate(records):
            if rec.get("_src") == args.src and rec.get("_line") == args.line:
                idx = i
                break
        if idx is None:
            fail("找不到这条历史记录")
        if args.expect and records[idx].get("_fingerprint") != args.expect:
            fail("指纹不匹配，记录已变化，拒绝删除")
        records.pop(idx)
        save_ledger(repo, data)
        print("已删除历史记录")
        return
    fail("delete 需要 --id 或 --src/--line")


def cmd_owners(args):
    repo = repo_of(args)
    data = load_ledger(repo)
    who = identity()
    me = who["uuid"] if who else None
    print(json.dumps({"count": len(data["owners"]), "owners": owners_view(data, me)}, ensure_ascii=False))


def task_view(task, data, me, stale_days, overdue_days, backlog_days, ref=None):
    ref = ref or now()
    created = parse_dt(task.get("created"))
    started = parse_dt(task.get("started")) or created
    updated = parse_dt(task.get("updated")) or started
    status = task.get("status") or "open"
    age = (ref - started).days if started and status == "doing" else None
    idle = (ref - updated).days if updated and status == "doing" else None
    waiting = (ref - created).days if created and status == "open" else None
    return {
        "title": task.get("title", ""),
        "status": status,
        "creator": task.get("creator"),
        "owner": task.get("owner"),
        "creator_name": name_of(data, task.get("creator")),
        "owner_name": name_of(data, task.get("owner")),
        "created": task.get("created"),
        "started": task.get("started"),
        "updated": task.get("updated"),
        "finished": task.get("finished"),
        "category": task.get("category") or "",
        "tags": task.get("tags") or [],
        "worklog": task.get("worklog") or "",
        "age_days": age,
        "idle_days": idle,
        "waiting_days": waiting,
        "stale": bool(status == "doing" and idle is not None and idle >= stale_days),
        "overdue": bool(status == "doing" and age is not None and age >= overdue_days),
        "backlog": bool(status == "open" and waiting is not None and waiting >= backlog_days),
        "mine": bool(me and task.get("owner") == me),
    }


def cmd_list(args):
    who = identity()
    me = who["uuid"] if who else None
    repo = repo_of(args)
    data = load_ledger(repo)
    rows = {}
    for task_id, task in data["tasks"].items():
        view = task_view(task, data, me, args.stale_days, args.overdue_days, args.backlog_days)
        if args.mine and not view["mine"]:
            continue
        if args.pool and view["owner"]:
            continue
        if args.owner and view["owner"] != args.owner:
            continue
        if args.owner_name and args.owner_name.lower() not in (view["owner_name"] or "").lower():
            continue
        if args.status and view["status"] not in [s.strip() for s in args.status.split(",")]:
            continue
        if args.category and view["category"] != args.category:
            continue
        if args.tag and args.tag not in (view["tags"] or []):
            continue
        rows[task_id] = view
    print(json.dumps(rows, ensure_ascii=False))


def cmd_stats(args):
    who = identity()
    me = who["uuid"] if who else None
    repo = repo_of(args)
    data = load_ledger(repo)
    if args.trend:
        print(json.dumps(trend(data, args, me), ensure_ascii=False))
        return
    rows = [task_view(t, data, me, args.stale_days, args.overdue_days, args.backlog_days)
            for t in data["tasks"].values()]
    if args.mine:
        rows = [r for r in rows if r["mine"]]
    if args.pool:
        rows = [r for r in rows if not r["owner"]]
    open_rows = [r for r in rows if r["status"] == "open"]
    doing_rows = [r for r in rows if r["status"] == "doing"]
    oldest = max([r["waiting_days"] for r in open_rows if r["waiting_days"] is not None], default=None)
    out = {
        "total": len(rows),
        "open": len(open_rows),
        "doing": len(doing_rows),
        "stale": sum(1 for r in rows if r["stale"]),
        "overdue": sum(1 for r in rows if r["overdue"]),
        "backlog": sum(1 for r in rows if r["backlog"]),
        "mine": sum(1 for r in rows if r["mine"]),
        "my_doing": sum(1 for r in rows if r["mine"] and r["status"] == "doing"),
        "my_stale": sum(1 for r in rows if r["mine"] and r["stale"]),
        "my_overdue": sum(1 for r in rows if r["mine"] and r["overdue"]),
        "oldest_open_days": oldest,
        "thresholds": {
            "stale_days": args.stale_days,
            "overdue_days": args.overdue_days,
            "backlog_days": args.backlog_days,
        },
    }
    print(json.dumps(out, ensure_ascii=False))


def trend_bounds(args):
    if args.since:
        start = parse_dt(args.since)
        end = parse_dt(args.until) or now()
        return start, end
    last = args.last or "8w"
    m = re.match(r"(\d+)([dwmy])", last)
    n, unit = (int(m.group(1)), m.group(2)) if m else (8, "w")
    end = now()
    days = {"d": 1, "w": 7, "m": 30, "y": 365}[unit] * n
    return end - timedelta(days=days), end


def bucket_starts(start, end, gran):
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    if gran == "week":
        start -= timedelta(days=start.weekday())
        step = timedelta(days=7)
    elif gran == "month":
        start = start.replace(day=1)
        step = "month"
    elif gran == "quarter":
        start = start.replace(month=((start.month - 1) // 3) * 3 + 1, day=1)
        step = "quarter"
    elif gran == "year":
        start = start.replace(month=1, day=1)
        step = "year"
    else:
        step = timedelta(days=1)
    out = []
    cur = start
    while cur <= end:
        if gran == "month":
            nxt = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
        elif gran == "quarter":
            nxt = (cur.replace(day=28) + timedelta(days=95)).replace(day=1)
            nxt = nxt.replace(month=((nxt.month - 1) // 3) * 3 + 1)
        elif gran == "year":
            nxt = cur.replace(year=cur.year + 1, month=1, day=1)
        else:
            nxt = cur + step
        out.append((cur, nxt - timedelta(days=1)))
        cur = nxt
    return out


def trend(data, args, me):
    start, end = trend_bounds(args)
    gran = args.trend
    buckets = []
    for bstart, bend in bucket_starts(start, end, gran):
        lo = bstart
        hi = bend.replace(hour=23, minute=59, second=59)
        added = done = cancelled = 0
        owners = {}
        for task in data["tasks"].values():
            created = parse_dt(task.get("created"))
            if created and lo <= created <= hi:
                added += 1
                owners.setdefault(task.get("creator"), {"added": 0, "done": 0, "cancelled": 0, "open": 0})["added"] += 1
        for rec in data["history"]:
            created = parse_dt(rec.get("created"))
            finished = parse_dt(rec.get("finished"))
            if created and lo <= created <= hi:
                added += 1
                owners.setdefault(rec.get("creator"), {"added": 0, "done": 0, "cancelled": 0, "open": 0})["added"] += 1
            if finished and lo <= finished <= hi:
                if rec.get("result") == "cancelled":
                    cancelled += 1
                    owners.setdefault(rec.get("owner"), {"added": 0, "done": 0, "cancelled": 0, "open": 0})["cancelled"] += 1
                else:
                    done += 1
                    owners.setdefault(rec.get("owner"), {"added": 0, "done": 0, "cancelled": 0, "open": 0})["done"] += 1
        open_count = 0
        for task in data["tasks"].values():
            created = parse_dt(task.get("created"))
            if created and created <= hi:
                open_count += 1
        for rec in data["history"]:
            created = parse_dt(rec.get("created"))
            finished = parse_dt(rec.get("finished"))
            if created and created <= hi and (finished is None or finished > hi):
                open_count += 1
        for uuid, cell in owners.items():
            cell["open"] = open_count if uuid == me else 0
        buckets.append({
            "from": bstart.strftime("%Y-%m-%d"),
            "to": bend.strftime("%Y-%m-%d"),
            "added": added,
            "done": done,
            "cancelled": cancelled,
            "open": open_count,
            "owners": {u: v for u, v in owners.items() if u},
        })
    return {
        "granularity": gran,
        "coverage": {"from": start.strftime("%Y-%m-%d"), "to": end.strftime("%Y-%m-%d")},
        "buckets": buckets,
        "warnings": [],
    }


def cmd_show(args):
    repo = repo_of(args)
    data = load_ledger(repo)
    task = data["tasks"].get(args.id)
    if task:
        who = identity()
        view = task_view(task, data, who["uuid"] if who else None, STALE_DAYS, OVERDUE_DAYS, BACKLOG_DAYS)
        path = worklog_path(repo, args.id)
        content = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
        print(json.dumps({**view, "id": args.id, "content": content, "path": path}, ensure_ascii=False))
        return
    for rec in data["history"]:
        if rec.get("id") == args.id:
            path = worklog_path(repo, args.id)
            content = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
            print(json.dumps({**rec, "id": args.id, "content": content, "path": path}, ensure_ascii=False))
            return
    fail(f"找不到任务：{args.id}")


def cmd_history(args):
    repo = repo_of(args)
    data = load_ledger(repo)
    who = identity()
    me = who["uuid"] if who else None
    records = []
    for i, rec in enumerate(data["history"]):
        finished = parse_dt(rec.get("finished"))
        if args.since and finished and finished < parse_dt(args.since):
            continue
        if args.until and finished and finished > parse_dt(args.until).replace(hour=23, minute=59):
            continue
        if args.mine and rec.get("owner") != me:
            continue
        if args.owner and rec.get("owner") != args.owner:
            continue
        if args.owner_name and args.owner_name.lower() not in (rec.get("owner_name") or "").lower():
            continue
        if args.category and rec.get("category") != args.category:
            continue
        if args.tag and args.tag not in (rec.get("tags") or []):
            continue
        src = rec.get("_src") or f"history/{str(rec.get('finished', ''))[:4]}{str(rec.get('finished', ''))[5:7]}.md"
        line = rec.get("_line") or (i + 2)
        fingerprint = rec.get("_fingerprint") or hashlib.sha1(
            json.dumps(rec, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12]
        records.append({
            "title": rec.get("title", ""),
            "summary": rec.get("summary", ""),
            "category": rec.get("category", ""),
            "tags": rec.get("tags") or [],
            "result": rec.get("result", "done"),
            "owner": rec.get("owner") or "",
            "owner_name": rec.get("owner_name") or "",
            "creator": rec.get("creator") or "",
            "creator_name": rec.get("creator_name") or "",
            "created": rec.get("created") or "",
            "finished": rec.get("finished") or "",
            "worklog": rec.get("worklog") or f"../worklog/{rec.get('id')}.md",
            "src": src,
            "line": line,
            "fingerprint": fingerprint,
            "mine": bool(me and rec.get("owner") == me),
        })
    records.sort(key=lambda r: r["finished"], reverse=True)
    if args.limit:
        records = records[: args.limit]
    print(json.dumps({"records": records, "count": len(records), "capped": False}, ensure_ascii=False))


def cmd_validate(args):
    repo = repo_of(args)
    data = load_ledger(repo)
    problems = []
    for task_id, task in data["tasks"].items():
        if not task.get("title"):
            problems.append(f"{task_id}: 缺 title")
        if task.get("status") not in ("open", "doing"):
            problems.append(f"{task_id}: 非法状态 {task.get('status')}")
    print(json.dumps({
        "problems": problems,
        "notices": [],
        "checked_files": 1,
        "total_tasks": len(data["tasks"]),
        "deep": bool(args.deep),
    }, ensure_ascii=False))
    sys.exit(1 if problems else 0)


def cmd_switch(args):
    if args.new:
        uuid = secrets.token_hex(8)
        data = {"uuid": uuid, "name": args.name or "未命名"}
        write_json(IDENTITY, data)
        print(json.dumps(data, ensure_ascii=False))
        return
    if args.claim:
        name = args.name or args.claim
        data = {"uuid": args.claim, "name": name}
        write_json(IDENTITY, data)
        print(json.dumps(data, ensure_ascii=False))
        return
    fail("switch 需要 --new 或 --claim")


def cmd_forget(args):
    print(json.dumps({"ok": True}, ensure_ascii=False))


def cmd_logout(args):
    try:
        os.remove(IDENTITY)
    except OSError:
        pass
    print(json.dumps({"ok": True}, ensure_ascii=False))


# ---------------- 参数 ----------------
def build_parser():
    p = argparse.ArgumentParser(prog="ledger", add_help=True)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, repo=True):
        if repo:
            sp.add_argument("--repo", default=None)
        sp.add_argument("--json", action="store_true")

    sp = sub.add_parser("root"); sp.add_argument("--dir", default=None); sp.add_argument("--json", action="store_true"); sp.set_defaults(func=cmd_root)
    sp = sub.add_parser("whoami"); sp.add_argument("--json", action="store_true"); sp.set_defaults(func=cmd_whoami)
    sp = sub.add_parser("init"); sp.add_argument("--new", action="store_true"); sp.add_argument("--name"); sp.add_argument("--claim"); sp.add_argument("--repo"); sp.set_defaults(func=cmd_init)
    sp = sub.add_parser("dirs"); sp.add_argument("--all", action="store_true"); sp.add_argument("--dir"); sp.add_argument("--name")
    sp.add_argument("--add", action="store_true"); sp.add_argument("--remove", action="store_true")
    sp.add_argument("--hide", action="store_true"); sp.add_argument("--unhide", action="store_true"); sp.add_argument("--rename")
    sp.add_argument("--json", action="store_true"); sp.set_defaults(func=cmd_dirs)

    sp = sub.add_parser("new"); sp.add_argument("--title", required=True); sp.add_argument("--tags", required=True)
    sp.add_argument("--category"); sp.add_argument("--id"); sp.add_argument("--created"); sp.add_argument("--self", action="store_true")
    sp.add_argument("--repo", default=None); sp.set_defaults(func=cmd_new)

    sp = sub.add_parser("claim"); sp.add_argument("--id", required=True); sp.add_argument("--repo"); sp.set_defaults(func=cmd_claim)
    sp = sub.add_parser("set"); sp.add_argument("--id", required=True); sp.add_argument("--release", action="store_true")
    sp.add_argument("--owner"); sp.add_argument("--tags"); sp.add_argument("--repo"); sp.set_defaults(func=cmd_set)
    sp = sub.add_parser("log"); sp.add_argument("--id", required=True); sp.add_argument("--note", required=True); sp.add_argument("--repo"); sp.set_defaults(func=cmd_log)
    sp = sub.add_parser("close"); sp.add_argument("--id", required=True); sp.add_argument("--summary"); sp.add_argument("--cancel", action="store_true")
    sp.add_argument("--finished"); sp.add_argument("--tags"); sp.add_argument("--repo"); sp.set_defaults(func=cmd_close)
    sp = sub.add_parser("delete"); sp.add_argument("--id"); sp.add_argument("--src"); sp.add_argument("--line", type=int)
    sp.add_argument("--expect"); sp.add_argument("--summary"); sp.add_argument("--repo"); sp.set_defaults(func=cmd_delete)

    sp = sub.add_parser("list"); sp.add_argument("--mine", action="store_true"); sp.add_argument("--pool", action="store_true")
    sp.add_argument("--owner"); sp.add_argument("--owner-name"); sp.add_argument("--status"); sp.add_argument("--category")
    sp.add_argument("--tag"); sp.add_argument("--since"); sp.add_argument("--until")
    sp.add_argument("--stale-days", type=int, default=STALE_DAYS); sp.add_argument("--overdue-days", type=int, default=OVERDUE_DAYS)
    sp.add_argument("--backlog-days", type=int, default=BACKLOG_DAYS); sp.add_argument("--repo"); sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("stats"); sp.add_argument("--mine", action="store_true"); sp.add_argument("--pool", action="store_true")
    sp.add_argument("--owner"); sp.add_argument("--owner-name"); sp.add_argument("--status"); sp.add_argument("--category")
    sp.add_argument("--tag"); sp.add_argument("--since"); sp.add_argument("--until")
    sp.add_argument("--stale-days", type=int, default=STALE_DAYS); sp.add_argument("--overdue-days", type=int, default=OVERDUE_DAYS)
    sp.add_argument("--backlog-days", type=int, default=BACKLOG_DAYS)
    sp.add_argument("--trend", choices=["day", "week", "month", "quarter", "year"]); sp.add_argument("--last")
    sp.add_argument("--by-owner", action="store_true"); sp.add_argument("--repo"); sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_stats)

    sp = sub.add_parser("owners"); sp.add_argument("--repo"); sp.add_argument("--json", action="store_true"); sp.set_defaults(func=cmd_owners)
    sp = sub.add_parser("show"); sp.add_argument("--id", required=True); sp.add_argument("--repo"); sp.add_argument("--json", action="store_true"); sp.set_defaults(func=cmd_show)
    sp = sub.add_parser("history"); sp.add_argument("--mine", action="store_true"); sp.add_argument("--owner"); sp.add_argument("--owner-name")
    sp.add_argument("--category"); sp.add_argument("--tag"); sp.add_argument("--since"); sp.add_argument("--until")
    sp.add_argument("--months", type=int); sp.add_argument("--limit", type=int); sp.add_argument("--repo"); sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_history)

    sp = sub.add_parser("validate"); sp.add_argument("--deep", action="store_true"); sp.add_argument("--repo"); sp.add_argument("--json", action="store_true"); sp.set_defaults(func=cmd_validate)
    sp = sub.add_parser("switch"); sp.add_argument("--new", action="store_true"); sp.add_argument("--claim"); sp.add_argument("--name")
    sp.add_argument("--repo"); sp.add_argument("--json", action="store_true"); sp.set_defaults(func=cmd_switch)
    sp = sub.add_parser("forget"); sp.add_argument("--id"); sp.add_argument("--keep-identity", action="store_true"); sp.add_argument("--repo"); sp.add_argument("--json", action="store_true"); sp.set_defaults(func=cmd_forget)
    sp = sub.add_parser("logout"); sp.add_argument("--repo"); sp.add_argument("--json", action="store_true"); sp.set_defaults(func=cmd_logout)
    return p


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
