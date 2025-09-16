# Changelog

## [0.3.0] - 2025-09-15
### Added
- **Preguntas sugeridas (business-friendly)** con toggle en el sidebar.
- **Triggers** para usar una sugerencia en:
  - Refinamiento iterativo (abre el panel refinado automáticamente).
  - Ejecución directa (consulta y muestra resultados).
- **Spinners** y manejo robusto de errores en sugerencias.
- **Keys estables** en tablas y descargas (usa `ts` cuando está disponible).
- **Hardening UX**: limpieza suave de triggers, fallbacks si el LLM devuelve algo inesperado.

### Changed
- Mejor copy en secciones y mensajes informativos.

### Fixed
- Caso donde al usar botones de sugerencias se re-renderizaba el bloque sin ejecutar la acción seleccionada.
