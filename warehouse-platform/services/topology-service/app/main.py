from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
import structlog
from contextlib import asynccontextmanager
from app.config import settings
from app.api.v1.topology_router import router as topology_router

logger = structlog.get_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup tasks
    logger.info("service_startup", service=settings.SERVICE_NAME)
    yield
    # Shutdown tasks
    logger.info("service_shutdown", service=settings.SERVICE_NAME)

app = FastAPI(
    title="Warehouse Audit Platform - Topology Service",
    description="Microservice managing the spatial layout and topology of warehouses.",
    version="1.0.0",
    lifespan=lifespan
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus metrics
Instrumentator().instrument(app).expose(app)

# Include router
app.include_router(topology_router, prefix="/api/v1")

@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "service": settings.SERVICE_NAME,
        "version": "1.0.0"
    }
