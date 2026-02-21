# Image Microservice (DB-Free, REST API)

A lightweight FastAPI-based image microservice that:

- Accepts image uploads per **project**
- Generates and stores:
  - Original
  - Medium
  - Thumbnail
- Uses filesystem storage only (no database)
- Maintains project metadata in `meta.json`
- Automatically sets the **first uploaded image as the project thumbnail (cover)**

This replaces the original text-file polling pipeline with a proper REST API.

---

# Table of Contents

- Requirements
- Installation
- Running the Service
- Storage Structure
- API Endpoints
- Integration Examples
- Frontend Usage Patterns
- Limitations & Scaling Notes

---

# Requirements

- Python 3.10+
- Packages:
  - fastapi
  - uvicorn
  - pillow
  - python-multipart

Install:

```bash
pip install fastapi uvicorn pillow python-multipart
