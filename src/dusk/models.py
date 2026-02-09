from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class DiskInfo:
    total_bytes: int
    used_bytes: int
    free_bytes: int
    available_bytes: int
    volume_name: str = ""
    fs_type: str = ""
    apfs_container: str = ""


@dataclass
class DirEntry:
    path: str
    size_bytes: int
    file_count: int | None = None


@dataclass
class FileEntry:
    path: str
    size_bytes: int


@dataclass
class ScanResult:
    scan_id: int | None
    timestamp: datetime
    root_path: str
    disk_info: DiskInfo
    directories: list[DirEntry] = field(default_factory=list)
    large_files: list[FileEntry] = field(default_factory=list)
    total_scanned_bytes: int = 0


@dataclass
class TrendEntry:
    path: str
    current_bytes: int
    previous_bytes: int
    delta_bytes: int
    delta_percent: float


@dataclass
class ScanComparison:
    current: ScanResult
    previous: ScanResult
    trends: list[TrendEntry] = field(default_factory=list)
    overall_delta: int = 0
    new_dirs: list[DirEntry] = field(default_factory=list)
    removed_dirs: list[DirEntry] = field(default_factory=list)


# --- Docker models ---


@dataclass
class DockerImage:
    repo: str
    tag: str
    image_id: str
    size_bytes: int
    unique_bytes: int
    shared_bytes: int
    created: str
    containers: int


@dataclass
class DockerContainer:
    name: str
    image: str
    container_id: str
    size_bytes: int
    state: str
    status: str
    created: str


@dataclass
class DockerVolume:
    name: str
    size_bytes: int
    driver: str
    mountpoint: str


@dataclass
class DockerBuildCache:
    cache_type: str
    size_bytes: int
    in_use: bool
    description: str


@dataclass
class DockerOverview:
    images_total: int
    images_active: int
    images_size: int
    images_reclaimable: int
    containers_total: int
    containers_active: int
    containers_size: int
    volumes_total: int
    volumes_active: int
    volumes_size: int
    volumes_reclaimable: int
    build_cache_total: int
    build_cache_size: int
    build_cache_reclaimable: int


@dataclass
class DockerReport:
    overview: DockerOverview
    images: list[DockerImage] = field(default_factory=list)
    containers: list[DockerContainer] = field(default_factory=list)
    volumes: list[DockerVolume] = field(default_factory=list)
    build_cache_by_type: dict[str, int] = field(default_factory=dict)
