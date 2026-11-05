# Política de seguridad

## Reportar una vulnerabilidad

No abras un issue público. Usa **Security → Report a vulnerability** en este repositorio
(GitHub Private Vulnerability Reporting). Recibirás respuesta en un máximo de 5 días hábiles.

## Prácticas del proyecto

- Secretos solo por variables de entorno; `.env` está en `.gitignore`.
- Dependabot mantiene actualizadas las dependencias de Python, Docker y GitHub Actions.
- Ruff ejecuta las reglas de seguridad de Bandit (`S`) en cada commit y en CI.
- Las imágenes corren con un usuario sin privilegios.
