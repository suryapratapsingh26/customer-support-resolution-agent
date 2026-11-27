import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import settings
from app.db.engine import engine
from app.api.v1.router import api_router
from app.api.bff import router as bff_router


class JsonLogFormatter(logging.Formatter):
    """Emit concise structured logs without exception payloads or request data."""

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }, ensure_ascii=False)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    # HTTP client/access logs include URL paths, which can contain customer IDs.
    for name in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(name).setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    settings.validate_runtime()
    logging.getLogger(__name__).info("Application startup configuration validated")
    try:
        yield
    finally:
        engine.dispose()


app = FastAPI(
    title="Customer Support Resolution Agent",
    description="API for the Customer Support Resolution Agent",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(api_router)
app.include_router(bff_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.bff_trusted_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token", "X-Backend-Service-Token",
                   "X-Agent-API-Key", "X-Agent-Customer-Token", "X-Approval-Token",
                   "X-Approval-Request-Token"],
)


@app.get("/health/live", tags=["Health"])
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["Health"])
def readiness() -> dict[str, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(status_code=503, detail="Service is not ready.") from None
    return {"status": "ready"}


@app.get("/health", tags=["Health"], include_in_schema=False)
def health_check() -> dict[str, str]:
    return liveness()
