from __future__ import annotations

import os
from datetime import datetime
from urllib.parse import quote

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .models import DockerReport, ScanComparison, ScanResult

console = Console()


def _format_bytes(b: int) -> str:
    """Human-readable byte size."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(b) < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024  # type: ignore[assignment]
    return f"{b:.1f} PB"


def _format_delta(delta: int) -> str:
    sign = "+" if delta >= 0 else ""
    return f"{sign}{_format_bytes(delta)}"


def _usage_color(pct: float) -> str:
    if pct < 70:
        return "green"
    elif pct < 85:
        return "yellow"
    return "red"


def _shorten_path(path: str, max_len: int = 50) -> str:
    """Shorten path for display, replacing home with ~."""
    home = os.path.expanduser("~")
    if path.startswith(home):
        path = "~" + path[len(home):]
    if len(path) <= max_len:
        return path
    return "..." + path[-(max_len - 3):]


def _file_type(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return ext if ext else "-"


def show_disk_overview(result: ScanResult) -> None:
    """Show disk usage panel with color-coded bar."""
    di = result.disk_info
    pct = (di.used_bytes / di.total_bytes * 100) if di.total_bytes else 0
    color = _usage_color(pct)

    bar_width = 40
    filled = int(bar_width * pct / 100)
    bar = f"[{color}]{'█' * filled}[/{color}]{'░' * (bar_width - filled)}"

    lines = [
        f"  Volume: {di.volume_name or 'N/A'}  ({di.fs_type or 'unknown'})",
        f"  Total:  {_format_bytes(di.total_bytes)}",
        f"  Used:   {_format_bytes(di.used_bytes)} [{color}]({pct:.1f}%)[/{color}]",
        f"  Free:   {_format_bytes(di.free_bytes)}",
        "",
        f"  {bar} {pct:.1f}%",
    ]
    if di.apfs_container:
        lines.insert(1, f"  APFS:   {di.apfs_container}")

    panel = Panel(
        "\n".join(lines),
        title="[bold]Disk Overview[/bold]",
        border_style=color,
        padding=(1, 2),
    )
    console.print(panel)


def show_directories(result: ScanResult) -> None:
    """Show top directories table with size bars."""
    if not result.directories:
        return

    max_size = result.directories[0].size_bytes if result.directories else 1

    table = Table(title="Top Directories", show_lines=False, padding=(0, 1))
    table.add_column("Directory", style="cyan", no_wrap=True, max_width=50)
    table.add_column("Size", style="bold", justify="right", width=10)
    table.add_column("Bar", width=25)

    for d in result.directories:
        name = _shorten_path(d.path)
        size = _format_bytes(d.size_bytes)
        bar_len = int(20 * d.size_bytes / max_size) if max_size else 0
        bar = "█" * bar_len
        table.add_row(name, size, f"[blue]{bar}[/blue]")

    console.print(table)


def _dir_link(path: str) -> str:
    """Return a Rich markup string with a clickable link to the containing folder."""
    folder = os.path.dirname(path)
    uri = "file://" + quote(folder, safe="/:")
    display_path = _shorten_path(path, 80)
    return f"[link={uri}]{display_path}[/link]"


def show_large_files(result: ScanResult) -> None:
    """Show largest files table."""
    if not result.large_files:
        return

    table = Table(title="Largest Files", show_lines=True, padding=(0, 1))
    table.add_column("Path", style="cyan")
    table.add_column("Type", style="dim", width=8)
    table.add_column("Size", style="bold", justify="right", width=10)

    for f in result.large_files:
        table.add_row(
            _dir_link(f.path),
            _file_type(f.path),
            _format_bytes(f.size_bytes),
        )

    console.print(table)


def show_trends(comparison: ScanComparison) -> None:
    """Show trend comparison between two scans."""
    if not comparison.trends and not comparison.new_dirs and not comparison.removed_dirs:
        return

    # Filter to entries with meaningful change (>0.1%)
    meaningful = [t for t in comparison.trends if abs(t.delta_percent) > 0.1]
    if not meaningful and not comparison.new_dirs and not comparison.removed_dirs:
        return

    overall = comparison.overall_delta
    overall_color = "red" if overall > 0 else "green"
    title = f"Trends (overall: [{overall_color}]{_format_delta(overall)}[/{overall_color}])"

    table = Table(title=title, show_lines=False, padding=(0, 1))
    table.add_column("Directory", style="cyan", no_wrap=True, max_width=40)
    table.add_column("Previous", justify="right", width=10)
    table.add_column("Current", justify="right", width=10)
    table.add_column("Delta", justify="right", width=12)
    table.add_column("Change", justify="right", width=8)

    for t in meaningful:
        if t.delta_bytes > 0:
            delta_style = "dark_orange"
            pct_style = "dark_orange"
        elif t.delta_bytes < 0:
            delta_style = "cyan"
            pct_style = "cyan"
        else:
            delta_style = "dim"
            pct_style = "dim"

        table.add_row(
            _shorten_path(t.path, 40),
            _format_bytes(t.previous_bytes),
            _format_bytes(t.current_bytes),
            f"[{delta_style}]{_format_delta(t.delta_bytes)}[/{delta_style}]",
            f"[{pct_style}]{t.delta_percent:+.1f}%[/{pct_style}]",
        )

    for d in comparison.new_dirs:
        table.add_row(
            _shorten_path(d.path, 40),
            "-",
            _format_bytes(d.size_bytes),
            f"[green]NEW[/green]",
            "",
        )
    for d in comparison.removed_dirs:
        table.add_row(
            _shorten_path(d.path, 40),
            _format_bytes(d.size_bytes),
            "-",
            f"[red]REMOVED[/red]",
            "",
        )

    console.print(table)


def show_scan_header(result: ScanResult) -> None:
    console.print()
    console.print(
        f"[bold]Scan:[/bold] {result.root_path}  "
        f"[dim]{result.timestamp.strftime('%Y-%m-%d %H:%M:%S')}[/dim]"
    )
    console.print()


def show_history(scans: list[ScanResult]) -> None:
    """Show scan history table."""
    if not scans:
        console.print("[dim]No scan history found.[/dim]")
        return

    table = Table(title="Scan History", show_lines=False, padding=(0, 1))
    table.add_column("ID", style="dim", width=5)
    table.add_column("Timestamp", width=20)
    table.add_column("Root", style="cyan", max_width=30)
    table.add_column("Scanned", justify="right", width=10)
    table.add_column("Disk Used", justify="right", width=10)
    table.add_column("Disk %", justify="right", width=8)

    for s in scans:
        pct = (s.disk_info.used_bytes / s.disk_info.total_bytes * 100) if s.disk_info.total_bytes else 0
        color = _usage_color(pct)
        table.add_row(
            str(s.scan_id or "?"),
            s.timestamp.strftime("%Y-%m-%d %H:%M"),
            _shorten_path(s.root_path, 30),
            _format_bytes(s.total_scanned_bytes),
            _format_bytes(s.disk_info.used_bytes),
            f"[{color}]{pct:.1f}%[/{color}]",
        )

    console.print(table)


def show_full_scan(result: ScanResult, comparison: ScanComparison | None = None) -> None:
    """Show a complete scan report."""
    show_scan_header(result)
    show_disk_overview(result)
    console.print()
    show_directories(result)
    console.print()
    show_large_files(result)
    if comparison:
        console.print()
        show_trends(comparison)
    console.print()


def format_scan_text(result: ScanResult, comparison: ScanComparison | None = None) -> str:
    """Format a scan as plain text for LLM context."""
    home = os.path.expanduser("~")

    def tilde(p: str) -> str:
        return "~" + p[len(home):] if p.startswith(home) else p

    di = result.disk_info
    pct = (di.used_bytes / di.total_bytes * 100) if di.total_bytes else 0
    lines = [
        f"Disk Usage Report — {tilde(result.root_path)} — {result.timestamp.strftime('%Y-%m-%d %H:%M')}",
        "",
        f"Volume: {di.volume_name or 'N/A'} ({di.fs_type or 'unknown'})",
        f"Total: {_format_bytes(di.total_bytes)}, Used: {_format_bytes(di.used_bytes)} ({pct:.1f}%), Free: {_format_bytes(di.free_bytes)}",
        "",
        "Top Directories:",
    ]
    for d in result.directories:
        lines.append(f"  {_format_bytes(d.size_bytes):>10}  {tilde(d.path)}")

    if result.large_files:
        lines.append("")
        lines.append("Largest Files:")
        for f in result.large_files:
            lines.append(f"  {_format_bytes(f.size_bytes):>10}  {tilde(f.path)}")

    if comparison:
        meaningful = [t for t in comparison.trends if abs(t.delta_percent) > 0.1]
        if meaningful or comparison.new_dirs or comparison.removed_dirs:
            lines.append("")
            lines.append(f"Trends (overall: {_format_delta(comparison.overall_delta)}):")
            for t in meaningful:
                lines.append(
                    f"  {tilde(t.path)}: {_format_bytes(t.previous_bytes)} -> "
                    f"{_format_bytes(t.current_bytes)} ({_format_delta(t.delta_bytes)}, {t.delta_percent:+.1f}%)"
                )
            for d in comparison.new_dirs:
                lines.append(f"  {tilde(d.path)}: NEW ({_format_bytes(d.size_bytes)})")
            for d in comparison.removed_dirs:
                lines.append(f"  {tilde(d.path)}: REMOVED ({_format_bytes(d.size_bytes)})")

    return "\n".join(lines)


# --- Docker display ---


def show_docker_overview(report: DockerReport) -> None:
    """Show Docker disk usage overview panel."""
    ov = report.overview
    total = ov.images_size + ov.containers_size + ov.volumes_size + ov.build_cache_size
    reclaimable = ov.images_reclaimable + ov.volumes_reclaimable + ov.build_cache_reclaimable
    reclaim_pct = (reclaimable / total * 100) if total else 0

    bar_width = 40
    filled = int(bar_width * reclaim_pct / 100)
    bar = f"[green]{'█' * filled}[/green]{'░' * (bar_width - filled)}"

    lines = [
        f"  Total Docker disk usage: [bold]{_format_bytes(total)}[/bold]",
        f"  Reclaimable:             [green]{_format_bytes(reclaimable)}[/green] ({reclaim_pct:.1f}%)",
        "",
        f"  {bar} {reclaim_pct:.1f}% reclaimable",
        "",
        f"  Images:      {ov.images_total} ({ov.images_active} active), "
        f"{_format_bytes(ov.images_size)}, {_format_bytes(ov.images_reclaimable)} reclaimable",
        f"  Containers:  {ov.containers_total} ({ov.containers_active} running), "
        f"{_format_bytes(ov.containers_size)}",
        f"  Volumes:     {ov.volumes_total} ({ov.volumes_active} active), "
        f"{_format_bytes(ov.volumes_size)}, {_format_bytes(ov.volumes_reclaimable)} reclaimable",
        f"  Build Cache: {ov.build_cache_total} entries, "
        f"{_format_bytes(ov.build_cache_size)}, {_format_bytes(ov.build_cache_reclaimable)} reclaimable",
    ]

    panel = Panel(
        "\n".join(lines),
        title="[bold]Docker Disk Usage[/bold]",
        border_style="blue",
        padding=(1, 2),
    )
    console.print(panel)


def show_docker_images(report: DockerReport, top: int = 15) -> None:
    """Show Docker images table."""
    if not report.images:
        console.print("[dim]No Docker images found.[/dim]")
        return

    table = Table(title="Docker Images", show_lines=False, padding=(0, 1))
    table.add_column("Repository", style="cyan", no_wrap=True, max_width=30)
    table.add_column("Tag", style="dim", max_width=20)
    table.add_column("Image ID", style="dim", width=19)
    table.add_column("Size", style="bold", justify="right", width=10)
    table.add_column("Unique", justify="right", width=10)
    table.add_column("Created", style="dim", width=14)
    table.add_column("Ctrs", justify="right", width=4)

    for img in report.images[:top]:
        ctrs_style = "green" if img.containers > 0 else "dim"
        table.add_row(
            img.repo,
            img.tag,
            img.image_id,
            _format_bytes(img.size_bytes),
            _format_bytes(img.unique_bytes),
            img.created,
            f"[{ctrs_style}]{img.containers}[/{ctrs_style}]",
        )

    if len(report.images) > top:
        console.print(table)
        console.print(f"[dim]  ... and {len(report.images) - top} more images[/dim]")
    else:
        console.print(table)


def show_docker_containers(report: DockerReport) -> None:
    """Show Docker containers table."""
    if not report.containers:
        console.print("[dim]No Docker containers found.[/dim]")
        return

    table = Table(title="Docker Containers", show_lines=False, padding=(0, 1))
    table.add_column("Name", style="cyan", no_wrap=True, max_width=30)
    table.add_column("Image", style="dim", max_width=25)
    table.add_column("Container ID", style="dim", width=12)
    table.add_column("Size", style="bold", justify="right", width=10)
    table.add_column("State", width=10)
    table.add_column("Created", style="dim", width=14)

    for ctr in report.containers:
        if ctr.state == "running":
            state_str = f"[green]{ctr.state}[/green]"
        else:
            state_str = f"[dim]{ctr.state}[/dim]"
        table.add_row(
            ctr.name,
            ctr.image,
            ctr.container_id,
            _format_bytes(ctr.size_bytes),
            state_str,
            ctr.created,
        )

    console.print(table)


def show_docker_volumes(report: DockerReport) -> None:
    """Show Docker volumes table."""
    if not report.volumes:
        return

    table = Table(title="Docker Volumes", show_lines=False, padding=(0, 1))
    table.add_column("Name", style="cyan", no_wrap=True, max_width=40)
    table.add_column("Driver", style="dim", width=10)
    table.add_column("Size", style="bold", justify="right", width=10)

    for vol in report.volumes:
        table.add_row(vol.name, vol.driver, _format_bytes(vol.size_bytes))

    console.print(table)


def show_docker_build_cache(report: DockerReport) -> None:
    """Show Docker build cache table."""
    if not report.build_cache_by_type:
        return

    table = Table(title="Docker Build Cache", show_lines=False, padding=(0, 1))
    table.add_column("Cache Type", style="cyan", width=20)
    table.add_column("Size", style="bold", justify="right", width=10)

    for cache_type, size in sorted(
        report.build_cache_by_type.items(), key=lambda x: x[1], reverse=True
    ):
        table.add_row(cache_type, _format_bytes(size))

    console.print(table)


def show_docker_report(report: DockerReport) -> None:
    """Show a complete Docker disk usage report."""
    console.print()
    show_docker_overview(report)
    console.print()
    show_docker_images(report)
    console.print()
    show_docker_containers(report)
    if report.volumes:
        console.print()
        show_docker_volumes(report)
    if report.build_cache_by_type:
        console.print()
        show_docker_build_cache(report)
    console.print()


def format_docker_text(report: DockerReport) -> str:
    """Format Docker report as plain text for LLM context."""
    ov = report.overview
    total = ov.images_size + ov.containers_size + ov.volumes_size + ov.build_cache_size
    reclaimable = ov.images_reclaimable + ov.volumes_reclaimable + ov.build_cache_reclaimable

    lines = [
        "Docker Disk Usage:",
        f"  Total: {_format_bytes(total)}, Reclaimable: {_format_bytes(reclaimable)}",
        f"  Images: {ov.images_total} ({ov.images_active} active), "
        f"{_format_bytes(ov.images_size)}, {_format_bytes(ov.images_reclaimable)} reclaimable",
        f"  Containers: {ov.containers_total} ({ov.containers_active} running), "
        f"{_format_bytes(ov.containers_size)}",
        f"  Volumes: {ov.volumes_total}, "
        f"{_format_bytes(ov.volumes_size)}, {_format_bytes(ov.volumes_reclaimable)} reclaimable",
        f"  Build Cache: {ov.build_cache_total} entries, "
        f"{_format_bytes(ov.build_cache_size)}, {_format_bytes(ov.build_cache_reclaimable)} reclaimable",
    ]

    if report.images:
        lines.append("")
        lines.append("Top Docker Images:")
        for img in report.images[:10]:
            lines.append(
                f"  {_format_bytes(img.size_bytes):>10}  {img.repo}:{img.tag}"
                f"  (unique: {_format_bytes(img.unique_bytes)}, containers: {img.containers})"
            )

    if report.containers:
        lines.append("")
        lines.append("Docker Containers:")
        for ctr in report.containers[:10]:
            lines.append(
                f"  {_format_bytes(ctr.size_bytes):>10}  {ctr.name} ({ctr.image}) [{ctr.state}]"
            )

    if report.volumes:
        lines.append("")
        lines.append("Docker Volumes:")
        for vol in report.volumes[:10]:
            lines.append(f"  {_format_bytes(vol.size_bytes):>10}  {vol.name}")

    return "\n".join(lines)
