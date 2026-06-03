"""OntologyMapper Web — FastAPI backend entry point."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes import runs, review, catalog, requests

LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"
LOG_DATEFMT = "%H:%M:%S"

logging.basicConfig(format=LOG_FORMAT, datefmt=LOG_DATEFMT, level=logging.INFO)

logging.warning(
    "NO AUTHENTICATION - this web layer runs with a single fixed local "
    "user with admin rights. There is no access control. Do not expose "
    "this deployment publicly."
)

# Apply timestamp format to uvicorn's access and error loggers
for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
    uv_logger = logging.getLogger(name)
    for handler in uv_logger.handlers:
        handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT))
    if not uv_logger.handlers:
        uv_logger.propagate = True

app = FastAPI(
    title="OntologyMapper Web",
    description="Web interface for the OntologyMapper pipeline",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(runs.router, prefix="/api")
app.include_router(review.router, prefix="/api")
app.include_router(catalog.router, prefix="/api")
app.include_router(requests.router, prefix="/api")


@app.get("/api/health")
async def health():
    return {"status": "ok"}
