"""
SQLite 資料庫管理模組
負責測試場次與統計結果的持久化儲存
"""

import sqlite3
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any


# 預設資料庫路徑
DEFAULT_DB_PATH = str(Path(__file__).parent.parent / "data" / "motor_test.db")


class DatabaseManager:
    """
    SQLite 資料庫管理器
    管理 test_sessions 與 test_results 兩張資料表
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        """
        Args:
            db_path: SQLite 資料庫檔案路徑
        """
        self._db_path = db_path
        self._ensure_dir()
        self._init_db()

    # ─── 初始化 ────────────────────────────────────────────────────────────────

    def _ensure_dir(self):
        """確保資料庫目錄存在"""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

    def _get_conn(self) -> sqlite3.Connection:
        """取得資料庫連線（每次操作建立新連線，避免多執行緒問題）"""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row  # 讓查詢結果可用欄位名稱存取
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self):
        """建立資料表（若不存在）"""
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS test_sessions (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    serial_no   TEXT    DEFAULT '',
                    operator    TEXT    DEFAULT '',
                    started_at  TEXT    NOT NULL,
                    ended_at    TEXT,
                    duration_s  REAL,
                    notes       TEXT    DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS test_results (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id      INTEGER NOT NULL
                                    REFERENCES test_sessions(id) ON DELETE CASCADE,
                    hall_total      INTEGER DEFAULT 0,
                    hall_pass       INTEGER DEFAULT 0,
                    hall_fail       INTEGER DEFAULT 0,
                    hall_pass_rate  REAL    DEFAULT 0.0,
                    enc_total       INTEGER DEFAULT 0,
                    enc_pass        INTEGER DEFAULT 0,
                    enc_fail        INTEGER DEFAULT 0,
                    enc_pass_rate   REAL    DEFAULT 0.0,
                    avg_rpm         REAL    DEFAULT 0.0,
                    max_rpm         REAL    DEFAULT 0.0,
                    min_rpm         REAL    DEFAULT 0.0,
                    overall_pass    INTEGER DEFAULT 0,
                    notes           TEXT    DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_sessions_started_at
                    ON test_sessions(started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_results_session_id
                    ON test_results(session_id);
            """)
        print(f"[DB] 資料庫已初始化: {self._db_path}")

    # ─── 路徑管理 ──────────────────────────────────────────────────────────────

    def set_db_path(self, new_path: str):
        """
        變更資料庫路徑並重新初始化
        Args:
            new_path: 新的資料庫檔案路徑
        """
        self._db_path = new_path
        self._ensure_dir()
        self._init_db()
        print(f"[DB] 資料庫路徑已變更: {new_path}")

    def get_db_path(self) -> str:
        """取得目前資料庫路徑"""
        return self._db_path

    # ─── 場次操作 ──────────────────────────────────────────────────────────────

    def create_session(
        self,
        serial_no: str = "",
        operator: str = "",
        notes: str = ""
    ) -> int:
        """
        建立新測試場次
        Args:
            serial_no: 馬達/測試物件序號
            operator:  操作員名稱
            notes:     備註
        Returns:
            int: 新建場次的 ID
        """
        started_at = datetime.now().isoformat(timespec="seconds")
        with self._get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO test_sessions (serial_no, operator, started_at, notes)
                   VALUES (?, ?, ?, ?)""",
                (serial_no, operator, started_at, notes)
            )
            session_id = cursor.lastrowid
        print(f"[DB] 建立場次 #{session_id}  序號={serial_no or '(無)'}")
        return session_id

    def close_session(self, session_id: int, duration_s: float):
        """
        結束測試場次，記錄結束時間與實際測試秒數
        Args:
            session_id: 場次 ID
            duration_s: 實際測試秒數
        """
        ended_at = datetime.now().isoformat(timespec="seconds")
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE test_sessions
                   SET ended_at = ?, duration_s = ?
                   WHERE id = ?""",
                (ended_at, duration_s, session_id)
            )
        print(f"[DB] 場次 #{session_id} 已結束，歷時 {duration_s:.1f} 秒")

    def update_session_serial(self, session_id: int, serial_no: str):
        """
        更新場次序號（允許測試後補填）
        Args:
            session_id: 場次 ID
            serial_no:  新序號
        """
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE test_sessions SET serial_no = ? WHERE id = ?",
                (serial_no, session_id)
            )
        print(f"[DB] 場次 #{session_id} 序號已更新: {serial_no}")

    def update_session_info(
        self,
        session_id: int,
        serial_no: str,
        operator: str,
        notes: str = None
    ):
        """
        更新場次的序號、操作員（及備註），允許測試後補填或修改
        Args:
            session_id: 場次 ID
            serial_no:  馬達序號
            operator:   操作員姓名
            notes:      備註（None 表示不修改）
        """
        if notes is None:
            with self._get_conn() as conn:
                conn.execute(
                    "UPDATE test_sessions SET serial_no = ?, operator = ? WHERE id = ?",
                    (serial_no, operator, session_id)
                )
        else:
            with self._get_conn() as conn:
                conn.execute(
                    "UPDATE test_sessions SET serial_no = ?, operator = ?, notes = ? WHERE id = ?",
                    (serial_no, operator, notes, session_id)
                )
        print(f"[DB] 場次 #{session_id} 資訊已更新: 序號={serial_no or '(無)'}, 操作員={operator or '(無)'}")

    # ─── 結果操作 ──────────────────────────────────────────────────────────────

    def save_result(
        self,
        session_id: int,
        hall_total: int,
        hall_pass: int,
        enc_total: int,
        enc_pass: int,
        avg_rpm: float,
        max_rpm: float,
        min_rpm: float,
        notes: str = ""
    ) -> int:
        """
        儲存測試統計結果
        Args:
            session_id: 對應場次 ID
            hall_total: Hall 總採樣次數
            hall_pass:  Hall PASS 次數
            enc_total:  Encoder 總採樣次數
            enc_pass:   Encoder PASS 次數
            avg_rpm:    平均轉速
            max_rpm:    最高轉速
            min_rpm:    最低轉速
            notes:      備註
        Returns:
            int: 結果記錄 ID
        """
        hall_fail = hall_total - hall_pass
        hall_pass_rate = (hall_pass / hall_total) if hall_total > 0 else 0.0

        enc_fail = enc_total - enc_pass
        enc_pass_rate = (enc_pass / enc_total) if enc_total > 0 else 0.0

        # 整體判定：Hall 與 Encoder 成功率都 >= 95% 才算 PASS
        overall_pass = 1 if (hall_pass_rate >= 0.95 and enc_pass_rate >= 0.95) else 0

        with self._get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO test_results (
                    session_id,
                    hall_total, hall_pass, hall_fail, hall_pass_rate,
                    enc_total,  enc_pass,  enc_fail,  enc_pass_rate,
                    avg_rpm, max_rpm, min_rpm,
                    overall_pass, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    hall_total, hall_pass, hall_fail, hall_pass_rate,
                    enc_total,  enc_pass,  enc_fail,  enc_pass_rate,
                    avg_rpm, max_rpm, min_rpm,
                    overall_pass, notes
                )
            )
            result_id = cursor.lastrowid

        print(
            f"[DB] 結果已儲存 #{result_id}  "
            f"Hall={hall_pass}/{hall_total}({hall_pass_rate*100:.1f}%)  "
            f"Enc={enc_pass}/{enc_total}({enc_pass_rate*100:.1f}%)  "
            f"整體={'PASS' if overall_pass else 'FAIL'}"
        )
        return result_id

    # ─── 查詢操作 ──────────────────────────────────────────────────────────────

    def query_sessions(
        self,
        limit: int = 200,
        serial_filter: str = ""
    ) -> List[Dict[str, Any]]:
        """
        查詢測試場次列表（含統計結果）
        Args:
            limit:         最多回傳筆數
            serial_filter: 依序號篩選（空字串=全部）
        Returns:
            List[dict]: 場次資料列表，依時間倒序排列
        """
        where_clause = ""
        params: list = []

        if serial_filter:
            where_clause = "WHERE s.serial_no LIKE ?"
            params.append(f"%{serial_filter}%")

        params.append(limit)

        with self._get_conn() as conn:
            rows = conn.execute(
                f"""SELECT
                    s.id,
                    s.serial_no,
                    s.operator,
                    s.started_at,
                    s.ended_at,
                    s.duration_s,
                    s.notes                 AS session_notes,
                    r.hall_total,
                    r.hall_pass,
                    r.hall_fail,
                    r.hall_pass_rate,
                    r.enc_total,
                    r.enc_pass,
                    r.enc_fail,
                    r.enc_pass_rate,
                    r.avg_rpm,
                    r.max_rpm,
                    r.min_rpm,
                    r.overall_pass,
                    r.notes                 AS result_notes
                FROM test_sessions s
                LEFT JOIN test_results r ON r.session_id = s.id
                {where_clause}
                ORDER BY s.started_at DESC
                LIMIT ?""",
                params
            ).fetchall()

        return [dict(row) for row in rows]

    def get_session_detail(self, session_id: int) -> Optional[Dict[str, Any]]:
        """
        取得單一場次詳細資料
        Args:
            session_id: 場次 ID
        Returns:
            dict 或 None
        """
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT
                    s.*, r.hall_total, r.hall_pass, r.hall_fail, r.hall_pass_rate,
                    r.enc_total, r.enc_pass, r.enc_fail, r.enc_pass_rate,
                    r.avg_rpm, r.max_rpm, r.min_rpm, r.overall_pass
                FROM test_sessions s
                LEFT JOIN test_results r ON r.session_id = s.id
                WHERE s.id = ?""",
                (session_id,)
            ).fetchone()
        return dict(row) if row else None

    def delete_session(self, session_id: int):
        """
        刪除場次（CASCADE 同時刪除對應結果）
        Args:
            session_id: 場次 ID
        """
        with self._get_conn() as conn:
            conn.execute("DELETE FROM test_sessions WHERE id = ?", (session_id,))
        print(f"[DB] 場次 #{session_id} 已刪除")

    def get_summary_stats(self) -> Dict[str, Any]:
        """
        取得全域統計摘要
        Returns:
            dict: 總場次數、整體 PASS 率等
        """
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT
                    COUNT(s.id)                         AS total_sessions,
                    SUM(CASE WHEN r.overall_pass = 1 THEN 1 ELSE 0 END) AS pass_sessions,
                    AVG(r.hall_pass_rate)               AS avg_hall_pass_rate,
                    AVG(r.enc_pass_rate)                AS avg_enc_pass_rate,
                    AVG(r.avg_rpm)                      AS avg_rpm_all
                FROM test_sessions s
                LEFT JOIN test_results r ON r.session_id = s.id
                WHERE s.ended_at IS NOT NULL"""
            ).fetchone()
        return dict(row) if row else {}
