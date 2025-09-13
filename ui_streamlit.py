import os, uuid
import streamlit as st
from dotenv import load_dotenv

from agent_core import answer, load_session  # historia en disco
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

    # (Opcional) Borrar historial persistido + resultados en memoria
    # from agent_core import clear_session
    # if st.button("🗑️ Borrar historial de esta sesión", key="wipe_hist_btn"):
    #     clear_session(st.session_state["session_id"])
    #     st.session_state["story"] = []
    #     st.session_state["results"] = []
    #     for idx in range(len(disk_history)):
    #         st.session_state.pop(f"pick_{idx}", None)
    #     st.rerun()

    # (Opcional) Nueva sesión limpia
    # if st.button("🆕 Nueva sesión", key="new_sess_btn"):
    #     import uuid
    #     st.session_state["session_id"] = str(uuid.uuid4())
    #     st.session_state["story"] = []
    #     st.session_state["results"] = []
    #     for k in list(st.session_state.keys()):
    #         if str(k).startswith("pick_"):
    #             st.session_state.pop(k, None)
    #     st.rerun()




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

# ============ Input ============
q = st.text_input("Preguntale a la base (ej: ventas por categoría por mes):", "")
run = st.button("Ejecutar", type="primary")

# ============ Acción ============
if run and q.strip():
    with st.spinner("Pensando y consultando..."):
        res = answer(q, session_id=st.session_state["session_id"])
        st.session_state["results"].append(res)  # guardamos para render

# ============ Render de resultados ============
for i, res in enumerate(reversed(st.session_state["results"]), 1):
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
        st.image(res["chart_bytes"], caption="Visualización sugerida")  # sin key

    with st.expander("Notas / supuestos", expanded=False):
        st.write(res.get("plan", {}).get("notes", ""))
