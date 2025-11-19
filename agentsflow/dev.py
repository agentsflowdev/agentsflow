import os
import signal
import subprocess
import sys
import time
from typing import Any, TextIO

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

PROCESSES: list[subprocess.Popen[Any]] = []


def cleanup(signum: int | None, frame: Any | None) -> None:
    console.print("\n[bold red]Stopping all services...[/bold red]")
    for p in PROCESSES:
        try:
            p.terminate()
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
        except Exception:
            pass
    sys.exit(0)


signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)


def is_temporal_running() -> bool:
    """Check if Temporal is running by attempting to connect to the port."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", 7233)) == 0


def start_temporal(log_file: TextIO) -> subprocess.Popen[Any] | None:
    """Start Temporal server if not running."""
    if is_temporal_running():
        console.print("[green]Temporal is already running.[/green]")
        return None

    console.print("[yellow]Starting Temporal server...[/yellow]")
    try:
        # Try to find temporal CLI
        p = subprocess.Popen(
            ["temporal", "server", "start-dev"],
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        PROCESSES.append(p)

        # Wait for it to be ready
        for _ in range(30):
            if is_temporal_running():
                console.print("[green]Temporal started successfully.[/green]")
                return p
            time.sleep(1)

        console.print("[red]Temporal failed to start within 30 seconds.[/red]")
        return p
    except FileNotFoundError:
        console.print(
            "[bold red]Error:[/bold red] 'temporal' CLI not found. " "Please install it or start Temporal manually."
        )
        sys.exit(1)


def start_worker(log_file: TextIO) -> subprocess.Popen[Any]:
    """Start the AgentsFlow worker."""
    console.print("[yellow]Starting Worker...[/yellow]")
    env = os.environ.copy()
    p = subprocess.Popen(
        [sys.executable, "-m", "agentsflow.worker"],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        env=env,
    )
    PROCESSES.append(p)
    return p


def start_mcp_server(log_file: TextIO) -> subprocess.Popen[Any]:
    """Start the MCP server."""
    console.print("[yellow]Starting MCP Server...[/yellow]")
    env = os.environ.copy()
    # Use uv to run fastmcp
    p = subprocess.Popen(
        ["uv", "run", "fastmcp", "run", "agentsflow/mcp_server.py"],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        env=env,
    )
    PROCESSES.append(p)
    return p


def tail_logs(files: list[str]) -> None:
    """Simple tail implementation to show output from multiple files."""
    # This is a simplified version; for a real robust solution we might want
    # to use asyncio to read streams directly.
    # For now, we just let the user know where logs are.
    pass


@click.command()
def main() -> None:
    """Start the AgentsFlow local development stack."""
    console.print(
        Panel.fit(
            "[bold blue]AgentsFlow Local Dev Launcher[/bold blue]\n" "Starting Temporal, Worker, and MCP Server...",
            border_style="blue",
        )
    )

    os.makedirs("logs", exist_ok=True)

    with open("logs/temporal.log", "w") as temporal_log, open("logs/worker.log", "w") as worker_log, open(
        "logs/mcp.log", "w"
    ) as mcp_log:
        temporal_proc = start_temporal(temporal_log)
        worker_proc = start_worker(worker_log)
        mcp_proc = start_mcp_server(mcp_log)

        table = Table(title="Service Status")
        table.add_column("Service", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Log File", style="magenta")

        table.add_row("Temporal", "Running" if is_temporal_running() else "Started", "logs/temporal.log")
        table.add_row("Worker", "Started", "logs/worker.log")
        table.add_row("MCP Server", "Started", "logs/mcp.log")

        console.print(table)
        console.print("\n[bold]Press Ctrl+C to stop all services.[/bold]")

        # Keep running until interrupted
        try:
            while True:
                time.sleep(1)
                # Check if processes are still alive
                if temporal_proc and temporal_proc.poll() is not None:
                    console.print("[red]Temporal stopped unexpectedly![/red]")
                    cleanup(None, None)
                if worker_proc.poll() is not None:
                    console.print("[red]Worker stopped unexpectedly![/red]")
                    cleanup(None, None)
                if mcp_proc.poll() is not None:
                    console.print("[red]MCP Server stopped unexpectedly![/red]")
                    cleanup(None, None)
        except KeyboardInterrupt:
            cleanup(None, None)


if __name__ == "__main__":
    main()
