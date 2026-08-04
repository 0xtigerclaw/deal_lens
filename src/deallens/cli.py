"""DealLens CLI: screen | web | demo | eval."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv
from rich.console import Console

from .config import PACKAGE_ROOT, load_jurisdiction, load_policy

load_dotenv()

app = typer.Typer(add_completion=False, help="10-minute M&A red-flag screen on Tavily.")
console = Console()


@app.command()
def screen(
    company: Annotated[str, typer.Option(help="Legal or trading name")],
    domain: Annotated[str, typer.Option(help="Company website domain")],
    company_id: Annotated[
        str, typer.Option(help="Legal entity identifier, e.g. UK company number")
    ],
    jurisdiction: Annotated[str, typer.Option(help="Jurisdiction pack, e.g. UK")] = "UK",
    policy: Annotated[str | None, typer.Option(help="Severity policy YAML")] = None,
    out: Annotated[Path, typer.Option(help="Output directory")] = Path("reports"),
) -> None:
    """Run a live screen against one acquisition target."""
    if not os.getenv("TAVILY_API_KEY"):
        console.print("[bold red]Missing TAVILY_API_KEY[/bold red] — create one at https://app.tavily.com and add it to .env")
        raise typer.Exit(1)
    if not os.getenv("NEBIUS_API_KEY"):
        console.print(
            "[bold red]Missing NEBIUS_API_KEY[/bold red] — create one at "
            "https://tokenfactory.nebius.com and add it to .env"
        )
        raise typer.Exit(1)

    from .llm import LLM
    from .memo import print_summary, write_outputs
    from .models import UsageLedger
    from .pipeline import run_screen
    from .tavily_client import Tavily

    pack = load_jurisdiction(jurisdiction)
    severity_policy = load_policy(policy)
    ledger = UsageLedger()

    try:
        with console.status(f"Screening {company} ({jurisdiction.upper()})..."):
            result = run_screen(
                company=company,
                domain=domain,
                company_id=company_id,
                jurisdiction_pack=pack,
                policy=severity_policy,
                tavily=Tavily(ledger=ledger),
                llm=LLM(ledger),
            )
    except KeyboardInterrupt:
        console.print("\n[bold red]Screen interrupted.[/bold red]")
        raise typer.Exit(130) from None
    except Exception as exc:
        console.print(f"\n[bold red]Screen failed:[/bold red] {exc}")
        console.print(
            "[dim]No memo was produced; incomplete observations are never "
            "reported as a clean screen.[/dim]"
        )
        raise typer.Exit(1) from None

    memo_path, json_path = write_outputs(result, out)
    print_summary(result, memo_path, json_path)


@app.command()
def demo() -> None:
    """Run the fixture screen: no API keys, no network, no credits.

    Quote validation and the evidence gate run live on five canonical
    bundles — including a paraphrased quote that gets discarded and an
    extraction failure that surfaces as UNRESOLVED rather than verified."""
    from .demo import run_demo
    from .memo import print_summary, write_outputs

    result = run_demo(PACKAGE_ROOT)
    memo_path, json_path = write_outputs(result, PACKAGE_ROOT / "reports")
    print_summary(result, memo_path, json_path)
    console.print("[dim]Fixture run: 0 Tavily credits spent. See fixtures/demo_screen.json.[/dim]")


@app.command()
def web(
    host: Annotated[str, typer.Option(help="Interface bind address")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Interface port")] = 8000,
    reload: Annotated[bool, typer.Option(help="Reload on source changes")] = False,
) -> None:
    """Launch the DealLens analyst interface."""
    import uvicorn

    console.print(
        f"[bold]DealLens UI[/bold] running at [link=http://{host}:{port}]"
        f"http://{host}:{port}[/link]"
    )
    uvicorn.run("deallens.web:app", host=host, port=port, reload=reload)


@app.command("eval")
def eval_cmd(
    json_out: Annotated[
        Path | None, typer.Option(help="Optional path for a machine-readable report")
    ] = None,
) -> None:
    """Run all offline safety evals and print reproducible metrics."""
    import json

    from .evalrun import (
        evaluation_summary,
        print_report,
        run_entity_eval,
        run_gate_eval,
        run_governance_eval,
    )

    pack = load_jurisdiction("uk")
    gate = run_gate_eval(PACKAGE_ROOT / "fixtures" / "eval_cases.json", pack)
    entity = run_entity_eval(
        PACKAGE_ROOT / "fixtures" / "entity_eval_cases.json", pack
    )
    governance = run_governance_eval(
        PACKAGE_ROOT / "fixtures" / "governance_eval_cases.json", pack
    )
    ok = print_report(gate, entity, governance)
    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(
            json.dumps(evaluation_summary(gate, entity, governance), indent=2) + "\n"
        )
        console.print(f"[dim]Machine-readable report: {json_out}[/dim]")
    raise typer.Exit(0 if ok else 1)


if __name__ == "__main__":
    app()
