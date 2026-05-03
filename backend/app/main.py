"""FastAPI app entrypoint. Run: `python -m app.main` from the backend dir."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import router as api_router
from .config import settings
from .trader import engine
from .ws import router as ws_router


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info(
        "FXTrader starting | instrument=%s env=%s trading_enabled=%s",
        settings.INSTRUMENT,
        settings.OANDA_ENV,
        settings.TRADING_ENABLED,
    )
    engine.start()
    try:
        yield
    finally:
        await engine.stop()


app = FastAPI(title="FXTrader", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_ORIGIN, "http://localhost:5179"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)
app.include_router(ws_router)


@app.get("/health")
async def health():
    return {"ok": True}


def main():
    uvicorn.run(
        "app.main:app",
        host=settings.BACKEND_HOST,
        port=settings.BACKEND_PORT,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
