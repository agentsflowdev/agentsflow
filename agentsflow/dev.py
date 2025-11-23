import asyncio
import os
import signal
import sys
from pathlib import Path
from typing import Any, NoReturn

import click
from dotenv import dotenv_values
from rich.console import Console

console = Console()

# Global list to keep track of running processes for cleanup
PROCESSES: list[asyncio.subprocess.Process] = []
SUPPORTED_TRANSPORTS = ("stdio", "http", "sse", "streamable-http")


def _load_dotenv(dotenv_path: Path = Path(".env")) -> dict[str, str]:
    """Parse .env without mutating os.environ."""
    if not dotenv_path.exists():
        return {}

    # Use python-dotenv to parse while avoiding automatic os.environ mutation.
    parsed = dotenv_values(dotenv_path)
    # Filter out None values (unset lines) and coerce to str for subprocess env.
    return {k: str(v) for k, v in parsed.items() if v is not None}


def build_process_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Return a safe env for subprocesses.

    - Drop virtualenv markers that confuse `uv` inside worktrees
      (VIRTUAL_ENV often points at the parent repo's .venv).
    - Prime the environment with entries from .env so local dev
      tooling (Temporal, API keys, etc.) stays consistent.
    """
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    env.pop("UV_ACTIVE_VIRTUALENV", None)
    env.update(_load_dotenv())
    if extra:
        env.update(extra)
    return env


async def stream_output(process: asyncio.subprocess.Process, name: str, color: str) -> None:
    """Stream output from a process to stdout with a prefixed tag."""
    if process.stdout is None:
        return

    try:
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            decoded_line = line.decode("utf-8", errors="replace").rstrip()
            if decoded_line:
                console.print(f"[{color}]{name}[/{color}] | {decoded_line}")
    except Exception as e:
        console.print(f"[red]Error reading stream from {name}: {e}[/red]")


async def start_service(name: str, command: list[str], color: str, env: dict[str, str] | None = None) -> None:
    """Start a service and stream its output."""
    console.print(f"[bold {color}]Starting {name}...[/bold {color}]")

    effective_env = env or build_process_env()

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=effective_env,
            preexec_fn=os.setsid,  # Create a new process group
        )
        PROCESSES.append(process)

        # Start streaming output
        await stream_output(process, name, color)

        # If we get here, the process has exited
        code = await process.wait()
        if code != 0:
            console.print(f"[bold red]{name} exited with code {code}[/bold red]")
        else:
            console.print(f"[bold green]{name} exited cleanly[/bold green]")

    except Exception as e:
        console.print(f"[bold red]Failed to start {name}: {e}[/bold red]")


async def run_stack(transport: str) -> None:
    """Run the full stack."""
    # Check if Temporal is running
    temporal_running = False
    try:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("localhost", 7233)) == 0:
                temporal_running = True
                console.print("[green]Temporal is already running.[/green]")
    except Exception:
        pass

    tasks = []

    # Start Temporal if needed
    if not temporal_running:
        tasks.append(start_service("Temporal", ["temporal", "server", "start-dev", "--ip", "0.0.0.0"], "blue"))

    # Start Worker
    tasks.append(start_service("Worker", [sys.executable, "-m", "agentsflow.worker"], "yellow"))

    # Start MCP Server
    tasks.append(
        start_service(
            "MCP",
            [
                "uv",
                "run",
                "fastmcp",
                "run",
                "agentsflow/mcp_server.py",
                "--transport",
                transport,
            ],
            "magenta",
        )
    )

    # Wait for all services
    await asyncio.gather(*tasks)


def handle_signal(sig: int, frame: Any) -> NoReturn:
    """Handle interrupt signals."""
    console.print("\n[bold red]Stopping all services...[/bold red]")
    for p in PROCESSES:
        try:
            if p.returncode is None:
                # Kill the process group to ensure all children (like uv's subprocesses) die
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)
        except Exception:
            pass
    sys.exit(0)


@click.command()
@click.option(
    "--transport",
    type=click.Choice(SUPPORTED_TRANSPORTS, case_sensitive=False),
    default="stdio",
    show_default=True,
    help="Transport passed to fastmcp run when launching the MCP server.",
)
def main(transport: str) -> None:
    """Start the AgentsFlow local development stack."""
    # Register signal handlers
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    console.print(
        "[bold blue]AgentsFlow Local Dev Launcher[/bold blue]\n"
        f"Streaming logs from all services using MCP transport '{transport}'. Press Ctrl+C to stop.\n"
    )

    try:
        asyncio.run(run_stack(transport=transport))
    except KeyboardInterrupt:
        handle_signal(signal.SIGINT, None)


if __name__ == "__main__":
    main()
