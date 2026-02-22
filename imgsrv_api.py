"""
Image Microservice (DB-free, multi-user safe)
- REST API for uploading images to a per-project directory
- Generates original / medium / thumbnail / game(50x50)
- Uses storage/projects/<project_id>/meta.json as lightweight metadata store
- First uploaded image becomes the project's primary thumbnail (cover)

Concurrency:
- Uses a per-project FILE LOCK (meta.lock) so concurrent users AND multiple server
  processes/workers won't corrupt meta.json or race primary selection.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image
from filelock import FileLock, Timeout

# -----------------------------
# Config
# -----------------------------
app = FastAPI(title="Image Microservice (DB-free, multi-user safe)")

STORAGE_ROOT = Path("storage/projects")

MEDIUM_MAX = (1600, 1600)
THUMB_MAX = (400, 400)
GAME_IMG = (50, 50)

JPEG_QUALITY_ORIGINAL = 92
JPEG_QUALITY_DERIVED = 85

# How long to wait for a project lock before failing (seconds)
LOCK_TIMEOUT_SECS = 15

ImageSize = Literal["original", "medium", "thumb", "game"]


# -----------------------------
# Helpers: filesystem layout
# -----------------------------
def _project_base(project_id: str) -> Path:
    base = STORAGE_ROOT / project_id
    (base / "original").mkdir(parents=True, exist_ok=True)
    (base / "medium").mkdir(parents=True, exist_ok=True)
    (base / "thumb").mkdir(parents=True, exist_ok=True)
    (base / "game").mkdir(parents=True, exist_ok=True)
    return base


def _meta_path(project_id: str) -> Path:
    return _project_base(project_id) / "meta.json"


def _lock_path(project_id: str) -> Path:
    # Per-project lock file so different projects don't block each other
    return _project_base(project_id) / "meta.lock"


def _paths_for(project_id: str, image_id: str, ext: str = "jpg") -> Dict[str, Path]:
    base = _project_base(project_id)
    filename = f"{image_id}.{ext}"
    return {
        "original": base / "original" / filename,
        "medium": base / "medium" / filename,
        "thumb": base / "thumb" / filename,
        "game": base / "game" / filename,
    }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# -----------------------------
# Helpers: meta.json read/write
# -----------------------------
def _default_meta(project_id: str) -> Dict[str, Any]:
    return {"project_id": project_id, "primary_image_id": None, "images": []}


def _read_meta(project_id: str) -> Dict[str, Any]:
    mp = _meta_path(project_id)
    if not mp.exists():
        return _default_meta(project_id)
    try:
        return json.loads(mp.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read meta.json for project {project_id}: {e}")


def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _write_meta(project_id: str, meta: Dict[str, Any]) -> None:
    mp = _meta_path(project_id)
    try:
        _atomic_write_json(mp, meta)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write meta.json for project {project_id}: {e}")


def _find_image_in_meta(meta: Dict[str, Any], image_id: str) -> Optional[Dict[str, Any]]:
    for img in meta.get("images", []):
        if img.get("id") == image_id:
            return img
    return None


def _with_project_lock(project_id: str):
    """
    Context manager for per-project lock. Ensures cross-process safety.
    """
    lock = FileLock(str(_lock_path(project_id)))
    try:
        return lock.acquire(timeout=LOCK_TIMEOUT_SECS)
    except Timeout:
        raise HTTPException(status_code=503, detail="Project is busy. Try again in a moment.")


# -----------------------------
# Helpers: image processing
# -----------------------------
def _save_as_jpeg(src_path: Path, dest_path: Path, quality: int) -> None:
    with Image.open(src_path) as im:
        im = im.convert("RGB")
        im.save(dest_path, format="JPEG", quality=quality, optimize=True)


def _save_resized(src_path: Path, dest_path: Path, max_size: tuple[int, int], quality: int) -> None:
    # Fit within max_size, preserve aspect ratio
    with Image.open(src_path) as im:
        im = im.convert("RGB")
        im.thumbnail(max_size)
        im.save(dest_path, format="JPEG", quality=quality, optimize=True)


def _save_fixed_square(src_path: Path, dest_path: Path, size: tuple[int, int], quality: int) -> None:
    # Exact WxH: center-crop square then resize
    target_w, target_h = size
    with Image.open(src_path) as im:
        im = im.convert("RGB")
        w, h = im.size
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        im = im.crop((left, top, left + side, top + side))
        im = im.resize((target_w, target_h))
        im.save(dest_path, format="JPEG", quality=quality, optimize=True)


# -----------------------------
# API: Upload
# -----------------------------
@app.post("/projects/{project_id}/images")
async def upload_image(project_id: str, file: UploadFile = File(...)) -> Dict[str, Any]:
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image uploads are allowed.")

    image_id = uuid.uuid4().hex
    ext = "jpg"
    paths = _paths_for(project_id, image_id, ext)
    tmp_upload = paths["original"].with_suffix(".upload")

    # We lock the entire operation to avoid:
    # - two simultaneous "first uploads" both becoming primary
    # - meta.json write races across processes
    lock_handle = _with_project_lock(project_id)
    try:
        meta = _read_meta(project_id)

        # Write temp upload
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Empty upload.")
        tmp_upload.write_bytes(content)

        # Convert + generate sizes
        _save_as_jpeg(tmp_upload, paths["original"], quality=JPEG_QUALITY_ORIGINAL)
        _save_resized(paths["original"], paths["medium"], MEDIUM_MAX, quality=JPEG_QUALITY_DERIVED)
        _save_resized(paths["original"], paths["thumb"], THUMB_MAX, quality=JPEG_QUALITY_DERIVED)
        _save_fixed_square(paths["original"], paths["game"], GAME_IMG, quality=JPEG_QUALITY_DERIVED)

        # Update meta
        meta["images"].append({"id": image_id, "ext": ext, "created_at": _utc_now_iso()})
        if meta.get("primary_image_id") is None:
            meta["primary_image_id"] = image_id
        _write_meta(project_id, meta)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid or unsupported image file: {e}")
    finally:
        tmp_upload.unlink(missing_ok=True)
        # release file lock
        lock_handle.release()

    return {
        "image_id": image_id,
        "project_id": project_id,
        "is_primary": (meta.get("primary_image_id") == image_id),
        "urls": {
            "original": f"/projects/{project_id}/images/{image_id}?size=original",
            "medium": f"/projects/{project_id}/images/{image_id}?size=medium",
            "thumb": f"/projects/{project_id}/images/{image_id}?size=thumb",
            "game": f"/projects/{project_id}/images/{image_id}?size=game",
        },
    }


# -----------------------------
# API: List images (project)
# -----------------------------
@app.get("/projects/{project_id}/images")
def list_images(project_id: str) -> List[Dict[str, Any]]:
    lock_handle = _with_project_lock(project_id)
    try:
        meta = _read_meta(project_id)
    finally:
        lock_handle.release()

    primary = meta.get("primary_image_id")
    out: List[Dict[str, Any]] = []
    for img in meta.get("images", []):
        image_id = img["id"]
        out.append(
            {
                "image_id": image_id,
                "is_primary": (image_id == primary),
                "created_at": img.get("created_at"),
                "urls": {
                    "original": f"/projects/{project_id}/images/{image_id}?size=original",
                    "medium": f"/projects/{project_id}/images/{image_id}?size=medium",
                    "thumb": f"/projects/{project_id}/images/{image_id}?size=thumb",
                    "game": f"/projects/{project_id}/images/{image_id}?size=game",
                },
            }
        )
    return out


# -----------------------------
# API: Serve project thumbnail
# -----------------------------
@app.get("/projects/{project_id}/thumbnail")
def project_thumbnail(project_id: str) -> FileResponse:
    lock_handle = _with_project_lock(project_id)
    try:
        meta = _read_meta(project_id)
        primary = meta.get("primary_image_id")
        if not primary:
            raise HTTPException(status_code=404, detail="Project has no images yet.")
        img = _find_image_in_meta(meta, primary)
        if not img:
            raise HTTPException(status_code=404, detail="Primary image metadata missing.")
        paths = _paths_for(project_id, primary, img.get("ext", "jpg"))
        thumb_path = paths["thumb"]
        if not thumb_path.exists():
            raise HTTPException(status_code=404, detail="Thumbnail file missing on disk.")
    finally:
        lock_handle.release()

    return FileResponse(thumb_path, media_type="image/jpeg")


# -----------------------------
# API: Serve a specific image size
# -----------------------------
@app.get("/projects/{project_id}/images/{image_id}")
def get_project_image(project_id: str, image_id: str, size: ImageSize = "original") -> FileResponse:
    lock_handle = _with_project_lock(project_id)
    try:
        meta = _read_meta(project_id)
        img = _find_image_in_meta(meta, image_id)
        if not img:
            raise HTTPException(status_code=404, detail="Image not found in this project.")
        paths = _paths_for(project_id, image_id, img.get("ext", "jpg"))
        p = paths[size]
        if not p.exists():
            raise HTTPException(status_code=404, detail=f"{size} image missing on disk.")
    finally:
        lock_handle.release()

    return FileResponse(p, media_type="image/jpeg")


# -----------------------------
# API: Delete image
# -----------------------------
@app.delete("/projects/{project_id}/images/{image_id}")
def delete_project_image(project_id: str, image_id: str) -> Dict[str, Any]:
    lock_handle = _with_project_lock(project_id)
    try:
        meta = _read_meta(project_id)
        img = _find_image_in_meta(meta, image_id)
        if not img:
            raise HTTPException(status_code=404, detail="Image not found in this project.")

        ext = img.get("ext", "jpg")
        paths = _paths_for(project_id, image_id, ext)

        # Remove files
        for k in ("original", "medium", "thumb", "game"):
            paths[k].unlink(missing_ok=True)

        # Update meta
        meta["images"] = [x for x in meta["images"] if x.get("id") != image_id]
        if meta.get("primary_image_id") == image_id:
            meta["primary_image_id"] = meta["images"][0]["id"] if meta["images"] else None
        _write_meta(project_id, meta)

        return {
            "ok": True,
            "project_id": project_id,
            "deleted_image_id": image_id,
            "new_primary": meta.get("primary_image_id"),
        }
    finally:
        lock_handle.release()


# -----------------------------
# API: Set primary image
# -----------------------------
@app.put("/projects/{project_id}/primary/{image_id}")
def set_primary(project_id: str, image_id: str) -> Dict[str, Any]:
    lock_handle = _with_project_lock(project_id)
    try:
        meta = _read_meta(project_id)
        img = _find_image_in_meta(meta, image_id)
        if not img:
            raise HTTPException(status_code=404, detail="Image not found in this project.")
        meta["primary_image_id"] = image_id
        _write_meta(project_id, meta)
        return {"ok": True, "project_id": project_id, "primary_image_id": image_id}
    finally:
        lock_handle.release()