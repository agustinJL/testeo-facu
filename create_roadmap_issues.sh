#!/usr/bin/env bash
set -euo pipefail

REPO="guzzipa/guzzito-analyst"

# Aseguramos labels útiles (si ya existen, ignora el error)
gh label create "feature"   -R "$REPO" --color C2E0C6 --description "New feature"   2>/dev/null || true
gh label create "enhancement" -R "$REPO" --color C5DEF5 --description "Improvement" 2>/dev/null || true
gh label create "question-refinement" -R "$REPO" --color F9D0C4 --description "Refined business questions" 2>/dev/null || true
gh label create "MVP" -R "$REPO" --color FEF2C0 --description "Minimum viable improvement" 2>/dev/null || true

create_issue () {
  local title="$1"
  local body="$2"
  local labels="$3"
  gh issue create -R "$REPO" -t "$title" -b "$body" --label "$labels"
}

create_issue "Refinamiento de preguntas (MVP)" "$(cat <<'EOF'
Antes de generar SQL, detectar ambigüedades y proponer reformulaciones.
- Desambiguar métricas (revenue vs órdenes vs ticket promedio)
- Aclarar periodos (últimos 6 meses vs mensual)
- NO ejecutar SQL todavía; devolver pregunta refinada
Salida: pregunta_original, pregunta_refinada
EOF
)" "feature,question-refinement,MVP"

create_issue "Historial extendido (original + refinada + ejecutada)" "$(cat <<'EOF'
Persistir en cada interacción:
- pregunta_original
- pregunta_refinada
- pregunta_ejecutada (con SQL final)
- explicación del modelo y notas
Mostrarlo en Storytelling y export Markdown.
EOF
)" "enhancement,MVP"

create_issue "Catálogo de preguntas frecuentes (inspiración)" "$(cat <<'EOF'
Agregar menú con 5–10 preguntas típicas por dominio:
- Ventas por categoría/mes, Top productos por revenue, Cohortes, Churn, % por canal
Botón “Inspírame” que autocompleta prompts ejemplo editables.
EOF
)" "feature"

create_issue "Mini diálogo de aclaración (hasta 2 preguntas)" "$(cat <<'EOF'
Antes de ejecutar, el agente puede devolver 1–2 preguntas para desambiguar:
- ¿Revenue o cantidad de órdenes?
- ¿Por mes o acumulado?
Luego de aclarar, generar SQL final.
EOF
)" "feature"

create_issue "Detección de sesgos comunes" "$(cat <<'EOF'
Reglas simples:
- Periodo demasiado corto -> sugerir ampliar rango
- Absolutos -> sugerir proporciones (% sobre total)
- Un solo segmento -> sugerir comparación
Devolver advertencias no bloqueantes.
EOF
)" "enhancement"

create_issue "Explicación NL + Next steps" "$(cat <<'EOF'
Además de la tabla/gráfico:
- “Esto responde a tu pregunta inicial…”
- Sugerir próximos pasos: otra métrica, otro corte, comparaciones.
Mostrar en el panel de resultado.
EOF
)" "enhancement"

create_issue "Recomendador de insights proactivo" "$(cat <<'EOF'
Post-query: detectar variaciones relevantes y outliers.
Ej: “La categoría Beauty cayó 10% vs mes anterior.”
Thresholds configurables.
EOF
)" "feature"

create_issue "Personalización por dominio" "$(cat <<'EOF'
Bundles de preguntas sugeridas/plantillas por:
- Marketing (CAC, funnel, ROAS)
- Producto (engagement, churn)
- Fraude (alertas, patrones)
EOF
)" "feature"

create_issue "Storytelling automático multi-turn (reporte)" "$(cat <<'EOF'
A partir de varias consultas, generar un mini informe:
- Pregunta → SQL → Resultado → Explicación → Next steps
Exportar a Markdown / PDF / Slides.
EOF
)" "feature"
