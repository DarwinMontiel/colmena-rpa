"""CLI ``rpa-producer``: encola tareas desde CSV y administra la base de datos."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import typer

from rpa_orchestrator.config import get_settings
from rpa_orchestrator.logging import configure_logging, get_logger
from rpa_orchestrator.messaging.publisher import open_publisher
from rpa_orchestrator.persistence import TaskRepository, create_db_engine
from rpa_orchestrator.producer.loader import read_tasks

app = typer.Typer(help="Productor de tareas RPA.", no_args_is_help=True)


@app.command()
def enqueue(
    file: Path = typer.Option(..., exists=True, readable=True, help="CSV con una tarea por fila."),
    process: str = typer.Option(
        "payment_agreement", help="Proceso (bot) que ejecutará las tareas."
    ),
    batch_id: str | None = typer.Option(None, help="Identificador del lote (correlation_id)."),
    dry_run: bool = typer.Option(False, help="Valida el archivo sin publicar."),
) -> None:
    """Registra cada fila como tarea PENDING en PostgreSQL y la publica en RabbitMQ."""
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    log = get_logger("rpa_orchestrator.producer")
    batch = batch_id or f"{file.stem}-{datetime.now(UTC):%Y%m%dT%H%M%S}"
    messages = list(read_tasks(file, process, batch))

    if dry_run:
        typer.echo(f"{len(messages)} tareas válidas en {file} (dry-run, nada publicado)")
        raise typer.Exit()

    repo = TaskRepository(create_db_engine(settings.database_url))
    published = skipped = 0
    with open_publisher(
        settings.amqp_url, settings.exchange, tuple(settings.retry_delays_seconds)
    ) as publisher:
        for message in messages:
            if repo.register_pending(message):
                publisher.publish(message)
                published += 1
            else:
                skipped += 1
    log.info("producer.batch_enqueued", batch=batch, published=published, duplicates=skipped)
    typer.echo(f"Lote {batch}: {published} publicadas, {skipped} duplicadas omitidas")


if __name__ == "__main__":
    app()
