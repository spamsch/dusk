from __future__ import annotations

import json
import re
import shutil
import subprocess

from .models import (
    DockerBuildCache,
    DockerContainer,
    DockerImage,
    DockerOverview,
    DockerReport,
    DockerVolume,
)


def is_docker_available() -> bool:
    return shutil.which("docker") is not None


def _parse_size(s: str) -> int:
    """Parse Docker size strings like '2.88GB', '178.3MB', '5.2kB' to bytes."""
    s = s.strip()
    if not s or s == "0B":
        return 0
    m = re.match(r"([\d.]+)\s*(B|kB|KB|MB|GB|TB)", s)
    if not m:
        return 0
    val = float(m.group(1))
    unit = m.group(2)
    multipliers = {"B": 1, "kB": 1000, "KB": 1024, "MB": 1e6, "GB": 1e9, "TB": 1e12}
    return int(val * multipliers.get(unit, 1))


def _run_docker(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["docker", *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return None
        return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def scan_docker() -> DockerReport | None:
    """Run a full Docker disk usage analysis."""
    raw = _run_docker("system", "df", "-v", "--format", "{{json .}}")
    if raw is None:
        return None

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None

    # Images
    images: list[DockerImage] = []
    for img in data.get("Images") or []:
        images.append(DockerImage(
            repo=img.get("Repository", "<none>"),
            tag=img.get("Tag", "<none>"),
            image_id=img.get("ID", "")[:19],
            size_bytes=_parse_size(img.get("Size", "0B")),
            unique_bytes=_parse_size(img.get("UniqueSize", "0B")),
            shared_bytes=_parse_size(img.get("SharedSize", "0B")),
            created=img.get("CreatedSince", ""),
            containers=int(img.get("Containers", 0)),
        ))
    images.sort(key=lambda i: i.size_bytes, reverse=True)

    # Containers
    containers: list[DockerContainer] = []
    for ctr in data.get("Containers") or []:
        size_str = ctr.get("Size", "0B")
        # Container size format: "1.2MB (virtual 3.4GB)" — take first part
        size_part = size_str.split("(")[0].strip()
        containers.append(DockerContainer(
            name=ctr.get("Names", ""),
            image=ctr.get("Image", ""),
            container_id=ctr.get("ID", "")[:12],
            size_bytes=_parse_size(size_part),
            state=ctr.get("State", ""),
            status=ctr.get("Status", ""),
            created=ctr.get("RunningFor", ""),
        ))
    containers.sort(key=lambda c: c.size_bytes, reverse=True)

    # Volumes
    volumes: list[DockerVolume] = []
    for vol in data.get("Volumes") or []:
        volumes.append(DockerVolume(
            name=vol.get("Name", ""),
            size_bytes=_parse_size(vol.get("Size", "0B")),
            driver=vol.get("Driver", ""),
            mountpoint=vol.get("Mountpoint", ""),
        ))
    volumes.sort(key=lambda v: v.size_bytes, reverse=True)

    # Build cache — aggregate by type
    build_cache_by_type: dict[str, int] = {}
    bc_total_size = 0
    bc_reclaimable = 0
    bc_count = 0
    for bc in data.get("BuildCache") or []:
        size = _parse_size(bc.get("Size", "0B"))
        cache_type = bc.get("CacheType", "unknown")
        build_cache_by_type[cache_type] = build_cache_by_type.get(cache_type, 0) + size
        bc_total_size += size
        bc_count += 1
        if not bc.get("InUse", False):
            bc_reclaimable += size

    # Build overview
    total_images_size = sum(i.size_bytes for i in images)
    unique_images_size = sum(i.unique_bytes for i in images)
    active_images = sum(1 for i in images if i.containers > 0)
    reclaimable_images = sum(i.size_bytes for i in images if i.containers == 0)

    active_containers = sum(1 for c in containers if c.state == "running")
    total_containers_size = sum(c.size_bytes for c in containers)

    active_volumes = 0  # approximate: volumes with non-zero links
    total_volumes_size = sum(v.size_bytes for v in volumes)

    overview = DockerOverview(
        images_total=len(images),
        images_active=active_images,
        images_size=total_images_size,
        images_reclaimable=reclaimable_images,
        containers_total=len(containers),
        containers_active=active_containers,
        containers_size=total_containers_size,
        volumes_total=len(volumes),
        volumes_active=active_volumes,
        volumes_size=total_volumes_size,
        volumes_reclaimable=total_volumes_size,
        build_cache_total=bc_count,
        build_cache_size=bc_total_size,
        build_cache_reclaimable=bc_reclaimable,
    )

    return DockerReport(
        overview=overview,
        images=images,
        containers=containers,
        volumes=volumes,
        build_cache_by_type=build_cache_by_type,
    )
