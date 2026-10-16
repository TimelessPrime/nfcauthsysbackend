from fastapi import FastAPI
from src.config import get_port, get_debug
app = FastAPI(debug=get_debug())

@app.get("/")
async def get_root():
    return {"Hello": "World"}

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=get_port(),
    )
