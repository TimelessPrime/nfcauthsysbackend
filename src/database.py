import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config import BASE_DIR, get_database_config
from src.logger import get_logger

logger = get_logger("database")


def _normalize_uid(uid: str) -> str:
    return uid.replace(":", "").replace(" ", "").strip().upper()


class Database:
    def __init__(self) -> None:
        self.config = get_database_config()
        self.db_type = str(self.config.get("type", "mysql")).lower()
        self.sqlite_path = BASE_DIR / str(self.config.get("sqlite_path", "data/attendance.db"))
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self.active_backend = "sqlite"
        self._using_failsafe = False
        self._recovery_thread = None

        if self.db_type == "mysql":
            if self._try_init_mysql():
                self.active_backend = "mysql"
            else:
                logger.warning(
                    "Falling back to local SQLite database so attendance tracking remains operational."
                )
                self._init_sqlite()
                self.active_backend = "sqlite"
                self._start_recovery_thread()
        else:
            self._init_sqlite()
            self.active_backend = "sqlite"

    def _get_mysql_connection(self, create_db_if_missing: bool = False, use_failsafe: bool = False):
        import pymysql

        db_name = None if create_db_if_missing else self.config.get("name", "nfc_attendance")
        failsafe_cfg = self.config.get("failsafe", {})

        if use_failsafe and failsafe_cfg.get("enabled", True):
            host = failsafe_cfg.get("host") or self.config.get("host", "127.0.0.1")
            port = int(failsafe_cfg.get("port") or self.config.get("port", 3306))
            user = failsafe_cfg.get("user", "nfc_backup")
            password = str(failsafe_cfg.get("password", ""))
        else:
            host = self.config.get("host", "127.0.0.1")
            port = int(self.config.get("port", 3306))
            user = self.config.get("user", "root")
            password = str(self.config.get("password", ""))

        return pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=db_name,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=3,
            autocommit=True,
        )

    def _get_active_mysql_connection(self, create_db_if_missing: bool = False):
        try:
            conn = self._get_mysql_connection(create_db_if_missing=create_db_if_missing, use_failsafe=False)
            if self._using_failsafe:
                logger.info("[Database] Primary MySQL user re-established.")
                self._using_failsafe = False
            return conn
        except Exception as primary_err:
            failsafe_cfg = self.config.get("failsafe", {})
            if failsafe_cfg.get("enabled", True):
                try:
                    conn = self._get_mysql_connection(create_db_if_missing=create_db_if_missing, use_failsafe=True)
                    if not self._using_failsafe:
                        logger.warning(
                            f"[Database] Primary MySQL user [{self.config.get('user')}] connection failed ({primary_err}). "
                            f"Using fail-safe user [{failsafe_cfg.get('user')}]!"
                        )
                        self._using_failsafe = True
                    return conn
                except Exception as failsafe_err:
                    raise primary_err from failsafe_err
            raise primary_err

    def _try_init_mysql(self, retries: int = 5, delay: float = 2.0) -> bool:
        import time

        db_name = self.config.get("name", "nfc_attendance")
        host = self.config.get("host", "127.0.0.1")
        port = int(self.config.get("port", 3306))

        for attempt in range(1, retries + 1):
            try:
                conn_root = self._get_active_mysql_connection(create_db_if_missing=True)
                with conn_root.cursor() as cur:
                    cur.execute(
                        f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
                    )
                conn_root.close()

                conn = self._get_active_mysql_connection(create_db_if_missing=False)
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS students (
                            uid VARCHAR(64) PRIMARY KEY,
                            student_id VARCHAR(64) UNIQUE NOT NULL,
                            full_name VARCHAR(128) NOT NULL,
                            class_name VARCHAR(64) NOT NULL,
                            created_at VARCHAR(64) NOT NULL
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
                        """
                    )
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS attendance_logs (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            uid VARCHAR(64) NOT NULL,
                            student_id VARCHAR(64),
                            full_name VARCHAR(128),
                            class_name VARCHAR(64),
                            status VARCHAR(32) NOT NULL,
                            device_id VARCHAR(64) DEFAULT 'ESP32_GATEWAY',
                            timestamp VARCHAR(64) NOT NULL,
                            notes TEXT,
                            INDEX idx_attendance_time (timestamp),
                            INDEX idx_attendance_uid (uid)
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
                        """
                    )
                conn.close()
                active_user = (
                    self.config.get("failsafe", {}).get("user", "failsafe")
                    if self._using_failsafe
                    else self.config.get("user", "root")
                )
                logger.info(
                    f"Connected and initialized MySQL database [{db_name}] at {host}:{port} (User: {active_user})"
                )
                return True
            except Exception as e:
                if attempt < retries:
                    logger.info(
                        f"Waiting for MySQL ({host}:{port}) to be ready... (attempt {attempt}/{retries})"
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        f"Failed to connect to MySQL ({host}:{port}) after {retries} attempts: {e}"
                    )
                    return False
        return False

    def _start_recovery_thread(self) -> None:
        import threading

        if self._recovery_thread and self._recovery_thread.is_alive():
            return

        def _recovery_loop():
            import time

            while self.active_backend == "sqlite":
                time.sleep(30)
                try:
                    if self._try_init_mysql(retries=1, delay=0.5):
                        self._sync_sqlite_to_mysql()
                        self.active_backend = "mysql"
                        logger.info("[Database] MySQL recovered and synchronized! Switched back to MySQL.")
                        break
                except Exception:
                    pass

        self._recovery_thread = threading.Thread(target=_recovery_loop, daemon=True)
        self._recovery_thread.start()

    def _sync_sqlite_to_mysql(self) -> None:
        try:
            with self._get_sqlite_connection() as s_conn:
                s_cur = s_conn.cursor()
                s_cur.execute("SELECT * FROM students;")
                students = [dict(r) for r in s_cur.fetchall()]

                s_cur.execute("SELECT * FROM attendance_logs;")
                logs = [dict(r) for r in s_cur.fetchall()]

            if students or logs:
                m_conn = self._get_active_mysql_connection()
                with m_conn.cursor() as m_cur:
                    for s in students:
                        m_cur.execute(
                            """
                            INSERT INTO students (uid, student_id, full_name, class_name, created_at)
                            VALUES (%s, %s, %s, %s, %s)
                            ON DUPLICATE KEY UPDATE student_id=VALUES(student_id), full_name=VALUES(full_name), class_name=VALUES(class_name);
                            """,
                            (s["uid"], s["student_id"], s["full_name"], s["class_name"], s["created_at"]),
                        )
                    for log in logs:
                        m_cur.execute(
                            """
                            INSERT INTO attendance_logs (uid, student_id, full_name, class_name, status, device_id, timestamp, notes)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                            """,
                            (
                                log["uid"],
                                log["student_id"],
                                log["full_name"],
                                log["class_name"],
                                log["status"],
                                log.get("device_id", "ESP32_GATEWAY"),
                                log["timestamp"],
                                log.get("notes", ""),
                            ),
                        )
                m_conn.close()
                logger.info(f"[Database] Synchronized {len(students)} students and {len(logs)} logs from SQLite to MySQL.")
        except Exception as e:
            logger.warning(f"[Database] Error syncing SQLite to MySQL: {e}")

    def _get_sqlite_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.sqlite_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_sqlite(self) -> None:
        with self._get_sqlite_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS students (
                    uid TEXT PRIMARY KEY,
                    student_id TEXT UNIQUE NOT NULL,
                    full_name TEXT NOT NULL,
                    class_name TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS attendance_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uid TEXT NOT NULL,
                    student_id TEXT,
                    full_name TEXT,
                    class_name TEXT,
                    status TEXT NOT NULL,
                    device_id TEXT DEFAULT 'ESP32_GATEWAY',
                    timestamp TEXT NOT NULL,
                    notes TEXT
                );
                """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_attendance_time ON attendance_logs(timestamp);"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_attendance_uid ON attendance_logs(uid);"
            )
            conn.commit()
            logger.info(f"SQLite fallback database initialized at {self.sqlite_path}")

    def add_student(
        self, uid: str, student_id: str, full_name: str, class_name: str
    ) -> dict[str, Any]:
        clean_uid = _normalize_uid(uid)
        now = datetime.now().astimezone().isoformat()

        if self.active_backend == "mysql":
            try:
                conn = self._get_active_mysql_connection()
                with conn.cursor() as cur:
                    sql = """
                    INSERT INTO students (uid, student_id, full_name, class_name, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        student_id = VALUES(student_id),
                        full_name = VALUES(full_name),
                        class_name = VALUES(class_name);
                    """
                    cur.execute(
                        sql,
                        (clean_uid, student_id.strip(), full_name.strip(), class_name.strip(), now),
                    )
                conn.close()
                logger.info(f"[MySQL] Saved student: {full_name} ({student_id}) - UID: {clean_uid}")
                return {
                    "uid": clean_uid,
                    "student_id": student_id.strip(),
                    "full_name": full_name.strip(),
                    "class_name": class_name.strip(),
                    "created_at": now,
                }
            except Exception as e:
                logger.warning(f"MySQL error in add_student ({e}), falling back to SQLite")
                self.active_backend = "sqlite"

        with self._get_sqlite_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO students (uid, student_id, full_name, class_name, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(uid) DO UPDATE SET
                    student_id = excluded.student_id,
                    full_name = excluded.full_name,
                    class_name = excluded.class_name;
                """,
                (clean_uid, student_id.strip(), full_name.strip(), class_name.strip(), now),
            )
            conn.commit()

        logger.info(f"[SQLite] Saved student: {full_name} ({student_id}) - UID: {clean_uid}")
        return {
            "uid": clean_uid,
            "student_id": student_id.strip(),
            "full_name": full_name.strip(),
            "class_name": class_name.strip(),
            "created_at": now,
        }

    def get_student(self, uid: str) -> dict[str, Any] | None:
        clean_uid = _normalize_uid(uid)

        if self.active_backend == "mysql":
            try:
                conn = self._get_active_mysql_connection()
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM students WHERE uid = %s LIMIT 1;", (clean_uid,))
                    row = cur.fetchone()
                conn.close()
                if row:
                    return dict(row)
                return None
            except Exception as e:
                logger.warning(f"MySQL error in get_student ({e}), using SQLite")
                self.active_backend = "sqlite"

        with self._get_sqlite_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM students WHERE uid = ?;", (clean_uid,))
            row = cursor.fetchone()
            if row:
                return dict(row)
        return None

    def get_all_students(self) -> list[dict[str, Any]]:
        if self.active_backend == "mysql":
            try:
                conn = self._get_active_mysql_connection()
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM students ORDER BY class_name ASC, student_id ASC;")
                    rows = cur.fetchall()
                conn.close()
                return [dict(r) for r in rows]
            except Exception as e:
                logger.warning(f"MySQL error in get_all_students ({e}), using SQLite")
                self.active_backend = "sqlite"

        with self._get_sqlite_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM students ORDER BY class_name ASC, student_id ASC;")
            return [dict(row) for row in cursor.fetchall()]

    def delete_student(self, uid: str) -> bool:
        clean_uid = _normalize_uid(uid)

        if self.active_backend == "mysql":
            try:
                conn = self._get_active_mysql_connection()
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM students WHERE uid = %s;", (clean_uid,))
                    count = cur.rowcount
                conn.close()
                return count > 0
            except Exception as e:
                logger.warning(f"MySQL error in delete_student ({e}), using SQLite")
                self.active_backend = "sqlite"

        with self._get_sqlite_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM students WHERE uid = ?;", (clean_uid,))
            conn.commit()
            return cursor.rowcount > 0

    def record_attendance(
        self,
        uid: str,
        device_id: str = "ESP32_GATEWAY",
        notes: str = "",
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        clean_uid = _normalize_uid(uid)
        student = self.get_student(clean_uid)
        now = timestamp or datetime.now().astimezone().isoformat()

        if student:
            status = "SUCCESS"
            student_id = student["student_id"]
            full_name = student["full_name"]
            class_name = student["class_name"]
            message = f"Diem danh thanh cong: {full_name} ({class_name})"
        else:
            status = "UNKNOWN_CARD"
            student_id = None
            full_name = "Chua dang ky"
            class_name = ""
            message = "The chua duoc dang ky trong he thong"

        final_notes = notes or message

        if self.active_backend == "mysql":
            try:
                conn = self._get_active_mysql_connection()
                with conn.cursor() as cur:
                    sql = """
                    INSERT INTO attendance_logs
                    (uid, student_id, full_name, class_name, status, device_id, timestamp, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                    """
                    cur.execute(
                        sql,
                        (
                            clean_uid,
                            student_id,
                            full_name,
                            class_name,
                            status,
                            device_id,
                            now,
                            final_notes,
                        ),
                    )
                    record_id = cur.lastrowid
                conn.close()
                logger.info(
                    f"[MySQL] Attendance recorded #{record_id}: [{status}] UID {clean_uid} - {full_name}"
                )
                return {
                    "id": record_id,
                    "uid": clean_uid,
                    "status": status,
                    "student": student,
                    "message": message,
                    "timestamp": now,
                    "device_id": device_id,
                    "backend": "mysql",
                }
            except Exception as e:
                logger.warning(f"MySQL error in record_attendance ({e}), using SQLite")
                self.active_backend = "sqlite"

        with self._get_sqlite_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO attendance_logs
                (uid, student_id, full_name, class_name, status, device_id, timestamp, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    clean_uid,
                    student_id,
                    full_name,
                    class_name,
                    status,
                    device_id,
                    now,
                    final_notes,
                ),
            )
            conn.commit()
            record_id = cursor.lastrowid

        logger.info(
            f"[SQLite] Attendance recorded #{record_id}: [{status}] UID {clean_uid} - {full_name}"
        )
        return {
            "id": record_id,
            "uid": clean_uid,
            "status": status,
            "student": student,
            "message": message,
            "timestamp": now,
            "device_id": device_id,
            "backend": "sqlite",
        }

    def get_attendance_logs(self, limit: int = 50) -> list[dict[str, Any]]:
        if self.active_backend == "mysql":
            try:
                conn = self._get_active_mysql_connection()
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT * FROM attendance_logs ORDER BY id DESC LIMIT %s;", (limit,)
                    )
                    rows = cur.fetchall()
                conn.close()
                return [dict(r) for r in rows]
            except Exception as e:
                logger.warning(f"MySQL error in get_attendance_logs ({e}), using SQLite")
                self.active_backend = "sqlite"

        with self._get_sqlite_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM attendance_logs
                ORDER BY id DESC
                LIMIT ?;
                """,
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_stats(self) -> dict[str, Any]:
        if self.active_backend == "mysql":
            try:
                conn = self._get_active_mysql_connection()
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) AS c FROM students;")
                    total_students = cur.fetchone()["c"]
                    cur.execute(
                        "SELECT COUNT(*) AS total, COALESCE(SUM(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END), 0) AS success FROM attendance_logs;"
                    )
                    res = cur.fetchone()
                    total_scans = int(res["total"])
                    success_scans = int(res["success"])
                conn.close()
                return {
                    "backend": "mysql",
                    "failsafe_active": self._using_failsafe,
                    "total_students": total_students,
                    "total_scans": total_scans,
                    "success_scans": success_scans,
                    "unknown_scans": total_scans - success_scans,
                }
            except Exception as e:
                logger.warning(f"MySQL error in get_stats ({e}), using SQLite")
                self.active_backend = "sqlite"
                self._start_recovery_thread()

        with self._get_sqlite_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM students;")
            total_students = cursor.fetchone()[0]

            cursor.execute(
                "SELECT COUNT(*), COALESCE(SUM(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END), 0) FROM attendance_logs;"
            )
            row = cursor.fetchone()
            total_scans = int(row[0])
            success_scans = int(row[1])

            return {
                "backend": "sqlite",
                "total_students": total_students,
                "total_scans": total_scans,
                "success_scans": success_scans,
                "unknown_scans": total_scans - success_scans,
            }


db = Database()
