"""Use the existing local management guard; executable assets use revocable tickets."""
from __future__ import annotations

import hashlib
import mimetypes
from fastapi import APIRouter, HTTPException, Request, Response
from .runtime import extension_store
from .store import MAX_PACKAGE
from app.plugin_security_v2.management import LocalManagementGuard


async def guarded_store(request: Request):
    guard = getattr(request.app.state, "plugin_platform_v2_management_guard", None)
    if not isinstance(guard, LocalManagementGuard):
        guard = getattr(request.app.state, "trusted_extension_management_guard", None)
    if not isinstance(guard, LocalManagementGuard):
        raise HTTPException(503, "Trusted extension management is unavailable")
    await guard(request)
    platform = getattr(request.app.state, "plugin_platform_v2", None)
    return extension_store(request.app, getattr(platform, "root", None))


def create_extension_router() -> APIRouter:
    from app.plugin_core_v2.api import _body, _bounded_binary_body
    router = APIRouter(prefix="/api/v2/plugins", tags=["trusted-extensions"])

    @router.get("/manage/extensions")
    async def catalog(request: Request):
        store = await guarded_store(request)
        host = getattr(request.app.state, "trusted_extension_host", None)
        return {**store.catalog(), "backendErrors": host.errors if host else {},
                "backendActive": [{"id": item[0]["manifest"]["id"], "version": item[0]["manifest"]["version"],
                    "digest": item[0]["digest"], "generation": item[0]["generation"]}
                    for item in host.loaded if item[0]["manifest"]["id"] not in host.errors] if host else [],
                "backendLoaded": [item[0]["digest"] for item in host.loaded] if host else []}

    @router.get("/manage/extensions/plan")
    async def plan(request: Request, afterRevision: int = -1):
        store = await guarded_store(request)
        try:
            if store.revision() == afterRevision:
                return {"unchanged": True}
            return store.plan()
        except Exception as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get("/manage/extensions/desktop")
    async def desktop_plan(request: Request):
        store = await guarded_store(request)
        try:
            plan = store.plan()
            entries = []
            for item in plan["active"]:
                if "desktop" in item["manifest"].get("entries", {}):
                    root = store.materialize(item["digest"])
                    _, files = store.package(item["digest"])
                    entries.append({**item, "root": str(root), "files": {
                        name: hashlib.sha256(data).hexdigest() for name, data in files.items()}})
            return {"active": entries, "revision": plan["revision"], "safeMode": plan["safeMode"]}
        except Exception as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/manage/extensions/stage")
    async def stage(request: Request):
        store = await guarded_store(request)
        data = await _bounded_binary_body(request, maximum=MAX_PACKAGE, allow_empty=False)
        try:
            return store.stage(data)
        except Exception as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/manage/extensions/change")
    async def change(request: Request):
        store = await guarded_store(request)
        body = await _body(request, required={"action", "id"}, optional={"digest", "acknowledgement"})
        if not all(isinstance(value, str) for value in body.values()):
            raise HTTPException(400, "Extension operation values must be strings")
        try:
            result = store.change(body["action"], body["id"], body.get("digest"), body.get("acknowledgement"))
            return result
        except Exception as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get("/manage/extensions/review/{digest}")
    async def review(digest: str, request: Request):
        store = await guarded_store(request)
        try:
            manifest, _ = store.package(digest)
            return {"manifest": manifest, "digest": digest, "signed": False}
        except Exception as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get("/extension-assets/{ticket}/{path:path}")
    async def asset(ticket: str, path: str, request: Request):
        try:
            data = extension_store(request.app).asset(ticket, path)
            media = "text/javascript" if path.endswith((".mjs", ".js")) else mimetypes.guess_type(path)[0] or "application/octet-stream"
            return Response(data, media_type=media, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"})
        except Exception as exc:
            raise HTTPException(404, "Extension asset unavailable") from exc
    return router
