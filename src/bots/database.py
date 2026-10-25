from datetime import datetime
from typing import Any

from src.database import db, _normalize_uid
from src.logger import get_logger

logger = get_logger("discord_bot.database")


def register_student_card(uid: str, student_id: str, full_name: str, class_name: str) -> dict[str, Any]:
    return db.add_student(
        uid=_normalize_uid(uid),
        student_id=student_id.strip(),
        full_name=full_name.strip(),
        class_name=class_name.strip(),
    )


def find_student(query: str) -> dict[str, Any] | None:
    clean = query.strip()
    student = db.get_student(_normalize_uid(clean))
    if student:
        return student

    clean_upper = clean.upper()
    clean_lower = clean.lower()
    for s in db.get_all_students():
        if s.get("student_id", "").strip().upper() == clean_upper or clean_lower in s.get("full_name", "").strip().lower():
            return s
    return None


def get_or_create_blank_student(query: str, uid: str | None = None) -> tuple[dict[str, Any], bool]:
    clean_query = query.strip()
    student = find_student(clean_query)

    if student:
        if uid:
            clean_uid = _normalize_uid(uid)
            updated = db.add_student(
                uid=clean_uid,
                student_id=student.get("student_id", clean_query),
                full_name=student.get("full_name", "Chưa cập nhật"),
                class_name=student.get("class_name", "Chưa phân lớp"),
            )
            return updated, False
        return student, False

    student_id = clean_query.upper()
    target_uid = _normalize_uid(uid) if uid else f"BLANK_{student_id}"

    created = db.add_student(
        uid=target_uid,
        student_id=student_id,
        full_name=f"Học Sinh ({student_id})",
        class_name="Chưa phân lớp",
    )
    logger.info(f"Created blank student record: {student_id} (UID: {target_uid})")
    return created, True


def delete_card(uid: str) -> bool:
    return db.delete_student(_normalize_uid(uid))


def get_stats() -> dict[str, Any]:
    students = db.get_all_students()
    today_str = datetime.now().strftime("%Y-%m-%d")
    today_logs = sum(1 for log in db.get_attendance_logs(limit=200) if str(log.get("timestamp", "")).startswith(today_str))

    return {
        "total_students": len(students),
        "today_scans": today_logs,
        "active_database": db.active_backend.upper(),
        "failsafe_active": getattr(db, "_using_failsafe", False),
    }


def get_recent_logs(limit: int = 10) -> list[dict[str, Any]]:
    return db.get_attendance_logs(limit=limit)
