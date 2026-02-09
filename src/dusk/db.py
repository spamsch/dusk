from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

from .models import (
    DirEntry,
    DiskInfo,
    FileEntry,
    ScanComparison,
    ScanResult,
    TrendEntry,
)

DB_DIR = Path.home() / ".dusk"
DB_PATH = DB_DIR / "dusk.db"


def _get_conn() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            root_path TEXT NOT NULL,
            total_scanned_bytes INTEGER NOT NULL,
            disk_total INTEGER NOT NULL,
            disk_used INTEGER NOT NULL,
            disk_free INTEGER NOT NULL,
            disk_available INTEGER NOT NULL,
            volume_name TEXT,
            fs_type TEXT,
            apfs_container TEXT
        );

        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id INTEGER NOT NULL,
            path TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            is_dir INTEGER NOT NULL DEFAULT 1,
            file_count INTEGER,
            FOREIGN KEY (scan_id) REFERENCES scans(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_entries_scan_id ON entries(scan_id);
        CREATE INDEX IF NOT EXISTS idx_scans_root_path ON scans(root_path);
    """)


def save_scan(result: ScanResult) -> int:
    """Save a scan result and return the scan id."""
    conn = _get_conn()
    try:
        cur = conn.execute(
            """INSERT INTO scans
               (timestamp, root_path, total_scanned_bytes,
                disk_total, disk_used, disk_free, disk_available,
                volume_name, fs_type, apfs_container)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                result.timestamp.isoformat(),
                result.root_path,
                result.total_scanned_bytes,
                result.disk_info.total_bytes,
                result.disk_info.used_bytes,
                result.disk_info.free_bytes,
                result.disk_info.available_bytes,
                result.disk_info.volume_name,
                result.disk_info.fs_type,
                result.disk_info.apfs_container,
            ),
        )
        scan_id = cur.lastrowid
        assert scan_id is not None

        dir_rows = [
            (scan_id, d.path, d.size_bytes, 1, d.file_count)
            for d in result.directories
        ]
        file_rows = [
            (scan_id, f.path, f.size_bytes, 0, None)
            for f in result.large_files
        ]
        conn.executemany(
            "INSERT INTO entries (scan_id, path, size_bytes, is_dir, file_count) VALUES (?, ?, ?, ?, ?)",
            dir_rows + file_rows,
        )
        conn.commit()
        result.scan_id = scan_id
        return scan_id
    finally:
        conn.close()


def _row_to_scan(row: sqlite3.Row, conn: sqlite3.Connection) -> ScanResult:
    scan_id = row[0]
    disk_info = DiskInfo(
        total_bytes=row[4],
        used_bytes=row[5],
        free_bytes=row[6],
        available_bytes=row[7],
        volume_name=row[8] or "",
        fs_type=row[9] or "",
        apfs_container=row[10] or "",
    )

    dir_rows = conn.execute(
        "SELECT path, size_bytes, file_count FROM entries WHERE scan_id = ? AND is_dir = 1 ORDER BY size_bytes DESC",
        (scan_id,),
    ).fetchall()
    file_rows = conn.execute(
        "SELECT path, size_bytes FROM entries WHERE scan_id = ? AND is_dir = 0 ORDER BY size_bytes DESC",
        (scan_id,),
    ).fetchall()

    return ScanResult(
        scan_id=scan_id,
        timestamp=datetime.fromisoformat(row[1]),
        root_path=row[2],
        disk_info=disk_info,
        directories=[DirEntry(path=r[0], size_bytes=r[1], file_count=r[2]) for r in dir_rows],
        large_files=[FileEntry(path=r[0], size_bytes=r[1]) for r in file_rows],
        total_scanned_bytes=row[3],
    )


def get_scan_by_id(scan_id: int) -> ScanResult | None:
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM scans WHERE id = ?",
            (scan_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_scan(row, conn)
    finally:
        conn.close()


def get_latest_scan(root_path: str) -> ScanResult | None:
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM scans WHERE root_path = ? ORDER BY timestamp DESC LIMIT 1",
            (root_path,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_scan(row, conn)
    finally:
        conn.close()


def get_previous_scan(root_path: str) -> ScanResult | None:
    """Get the second-most-recent scan for a root path."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM scans WHERE root_path = ? ORDER BY timestamp DESC LIMIT 2",
            (root_path,),
        ).fetchall()
        if len(rows) < 2:
            return None
        return _row_to_scan(rows[1], conn)
    finally:
        conn.close()


def get_scan_history(root_path: str | None = None, limit: int = 20) -> list[ScanResult]:
    conn = _get_conn()
    try:
        if root_path:
            rows = conn.execute(
                "SELECT * FROM scans WHERE root_path = ? ORDER BY timestamp DESC LIMIT ?",
                (root_path, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM scans ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_scan(r, conn) for r in rows]
    finally:
        conn.close()


def compare_scans(current: ScanResult, previous: ScanResult) -> ScanComparison:
    """Compare two scans and produce trend entries."""
    current_dirs = {os.path.basename(d.path.rstrip("/")): d for d in current.directories}
    previous_dirs = {os.path.basename(d.path.rstrip("/")): d for d in previous.directories}

    all_keys = set(current_dirs.keys()) | set(previous_dirs.keys())
    trends: list[TrendEntry] = []
    new_dirs: list[DirEntry] = []
    removed_dirs: list[DirEntry] = []

    for key in all_keys:
        cur = current_dirs.get(key)
        prev = previous_dirs.get(key)

        if cur and prev:
            delta = cur.size_bytes - prev.size_bytes
            pct = (delta / prev.size_bytes * 100) if prev.size_bytes else 0.0
            trends.append(TrendEntry(
                path=cur.path,
                current_bytes=cur.size_bytes,
                previous_bytes=prev.size_bytes,
                delta_bytes=delta,
                delta_percent=pct,
            ))
        elif cur and not prev:
            new_dirs.append(cur)
        elif prev and not cur:
            removed_dirs.append(prev)

    trends.sort(key=lambda t: abs(t.delta_bytes), reverse=True)
    overall_delta = current.total_scanned_bytes - previous.total_scanned_bytes

    return ScanComparison(
        current=current,
        previous=previous,
        trends=trends,
        overall_delta=overall_delta,
        new_dirs=new_dirs,
        removed_dirs=removed_dirs,
    )


def prune_old_scans(keep: int = 10) -> int:
    """Delete old scans keeping only the most recent `keep` per root_path."""
    conn = _get_conn()
    try:
        roots = conn.execute("SELECT DISTINCT root_path FROM scans").fetchall()
        deleted = 0
        for (root_path,) in roots:
            ids = conn.execute(
                "SELECT id FROM scans WHERE root_path = ? ORDER BY timestamp DESC",
                (root_path,),
            ).fetchall()
            to_delete = [row[0] for row in ids[keep:]]
            if to_delete:
                placeholders = ",".join("?" * len(to_delete))
                conn.execute(f"DELETE FROM scans WHERE id IN ({placeholders})", to_delete)
                deleted += len(to_delete)
        conn.commit()
        return deleted
    finally:
        conn.close()
