"""``nativ`` CLI entry point — typer app exposing the ``nativ test`` command tree.

Per ``docs/test_plan.md`` § 4.2. Subcommands light up per milestone:

- ``nativ test smoke {db,redis,minio,langfuse,llm,vendors}`` — works at M2.
- ``nativ test eval --pack X --record|--real`` — cassette eval (M2).
- ``nativ test fixtures status`` — works at M2 (queries Postgres).
- ``nativ test fixtures load synthetic`` — calls ``just seed`` (M1 brand import).
- ``nativ test phase`` / ``e2e`` / ``report`` — print "lands in M<X>" + exit 0.

Wired via ``pyproject.toml`` ``[project.scripts] nativ = "app.cli.main:app"``.
"""

from __future__ import annotations

import typer

from app.cli.eval import eval_app
from app.cli.fixtures import fixtures_app
from app.cli.smoke import smoke_app

app = typer.Typer(
    name="nativ",
    help="NATIV2 dev + test CLI. See `nativ test --help` for the test command tree.",
    no_args_is_help=True,
)

test_app = typer.Typer(name="test", help="Test runner commands.", no_args_is_help=True)
app.add_typer(test_app, name="test")

test_app.add_typer(smoke_app, name="smoke", help="Smoke tests (service connectivity).")
test_app.add_typer(eval_app, name="eval", help="LLM eval suite (cassette-based).")
test_app.add_typer(fixtures_app, name="fixtures", help="Fixture loading + status.")


# ── Deferred subcommands ──────────────────────────────────────────────


@test_app.command()
def phase(
    phase_id: str = typer.Argument(..., help="Phase to walk through (e.g. '0', '4.5')."),
    auto: bool = typer.Option(False, "--auto", help="Non-interactive mode."),
) -> None:
    """Interactive phase walkthrough. Lands per-phase (M4+)."""
    _ = (phase_id, auto)
    typer.echo(
        "`nativ test phase <X>` lands per-phase as milestones M4-M16 ship.\n"
        "Check `docs/project_plan.md` for the milestone status."
    )


@test_app.command()
def e2e(
    pack: str | None = typer.Option(None, "--pack", help="Run e2e for a specific pack."),
) -> None:
    """End-to-end pipeline tests. First useful at M11 (discovery prep pack)."""
    _ = pack
    typer.echo("`nativ test e2e` lands at M11 (first AI pack milestone).")


@test_app.command()
def report() -> None:
    """Coverage + LLM-cost + perf report. Lands at M17 (production hardening)."""
    typer.echo("`nativ test report` lands at M17 (production hardening).")


if __name__ == "__main__":
    app()
