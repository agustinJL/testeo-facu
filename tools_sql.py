import os
import re
import sqlite3
from pathlib import Path
import pandas as pd
from sqlglot import parse_one, exp
from sqlglot.errors import ParseError

# =========================================
# Config y helpers de conexión / semilla
# =========================================

# Ruta portable por defecto: <repo>/tools_sql/data/toy.db
_DEFAULT_DB = Path(__file__).parent / "data" / "toy.db"
DB_PATH = Path(os.getenv("DB_PATH", str(_DEFAULT_DB))).resolve()
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

ROW_LIMIT = int(os.getenv("ROW_LIMIT", "1000"))

def _conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def _tables_present() -> set[str]:
    with _conn() as cx:
        cur = cx.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        return {r[0] for r in cur.fetchall()}

def ensure_db():
    """
    Crea/siembra la DB si no existe o si faltan tablas clave.
    Usa seed_db.seed_db(DB_PATH) sin side-effects (seed_db refactorizado).
    """
    must_seed = not DB_PATH.exists()
    needed = {"customers", "products", "orders"}
    if not must_seed:
        # Si existe el archivo, verificamos tablas requeridas
        try:
            present = _tables_present()
            if not needed.issubset(present):
                must_seed = True
        except Exception:
            must_seed = True

    if must_seed:
        # Import tardío para evitar side-effects
        from seed_db import seed_db as _seed
        _seed(str(DB_PATH))

# =========================================
# Esquema / info
# =========================================

def get_foreign_keys():
    """Devuelve lista de relaciones [(from_table, from_col, to_table, to_col)]."""
    ensure_db()
    with _conn() as cx:
        cur = cx.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        rels = []
        for t in tables:
            try:
                cur.execute(f"PRAGMA foreign_key_list({t})")
                for (_id, _seq, table, from_col, to_col, _up, _del, _match) in cur.fetchall():
                    rels.append((t, from_col, table, to_col))
            except Exception:
                pass
    return rels

def table_row_count(table: str) -> int:
    ensure_db()
    with _conn() as cx:
        cur = cx.cursor()
        try:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            n = cur.fetchone()[0]
        except Exception:
            n = 0
    return n

def sample_rows(table: str, n: int = 5):
    ensure_db()
    with _conn() as cx:
        df = pd.read_sql_query(f"SELECT * FROM {table} LIMIT {n}", cx)
    return df

def get_schema():
    """
    Devuelve un dict {tabla: [{name, type}, ...]} usando PRAGMA table_info.
    """
    ensure_db()
    schema = {}
    with _conn() as cx:
        cur = cx.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        for t in tables:
            cur.execute(f"PRAGMA table_info({t})")
            cols = [{"name": c[1], "type": c[2]} for c in cur.fetchall()]
            schema[t] = cols
    return schema

# =========================================
# Sanitización de SQL
# =========================================

def strip_fences(sql: str) -> str:
    sql = sql.strip()
    if sql.startswith("```"):
        parts = sql.split("```")
        if len(parts) >= 3:
            sql = parts[1]
        else:
            sql = sql.strip("`")
    return sql.strip()

def strip_line_comments(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())

def strip_block_comments(sql: str) -> str:
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
    """
    Prepara lista dinámica de nodos prohibidos según versión de sqlglot disponible.
    """
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

# =========================================
# Validación y ejecución
# =========================================

def validate_sql(sql: str, debug: bool = False) -> str:
    sql = sanitize(sql)
    if ";" in sql:
        raise ValueError("Una sola sentencia permitida")

    try:
        tree = parse_one(sql, read="sqlite")
    except ParseError as e:
        raise ValueError(f"SQL inválido: {e}")

    forbidden_nodes = _forbidden_nodes_tuple()
    if any(tree.find(n) for n in forbidden_nodes):
        raise ValueError("Operación no permitida")

    return sql

def enforce_limit(sql: str) -> str:
    if re.search(r"\bLIMIT\b", sql, re.IGNORECASE):
        return sql
    return f"{sql.strip()} LIMIT {ROW_LIMIT}"

def run_sql(sql: str) -> pd.DataFrame:
    ensure_db()
    sql = validate_sql(sql)
    sql = enforce_limit(sql)
    with _conn() as cx:
        df = pd.read_sql_query(sql, cx)
    return df
