import uvicorn
from fastapi import FastAPI

from src.config import get_debug_status, get_host, get_reload, get_server_port

app = FastAPI(debug=get_debug_status())

@app.get("/")
async def get_root():
    return {"Hello": "World"}


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=get_host(),
        port=get_server_port(),
        reload=get_reload(),
    )
