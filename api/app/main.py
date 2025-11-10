from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.logging import get_logger
from .routers import health, stops, heatmap
from .routers import routes as routes_router
from .routers import summary as summary_router
from .routers import anomalies as anomalies_router
from .routers.stops import prime_stops_cache
from .models.base import Base
from .storage.session import get_engine


app = FastAPI(title="mta-subway-anomaly-scan", version="0.1.0")


@app.get("/", tags=["root"])
def root():
    return {"service": "mta-subway-anomaly-scan", "ok": True}


# Mount API routers under /api
app.include_router(health.router, prefix="/api")
app.include_router(stops.router, prefix="/api")
app.include_router(heatmap.router, prefix="/api")
app.include_router(routes_router.router, prefix="/api")
app.include_router(summary_router.router, prefix="/api")
app.include_router(anomalies_router.router, prefix="/api")

# CORS for local UI dev (broader to avoid mismatches)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    # Minimal MVP: ensure tables exist
    Base.metadata.create_all(bind=get_engine())
    get_logger(__name__).info("startup complete; tables ensured")
    prime_stops_cache()
