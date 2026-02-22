# Image Microservice (DB-Free, REST API)

A lightweight FastAPI image microservice that:

- Accepts image uploads per **project**
- Generates and stores:
  - `original` (converted to JPEG)
  - `medium` (max 1600×1600, preserves aspect ratio)
  - `thumb` (max 400×400, preserves aspect ratio)
  - `game` (**exact 50×50**, center-cropped square then resized)
- Stores everything on disk (no database)
- Maintains project metadata in `meta.json`
- Automatically sets the **first uploaded image** as the project thumbnail/cover

Concurrency:
- Uses a per-project **file lock** (`meta.lock`) so multiple users and multiple server workers/processes can safely upload/delete at the same time without corrupting `meta.json`.

---


# Table of Contents

- Requirements
- Installation
- Running the Service
- Storage Structure
- API Endpoints
- Integration Examples
- Frontend Usage Patterns
---

# Requirements

- Python 3.10+
- pip
- Packages:
  - fastapi
  - uvicorn
  - pillow
  - python-multipart
  - filelock

# Installation:
*Clone your repository, then install dependencies:*

```bash
pip install fastapi uvicorn pillow python-multipart filelock
```
No database setup required. 

# Running the service

*From the directory containing imgsrv.py*

```bash
uvicorn imgsrv:app --reload --port 8001
```

*Service will be available at*
```
http://localhost:8001
```

*Interactive API docs*
```
http://localhost:8001/docs
```

*OpenAPI schema*
```
http://localhost:8001/openapi.json
```

# Storage Structure

*All files are stored in the filesystem under:*
```
storage/projects/<project_id>/
```

*Example Structure*
```
storage/projects/123/
  meta.json
  original/abc123.jpg
  medium/abc123.jpg
  thumb/abc123.jpg
  game/abc123.jpg
```

*Image Sizes*

| Size     | Behavior                                         |
| -------- | ------------------------------------------------ |
| original | Converted to JPEG                                |
| medium   | Resized to fit within 1600×1600                  |
| thumb    | Resized to fit within 400×400                    |
| game     | Center-cropped square → resized to exactly 50×50 |

# meta.json Structure

*Each project contains a metadata file:*

```
{
  "project_id": "123",
  "primary_image_id": "abc123",
  "images": [
    {
      "id": "abc123",
      "ext": "jpg",
      "created_at": "2026-02-21T19:01:02.123Z"
    }
  ]
}
```

### Primary Image Rules

- The **first uploaded image** automatically becomes the primary image.
- The primary image determines:
  - /projects/{project_id}/thumbnail

# API Endpoints

## Upload Image

### POST

```
/projects/{project_id}/images
```
### Content-Type
multipart/form-data

### Field Name
file

### Example
```
curl -X POST "http://localhost:8001/projects/123/images" \
  -F "file=@/path/to/image.jpg
```

### Response
```
{
  "image_id": "abc123",
  "project_id": "123",
  "is_primary": true,
  "urls": {
    "original": "/projects/123/images/abc123?size=original",
    "medium": "/projects/123/images/abc123?size=medium",
    "thumb": "/projects/123/images/abc123?size=thumb",
    "game": "/projects/123/images/abc123?size=game"
  }
}
```
## List Project Images

### GET
```
/projects/{project_id}/images
```
Returns all images in upload order, including size, URLs, and primary flag.

## Get Project Thumbnail (Cover Image)

### GET
```
/projects/{project_id}/thumbnail
```
#### Returns
```
image/jpeg
```

This serves the *thumb* version of the primary image.

## Get Image by Size

### GET
```
/projects/{project_id}/images/{image_id}?size=original|medium|thumb|game
```

### Examples

```
/projects/123/images/abc123?size=original
/projects/123/images/abc123?size=medium
/projects/123/images/abc123?size=thumb
/projects/123/images/abc123?size=game
```

## Delete Image

### Delete
```
/projects/{project_id}/images/{image_id}
```
If the deleted image was primary:
  - The next remaining image becomes the primary automatically.

## Set Primary Image

### PUT
```
/projects/{project_id}/primary/{image_id}
```

## Image Format

All uploads are converted to JPEG for consistency and predictable performance.

# Frontend Usage Patterns

## Collections page:

  - Use GET /projects/{project_id}/thumbnail

## Project detail page:

  - GET /projects/{project_id}/images
  - Render medium for gallery
  - Use original for full-size view 
  - Use game for strict 50×50 UI icons



