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
# DEFAULT_DB_PATH = str(Path(__file__).parent.parent / "data" / "motor_test.db")
import sys

def _get_default_db_path() -> str:
    # 執行檔模式：寫到執行檔同層的 data/ 目錄
    if getattr(sys, 'frozen', False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).parent.parent
    return str(base / "data" / "motor_test.db")

DEFAULT_DB_PATH = _get_default_db_path()

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
        """建立資料表（若不存在），並執行 schema migration"""
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS test_sessions (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    serial_no      TEXT    DEFAULT '',
                    operator       TEXT    DEFAULT '',
                    started_at     TEXT    NOT NULL,
                    ended_at       TEXT,
                    duration_s     REAL,
                    notes          TEXT    DEFAULT '',
                    waveform_path  TEXT    DEFAULT '',
                    session_type   TEXT    DEFAULT 'test'
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
            # Schema migration：為舊資料庫補上欄位
            self._migrate_add_column(conn, "test_sessions", "waveform_path",   "TEXT DEFAULT ''")
            self._migrate_add_column(conn, "test_sessions", "session_type",    "TEXT DEFAULT 'test'")
            # 診斷 PASS/FAIL 欄位（診斷場次用）
            self._migrate_add_column(conn, "test_sessions", "diag_pass",       "INTEGER DEFAULT -1")
            self._migrate_add_column(conn, "test_sessions", "diag_ch_results", "TEXT DEFAULT ''")
            # 診斷完整摘要文字（含比值交叉驗證、fail 原因，供歷史記錄回看）
            self._migrate_add_column(conn, "test_sessions", "diag_summary",    "TEXT DEFAULT ''")
        print(f"[DB] 資料庫已初始化: {self._db_path}")

    def _migrate_add_column(self, conn: sqlite3.Connection, table: str, column: str, col_def: str):
        """
        安全地為既有資料表新增欄位（若欄位已存在則跳過）
        Args:
            conn:    資料庫連線
            table:   資料表名稱
            column:  欄位名稱
            col_def: 欄位定義（如 "TEXT DEFAULT ''"）
        """
        existing = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
            print(f"[DB] Migration: {table}.{column} 欄位已新增")

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
        notes: str = "",
        session_type: str = "test"
    ) -> int:
        """
        建立新測試場次
        Args:
            serial_no:    馬達/測試物件序號
            operator:     操作員名稱
            notes:        備註
            session_type: 場次類型，'test'=一般測試，'diagnostic'=高取樣診斷
        Returns:
            int: 新建場次的 ID
        """
        started_at = datetime.now().isoformat(timespec="seconds")
        with self._get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO test_sessions (serial_no, operator, started_at, notes, session_type)
                   VALUES (?, ?, ?, ?, ?)""",
                (serial_no, operator, started_at, notes, session_type)
            )
            session_id = cursor.lastrowid
        print(f"[DB] 建立場次 #{session_id}  序號={serial_no or '(無)'}  類型={session_type}")
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

    def update_waveform_path(self, session_id: int, waveform_path: str):
        """
        更新場次的波形檔案路徑（FAIL 時儲存波形後呼叫）
        Args:
            session_id:    場次 ID
            waveform_path: .npz 波形檔案的絕對路徑
        """
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE test_sessions SET waveform_path = ? WHERE id = ?",
                (waveform_path, session_id)
            )
        print(f"[DB] 場次 #{session_id} 波形路徑已更新: {waveform_path}")

    def get_waveform_path(self, session_id: int) -> Optional[str]:
        """
        取得場次的波形檔案路徑
        Args:
            session_id: 場次 ID
        Returns:
            str: 波形檔案路徑（無資料時回傳 None）
        """
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT waveform_path FROM test_sessions WHERE id = ?",
                (session_id,)
            ).fetchone()
        if row and row["waveform_path"]:
            return row["waveform_path"]
        return None

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
        serial_filter: str = "",
        session_type: str = ""
    ) -> List[Dict[str, Any]]:
        """
        查詢測試場次列表（含統計結果）
        Args:
            limit:         最多回傳筆數
            serial_filter: 依序號篩選（空字串=全部）
            session_type:  依類型篩選（空字串=全部，'test'=一般，'diagnostic'=診斷）
        Returns:
            List[dict]: 場次資料列表，依時間倒序排列
        """
        where_parts = []
        params: list = []

        if serial_filter:
            where_parts.append("s.serial_no LIKE ?")
            params.append(f"%{serial_filter}%")

        if session_type:
            where_parts.append("s.session_type = ?")
            params.append(session_type)

        where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
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
                    s.waveform_path,
                    s.session_type,
                    s.diag_pass,
                    s.diag_ch_results,
                    s.diag_summary,
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

    def create_diagnostic_session(
        self,
        operator: str = "",
        notes: str = "",
        serial_no: str = ""
    ) -> int:
        """
        建立診斷場次（session_type='diagnostic'）
        Args:
            operator:  操作員名稱
            notes:     備註
            serial_no: 馬達序號（由參數設置帶入，留空時顯示為「[診斷]」）
        Returns:
            int: 新建場次的 ID
        """
        return self.create_session(
            serial_no=serial_no if serial_no else "[診斷]",
            operator=operator,
            notes=notes,
            session_type="diagnostic"
        )

    def close_diagnostic_session(
        self,
        session_id: int,
        duration_s: float,
        npz_path: str,
        completed: bool,
        rounds_done: int,
        diag_pass: bool = None,
        diag_ch_results: str = "",
        diag_summary: str = ""
    ):
        """
        結束診斷場次，記錄結束時間、波形路徑、完成狀態與診斷 PASS/FAIL 結果

        Args:
            session_id:       場次 ID
            duration_s:       實際診斷秒數
            npz_path:         診斷 npz 檔案路徑
            completed:        是否跑完所有輪次
            rounds_done:      已完成輪數
            diag_pass:        診斷整體 PASS/FAIL（None 表示未分析）
            diag_ch_results:  各通道診斷結果 JSON 字串（供歷史記錄顯示，舊格式相容）
            diag_summary:     完整診斷摘要文字（含比值交叉驗證、fail 原因，供歷史記錄回看）
        """
        ended_at = datetime.now().isoformat(timespec="seconds")
        notes = f"完成={'是' if completed else '否（提早停止）'}，已完成 {rounds_done} 輪"
        if diag_pass is not None:
            notes += f"，診斷={'PASS' if diag_pass else 'FAIL'}"

        # diag_pass: 1=PASS, 0=FAIL, -1=未分析
        diag_pass_int = (1 if diag_pass else 0) if diag_pass is not None else -1

        with self._get_conn() as conn:
            conn.execute(
                """UPDATE test_sessions
                   SET ended_at = ?, duration_s = ?, waveform_path = ?, notes = ?,
                       diag_pass = ?, diag_ch_results = ?, diag_summary = ?
                   WHERE id = ?""",
                (ended_at, duration_s, npz_path or "", notes,
                 diag_pass_int, diag_ch_results or "", diag_summary or "", session_id)
            )
        print(
            f"[DB] 診斷場次 #{session_id} 已結束，"
            f"歷時 {duration_s:.1f}s，npz={npz_path}，"
            f"診斷={'PASS' if diag_pass else 'FAIL' if diag_pass is not None else '未分析'}"
        )

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
        # s.* 已包含 waveform_path
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
