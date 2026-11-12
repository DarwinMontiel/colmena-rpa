# Guía de contribución

## Flujo de trabajo

1. Crear una rama desde `main`: `feat/<tema>`, `fix/<tema>` o `docs/<tema>`.
2. Instalar el entorno: `make install` (instala dependencias, Chromium y los *hooks* de pre-commit).
3. Hacer commits pequeños con [Conventional Commits](https://www.conventionalcommits.org/es/):
   `feat(worker): …`, `fix(monitor): …`, `docs(adr): …`, `test: …`, `ci: …`.
4. Antes de abrir el PR: `make lint test e2e` en verde.
5. El PR debe explicar el **qué** y el **por qué**, y enlazar el issue.

## Estándares

- Tipado estricto (`mypy --strict`) y `ruff` sin advertencias.
- Toda regla de negocio nueva lleva prueba unitaria; todo endpoint nuevo, prueba de API.
- Las decisiones de arquitectura se documentan como ADR en `docs/adr/`.
- Cambios de esquema solo mediante migraciones Alembic compatibles hacia atrás.

## Agregar un bot nuevo

1. Crear `src/colmena_rpa/bots/<proceso>.py` con una clase que herede de `Bot`.
2. Traducir errores conocidos a `BusinessRuleError` o `TransientError`.
3. Garantizar idempotencia respecto a `ctx.task_id`.
4. Registrarlo en `bots/catalog.py` y agregarlo a `RPA_PROCESSES` de la obrera que lo ejecutará.
