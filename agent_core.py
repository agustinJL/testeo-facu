import os
import json
import io
import uuid
import pathlib
import time
import pandas as pd
import matplotlib.pyplot as plt
from dotenv import load_dotenv
from openai import OpenAI
from tools_sql import get_schema, run_sql

# ========= Memoria (helpers) =========
SESS_DIR = pathlib.Path("./.session")
SESS_DIR.mkdir(exist_ok=True)


def _session_path(session_id: str):
    return SESS_DIR / f"{session_id}.json"


def load_session(session_id: str) -> list:
    p = _session_path(session_id)
    if p.exists():
        return json.loads(p.read_text())
    return []


def save_session(session_id: str, history: list):
    _session_path(session_id).write_text(
        json.dumps(history, ensure_ascii=False, indent=2))


def summarize_for_context(history: list, max_items: int = 4) -> str:
    """
    Devuelve últimas interacciones como bullets cortos:
    - Q: ...
    - SQL: ...
    - Insight: ...
    """
    if not history:
        return ""
    tail = history[-max_items:]
    bullets = []
    for h in tail:
        # compat: usa refinada si existe
        q = (h.get("question_refined") or h.get("question") or "")[:220]
        sql = (h.get("sql", "") or "").replace("\n", " ")[:220]
        insight = (h.get("plan", {}).get("explain", "") or "")[:240]
        bullets.append(f"- Q: {q}\n  SQL: {sql}\n  Insight: {insight}")
    return "\n".join(bullets)


# === Sugeridor de preguntas (business-friendly) ===
SUGGEST_SYSTEM = """Eres un analista de negocio senior.
Dado un ESQUEMA de base de datos y (opcional) un inicio de pregunta del usuario,
propón entre 3 y 6 preguntas útiles, claras y accionables.
Devuelve SOLO JSON con una lista bajo 'suggestions', donde cada item es:
- question: string (una pregunta lista para ejecutar/refinar)
- why: string (por qué es útil)
- tags: lista corta de etiquetas (p.ej., ["ventas","mensual"])

Evita jerga técnica, sé concreto y con foco en negocio.
"""


def suggest_questions(schema: dict, partial: str | None = None, k: int = 5) -> list[dict]:
    """
    Retorna una lista de sugerencias [{question, why, tags}, ...]
    """
    user_content = {
        "schema": schema,
        "partial": (partial or "").strip(),
        "k": max(3, min(int(k), 8)),
    }
    messages = [
        {"role": "system", "content": SUGGEST_SYSTEM},
        {"role": "user", "content": "Responde SOLO en JSON (json estricto)."},
        {"role": "user", "content": json.dumps(
            user_content, ensure_ascii=False)}
    ]
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        data = json.loads(resp.choices[0].message.content)
        suggestions = data.get("suggestions", []) or []
        # saneo mínimo
        out = []
        for s in suggestions:
            q = (s.get("question") or "").strip()  # <-- () faltaban
            if not q:
                continue
            out.append({
                "question": q,
                "why": (s.get("why") or "").strip(),
                "tags": s.get("tags") or [],
            })
        return out[:k]
    except Exception:
        # fallback simple si el modelo falla
        return [
            {"question": "ventas por categoría por mes", "why": "tendencia básica por mix",
                "tags": ["ventas", "categoría", "mensual"]},
            {"question": "top 10 productos por revenue",
                "why": "ranking de contribución", "tags": ["top", "producto", "revenue"]},
            {"question": "evolución mensual por país", "why": "comparar mercados",
                "tags": ["evolución", "país", "mensual"]},
        ][:k]


# --- Prompt corto para refinar preguntas ---
REFINE_SYSTEM = """Eres un PM/BI senior. Tu tarea es ayudar a un analista a
formular una pregunta clara, medible y libre de ambigüedades antes de generar SQL.
Debes devolver SOLO JSON válido, con estos campos:
- refined_question: string breve y precisa (sin sesgo).
- clarifications: lista[str] con preguntas de aclaración razonables (máx 3).
- assumptions: lista[str] con supuestos seguros si falta info (máx 3).
- confidence: float 0..1 (qué tan seguro estás de que ya es ejecutable).
"""


def refine_question_step(
    base_question: str,
    schema: dict,
    session_id: str,
    user_selected_clarifications: list[str] | None = None,
    user_edited_question: str | None = None,
) -> dict:
    """
    Un paso de refinamiento. Si el usuario eligió aclaraciones o editó la pregunta,
    el LLM las considera y devuelve una nueva sugerencia.
    """
    user_selected_clarifications = user_selected_clarifications or []
    effective_question = user_edited_question.strip(
    ) if user_edited_question else base_question

    guidance = {
        "base_question": base_question,
        "effective_question": effective_question,
        "user_selected_clarifications": user_selected_clarifications,
    }

    short_ctx = summarize_for_context(load_session(session_id))
    messages = [
        {"role": "system", "content": REFINE_SYSTEM +
            "\n\nContexto reciente:\n" + (short_ctx or "- (sin contexto)")},
        {"role": "user", "content": (
            "Refina de manera iterativa. Responde SOLO con un objeto JSON. "
            "Si el usuario agregó aclaraciones, incorpóralas en la versión refinada.\n\n"
            f"Esquema (JSON):\n{json.dumps(schema, ensure_ascii=False)}\n\n"
            f"Instrucciones de usuario (JSON):\n{json.dumps(guidance, ensure_ascii=False)}"
        )}
    ]

    resp = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        response_format={"type": "json_object"},
    )
    out = json.loads(resp.choices[0].message.content)
    out.setdefault("refined_question", effective_question)
    out.setdefault("clarifications", [])
    out.setdefault("assumptions", [])
    out.setdefault("confidence", 0.0)
    return out


def refine_question(user_question: str, schema: dict, session_id: str) -> dict:
    """
    Devuelve JSON: { refined_question, clarifications, assumptions, confidence }
    """
    short_ctx = summarize_for_context(load_session(session_id))
    messages = [
        {"role": "system", "content": REFINE_SYSTEM +
            "\n\nContexto reciente:\n" + (short_ctx or "- (sin contexto)")},
        {"role": "user", "content": (
            "Responde SOLO en JSON (json estricto). No incluyas texto fuera del objeto JSON.\n"
            "Esquema disponible (JSON):\n"
            f"{json.dumps(schema, ensure_ascii=False)}\n\n"
            f"Pregunta del usuario:\n{user_question}\n"
        )}
    ]
    resp = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        response_format={"type": "json_object"}
    )
    out = json.loads(resp.choices[0].message.content)
    out.setdefault("refined_question", user_question)
    out.setdefault("clarifications", [])
    out.setdefault("assumptions", [])
    out.setdefault("confidence", 0.0)
    return out


# ========= LLM setup =========
load_dotenv()
client = OpenAI(api_key=os.getenv("GITHUB_API_KEY"),
                base_url=os.getenv("BASE_URL"))
MODEL = os.getenv("MODEL")
SYSTEM = open("sample_prompts/system_sql_analyst.md").read()


# ========= Planificación =========
def plan_query(user_question: str, schema: dict, session_id: str) -> dict:
    short_ctx = summarize_for_context(load_session(session_id))
    messages = [
        {"role": "system", "content": (
            SYSTEM
            + "\n\nIMPORTANTE: Responde en JSON válido (un único objeto JSON)."
            + "\nContexto reciente (resumen para mantener coherencia):\n"
            + (short_ctx or "- (sin contexto)")
        )},
        {"role": "user", "content": (
            "Formato de salida: JSON estricto. "
            "Entrega solo un objeto JSON, sin texto adicional."
            f"\nEsquema disponible (en JSON):\n{json.dumps(schema, ensure_ascii=False)}\n\n"
            f"Pregunta: {user_question}"
        )}
    ]
    resp = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        response_format={"type": "json_object"}
    )
    out = json.loads(resp.choices[0].message.content)
    assert {"sql", "explain", "viz_suggestion", "notes"} <= set(out.keys())
    return out

# ========= Charting =========


def make_chart(df: pd.DataFrame, viz: dict):
    if df.empty:
        return None
    kind = (viz or {}).get("type", "none")
    if kind == "none":
        return None

    num_cols = df.select_dtypes(include=["number"]).columns.tolist()
    cat_cols = df.select_dtypes(exclude=["number"]).columns.tolist()
    if not num_cols:
        return None

    x = cat_cols[0] if cat_cols else df.columns[0]
    y = num_cols[0] if num_cols else (
        df.columns[1] if len(df.columns) > 1 else df.columns[0])

    if not pd.api.types.is_numeric_dtype(df[y]):
        df = df.copy()
        df[y] = pd.to_numeric(df[y], errors="coerce")

    try:
        if pd.api.types.is_object_dtype(df[x]):
            if df[x].astype(str).str.match(r"^\d{4}[-/]\d{2}([-/]\d{2})?$").all():
                _x_dt = pd.to_datetime(df[x].astype(
                    str), errors="coerce").rename("_x_dt")
                df = pd.concat([df, _x_dt], axis=1).sort_values(
                    "_x_dt").drop(columns=["_x_dt"])
    except (ValueError, TypeError, pd.errors.OutOfBoundsDatetime):
        pass

    df = df.dropna(subset=[y])
    if df.empty:
        return None

    plt.figure()
    if kind == "bar":
        df.plot(kind="bar", x=x, y=y, legend=False)
    elif kind == "line":
        df.plot(kind="line", x=x, y=y, legend=False)
    else:
        return None

    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format="png")
    buf.seek(0)
    return buf

# ========= Orquestación / Respuesta =========


def answer(user_question: str, session_id: str, auto_use_refined: bool = True):
    schema = get_schema()

    # 1) Refinar la pregunta
    refinement = refine_question(user_question, schema, session_id)
    final_question = refinement.get("refined_question") or user_question
    if not auto_use_refined:
        final_question = user_question

    # 2) Planificar y ejecutar
    plan = plan_query(final_question, schema, session_id)
    sql = plan.get("sql", "")

    try:
        df = run_sql(sql)
        chart = make_chart(df, plan.get("viz_suggestion", {}))

        # Guardar en historial (extendido)
        hist = load_session(session_id)
        hist.append({
            "ts": time.time(),
            "question": final_question,             # <-- compat UI
            "question_original": user_question,
            "question_refined": final_question,
            "refinement": refinement,
            "plan": plan,
            "sql": sql,
            "df_head": df.head(20).to_dict(orient="records"),
            "error": None,
        })
        save_session(session_id, hist)

        return {
            "question_original": user_question,
            "question_refined": final_question,
            "refinement": refinement,
            "plan": plan,
            "sql": sql,
            "df": df,
            "chart_bytes": chart.read() if chart else None,
            "error": None,
        }

    except Exception as e:
        hist = load_session(session_id)
        hist.append({
            "ts": time.time(),
            "question": final_question,             # <-- compat UI
            "question_original": user_question,
            "question_refined": final_question,
            "refinement": refinement,
            "plan": plan,
            "sql": sql,
            "df_head": None,
            "error": str(e),
        })
        save_session(session_id, hist)

        return {
            "question_original": user_question,
            "question_refined": final_question,
            "refinement": refinement,
            "plan": plan,
            "sql": sql,
            "df": None,
            "chart_bytes": None,
            "error": str(e),
        }


def clear_session(session_id: str):
    """Borra por completo el historial persistido de la sesión."""
    p = _session_path(session_id)
    if p.exists():
        p.unlink()
