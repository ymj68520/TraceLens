"""RAID image preparation inside the existing task intake namespace."""
import asyncio
from fastapi import APIRouter, Body, HTTPException, Request

from ..services import raid_task_intake as intake
from ..services.task_store import get_task_record, TaskStoreError

router = APIRouter()


def actor(request):
    subject = getattr(request.state, "principal", None)
    if not subject or subject.get("kind") != "user" or not subject.get("id"):
        raise HTTPException(status_code=401, detail="authentication required")
    return subject


def writer(request):
    subject = actor(request)
    if subject.get("role") not in ("admin", "analyst", "reviewer"):
        raise HTTPException(status_code=403, detail="write permission required")
    return subject


def error(exc):
    return HTTPException(status_code=403 if isinstance(exc, PermissionError) else 400,
                         detail="RAID job access denied" if isinstance(exc, PermissionError) else str(exc))


@router.get("/raid/candidates")
async def candidates(request: Request):
    actor(request)
    try: return {"success": True, **await asyncio.to_thread(intake.catalog)}
    except intake.RaidError as exc: raise error(exc)


@router.post("/raid/jobs", status_code=202)
async def start(request: Request, payload: dict = Body(...)):
    principal = writer(request)
    if set(payload) != {"member_ids"}: raise HTTPException(status_code=400, detail="member IDs required")
    try: return {"success": True, "job": await asyncio.to_thread(intake.start, payload["member_ids"], principal["id"])}
    except (intake.RaidError, PermissionError) as exc: raise error(exc)


@router.get("/raid/jobs/{job_id}")
async def status(request: Request, job_id: str):
    try: return {"success": True, "job": intake.public(job_id, actor(request)["id"])}
    except (intake.RaidError, PermissionError) as exc: raise error(exc)


@router.post("/raid/jobs/{job_id}/prepare", status_code=202)
async def prepare(request: Request, job_id: str, payload: dict = Body(...)):
    principal = writer(request)
    if set(payload) - {"candidate_id", "allow_partial"} or not isinstance(payload.get("candidate_id"), str):
        raise HTTPException(status_code=400, detail="candidate ID required")
    partial = payload.get("allow_partial", False)
    if not isinstance(partial, bool): raise HTTPException(status_code=400, detail="allow_partial must be boolean")
    if partial and principal.get("role") != "admin":
        raise HTTPException(status_code=403, detail="partial diagnostic requires administrator")
    try: return {"success": True, "job": intake.prepare(job_id, payload["candidate_id"], principal["id"], allow_partial=partial)}
    except (intake.RaidError, PermissionError) as exc: raise error(exc)


@router.post("/raid/jobs/{job_id}/cancel")
async def cancel(request: Request, job_id: str):
    try: return {"success": True, "job": intake.cancel(job_id, writer(request)["id"])}
    except (intake.RaidError, PermissionError) as exc: raise error(exc)


@router.get("/tasks/{task_id}/raid-source")
async def source(request: Request, task_id: str):
    actor(request)
    try:
        task = await get_task_record(task_id)
        metadata = task.get("metadata") or {}
        if metadata.get("source_kind") != "raid":
            return {"success": True, "source": None}
        job = intake._read(metadata["raid_job_id"])
        if (job["owner"] != metadata.get("requested_by") or job["status"] != "ready" or
                job["manifest_sha256"] != metadata.get("raid_manifest_sha256") or
                job["image_path"] != task.get("image_path")):
            raise intake.RaidError("TASK_RAID_SOURCE_BINDING_MISMATCH")
        return {"success": True, "source": {"kind": "raid", "label": job["display_name"],
                "integrity_status": job["integrity_status"], "member_count": job["member_count"],
                "manifest_sha256": job["manifest_sha256"], "image_sha256": job["image_sha256"],
                "members": [{"relative_source": name, "sha256": sha256}
                            for name, sha256 in sorted(job["member_sha256"].items())],
                "verification_state": "MACHINE_RECONSTRUCTED_UNVERIFIED"}}
    except TaskStoreError as exc: raise HTTPException(status_code=404, detail="task not found") from exc
    except (intake.RaidError, PermissionError, KeyError) as exc: raise error(exc)
