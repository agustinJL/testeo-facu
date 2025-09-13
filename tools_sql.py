import os
import re
import sqlite3
import pandas as pd
from sqlglot import parse_one, exp
from sqlglot.errors import ParseError

# --- Config ---
DB_PATH = os.getenv("DB_PATH", "toy.db")
ROW_LIMIT = int(os.getenv("ROW_LIMIT", "1000"))

# Raíces de lectura válidas (sqlglot tree.key)
ALLOWED_ROOTS = {"SELECT", "WITH", "UNION", "EXCEPT", "INTERSECT", "JOIN"}



def get_foreign_keys():
    """Devuelve lista de relaciones [(from_table, from_col, to_table, to_col)]."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    rels = []
    for t in tables:
        try:
            cur.execute(f"PRAGMA foreign_key_list({t})")
            for (id, seq, table, from_col, to_col, on_update, on_delete, match) in cur.fetchall():
                rels.append((t, from_col, table, to_col))
        except Exception:
            pass
    conn.close()
    return rels

def table_row_count(table: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        n = cur.fetchone()[0]
    except Exception:
        n = 0
    conn.close()
    return n

def sample_rows(table: str, n: int = 5):
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(f"SELECT * FROM {table} LIMIT {n}", conn)
    conn.close()
    return df


# =========================
#  Esquema de la base
# =========================
def get_schema():
    """
    Devuelve un dict {tabla: [{name, type}, ...]} usando PRAGMA table_info.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]

    schema = {}
    for t in tables:
        cur.execute(f"PRAGMA table_info({t})")
        cols = [{"name": c[1], "type": c[2]} for c in cur.fetchall()]
        schema[t] = cols

    conn.close()
    return schema


# =========================
#  Sanitización de SQL
# =========================
def strip_fences(sql: str) -> str:
    sql = sql.strip()
    # Maneja ```sql ... ``` o ``` ... ```
    if sql.startswith("```"):
        parts = sql.split("```")
        if len(parts) >= 3:
            # contenido entre fences
            sql = parts[1]
        else:
            sql = sql.strip("`")
    return sql.strip()


def strip_line_comments(sql: str) -> str:
    # quita comentarios de línea -- ...
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def strip_block_comments(sql: str) -> str:
    # quita /* ... */ (naive pero suficiente aquí)
    return re.sub(r"/\*.*?\*/", "", sql, flags=re.S)


def strip_trailing_semicolon(sql: str) -> str:
    return sql.rstrip().rstrip(";").rstrip()


def sanitize(sql: str) -> str:
    sql = strip_fences(sql)
    sql = strip_block_comments(sql)
    sql = strip_line_comments(sql)
    sql = strip_trailing_semicolon(sql)
    return sql.strip()

def _forbidden_nodes_tuple():
    # Tomamos solo las clases que existan en esta versión de sqlglot
    names = [
        "Insert", "Update", "Delete", "Create", "Alter", "Drop",
        "Command",      # PRAGMA, VACUUM, etc.
        "Attach", "Detach",
        "Analyze", "Reindex",
    ]
    nodes = []
    for name in names:
        cls = getattr(exp, name, None)
        if cls is not None:
            nodes.append(cls)
    return tuple(nodes)


# =========================
#  Validación segura
# =========================
def validate_sql(sql: str, debug: bool = False) -> str:
    sql = sanitize(sql)
    if ";" in sql:
        raise ValueError("Una sola sentencia permitida")

    try:
        tree = parse_one(sql, read="sqlite")
    except ParseError as e:
        raise ValueError(f"SQL inválido: {e}")

    # 👇 usa la lista dinámica
    forbidden_nodes = _forbidden_nodes_tuple()
    if any(tree.find(n) for n in forbidden_nodes):
        raise ValueError("Operación no permitida")

    return sql



def enforce_limit(sql: str) -> str:
    # agrega LIMIT si no existe (sobre el último SELECT)
    if re.search(r"\bLIMIT\b", sql, re.IGNORECASE):
        return sql
    return f"{sql.strip()} LIMIT {ROW_LIMIT}"


# =========================
#  Ejecución
# =========================
def run_sql(sql: str) -> pd.DataFrame:
    sql = validate_sql(sql)
    sql = enforce_limit(sql)
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(sql, conn)
    conn.close()
    return df
