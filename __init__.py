"""firecrawl-accounts — Firecrawl tools with a user-controlled account switcher.

The agent gets scrape/search/map/crawl tools that always run under the account the USER
selected (desktop status-bar switcher or /firecrawl). The agent can read which account is
active but has no tool to change it.
"""

from __future__ import annotations

import json
import logging

from . import core

logger = logging.getLogger(__name__)

TOOLSET = "firecrawl_accounts"
MAX_CHARS = 40_000


def _ok(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _err(msg: str) -> str:
    return json.dumps({"error": msg}, ensure_ascii=False)


def _clip(text, limit=MAX_CHARS):
    if isinstance(text, str) and len(text) > limit:
        return text[:limit] + f"\n\n…[обрезано: {len(text) - limit} символов]"
    return text


def _guard(fn):
    def wrapper(args, **kwargs):
        try:
            return fn(args or {})
        except (RuntimeError, ValueError) as exc:
            return _err(str(exc))
        except Exception as exc:  # never crash the turn
            logger.exception("firecrawl-accounts tool failed")
            return _err(f"Внутренняя ошибка: {exc}")
    return wrapper


# ------------------------------------------------------------------ tools

@_guard
def t_status(args):
    info = core.list_accounts()
    active = next((a for a in info["accounts"] if a["id"] == info["active"]), None)
    return _ok({
        "active_account": active["label"] if active else None,
        "accounts": [{"label": a["label"], "credits": a["credits"]} for a in info["accounts"]],
        "note": "Аккаунт выбирает только пользователь в переключателе Firecrawl.",
    })


@_guard
def t_scrape(args):
    url = args.get("url")
    if not url:
        raise ValueError("Нужен url")
    body = {"url": url, "formats": args.get("formats") or ["markdown"],
            "onlyMainContent": args.get("only_main_content", True)}
    if args.get("wait_for"):
        body["waitFor"] = int(args["wait_for"])
    if args.get("max_age") is not None:
        # 0 = always fetch fresh (Firecrawl v2 otherwise may serve a cached copy up to 2 days old)
        body["maxAge"] = max(0, int(args["max_age"]))
    res, _, label = core.call("POST", "/scrape", body)
    d = res.get("data") or {}
    out = {"account": label, "url": url, "metadata": {
        k: (d.get("metadata") or {}).get(k) for k in ("title", "description", "sourceURL", "statusCode")}}
    for f in ("markdown", "summary", "html", "links"):
        if d.get(f) is not None:
            out[f] = _clip(d[f]) if f != "links" else d[f][:300]
    return _ok(out)


@_guard
def t_search(args):
    q = args.get("query")
    if not q:
        raise ValueError("Нужен query")
    body = {"query": q, "limit": max(1, min(int(args.get("limit") or 5), 20))}
    for src, dst in (("country", "country"), ("location", "location"), ("tbs", "tbs")):
        if args.get(src):
            body[dst] = args[src]
    if args.get("scrape_results"):
        body["scrapeOptions"] = {"formats": ["markdown"], "onlyMainContent": True}
    res, _, label = core.call("POST", "/search", body)
    data = res.get("data") or {}
    web = data.get("web") if isinstance(data, dict) else data
    items = []
    per = MAX_CHARS // max(1, len(web or []))
    for r in web or []:
        item = {k: r.get(k) for k in ("url", "title", "description")}
        if r.get("markdown"):
            item["markdown"] = _clip(r["markdown"], per)
        items.append(item)
    return _ok({"account": label, "query": q, "results": items})


@_guard
def t_map(args):
    url = args.get("url")
    if not url:
        raise ValueError("Нужен url")
    body = {"url": url, "limit": max(1, min(int(args.get("limit") or 200), 5000))}
    if args.get("search"):
        body["search"] = args["search"]
    res, _, label = core.call("POST", "/map", body)
    links = res.get("links") or []
    links = [l.get("url") if isinstance(l, dict) else l for l in links]
    return _ok({"account": label, "count": len(links), "links": links[:1000]})


@_guard
def t_crawl(args):
    url = args.get("url")
    if not url:
        raise ValueError("Нужен url")
    body = {"url": url, "limit": max(1, min(int(args.get("limit") or 10), 200)),
            "scrapeOptions": {"formats": ["markdown"], "onlyMainContent": True}}
    for src, dst in (("include_paths", "includePaths"), ("exclude_paths", "excludePaths"),
                     ("max_depth", "maxDiscoveryDepth")):
        if args.get(src):
            body[dst] = args[src]
    res, acc_id, label = core.call("POST", "/crawl", body)
    job = res.get("id")
    if not job:
        raise RuntimeError(f"Firecrawl не вернул id задачи: {res}")
    core.pin_job(job, acc_id)
    return _ok({"account": label, "job_id": job, "status": "started",
                "note": "Задача закреплена за этим аккаунтом. Проверяйте firecrawl_crawl_status."})


@_guard
def t_crawl_status(args):
    job = args.get("job_id")
    if not job:
        raise ValueError("Нужен job_id")
    acc = core.job_account(job)  # pinned account wins over the current selection
    res, _, label = core.call("GET", f"/crawl/{job}", None, account_id=acc)
    pages = res.get("data") or []
    per = MAX_CHARS // max(1, len(pages))
    return _ok({
        "account": label, "status": res.get("status"), "completed": res.get("completed"),
        "total": res.get("total"), "credits_used": res.get("creditsUsed"),
        "has_more": bool(res.get("next")),
        "pages": [{"url": (p.get("metadata") or {}).get("sourceURL"),
                   "title": (p.get("metadata") or {}).get("title"),
                   "markdown": _clip(p.get("markdown") or "", per)} for p in pages],
    })


S = lambda name, desc, props, req: {  # noqa: E731
    "name": name, "description": desc,
    "parameters": {"type": "object", "properties": props, "required": req},
}

TOOLS = [
    ("firecrawl_account_status", t_status, S(
        "firecrawl_account_status",
        "Показать, какой аккаунт Firecrawl сейчас выбран пользователем, и остаток кредитов. "
        "Переключать аккаунт агент не может — это делает пользователь.", {}, [])),
    ("firecrawl_scrape", t_scrape, S(
        "firecrawl_scrape",
        "Скачать одну веб-страницу через Firecrawl (выбранный пользователем аккаунт) и вернуть markdown.",
        {"url": {"type": "string"},
         "formats": {"type": "array", "items": {"type": "string",
                     "enum": ["markdown", "summary", "html", "links"]}},
         "only_main_content": {"type": "boolean", "default": True},
         "wait_for": {"type": "integer", "description": "мс ожидания JS-рендера"},
         "max_age": {"type": "integer", "description": "Макс. возраст кеша Firecrawl в мс. 0 = всегда свежая загрузка "
                     "(по умолчанию Firecrawl может отдать кеш до 2 дней)."}}, ["url"])),
    ("firecrawl_search", t_search, S(
        "firecrawl_search",
        "Веб-поиск через Firecrawl (выбранный пользователем аккаунт). scrape_results=true добавит текст страниц.",
        {"query": {"type": "string"}, "limit": {"type": "integer", "default": 5},
         "country": {"type": "string", "description": "ISO код, напр. PL, UA, US"},
         "location": {"type": "string"}, "tbs": {"type": "string", "description": "напр. qdr:w"},
         "scrape_results": {"type": "boolean", "default": False}}, ["query"])),
    ("firecrawl_map", t_map, S(
        "firecrawl_map", "Получить список URL сайта через Firecrawl.",
        {"url": {"type": "string"}, "search": {"type": "string"},
         "limit": {"type": "integer", "default": 200}}, ["url"])),
    ("firecrawl_crawl", t_crawl, S(
        "firecrawl_crawl",
        "Запустить обход сайта (асинхронно). Возвращает job_id; задача закрепляется за текущим аккаунтом.",
        {"url": {"type": "string"}, "limit": {"type": "integer", "default": 10},
         "include_paths": {"type": "array", "items": {"type": "string"}},
         "exclude_paths": {"type": "array", "items": {"type": "string"}},
         "max_depth": {"type": "integer"}}, ["url"])),
    ("firecrawl_crawl_status", t_crawl_status, S(
        "firecrawl_crawl_status",
        "Статус и результаты обхода по job_id (всегда через аккаунт, запустивший задачу).",
        {"job_id": {"type": "string"}}, ["job_id"])),
]


# ------------------------------------------------------------------ /firecrawl (user-only)

def _slash(raw: str) -> str:
    parts = (raw or "").split()
    cmd = parts[0].lower() if parts else "list"
    try:
        if cmd in ("list", "ls", "status"):
            info = core.list_accounts()
            if not info["accounts"]:
                return "Аккаунтов Firecrawl нет. Добавьте их в переключателе Firecrawl в Hermes Desktop."
            lines = []
            for a in info["accounts"]:
                mark = "●" if a["id"] == info["active"] else "○"
                cr = f" — {a['credits']} кредитов" if a["credits"] is not None else ""
                lines.append(f"{mark} {a['label']} ({a['id']}){cr}")
            return "Firecrawl:\n" + "\n".join(lines)
        if cmd == "use" and len(parts) > 1:
            target = " ".join(parts[1:]).lower()
            info = core.list_accounts()
            acc = next((a for a in info["accounts"]
                        if target in (a["id"], a["label"].lower())), None)
            if not acc:
                return f"Не найден аккаунт '{target}'. /firecrawl list"
            core.set_active(acc["id"])
            _broadcast()
            return f"Firecrawl: активный аккаунт — {acc['label']}"
        if cmd == "refresh":
            core.refresh_credits()
            _broadcast()
            return _slash("list")
        return "Использование: /firecrawl [list | use <имя> | refresh]"
    except ValueError as exc:
        return str(exc)


def _broadcast():
    try:
        from hermes_cli.plugin_events import broadcast_plugin_event

        broadcast_plugin_event("firecrawl-accounts", "changed", {})
    except Exception:
        pass


def register(ctx):
    for name, handler, schema in TOOLS:
        ctx.register_tool(name=name, toolset=TOOLSET, schema=schema, handler=handler,
                          emoji="🔥", description=schema["description"])
    ctx.register_command("firecrawl", _slash,
                         description="Аккаунты Firecrawl: list | use <имя> | refresh")
