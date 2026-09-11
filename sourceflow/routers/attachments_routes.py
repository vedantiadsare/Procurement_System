"""Attachment download, ownership-checked: buyers can download anything,
requesters only their own case's documents."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

import db
from config import REPO_DIR
from deps import require_login

router = APIRouter()


@router.get("/attachments/{attachment_id}/download")
async def download_attachment(attachment_id: int, user=Depends(require_login)):
    attachment = db.get_attachment(attachment_id)
    if attachment is None:
        raise HTTPException(status_code=404)

    case = db.get_case(attachment["case_id"])
    if case is None:
        raise HTTPException(status_code=404)

    if user["role"] != "buyer" and case["requestor_email"] != user["email"]:
        raise HTTPException(status_code=403)

    full_path = REPO_DIR / attachment["file_path"]
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File missing on disk.")

    return FileResponse(full_path, filename=attachment["filename"])
