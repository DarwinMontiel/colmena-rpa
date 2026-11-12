"""CLI ``colmena-carga``: registra y encola lotes de tareas desde archivos CSV."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import typer

from colmena_rpa.config import get_settings
from colmena_rpa.logging import configure_logging, get_logger
from colmena_rpa.messaging.publisher import open_publisher
from colmena_rpa.persistence import TaskRepository, create_db_engine
from colmena_rpa.producer.loader import read_tasks

app = typer.Typer(
    help="Carga lotes de tareas para los bots obreros de Colmena RPA.",
    no_args_is_help=True,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


@app.command("encolar")
def encolar(
    archivo: Path = typer.Option(
        ...,
        "--archivo",
        "--file",
        exists=True,
        readable=True,
        help="CSV con una tarea por fila.",
    ),
    proceso: str = typer.Option(
        "payment_agreement",
        "--proceso",
        "--process",
        help="Proceso (bot) que ejecutará las tareas.",
    ),
    lote: str | None = typer.Option(
        None, "--lote", "--batch-id", help="Identificador del lote (correlation_id)."
    ),
    simular: bool = typer.Option(
        False, "--simular", "--dry-run", help="Valida el archivo sin registrar ni publicar nada."
    ),
) -> None:
    """Registra cada fila como tarea PENDING en PostgreSQL y la publica en RabbitMQ."""
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    log = get_logger("colmena_rpa.producer")
    batch = lote or f"{archivo.stem}-{datetime.now(UTC):%Y%m%dT%H%M%S}"
    messages = list(read_tasks(archivo, proceso, batch))

    if simular:
        typer.echo(f"{len(messages)} tareas válidas en {archivo} (simulación: nada publicado)")
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


# Alias de compatibilidad con la v1: ``rpa-producer enqueue --file ...``.
app.command("enqueue", hidden=True)(encolar)


if __name__ == "__main__":
    app()
