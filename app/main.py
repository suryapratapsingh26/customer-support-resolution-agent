from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.v1.router import api_router
from app.api.bff import router as bff_router


app = FastAPI(
    title="Customer Support Resolution Agent",
    description="API for the Customer Support Resolution Agent",
    version="1.0.0",
)

app.include_router(api_router)
app.include_router(bff_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.bff_trusted_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)


@app.get("/health", tags=["Health"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}
