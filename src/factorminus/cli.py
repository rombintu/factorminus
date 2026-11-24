"""CLI `fm`."""

import typer

app = typer.Typer(
    no_args_is_help=True, add_completion=False, help="Фактор-минус: данные и проверки"
)


@app.callback()
def main() -> None:
    """Фактор-минус."""
