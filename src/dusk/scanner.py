from __future__ import annotations

import os
import plistlib
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from .models import DirEntry, DiskInfo, FileEntry, ScanResult


def _get_mount_point(path: str) -> str:
    """Resolve a path to its filesystem mount point."""
    path = os.path.realpath(path)
    while not os.path.ismount(path):
        path = os.path.dirname(path)
    return path


def get_disk_info(path: str = "/") -> DiskInfo:
    """Get disk info via os.statvfs + diskutil."""
    mount = _get_mount_point(path)
    st = os.statvfs(mount)
    total = st.f_frsize * st.f_blocks
    free = st.f_frsize * st.f_bfree
    available = st.f_frsize * st.f_bavail
    used = total - free

    volume_name = ""
    fs_type = ""
    apfs_container = ""

    try:
        result = subprocess.run(
            ["diskutil", "info", "-plist", mount],
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 0:
            plist = plistlib.loads(result.stdout)
            volume_name = plist.get("VolumeName", "")
            fs_type = plist.get("FilesystemType", "")
            apfs_container = plist.get("APFSContainerReference", "")
    except (subprocess.TimeoutExpired, Exception):
        pass

    return DiskInfo(
        total_bytes=total,
        used_bytes=used,
        free_bytes=free,
        available_bytes=available,
        volume_name=volume_name,
        fs_type=fs_type,
        apfs_container=apfs_container,
    )


def scan_directories(
    root: str, depth: int = 1, top_n: int = 20
) -> list[DirEntry]:
    """Scan directory sizes using du -x (stay on same filesystem)."""
    try:
        proc = subprocess.Popen(
            ["du", "-x", f"-d{depth}", "-k", root],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        stdout, _ = proc.communicate(timeout=300)
    except subprocess.TimeoutExpired:
        # Capture whatever partial output we have
        assert proc.stdout is not None
        stdout = proc.stdout.read()
        proc.kill()
        proc.wait()
    except Exception:
        return []

    entries: list[DirEntry] = []
    for line in stdout.strip().splitlines():
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        try:
            size_kb = int(parts[0])
        except ValueError:
            continue
        path = parts[1]
        # Skip the root itself — we want children only
        if os.path.normpath(path) == os.path.normpath(root):
            continue
        entries.append(DirEntry(path=path, size_bytes=size_kb * 1024))

    entries.sort(key=lambda e: e.size_bytes, reverse=True)
    return entries[:top_n]


def find_large_files(
    root: str, min_size_mb: int = 100, top_n: int = 10
) -> list[FileEntry]:
    """Find large files using mdfind, fallback to find."""
    min_bytes = min_size_mb * 1024 * 1024
    files = _find_large_files_mdfind(root, min_bytes)
    if files is None:
        files = _find_large_files_find(root, min_size_mb)

    files.sort(key=lambda f: f.size_bytes, reverse=True)
    return files[:top_n]


def _find_large_files_mdfind(
    root: str, min_bytes: int
) -> list[FileEntry] | None:
    """Use mdfind (Spotlight) to find large files quickly."""
    try:
        result = subprocess.run(
            [
                "mdfind",
                "-onlyin",
                root,
                f"kMDItemFSSize >= {min_bytes}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return None
    except (subprocess.TimeoutExpired, Exception):
        return None

    files: list[FileEntry] = []
    for path in result.stdout.strip().splitlines():
        if not path:
            continue
        try:
            size = os.path.getsize(path)
            files.append(FileEntry(path=path, size_bytes=size))
        except OSError:
            continue
    return files


def _find_large_files_find(root: str, min_size_mb: int) -> list[FileEntry]:
    """Fallback: use find command for large files."""
    try:
        result = subprocess.run(
            [
                "find",
                root,
                "-xdev",
                "-type",
                "f",
                "-size",
                f"+{min_size_mb}M",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return []

    files: list[FileEntry] = []
    for path in result.stdout.strip().splitlines():
        if not path:
            continue
        try:
            size = os.path.getsize(path)
            files.append(FileEntry(path=path, size_bytes=size))
        except OSError:
            continue
    return files


def scan(
    root: str = "~",
    depth: int = 1,
    top_n: int = 20,
    file_count: int = 10,
    min_file_size_mb: int = 100,
) -> ScanResult:
    """Run a full scan: disk info + directories + large files in parallel."""
    root = os.path.expanduser(root)

    with ThreadPoolExecutor(max_workers=3) as pool:
        disk_future = pool.submit(get_disk_info, root)
        dirs_future = pool.submit(scan_directories, root, depth, top_n)
        files_future = pool.submit(
            find_large_files, root, min_file_size_mb, file_count
        )

        disk_info = disk_future.result()
        directories = dirs_future.result()
        large_files = files_future.result()

    total_scanned = sum(d.size_bytes for d in directories)

    return ScanResult(
        scan_id=None,
        timestamp=datetime.now(),
        root_path=root,
        disk_info=disk_info,
        directories=directories,
        large_files=large_files,
        total_scanned_bytes=total_scanned,
    )
