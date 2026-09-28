"""Field-only local login and C++ auth introspection endpoints."""

import os

from fastapi import APIRouter, Body, HTTPException, Request

from ..services.field_security import (
    FIELD_SECURITY_VERSION, FieldAuthenticationError, FieldConfigurationError, authorize, login,
    principal, valid_internal,
)
from ..release_info import RELEASE_ID, RELEASE_LAYOUT_VERSION, SOURCE_COMMIT, SOURCE_TREE_SHA256

router = APIRouter()


@router.get("/status")
async def field_status(request: Request):
    policy = request.app.state.field_policy
    return {"field_security_version": FIELD_SECURITY_VERSION,
            "release_id": RELEASE_ID, "release_layout_version": RELEASE_LAYOUT_VERSION,
            "source_commit": SOURCE_COMMIT, "source_tree_sha256": SOURCE_TREE_SHA256,
            "field_auth": policy.enabled, "required_auth": os.environ.get("TRACELENS_REQUIRE_FIELD_AUTH") == "1",
            "outbound_policy": policy.outbound_mode}


@router.post("/login")
async def field_login(request: Request, payload: dict = Body(...)):
    policy = request.app.state.field_policy
    if not policy.enabled:
        raise HTTPException(status_code=404, detail="field login is disabled")
    try:
        return login(policy, payload.get("username"), payload.get("password"))
    except (FieldAuthenticationError, FieldConfigurationError):
        raise HTTPException(status_code=401, detail="invalid credentials") from None


@router.get("/me")
async def field_me(request: Request):
    subject = getattr(request.state, "principal", None)
    if not subject or subject.get("kind") != "user":
        raise HTTPException(status_code=401, detail="user authentication required")
    return {"id": subject["id"], "role": subject["role"]}


@router.post("/introspect")
async def field_introspect(request: Request, payload: dict = Body(...)):
    policy = request.app.state.field_policy
    peer = request.client.host if request.client else ""
    if not valid_internal(policy, request.headers.get("x-tracelens-service-token", ""),
                          direction="cpp_to_python", peer=peer):
        raise HTTPException(status_code=401, detail="internal authentication required")
    method, path = payload.get("method"), payload.get("path")
    if not isinstance(method, str) or not isinstance(path, str) or not path.startswith("/") or len(path) > 2048:
        raise HTTPException(status_code=400, detail="invalid introspection request")
    try:
        subject = principal(policy, payload.get("authorization", ""))
        authorize(subject, method, path)
    except FieldAuthenticationError:
        raise HTTPException(status_code=401, detail="invalid bearer token") from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="insufficient permission") from None
    return {"principal": subject}
