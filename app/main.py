from fastapi import FastAPI

from app.api.v1.router import api_router


app = FastAPI(
    title="Customer Support Resolution Agent",
    description="API for the Customer Support Resolution Agent",
    version="1.0.0",
)

app.include_router(api_router)


@app.get("/health", tags=["Health"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}