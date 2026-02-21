# imgsrv_api.py
import os
import uuid
import sqlite3
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from PIL import Image

APP_DB = "imgsrv.sqlite"
STORAGE_ROOT = Path("storage/projects")

# sizes (tune as you like)
MEDIUM_MAX = (1600, 1600)
THUMB_MAX = (400, 400)

app = FastAPI(title="Image Microservice")

def db():
    conn = sqlite3.connect(APP_DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS images (
            image_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            ext TEXT NOT NULL,
            upload_index INTEGER NOT NULL,
            is_primary INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_images_project ON images(project_id)")
    conn.commit()
    conn.close()

@app.on_event("startup")
def startup():
    init_db()
    STORAGE_ROOT.mkdir(parents=True, exist_ok=True)

def project_dir(project_id: str) -> Path:
    base = STORAGE_ROOT / project_id
    for sub in ("original", "medium", "thumb"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base

def save_and_resize(src_path: Path, dest_path: Path, max_size: tuple[int, int]):
    with Image.open(src_path) as im:
        im = im.convert("RGB")
        im.thumbnail(max_size)  # keeps aspect ratio
        im.save(dest_path, format="JPEG", quality=85, optimize=True)

def build_paths(project_id: str, image_id: str, ext: str):
    base = project_dir(project_id)
    filename = f"{image_id}.{ext}"
    return {
        "original": base / "original" / filename,
        "medium": base / "medium" / filename,
        "thumb": base / "thumb" / filename,
    }

@app.post("/projects/{project_id}/images")
async def upload_image(project_id: str, file: UploadFile = File(...)):
    # Basic validation
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image uploads are allowed.")

    # Normalize extension: always store as jpg to simplify serving
    image_id = uuid.uuid4().hex
    ext = "jpg"

    conn = db()

    # Determine upload_index and whether this becomes primary
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM images WHERE project_id = ?",
        (project_id,)
    ).fetchone()
    upload_index = int(row["cnt"])
    is_primary = 1 if upload_index == 0 else 0

    paths = build_paths(project_id, image_id, ext)

    # Save original upload to disk (then convert to jpg)
    tmp_path = paths["original"].with_suffix(".upload")
    with open(tmp_path, "wb") as out:
        out.write(await file.read())

    # Convert + save original as JPEG (and remove tmp)
    try:
        with Image.open(tmp_path) as im:
            im = im.convert("RGB")
            im.save(paths["original"], format="JPEG", quality=92, optimize=True)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Invalid or unsupported image file.")
    tmp_path.unlink(missing_ok=True)

    # Generate medium + thumb
    save_and_resize(paths["original"], paths["medium"], MEDIUM_MAX)
    save_and_resize(paths["original"], paths["thumb"], THUMB_MAX)

    # Store metadata
    conn.execute(
        "INSERT INTO images(image_id, project_id, ext, upload_index, is_primary) VALUES (?, ?, ?, ?, ?)",
        (image_id, project_id, ext, upload_index, is_primary)
    )
    conn.commit()
    conn.close()

    return {
        "image_id": image_id,
        "project_id": project_id,
        "is_primary": bool(is_primary),
        "urls": {
            "original": f"/images/{image_id}?size=original",
            "medium": f"/images/{image_id}?size=medium",
            "thumb": f"/images/{image_id}?size=thumb",
        }
    }

@app.get("/projects/{project_id}/images")
def list_images(project_id: str):
    conn = db()
    rows = conn.execute(
        "SELECT image_id, is_primary, upload_index FROM images WHERE project_id = ? ORDER BY upload_index ASC",
        (project_id,)
    ).fetchall()
    conn.close()

    return [
        {
            "image_id": r["image_id"],
            "is_primary": bool(r["is_primary"]),
            "upload_index": r["upload_index"],
            "urls": {
                "original": f"/images/{r['image_id']}?size=original",
                "medium": f"/images/{r['image_id']}?size=medium",
                "thumb": f"/images/{r['image_id']}?size=thumb",
            }
        }
        for r in rows
    ]

@app.get("/projects/{project_id}/thumbnail")
def project_thumbnail(project_id: str):
    conn = db()
    r = conn.execute(
        "SELECT image_id, ext FROM images WHERE project_id = ? AND is_primary = 1 LIMIT 1",
        (project_id,)
    ).fetchone()
    conn.close()

    if not r:
        raise HTTPException(status_code=404, detail="Project has no images yet.")

    paths = build_paths(project_id, r["image_id"], r["ext"])
    if not paths["thumb"].exists():
        raise HTTPException(status_code=404, detail="Thumbnail missing on disk.")
    return FileResponse(paths["thumb"], media_type="image/jpeg")

@app.get("/images/{image_id}")
def get_image(image_id: str, size: Literal["original", "medium", "thumb"] = "original"):
    conn = db()
    r = conn.execute(
        "SELECT project_id, ext FROM images WHERE image_id = ?",
        (image_id,)
    ).fetchone()
    conn.close()

    if not r:
        raise HTTPException(status_code=404, detail="Image not found.")

    paths = build_paths(r["project_id"], image_id, r["ext"])
    p = paths[size]
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"{size} image missing on disk.")
    return FileResponse(p, media_type="image/jpeg")

@app.put("/projects/{project_id}/primary/{image_id}")
def set_primary(project_id: str, image_id: str):
    conn = db()

    # verify image belongs to project
    r = conn.execute(
        "SELECT 1 FROM images WHERE project_id = ? AND image_id = ?",
        (project_id, image_id)
    ).fetchone()
    if not r:
        conn.close()
        raise HTTPException(status_code=404, detail="Image not in that project.")

    # unset others, set this one
    conn.execute("UPDATE images SET is_primary = 0 WHERE project_id = ?", (project_id,))
    conn.execute("UPDATE images SET is_primary = 1 WHERE project_id = ? AND image_id = ?", (project_id, image_id))
    conn.commit()
    conn.close()

    return {"ok": True, "project_id": project_id, "primary_image_id": image_id}