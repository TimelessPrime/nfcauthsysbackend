import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.client_logger import client_logger

from src.config import (
    get_auth_token,
    get_debug_status,
    get_host,
    get_reload,
    get_server_port,
    get_tcp_config,
    is_auth_required,
)
from src.connector import tcp_connector
from src.database import db
from src.logger import get_logger, setup_logger, tail_log
from src.mdns_broadcaster import start_mdns_broadcaster, stop_mdns_broadcaster
from src.security import compute_hmac, verify_token

logger = setup_logger("backend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing NFC School Auth backend services...")
    tcp_settings = get_tcp_config()
    if tcp_settings.get("enabled", True):
        tcp_connector.start()
        logger.info(
            f"TCP socket listener started on {tcp_settings.get('host')}:{tcp_settings.get('port')}"
        )

    start_mdns_broadcaster()

    discord_task = None
    try:
        from src.bots.config import is_discord_bot_enabled
        if is_discord_bot_enabled():
            from src.bots.reg import start_discord_bot
            logger.info("Starting Discord Registration & Attendance Bot service...")
            discord_task = asyncio.create_task(start_discord_bot())
    except Exception as e:
        logger.warning(f"Could not initialize Discord bot: {e}")

    yield

    logger.info("Shutting down backend services...")
    if discord_task:
        discord_task.cancel()
    stop_mdns_broadcaster()
    if tcp_settings.get("enabled", True):
        tcp_connector.stop()
    client_logger.close()
    logger.info("Shutdown completed.")


app = FastAPI(
    title="NFC School Auth API",
    description="Backend API for NFC-based student attendance and access management.",
    version="1.1.0",
    debug=get_debug_status(),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)


class ScanRequest(BaseModel):
    uid: str = Field(..., description="NFC Card UID (e.g. 04A1B2C3 or 04:A1:B2:C3)")
    device_id: str = Field(default="ESP32_MAIN", description="ID of scanning hardware")
    auth_token: str | None = Field(default=None, description="Device authentication token")
    notes: str = Field(default="", description="Optional additional scan details")


class StudentCreate(BaseModel):
    uid: str = Field(..., description="NFC Card UID to link with student")
    student_id: str = Field(..., description="Student identification number (e.g. HS001)")
    full_name: str = Field(..., description="Full name of student")
    class_name: str = Field(..., description="Classroom name (e.g. 12A1)")


class ClientLogRequest(BaseModel):
    device_id: str = Field(default="ESP32_MAIN", description="ID of client device")
    level: str = Field(default="INFO", description="Log level: INFO, WARNING, ERROR, DEBUG")
    tag: str = Field(default="CLIENT", description="Module/tag generating the log")
    message: str = Field(..., description="Log message text")
    auth_token: str | None = Field(default=None, description="Optional auth token")
    extra: dict[str, Any] = Field(default_factory=dict, description="Additional context fields")


def verify_request_auth(token: str | None) -> None:
    if is_auth_required() and not verify_token(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token xac thuc khong hop le hoac bi thieu",
        )


def attach_anti_spoofing_headers(response: Response, payload_id: str = "ok") -> None:
    signature = compute_hmac(get_auth_token(), payload_id)
    response.headers["X-Server-Identity"] = "NFC-School-Auth-Backend"
    response.headers["X-Server-Signature"] = signature


@app.get("/")
async def get_root(response: Response) -> dict[str, Any]:
    """Root endpoint returning service identity, stats, and verification proof."""
    stats = db.get_stats()
    attach_anti_spoofing_headers(response, "root")
    return {
        "service": "NFC School Auth Backend",
        "status": "online",
        "version": "1.1.0",
        "stats": stats,
    }


@app.get("/api/stats")
async def get_system_stats(response: Response) -> dict[str, Any]:
    """Retrieve overall statistics for students and scans."""
    attach_anti_spoofing_headers(response, "stats")
    return db.get_stats()


@app.post("/api/scan", status_code=status.HTTP_200_OK)
async def process_nfc_scan(
    payload: ScanRequest,
    response: Response,
    x_auth_token: str | None = Header(default=None),
) -> dict[str, Any]:
    """Process an NFC card scan from ESP32 or client.

    Verifies auth token, student registration, records attendance, and returns status.
    """
    token = payload.auth_token or x_auth_token
    verify_request_auth(token)

    clean_uid = payload.uid.strip()
    if not clean_uid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ma UID the khong duoc de trong",
        )

    result = await asyncio.to_thread(
        db.record_attendance,
        uid=clean_uid,
        device_id=payload.device_id,
        notes=payload.notes,
    )
    attach_anti_spoofing_headers(response, str(result.get("id", "")))
    return result


@app.get("/api/attendance")
async def get_attendance_history(
    response: Response,
    limit: int = Query(default=50, ge=1, le=500, description="Max records to return"),
    x_auth_token: str | None = Header(default=None),
    token: str | None = Query(default=None, description="Auth token for query authentication"),
) -> dict[str, Any]:
    """Retrieve recent attendance logs ordered newest first."""
    verify_request_auth(token or x_auth_token)
    logs = await asyncio.to_thread(db.get_attendance_logs, limit=limit)
    attach_anti_spoofing_headers(response, str(len(logs)))
    return {
        "count": len(logs),
        "limit": limit,
        "logs": logs,
    }


@app.get("/api/students")
async def get_students(
    response: Response,
    x_auth_token: str | None = Header(default=None),
    token: str | None = Query(default=None, description="Auth token for query authentication"),
) -> dict[str, Any]:
    """List all registered students in the system."""
    verify_request_auth(token or x_auth_token)
    students = await asyncio.to_thread(db.get_all_students)
    attach_anti_spoofing_headers(response, str(len(students)))
    return {
        "total": len(students),
        "students": students,
    }


@app.post("/api/students", status_code=status.HTTP_201_CREATED)
async def register_student(
    student: StudentCreate,
    response: Response,
    x_auth_token: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> dict[str, Any]:
    """Register a new student or update an existing student card UID."""
    verify_request_auth(token or x_auth_token)
    try:
        saved = await asyncio.to_thread(
            db.add_student,
            uid=student.uid,
            student_id=student.student_id,
            full_name=student.full_name,
            class_name=student.class_name,
        )
        attach_anti_spoofing_headers(response, saved["uid"])
        return {
            "status": "success",
            "message": f"Da luu thong tin hoc sinh: {student.full_name}",
            "student": saved,
        }
    except Exception as e:
        logger.error(f"Error registering student: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Loi khi luu thong tin hoc sinh: {e}",
        ) from e


@app.delete("/api/students/{uid}")
async def delete_student(
    uid: str,
    response: Response,
    x_auth_token: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> dict[str, Any]:
    """Delete a student registration by card UID."""
    verify_request_auth(token or x_auth_token)
    deleted = await asyncio.to_thread(db.delete_student, uid)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Khong tim thay hoc sinh voi ma the nay",
        )
    attach_anti_spoofing_headers(response, uid)
    return {"status": "success", "message": f"Da xoa hoc sinh co the {uid}"}


@app.get("/api/logs")
async def get_system_logs(
    lines: int = Query(default=100, ge=10, le=500),
    x_auth_token: str | None = Header(default=None),
    token: str | None = Query(default=None, description="Auth token for query authentication"),
) -> dict[str, Any]:
    """Retrieve recent lines from latest.log using memory-safe seek backwards."""
    verify_request_auth(token or x_auth_token)
    selected_lines = await asyncio.to_thread(tail_log, lines=lines)
    return {
        "count": len(selected_lines),
        "lines": selected_lines,
    }


@app.post("/api/client-logs", status_code=status.HTTP_201_CREATED)
async def ingest_client_log(
    payload: ClientLogRequest,
    x_auth_token: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> dict[str, Any]:
    """Ingest a log event streamed from an ESP32 or client device into client_log/."""
    effective_token = payload.auth_token or token or x_auth_token
    verify_request_auth(effective_token)

    recorded = client_logger.log_event(
        device_id=payload.device_id,
        level=payload.level,
        tag=payload.tag,
        message=payload.message,
        extra=payload.extra,
    )
    return {"status": "success", "recorded": recorded}


@app.get("/api/client-logs")
async def get_client_logs(
    device_id: str | None = Query(default=None, description="Optional device ID filter"),
    lines: int = Query(default=100, ge=10, le=1000),
    x_auth_token: str | None = Header(default=None),
    token: str | None = Query(default=None, description="Auth token for query authentication"),
) -> dict[str, Any]:
    """Retrieve recent logs recorded in client_log/ directory safely without memory bloat."""
    verify_request_auth(token or x_auth_token)
    log_lines = await asyncio.to_thread(client_logger.get_device_logs, device_id=device_id, lines=lines)
    return {
        "device_id": device_id or "all_clients",
        "count": len(log_lines),
        "lines": log_lines,
    }


@app.get("/api/client-logs/devices")
async def list_logging_devices(
    x_auth_token: str | None = Header(default=None),
    token: str | None = Query(default=None, description="Auth token for query authentication"),
) -> dict[str, Any]:
    """List all client devices that have generated logs in client_log/."""
    verify_request_auth(token or x_auth_token)
    devices = await asyncio.to_thread(client_logger.list_client_devices)
    return {"total": len(devices), "devices": devices}


@app.get("/api/client-logs/stream")
async def stream_live_client_logs(
    x_auth_token: str | None = Query(default=None),
):
    """Server-Sent Events (SSE) live stream of all logs arriving from client devices."""
    verify_request_auth(x_auth_token)
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    loop = asyncio.get_running_loop()
    client_logger.add_subscriber(queue, loop=loop)

    async def event_generator():
        try:
            yield "event: connected\ndata: {\"status\": \"streaming_active\"}\n\n"
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            client_logger.remove_subscriber(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )



if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=get_host(),
        port=get_server_port(),
        reload=get_reload(),
    )