# Hobby Loggy – Image Microservice (FastAPI)

This microservice provides DB-free image storage for Hobby Loggy projects.

It handles image uploads, generates multiple image sizes, and stores lightweight metadata per project using the local filesystem.

---

# Overview

This service:

- Accepts image uploads via REST API
- Generates four image sizes:
  - `original` (high quality JPEG)
  - `medium` (max 1600x1600)
  - `thumb` (max 400x400)
  - `game` (50x50 square crop)
- Stores metadata in: storage/projects/<project_id>/meta.json

- Automatically sets the first uploaded image as the project's primary image
- Uses file locking to ensure safe multi-user access

---

# Storage Location

All files are stored relative to `imgsrv_api.py`: image-service/storage/projects/


Each folder contains a `.jpg` version of the image.

You do NOT need to manually create these folders — the microservice creates them automatically on first upload.

---

# API Endpoints

## Health Check

GET /health

Response:

```json
{ "ok": true }
```

Upload Image
```POST /projects/{project_id}/images

Content-Type: multipart/form-data
Form field name: file
```

Example response:

```json
{
  "image_id": "abc123",
  "project_id": "demo-project",
  "is_primary": true,
  "urls": {
    "original": "/projects/demo-project/images/abc123?size=original",
    "medium": "/projects/demo-project/images/abc123?size=medium",
    "thumb": "/projects/demo-project/images/abc123?size=thumb",
    "game": "/projects/demo-project/images/abc123?size=game"
  }
}
```

---

## Local Development Setup (Windows)
### Create Virtual Environment

From inside image-service/:

```python -m venv .venv```

Activate it:

```.\.venv\Scripts\Activate.ps1```

You should see:

```(.venv) PS ...```
### Install Dependencies
```python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
```   
### Run the Service
```python -m uvicorn imgsrv_api:app --host 127.0.0.1 --port 8001 --reload
```   

### Open:

http://127.0.0.1:8001/docs

Swagger UI will display all endpoints.

### requirements.txt

The required dependencies are:

fastapi
uvicorn
pillow
filelock
python-multipart



