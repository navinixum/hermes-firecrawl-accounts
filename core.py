"""Shared state + Firecrawl HTTP client for the firecrawl-accounts plugin.

Design rules:
- API keys live ONLY in $HERMES_HOME/.env as FIRECRAWL_ACCT_<ID>_API_KEY. They are never
  returned by any tool or REST route (only a masked tail).
- The active account is chosen by the USER (desktop switcher / slash command). The agent's
  tools can read it but cannot change it, and nothing ever rotates accounts automatically.
- A crawl job is pinned to the account that started it, so later switches never break it.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional

API_BASE = "https://api.firecrawl.dev/v2"
ID_RE = re.compile(r"^[a-z0-9_]{1,24}$")
MAX_JOBS = 200


def _home() -> Path:
    try:
        from hermes_constants import get_hermes_home

        return Path(get_hermes_home())
    except Exception:
        return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")


def _dir() -> Path:
    d = _home() / "firecrawl-accounts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_path() -> Path:
    return _dir() / "state.json"


def env_key(account_id: str) -> str:
    return f"FIRECRAWL_ACCT_{account_id.upper()}_API_KEY"


@contextmanager
def _locked():
    lock = open(_dir() / ".lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def _read() -> dict:
    try:
        data = json.loads(_state_path().read_text("utf-8"))
    except (OSError, ValueError):
        data = {}
    data.setdefault("accounts", [])
    data.setdefault("active", None)
    data.setdefault("jobs", {})
    return data


def _write(data: dict) -> None:
    path = _state_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


# ---------------------------------------------------------------- secrets

def _get_key(account_id: str) -> Optional[str]:
    name = env_key(account_id)
    try:
        from hermes_cli.config import invalidate_env_cache, load_env

        invalidate_env_cache()
        val = load_env().get(name)
    except Exception:
        val = None
    return val or os.environ.get(name) or None


def _save_key(account_id: str, key: str) -> None:
    from hermes_cli.config import require_env_writable, save_env_value

    name = env_key(account_id)
    require_env_writable(name, "set")
    save_env_value(name, key)


def _remove_key(account_id: str) -> None:
    try:
        from hermes_cli.config import remove_env_value

        remove_env_value(env_key(account_id))
    except Exception:
        pass


def _mask(key: Optional[str]) -> str:
    if not key:
        return "— ключ не найден —"
    return f"fc-…{key[-4:]}" if len(key) > 8 else "fc-…"


# ---------------------------------------------------------------- HTTP

class FirecrawlError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _http(key: str, method: str, path: str, body: Optional[dict] = None, timeout: int = 120) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        API_BASE + path,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error") or exc.reason
        except Exception:
            detail = exc.reason
        raise FirecrawlError(exc.code, str(detail)) from None
    except urllib.error.URLError as exc:
        raise FirecrawlError(0, f"сеть: {exc.reason}") from None


def explain(err: FirecrawlError, label: str) -> str:
    hints = {
        401: "ключ недействителен или отозван",
        402: "закончились кредиты / нужна оплата",
        429: "превышен лимит запросов, подождите",
    }
    hint = hints.get(err.status, "")
    msg = f"Firecrawl [{label}] ошибка {err.status or ''}: {err}".strip()
    if hint:
        msg += f" ({hint})"
    if err.status in (401, 402, 429):
        msg += ". Аккаунт автоматически НЕ переключается — выберите другой в переключателе Firecrawl."
    return msg


# ---------------------------------------------------------------- accounts

def slugify(label: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")[:24]
    return s or "account"


def list_accounts() -> dict:
    data = _read()
    out = []
    for acc in data["accounts"]:
        key = _get_key(acc["id"])
        out.append({
            "id": acc["id"],
            "label": acc.get("label") or acc["id"],
            "masked": _mask(key),
            "has_key": bool(key),
            "credits": acc.get("credits"),
            "plan_credits": acc.get("plan_credits"),
            "checked_at": acc.get("checked_at"),
            "check_error": acc.get("check_error"),
        })
    return {"accounts": out, "active": data["active"]}


def _find(data: dict, account_id: str) -> Optional[dict]:
    return next((a for a in data["accounts"] if a["id"] == account_id), None)


def add_account(label: str, key: str) -> dict:
    label = (label or "").strip()[:40]
    key = (key or "").strip()
    if not label:
        raise ValueError("Укажите название аккаунта")
    if not key.startswith("fc-") or len(key) < 12:
        raise ValueError("Ключ Firecrawl должен начинаться с fc-")
    # Validate before saving: a typo should not become an account.
    try:
        usage = _http(key, "GET", "/team/credit-usage", timeout=20).get("data") or {}
    except FirecrawlError as exc:
        raise ValueError(f"Firecrawl отклонил ключ ({exc.status}): {exc}") from None
    with _locked():
        data = _read()
        base = slugify(label)
        acc_id, n = base, 2
        while _find(data, acc_id):
            acc_id = f"{base[:21]}_{n}"
            n += 1
        _save_key(acc_id, key)
        data["accounts"].append({
            "id": acc_id,
            "label": label,
            "credits": usage.get("remainingCredits"),
            "plan_credits": usage.get("planCredits"),
            "checked_at": int(time.time()),
        })
        if not data["active"]:
            data["active"] = acc_id
        _write(data)
    return {"id": acc_id}


def remove_account(account_id: str) -> None:
    with _locked():
        data = _read()
        if not _find(data, account_id):
            raise ValueError("Нет такого аккаунта")
        data["accounts"] = [a for a in data["accounts"] if a["id"] != account_id]
        if data["active"] == account_id:
            data["active"] = None  # never auto-pick a replacement
        _write(data)
    _remove_key(account_id)


def set_active(account_id: Optional[str]) -> None:
    with _locked():
        data = _read()
        if account_id is not None and not _find(data, account_id):
            raise ValueError("Нет такого аккаунта")
        data["active"] = account_id
        _write(data)


def refresh_credits() -> None:
    data = _read()
    results = {}
    for acc in data["accounts"]:
        key = _get_key(acc["id"])
        if not key:
            results[acc["id"]] = {"check_error": "ключ не найден в .env"}
            continue
        try:
            u = _http(key, "GET", "/team/credit-usage", timeout=20).get("data") or {}
            results[acc["id"]] = {"credits": u.get("remainingCredits"),
                                  "plan_credits": u.get("planCredits"), "check_error": None}
        except FirecrawlError as exc:
            results[acc["id"]] = {"check_error": f"{exc.status}: {exc}"}
    with _locked():
        data = _read()
        for acc in data["accounts"]:
            if acc["id"] in results:
                acc.update(results[acc["id"]])
                acc["checked_at"] = int(time.time())
        _write(data)


# ---------------------------------------------------------------- calls used by tools

def resolve(account_id: Optional[str] = None) -> tuple[str, str, str]:
    """Return (id, label, key) for the given or the active account; raise RuntimeError otherwise."""
    data = _read()
    acc_id = account_id or data["active"]
    if not acc_id:
        raise RuntimeError(
            "Аккаунт Firecrawl не выбран. Выберите его в переключателе Firecrawl "
            "(строка статуса Hermes Desktop) или командой /firecrawl use <имя>."
        )
    acc = _find(data, acc_id)
    if not acc:
        raise RuntimeError(f"Аккаунт Firecrawl '{acc_id}' удалён.")
    key = _get_key(acc_id)
    if not key:
        raise RuntimeError(f"Для аккаунта '{acc.get('label')}' нет ключа в .env.")
    return acc_id, acc.get("label") or acc_id, key


def pin_job(job_id: str, account_id: str) -> None:
    with _locked():
        data = _read()
        data["jobs"][job_id] = {"account": account_id, "at": int(time.time())}
        if len(data["jobs"]) > MAX_JOBS:
            oldest = sorted(data["jobs"].items(), key=lambda kv: kv[1].get("at", 0))
            for jid, _ in oldest[: len(data["jobs"]) - MAX_JOBS]:
                data["jobs"].pop(jid, None)
        _write(data)


def job_account(job_id: str) -> Optional[str]:
    rec = _read()["jobs"].get(job_id)
    return rec.get("account") if rec else None


def call(method: str, path: str, body: Optional[dict] = None, account_id: Optional[str] = None,
         timeout: int = 120) -> tuple[dict, str, str]:
    acc_id, label, key = resolve(account_id)
    try:
        return _http(key, method, path, body, timeout=timeout), acc_id, label
    except FirecrawlError as exc:
        raise RuntimeError(explain(exc, label)) from None
