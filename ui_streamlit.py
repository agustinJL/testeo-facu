import os, uuid
import streamlit as st
from dotenv import load_dotenv

from agent_core import answer, load_session, refine_question_step  # <-- + refine
from tools_sql import get_schema, get_foreign_keys, table_row_count, sample_rows

# ============ Config ============
load_dotenv()
st.set_page_config(page_title="Data Analyst Agent", layout="wide")

# ============ Estado ============
if "session_id" not in st.session_state:
    st.session_state["session_id"] = str(uuid.uuid4())

# Resultados completos para render inmediato (df/chart_bytes)
if "results" not in st.session_state:
    st.session_state["results"] = []

# Estado del refinamiento iterativo
if "refine" not in st.session_state:
    st.session_state["refine"] = None

# ============ Utils: diagrama ============
def build_schema_dot(schema: dict, fks: list) -> str:
    def esc(s: str) -> str:
        return str(s).replace('"', '\\"')
    lines = [
        'digraph G {',
        '  graph [rankdir=LR, splines=ortho];',
        '  node  [shape=plaintext, fontname="Helvetica"];'
    ]
    for t, cols in schema.items():
        header = f'<tr><td bgcolor="#f2f2f2"><b>{esc(t)}</b></td></tr>'
        body = "\n".join(
            f'<tr><td align="left"><font face="monospace">{esc(c["name"])} : {esc(c["type"])}</font></td></tr>'
            for c in cols
        )
        table_html = f'<<table border="1" cellborder="0" cellspacing="0">{header}{body}</table>>'
        lines.append(f'  "{esc(t)}" [label={table_html}];')
    for ft, fc, tt, tc in fks:
        lines.append(f'  "{esc(ft)}" -> "{esc(tt)}" [label="{esc(fc)} → {esc(tc)}", fontsize=10];')
    lines.append('}')
    return "\n".join(lines)

@st.cache_data
def _cached_schema():
    return get_schema(), get_foreign_keys()

# ============ Sidebar: Storytelling ============
with st.sidebar:
    st.header("🧵 Storytelling")
    disk_history = load_session(st.session_state["session_id"])
    if "story" not in st.session_state:
        st.session_state["story"] = []

    # checkboxes (cada uno con key estable)
    for idx, item in enumerate(disk_history):
        label = (item.get("question") or "(sin pregunta)")[:60]
        checked = idx in st.session_state["story"]
        if st.checkbox(label, value=checked, key=f"pick_{idx}"):
            if idx not in st.session_state["story"]:
                st.session_state["story"].append(idx)
        else:
            if idx in st.session_state["story"]:
                st.session_state["story"].remove(idx)

    # Exportar selección -> botón con key único
    if st.button("📝 Exportar Story (Markdown)", key="export_story_btn"):
        md = ["# Story - Data Analyst Agent\n"]
        for idx in st.session_state["story"]:
            it = disk_history[idx]
            md += [
                f"## {it.get('question','')}",
                "```sql",
                it.get("sql",""),
                "```",
                it.get("plan",{}).get("explain",""),
                ""
            ]
        st.download_button(
            "Descargar Story.md",
            data="\n".join(md).encode(),
            file_name="story.md",
            mime="text/markdown",
            key="dl_story"
        )

    # Limpiar selección (checkboxes) -> botón con key único
    if st.button("🧹 Limpiar Story", key="clear_story_btn"):
        for idx in range(len(disk_history)):
            st.session_state.pop(f"pick_{idx}", None)
        st.session_state["story"] = []
        st.rerun()

# ============ Título & Esquema visual ============
st.title("🧠📊 Data Analyst Agent")

with st.expander("🔎 Esquema de la base (visual y navegable)", expanded=False):
    schema, fks = _cached_schema()

    tab1, tab2, tab3 = st.tabs(["🗺️ Diagrama", "📋 Tablas & columnas", "👀 Muestras"])

    with tab1:
        dot = build_schema_dot(schema, fks)
        st.graphviz_chart(dot, use_container_width=True)

    with tab2:
        for t, cols in schema.items():
            n = table_row_count(t)
            with st.expander(f"**{t}** — {n} filas"):
                st.table([{ "columna": c["name"], "tipo": c["type"] } for c in cols])

    with tab3:
        for t in schema.keys():
            with st.expander(f"Preview: {t} (5 filas)"):
                st.dataframe(sample_rows(t, 5))

# ============ Refinamiento iterativo (opcional) ============
st.subheader("🗣️ Refinamiento iterativo (opcional)")
schema_cached, _ = _cached_schema()

user_q = st.text_input("Planteá tu pregunta de negocio:", key="user_q")

cols_ref = st.columns([1,1,1])
if cols_ref[0].button("🔍 Empezar a refinar", key="start_refine_btn") and user_q.strip():
    base_q = user_q.strip()
    step = refine_question_step(
        base_question=base_q,
        schema=schema_cached,
        session_id=st.session_state["session_id"]
    )
    st.session_state["refine"] = {
        "original": base_q,
        "current": step.get("refined_question", base_q),
        "steps": [step],
        "user_choices": [],
        "done": False,
    }
    st.rerun()

# Panel interactivo si hay refinamiento activo
if st.session_state["refine"]:
    R = st.session_state["refine"]
    st.caption("Editá la pregunta refinada, elegí aclaraciones sugeridas y refiná de nuevo. Ejecutá cuando estés conforme.")
    st.text_area("Pregunta refinada (editable):", value=R["current"], key="refined_edit", height=90)

    last = R["steps"][-1]
    sugg = last.get("clarifications", []) or []
    chosen = []
    if sugg:
        st.write("**Aclaraciones sugeridas (tildá las que apliquen):**")
        for i, s in enumerate(sugg):
            if st.checkbox(s, key=f"clar_{len(R['steps'])}_{i}"):
                chosen.append(s)

    extra = st.text_input("Agregar alguna aclaración propia (opcional):", key=f"extra_{len(R['steps'])}")

    c1, c2, c3 = st.columns([1,1,1])
    if c1.button("➕ Refinar con estas aclaraciones", key=f"refine_again_{len(R['steps'])}"):
        if extra.strip():
            chosen.append(extra.strip())
        step = refine_question_step(
            base_question=R["current"],
            schema=schema_cached,
            session_id=st.session_state["session_id"],
            user_selected_clarifications=chosen,
            user_edited_question=st.session_state["refined_edit"]
        )
        R["user_choices"].extend(chosen)
        R["current"] = step.get("refined_question", st.session_state["refined_edit"])
        R["steps"].append(step)
        st.session_state["refine"] = R
        st.rerun()

    if c2.button("✅ Ejecutar ahora", key=f"exec_now_{len(R['steps'])}"):
        with st.spinner("Generando SQL y ejecutando..."):
            res = answer(R["current"], session_id=st.session_state["session_id"])
            st.session_state["results"].append(res)
        st.session_state["refine"] = None
        st.rerun()

    if c3.button("🧹 Reiniciar refinamiento", key=f"reset_refine_{len(R['steps'])}"):
        st.session_state["refine"] = None
        st.rerun()

    # Info de confianza
    conf = float(last.get("confidence", 0.0))
    if conf >= 0.75:
        st.info("La confianza del agente es alta. Si estás conforme, podés **Ejecutar ahora**.")

    # Timeline de pasos
    with st.expander("Ver pasos de refinamiento"):
        for idx, s in enumerate(R["steps"], 1):
            st.markdown(f"**Paso {idx}** — Confianza: {int(100*s.get('confidence',0))}%")
            st.write("Refinada:", s.get("refined_question",""))
            if s.get("assumptions"):
                st.caption("Supuestos de este paso:")
                for a in s["assumptions"]:
                    st.write(f"• {a}")
            st.divider()

# ============ Ejecución directa (salteando refinamiento) ============
st.subheader("⚡ Ejecución rápida (saltear refinamiento)")
q = st.text_input("Preguntale a la base (ej: ventas por categoría por mes):", "", key="direct_q")
run = st.button("Ejecutar", type="primary", key="direct_run_btn")

if run and q.strip():
    with st.spinner("Pensando y consultando..."):
        res = answer(q, session_id=st.session_state["session_id"])
        st.session_state["results"].append(res)

# ============ Render de resultados ============
for i, res in enumerate(reversed(st.session_state["results"]), 1):

    # --- Mostrar refinamiento de la pregunta usada ---
    ref = res.get("refinement", {}) or {}
    q_orig = res.get("question_original", "")
    q_ref = res.get("question_refined", "")

    with st.expander("🎯 Pregunta (refinada)", expanded=True):
        if q_orig and q_ref and q_orig != q_ref:
            st.markdown(f"**Original:** {q_orig}")
            st.markdown(f"**Refinada:** {q_ref}")
        else:
            st.markdown(f"**Pregunta:** {q_ref or q_orig}")

        if ref.get("clarifications"):
            st.caption("Posibles aclaraciones:")
            for c in ref["clarifications"]:
                st.write(f"• {c}")

        if ref.get("assumptions"):
            st.caption("Supuestos usados:")
            for a in ref["assumptions"]:
                st.write(f"• {a}")

        if "confidence" in ref:
            st.caption(f"Confianza del agente: {round(float(ref['confidence'])*100):d}%")

        st.markdown(f"### Resultado #{i}")
        st.code(res.get("sql", ""), language="sql")

        if res.get("error"):
            st.error(f"Error: {res['error']}")
            if res.get("plan", {}).get("explain"):
                with st.expander("Explicación del plan (del modelo)", expanded=False):
                    st.write(res["plan"]["explain"])
            continue

        st.write(res.get("plan", {}).get("explain", ""))

        if res.get("df") is not None and not res["df"].empty:
            st.dataframe(res["df"].head(50), key=f"df_{i}")
            csv_bytes = res["df"].to_csv(index=False).encode()
            st.download_button(
                "Descargar CSV",
                data=csv_bytes,
                file_name=f"resultado_{i}.csv",
                mime="text/csv",
                key=f"dl_{i}"
            )

        if res.get("chart_bytes"):
            st.image(res["chart_bytes"], caption="Visualización sugerida")

        with st.expander("Notas / supuestos", expanded=False):
            st.write(res.get("plan", {}).get("notes", ""))
