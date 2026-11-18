"""Unified management, realm sync and revocable assets under the existing guard."""

from __future__ import annotations

import asyncio
import mimetypes
import tempfile
from pathlib import Path

from candlescope_plugin_sdk.platform_v2 import (
    JsonLimits,
    PlatformContractError,
    loads_strict,
)
from fastapi import APIRouter, HTTPException, Request, Response

from app.plugin_security_v2.management import LocalManagementGuard

from .bundle import MAX_PACKAGE_BYTES
from .store import LifecycleError


async def _runtime(request, *, background=False):
    guard = getattr(request.app.state, "plugin_platform_v2_management_guard", None)
    if not isinstance(guard, LocalManagementGuard):
        guard = getattr(request.app.state, "trusted_extension_management_guard", None)
    if not isinstance(guard, LocalManagementGuard):
        raise HTTPException(503, "Plugin management is unavailable")
    await (guard.authorize_background(request) if background else guard(request))
    runtime = getattr(request.app.state, "unified_plugin_runtime", None)
    if runtime is None:
        raise HTTPException(503, "Unified lifecycle is unavailable")
    return runtime


async def _body(request):
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 64 * 1024:
            raise HTTPException(413, "Plugin operation is too large")
        body.extend(chunk)
    try:
        value = loads_strict(
            bytes(body), limits=JsonLimits(max_message_bytes=64 * 1024)
        )
        if not isinstance(value, dict):
            raise TypeError("object required")
        return value
    except (ValueError, TypeError, PlatformContractError) as exc:
        raise HTTPException(400, "Invalid plugin operation") from exc


def create_unified_router():
    router = APIRouter(prefix="/api/v2/plugins", tags=["unified-plugins"])

    @router.get("/manage/unified")
    async def catalog(request: Request):
        runtime = await _runtime(request)
        await runtime.reconcile()
        async with runtime.lock:
            return await asyncio.to_thread(runtime.catalog)

    @router.post("/manage/unified/stage")
    async def stage(request: Request):
        runtime = await _runtime(request)
        # Streaming spool keeps uploads out of memory and outside executable trees.
        with tempfile.TemporaryDirectory(
            prefix="candlescope-unified-upload-"
        ) as directory:
            path = Path(directory) / "upload.cspkg"
            size = 0
            with path.open("wb") as output:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > MAX_PACKAGE_BYTES:
                        raise HTTPException(
                            413, "Plugin package exceeds its byte budget"
                        )
                    output.write(chunk)
            try:
                package = await asyncio.to_thread(runtime.store.stage, path)
                return await asyncio.to_thread(runtime.store.review, package.sha256)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc

    @router.post("/manage/unified/change")
    async def change(request: Request):
        runtime = await _runtime(request)
        body = await _body(request)
        action = body.get("action")
        try:
            if action == "activate" and set(body) == {
                "action",
                "digest",
                "revision",
                "acknowledgement",
            }:
                review = await asyncio.to_thread(runtime.store.review, body["digest"])
                from candlescope_plugin_sdk.unified import Manifest

                await asyncio.to_thread(
                    runtime.validate_activation, Manifest.from_wire(review["manifest"])
                )
                result = await asyncio.to_thread(
                    runtime.store.activate,
                    body["digest"],
                    expected_revision=body["revision"],
                    acknowledgement=body["acknowledgement"],
                )
            elif action in {"disable", "uninstall"} and set(body) == {
                "action",
                "id",
                "revision",
            }:
                result = await asyncio.to_thread(
                    getattr(runtime.store, action),
                    body["id"],
                    expected_revision=body["revision"],
                )
            else:
                raise LifecycleError("Invalid unified lifecycle operation")
            await runtime.reconcile()
            return {"revision": result["revision"], "catalog": runtime.catalog()}
        except (ValueError, TypeError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/manage/unified/review")
    async def review(request: Request):
        runtime = await _runtime(request)
        body = await _body(request)
        if set(body) != {"digest"}:
            raise HTTPException(400, "digest required")
        try:
            return await asyncio.to_thread(runtime.store.review, body["digest"])
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/manage/unified/realm")
    async def realm(request: Request):
        runtime = await _runtime(request, background=True)
        body = await _body(request)
        try:
            if set(body) != {"clientId", "realm"}:
                raise LifecycleError("Invalid realm request")
            return await runtime.realm_plan(body["clientId"], body["realm"])
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/manage/unified/check")
    async def check(request: Request):
        runtime = await _runtime(request, background=True)
        body = await _body(request)
        try:
            if set(body) != {"sessionId", "instanceId"}:
                raise LifecycleError("Invalid instance check")
            runtime.check_remote(body["sessionId"], body["instanceId"])
            return {"ok": True}
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/manage/unified/report")
    async def report(request: Request):
        runtime = await _runtime(request, background=True)
        body = await _body(request)
        if (
            set(body) - {"sessionId", "instanceId", "state", "error"}
            or not {"sessionId", "instanceId", "state"} <= body.keys()
        ):
            raise HTTPException(400, "Invalid execution report")
        try:
            runtime.report(
                body["sessionId"], body["instanceId"], body["state"], body.get("error")
            )
            if body["state"] == "failed":
                await runtime.reconcile()
            return {"ok": True}
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/manage/unified/invoke")
    async def invoke(request: Request):
        runtime = await _runtime(request)
        body = await _body(request)
        try:
            if set(body) != {"pluginId", "entryId", "identity", "instanceId", "input"}:
                raise LifecycleError("Invalid invocation")
            return {
                "identity": body["identity"],
                "instanceId": body["instanceId"],
                "result": await runtime.invoke(
                    body["pluginId"],
                    body["entryId"],
                    body["identity"],
                    body["instanceId"],
                    body["input"],
                ),
            }
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/manage/unified/invoke-chart")
    async def invoke_chart(request: Request):
        runtime = await _runtime(request, background=True)
        body = await _body(request)
        if set(body) != {"target", "scope", "bars", "input"}:
            raise HTTPException(400, "Invalid chart computation")

        # A renderer losing the chart cancels the HTTP request. Stop awaiting
        # that entry when the connection closes, including on window teardown.
        async def disconnect():
            while (await request.receive())["type"] != "http.disconnect":
                pass

        job = asyncio.create_task(
            runtime.compute_chart(
                body["target"], body["scope"], body["bars"], body["input"]
            )
        )
        gone = asyncio.create_task(disconnect())
        try:
            done, _ = await asyncio.wait(
                {job, gone}, return_when=asyncio.FIRST_COMPLETED
            )
            if gone in done:
                return Response(status_code=499)
            if job.cancelled():
                raise LifecycleError("Chart computation was revoked")
            return job.result()
        except (ValueError, TypeError) as exc:
            raise HTTPException(409, str(exc)) from exc
        finally:
            for task in (job, gone):
                if not task.done():
                    task.cancel()
            await asyncio.gather(job, gone, return_exceptions=True)

    @router.get("/unified-assets/{ticket}/{name:path}")
    async def asset(ticket: str, name: str, request: Request):
        runtime = getattr(request.app.state, "unified_plugin_runtime", None)
        try:
            if runtime is None:
                raise LifecycleError("Unavailable")
            data, sandbox = runtime.asset(ticket, name)
            headers = {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
            }
            if sandbox:
                headers["Content-Security-Policy"] = (
                    "sandbox allow-scripts; default-src 'none'; script-src 'self' 'unsafe-inline'; "
                    "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'none'; base-uri 'none'; form-action 'none'"
                )
            media = (
                "text/javascript"
                if name.endswith((".mjs", ".js"))
                else mimetypes.guess_type(name)[0] or "application/octet-stream"
            )
            return Response(data, media_type=media, headers=headers)
        except (ValueError, OSError) as exc:
            raise HTTPException(404, "Plugin asset unavailable") from exc

    return router
