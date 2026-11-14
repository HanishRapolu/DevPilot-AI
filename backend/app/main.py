import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from app.api import health, tasks
from app.config import Settings
from app.api.security import authorize
from app.services.jobs import Jobs
from fastapi import Depends


def create_app(settings: Settings | None = None, database=None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        client = None
        if database is None:
            client = MongoClient(settings.mongodb_uri.get_secret_value(),
                                 serverSelectionTimeoutMS=3000, connectTimeoutMS=3000,
                                 socketTimeoutMS=5000, tz_aware=True, connect=False)
            app.state.database = client[settings.mongodb_database]
        else:
            app.state.database = database
        app.state.settings = settings
        app.state.jobs = Jobs(settings, app.state.database)
        # Do not block startup: readiness reports DB failure, liveness remains usable.
        try:
            yield
        finally:
            app.state.jobs.close()
            if client is not None:
                client.close()

    app = FastAPI(title="DevPilot AI", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type", "Authorization"])

    @app.exception_handler(PyMongoError)
    async def database_error(request: Request, exc: PyMongoError):
        # Neither connection strings nor driver exception text reach logs or clients.
        logging.getLogger(__name__).warning("Database operation failed: %s", type(exc).__name__)
        return JSONResponse(status_code=503, content={"detail": "Database unavailable. Check MongoDB configuration."})

    app.include_router(health.router, prefix="/api")
    app.include_router(tasks.router, prefix="/api", dependencies=[Depends(authorize)])
    return app


app = create_app()
