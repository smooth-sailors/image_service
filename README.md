# Image Microservice (DB-free, REST API)

A lightweight image microservice that:
- Accepts image uploads per **project**
- Generates and serves **original**, **medium**, and **thumbnail** sizes
- Stores images on disk (no database)
- Tracks per-project metadata in `meta.json`
- Uses the rule: **first uploaded image becomes the project thumbnail/cover**

---

## Features

- **Upload** images via multipart form-data
- **List** all images for a project
- **Serve** project thumbnail (primary cover image)
- **Serve** any image in original/medium/thumb
- **Delete** an image (auto-updates primary if needed)
- **Set primary** cover image explicitly (optional)

---

## Requirements

- Python 3.10+ recommended
- Packages:
  - `fastapi`
  - `uvicorn`
  - `pillow`
  - `python-multipart`

Install:
```bash
pip install fastapi uvicorn pillow python-multipart