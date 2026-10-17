from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from src.config import get_debug_status, get_host, get_reload, get_server_port
from src.logger import log_program_exit, log_program_start, logger


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Log application lifecycle events for both direct and Uvicorn startup."""
    log_program_start()
    try:
        yield
    finally:
        log_program_exit()


app = FastAPI(debug=get_debug_status(), lifespan=lifespan)


@app.get("/")
async def get_root() -> dict[str, str]:
    logger.info("Endpoint '/' was accessed")
    return {"Hello": "World"}


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=get_host(),
        port=get_server_port(),
        reload=get_reload(),
    )
