"""REST backend for the desktop switcher → /api/plugins/firecrawl-accounts/*

Keys travel desktop → backend only on POST /add and are written straight to .env.
No route ever returns a key.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

_CORE_PATH = Path(__file__).resolve().parent.parent / "core.py"
_spec = importlib.util.spec_from_file_location("firecrawl_accounts_core_api", _CORE_PATH)
core = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = core
_spec.loader.exec_module(core)

router = APIRouter()


class SelectBody(BaseModel):
    id: str | None = None


class AddBody(BaseModel):
    label: str
    key: str


class IdBody(BaseModel):
    id: str


def _changed():
    try:
        from hermes_cli.plugin_events import broadcast_plugin_event

        broadcast_plugin_event("firecrawl-accounts", "changed", {})
    except Exception:
        pass


@router.get("/accounts")
async def accounts():
    return core.list_accounts()


@router.post("/select")
async def select(body: SelectBody):
    try:
        core.set_active(body.id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    _changed()
    return core.list_accounts()


@router.post("/add")
async def add(body: AddBody):
    try:
        res = await asyncio.to_thread(core.add_account, body.label, body.key)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    _changed()
    return {**core.list_accounts(), "added": res["id"]}


@router.post("/remove")
async def remove(body: IdBody):
    try:
        core.remove_account(body.id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    _changed()
    return core.list_accounts()


@router.post("/refresh")
async def refresh():
    await asyncio.to_thread(core.refresh_credits)
    _changed()
    return core.list_accounts()
