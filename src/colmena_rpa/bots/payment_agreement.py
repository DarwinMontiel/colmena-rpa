"""Bot: registra acuerdos de pago de cartera en el portal web (automatización con Playwright).

Flujo: iniciar sesión → buscar cliente por documento → abrir formulario de acuerdo →
diligenciar cuotas/valor/fecha → guardar → leer número de confirmación.

Idempotencia: se envía ``referencia`` = ``task_id``. Si la tarea se reprocesa (reentrega
de RabbitMQ, reintento), el portal devuelve la misma confirmación en vez de duplicar el acuerdo.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from pydantic import BaseModel, Field, ValidationError

from colmena_rpa.bots.base import Bot, BotContext, BotResult
from colmena_rpa.config import Settings
from colmena_rpa.domain.errors import BusinessRuleError, TransientError
from colmena_rpa.logging import get_logger

log = get_logger(__name__)


class AgreementRequest(BaseModel):
    documento: str = Field(pattern=r"^\d{5,12}$")
    cuotas: int = Field(ge=1, le=36)
    valor_cuota: float = Field(gt=0)
    fecha_primer_pago: date
    referencia: str | None = Field(default=None, max_length=64)


class PaymentAgreementBot(Bot):
    name = "payment_agreement"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base = settings.portal_url.rstrip("/")
        self._artifacts = Path(settings.artifacts_dir)
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    def setup(self) -> None:
        self._artifacts.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self._settings.headless)
        self._context = self._browser.new_context(locale="es-CO")
        self._context.set_default_timeout(self._settings.browser_timeout_ms)
        log.info("bot.setup", bot=self.name, portal=self._base)

    def teardown(self) -> None:
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def run(self, ctx: BotContext, payload: dict[str, Any]) -> BotResult:
        try:
            request = AgreementRequest.model_validate(payload)
        except ValidationError as exc:
            fields = ", ".join(".".join(map(str, e["loc"])) for e in exc.errors())
            raise BusinessRuleError(f"payload inválido en: {fields}") from exc

        reference = request.referencia or str(ctx.task_id)
        assert self._context is not None, "setup() no fue llamado"
        page = self._context.new_page()
        try:
            self._ensure_session(page)
            page.goto(f"{self._base}/clientes?documento={request.documento}")
            if page.locator("#not-found").count():
                raise BusinessRuleError(f"cliente {request.documento} no existe en el portal")

            page.click("#registrar-acuerdo")
            page.fill("#cuotas", str(request.cuotas))
            page.fill("#valor_cuota", f"{request.valor_cuota:.2f}")
            page.fill("#fecha_primer_pago", request.fecha_primer_pago.isoformat())
            page.fill("#referencia", reference)
            page.click("#guardar")
            page.wait_for_selector("#confirmation, .error-negocio, .error-sistema")

            if page.locator(".error-negocio").count():
                raise BusinessRuleError(page.locator(".error-negocio").inner_text().strip())
            if page.locator(".error-sistema").count():
                raise TransientError(page.locator(".error-sistema").inner_text().strip())

            confirmation = page.locator("#confirmation").inner_text().strip()
            log.info(
                "bot.agreement_registered", task_id=str(ctx.task_id), confirmation=confirmation
            )
            return BotResult({"confirmation": confirmation, "reference": reference})
        except PlaywrightTimeoutError as exc:
            self._evidence(page, ctx)
            raise TransientError(f"timeout en el portal: {exc.message.splitlines()[0]}") from exc
        except (BusinessRuleError, TransientError):
            self._evidence(page, ctx)
            raise
        finally:
            page.close()

    def _ensure_session(self, page: Page) -> None:
        page.goto(f"{self._base}/clientes")
        if not page.url.endswith("/login"):
            return
        page.fill("#username", self._settings.portal_user)
        page.fill("#password", self._settings.portal_password)
        page.click("#submit")
        page.wait_for_load_state()
        if page.locator(".error-login").count():
            # Error de sistema: se corrige la credencial y la tarea se reprocesa.
            raise TransientError("credenciales del portal rechazadas")

    def _evidence(self, page: Page, ctx: BotContext) -> None:
        """Guarda una captura como evidencia del fallo (práctica estándar en RPA)."""
        path = self._artifacts / f"{ctx.task_id}-attempt{ctx.attempt}.png"
        try:
            page.screenshot(path=str(path), full_page=True)
            log.info("bot.evidence_saved", path=str(path))
        except Exception:
            log.warning("bot.evidence_failed", task_id=str(ctx.task_id))
