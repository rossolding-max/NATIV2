"""``nativ test smoke {db,redis,minio,langfuse,llm,vendors}``.

Pings each service to confirm it's reachable. Works against the running
local stack (docker-compose) — call ``just up`` first.
"""

from __future__ import annotations

import asyncio

import typer

smoke_app = typer.Typer()


@smoke_app.command()
def db() -> None:
    """Ping Postgres + Redis + MinIO."""

    async def _check() -> None:
        # Imports underscored funcs (private to app.main) — CLI is a permitted
        # internal caller per app/cli's purpose.
        from app.main import (
            _ping_minio,  # pyright: ignore[reportPrivateUsage]
            _ping_postgres,  # pyright: ignore[reportPrivateUsage]
            _ping_redis,  # pyright: ignore[reportPrivateUsage]
        )

        pg = await _ping_postgres()
        rd = await _ping_redis()
        mi = await _ping_minio()
        typer.echo(f"Postgres: {pg}")
        typer.echo(f"Redis:    {rd}")
        typer.echo(f"MinIO:    {mi}")
        if any(s != "ok" for s in (pg, rd, mi)):
            raise typer.Exit(code=1)

    asyncio.run(_check())


@smoke_app.command()
def llm() -> None:
    """Ping Anthropic API via ``messages.count_tokens`` (cheapest read endpoint)."""

    async def _check() -> None:
        from app.agents.llm_client import get_async_anthropic

        client = get_async_anthropic()
        try:
            # count_tokens is the cheapest endpoint; $0 cost.
            await client.messages.count_tokens(
                model="claude-opus-4-7",
                messages=[{"role": "user", "content": "ping"}],
            )
            typer.echo("Anthropic: ok")
        except Exception as exc:
            typer.echo(f"Anthropic: down ({exc})")
            raise typer.Exit(code=1) from exc

    asyncio.run(_check())


@smoke_app.command()
def vendors() -> None:
    """Ping every vendor M2+ knows about. M2 = Anthropic only; M3 adds more."""
    typer.echo("Smoking vendors...")
    llm()
    typer.echo("  (Smartlead, Exa, Apollo, Meta, TikTok land per-milestone in M3 +.)")
