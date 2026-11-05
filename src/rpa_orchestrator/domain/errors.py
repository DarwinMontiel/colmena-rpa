"""Clasificación de excepciones al estilo RPA (Business Exception vs System Exception).

- ``BusinessRuleError``: el dato o la regla de negocio impide completar la tarea
  (cliente inexistente, monto inválido). Reintentar no sirve: va directo a la DLQ.
- ``TransientError``: falla del sistema (timeout, portal caído, 503). Se reintenta con backoff.

Cualquier otra excepción no prevista se trata como transitoria: es preferible reintentar
y terminar en la DLQ con el error registrado que perder la tarea.
"""


class BotError(Exception):
    """Error base de un bot."""


class BusinessRuleError(BotError):
    """Error de negocio: no reintentable."""


class TransientError(BotError):
    """Error de sistema o de disponibilidad: reintentable."""


class UnknownProcessError(BusinessRuleError):
    """El mensaje pide un proceso que este worker no tiene registrado."""
