# OntologyMapper — Web

Web interface and agentic service layer for the [OntologyMapper](../README.md) pipeline. Provides a browser-based review interface for Stage 5 human review, project setup, and source file upload.

## Stack

| Layer | Technology |
|-------|-----------|
| Auth | None — single fixed local user (internal / reviewer use) |
| Backend | FastAPI (Python) |
| Frontend | Svelte 5 + Tailwind CSS |
| Build | Vite |

## Setup

### Prerequisites

- Python 3.10+ with `ontology-mapper` and `ontology-mapper-runner` installed
- Node.js 20.19+ or 22.12+ (required by Vite 8)

### 1. Environment

Copy `.env.example` to `.env` and fill in values:

```bash
cp .env.example .env
```

### 2. Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server runs on `http://localhost:5173` and proxies `/api` to the FastAPI backend on port 8000.

## Project Structure

```
backend/
  main.py                 # FastAPI app entry
  config.py               # Settings from .env
  auth.py                 # Local user stub (no external auth)
  models.py               # Pydantic request/response models
  routes/
    runs.py               # Pipeline run management
    review.py             # Stage 5 review operations
    catalog.py            # Target catalog search

frontend/
  src/
    App.svelte            # Root component + routing
    lib/
      api.js              # API client with auth
      auth.js             # Local auth stub
      stores.js           # Svelte stores
    components/           # Reusable UI components
    pages/                # Page-level components
```
