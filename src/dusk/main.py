from __future__ import annotations

import os
import shutil
import subprocess

import click
from rich.console import Console

from . import db, display, docker, scanner

console = Console()

EXAMPLES = """
[bold]Examples:[/bold]

  dusk scan              Scan home directory
  dusk scan ~/Projects   Scan a specific path
  dusk scan . -d2 -t10   Depth 2, top 10 dirs
  dusk history           List past scans
  dusk show 3            Show report for scan #3
  dusk compare           Diff last two scans
  dusk docker            Show Docker disk usage
  dusk ask "what can I delete?"          Ask Claude (auto-includes Docker data)
  dusk ask --codex "cleanup suggestions" Ask Codex instead
  dusk ask --scan-id 3 "why so big?"     Ask about a specific scan
  dusk prune             Clean old scan data
"""


@click.group(invoke_without_command=True)
@click.pass_context
def main(ctx: click.Context) -> None:
    """Dusk — macOS disk usage tracker with trend analysis."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
        console.print(EXAMPLES)


@main.command("scan")
@click.argument("path", default="~")
@click.option("--depth", "-d", default=1, help="Directory depth for scanning.")
@click.option("--top", "-t", default=20, help="Number of top directories to show.")
@click.option("--files", "-f", default=10, help="Number of large files to show.")
@click.option("--min-size", default=100, help="Minimum file size in MB for large files.")
@click.option("--no-history", is_flag=True, help="Don't save this scan to history.")
@click.option("--no-trend", is_flag=True, help="Don't show trend comparison.")
def scan_cmd(
    path: str,
    depth: int,
    top: int,
    files: int,
    min_size: int,
    no_history: bool,
    no_trend: bool,
) -> None:
    """Scan disk usage and show results."""
    expanded = os.path.expanduser(path)
    if not os.path.isdir(expanded):
        console.print(f"[red]Error:[/red] {path} is not a directory")
        raise SystemExit(1)

    with console.status("[bold blue]Scanning...[/bold blue]"):
        result = scanner.scan(
            root=path,
            depth=depth,
            top_n=top,
            file_count=files,
            min_file_size_mb=min_size,
        )

    comparison = None
    if not no_history:
        db.save_scan(result)
        if not no_trend:
            previous = db.get_previous_scan(expanded)
            if previous:
                comparison = db.compare_scans(result, previous)

    display.show_full_scan(result, comparison)


@main.command("history")
@click.argument("root_path", default="")
@click.option("--limit", "-n", default=20, help="Max number of scans to show.")
def history_cmd(root_path: str, limit: int) -> None:
    """Show past scan history."""
    resolved = os.path.expanduser(root_path) if root_path else None
    scans = db.get_scan_history(resolved, limit=limit)
    console.print()
    display.show_history(scans)
    console.print()


@main.command("show")
@click.argument("scan_id", type=int)
def show_cmd(scan_id: int) -> None:
    """Show the full report for a past scan by ID."""
    result = db.get_scan_by_id(scan_id)
    if not result:
        console.print(f"[yellow]No scan found with ID {scan_id}.[/yellow]")
        raise SystemExit(1)

    display.show_full_scan(result)


@main.command("compare")
@click.argument("root_path", default="~")
def compare_cmd(root_path: str) -> None:
    """Compare the two most recent scans for a path."""
    expanded = os.path.expanduser(root_path)

    latest = db.get_latest_scan(expanded)
    if not latest:
        console.print(f"[yellow]No scans found for {root_path}[/yellow]")
        raise SystemExit(1)

    previous = db.get_previous_scan(expanded)
    if not previous:
        console.print(f"[yellow]Only one scan found for {root_path} — need at least two to compare.[/yellow]")
        raise SystemExit(1)

    comparison = db.compare_scans(latest, previous)

    console.print()
    console.print(
        f"[bold]Comparing:[/bold] "
        f"{previous.timestamp.strftime('%Y-%m-%d %H:%M')} → "
        f"{latest.timestamp.strftime('%Y-%m-%d %H:%M')}"
    )
    console.print()
    display.show_trends(comparison)
    console.print()


@main.command("prune")
@click.option("--keep", "-k", default=10, help="Number of recent scans to keep per path.")
def prune_cmd(keep: int) -> None:
    """Clean old scan data."""
    deleted = db.prune_old_scans(keep=keep)
    if deleted:
        console.print(f"[green]Pruned {deleted} old scan(s).[/green]")
    else:
        console.print("[dim]Nothing to prune.[/dim]")


@main.command("docker")
def docker_cmd() -> None:
    """Show Docker disk usage analysis."""
    if not docker.is_docker_available():
        console.print("[red]Error:[/red] Docker CLI not found. Is Docker installed?")
        raise SystemExit(1)

    with console.status("[bold blue]Scanning Docker...[/bold blue]"):
        report = docker.scan_docker()

    if report is None:
        console.print(
            "[red]Error:[/red] Could not read Docker disk usage. "
            "Is the Docker daemon running?"
        )
        raise SystemExit(1)

    display.show_docker_report(report)


@main.command("ask")
@click.argument("query")
@click.option("--scan-id", type=int, default=None, help="Use a specific scan by ID.")
@click.option("--codex", is_flag=True, help="Use Codex instead of Claude.")
def ask_cmd(query: str, scan_id: int | None, codex: bool) -> None:
    """Ask Claude or Codex a question about your disk usage."""
    tool = "codex" if codex else "claude"
    bin_path = shutil.which(tool)
    if not bin_path:
        console.print(f"[red]Error:[/red] {tool} CLI not found. Install it first.")
        raise SystemExit(1)

    # Load the scan
    if scan_id:
        result = db.get_scan_by_id(scan_id)
        if not result:
            console.print(f"[yellow]No scan found with ID {scan_id}.[/yellow]")
            raise SystemExit(1)
    else:
        # Use the most recent scan across all root paths
        scans = db.get_scan_history(limit=1)
        if not scans:
            console.print("[yellow]No scans found. Run `dusk scan` first.[/yellow]")
            raise SystemExit(1)
        result = scans[0]

    scan_text = display.format_scan_text(result)
    prompt = f"Here is a macOS disk usage report:\n\n{scan_text}"

    # Auto-include Docker data when available
    if docker.is_docker_available():
        docker_report = docker.scan_docker()
        if docker_report:
            prompt += f"\n\n{display.format_docker_text(docker_report)}"

    prompt += f"\n\nQuestion: {query}"

    console.print(f"[dim]Using scan #{result.scan_id} ({result.timestamp.strftime('%Y-%m-%d %H:%M')})[/dim]")
    console.print(f"[dim]Asking {tool}...[/dim]\n")

    if codex:
        cmd = [bin_path, "-p", prompt]
    else:
        cmd = [
            bin_path,
            "--allowedTools", "WebSearch", "WebFetch",
            "--tools", "WebSearch,WebFetch",
            "-p", prompt,
        ]
    subprocess.run(cmd)
