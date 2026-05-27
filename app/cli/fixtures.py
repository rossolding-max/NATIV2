"""``nativ test fixtures {status,load synthetic,load real}``.

``status`` queries Postgres for row counts per domain table.
``load synthetic`` runs ``just seed`` (M1 brand import).
``load real`` defers to M4 (full agency setup).
"""

from __future__ import annotations

import subprocess

import typer

fixtures_app = typer.Typer()


@fixtures_app.command()
def status() -> None:
    """Print row counts for each domain table."""
    import asyncio

    async def _query() -> None:
        from sqlalchemy import func, select

        from app.db.session import async_session_factory
        from app.models.sqla import (
            AgencyProfile,
            Brand,
            BrandContact,
            BrandDeal,
            Deal,
            Memo,
            Talent,
        )

        tables = {
            "agency_profile": AgencyProfile,
            "brand": Brand,
            "talent": Talent,
            "brand_contact": BrandContact,
            "brand_deal": BrandDeal,
            "deal": Deal,
            "memo": Memo,
        }
        async with async_session_factory() as session:
            for name, model in tables.items():
                stmt = select(func.count()).select_from(model)
                result = await session.execute(stmt)
                typer.echo(f"  {name:>15}: {result.scalar_one()}")

    asyncio.run(_query())


@fixtures_app.command("load")
def load_(
    target: str = typer.Argument(..., help="Fixture type: synthetic | real"),
) -> None:
    """Load a fixture into the running stack."""
    if target == "synthetic":
        typer.echo("Loading synthetic fixture (brand_industry_map; 290 brands)...")
        # ruff S603/S607: partial executable path is intentional (uv on PATH).
        result = subprocess.run(
            ["uv", "run", "python", "scripts/import_brand_industry_map.py"],  # noqa: S607
            check=False,
        )
        raise typer.Exit(code=result.returncode)
    if target == "real":
        typer.echo("`nativ test fixtures load real` lands in M4 with full agency setup.")
        raise typer.Exit(code=0)
    typer.echo(f"Unknown fixture target: {target}. Use `synthetic` or `real`.")
    raise typer.Exit(code=2)
