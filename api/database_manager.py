"""
api/database_manager.py
========================
Manages multiple live database connections.

To add a new DB type:
  1. pip install the driver
  2. Add an entry to SUPPORTED_TYPES
  3. No other changes needed
"""

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

SUPPORTED_TYPES = {
    "sqlite":     "sqlite",
    "postgresql": "postgresql",
    "postgres":   "postgresql",
    "mysql":      "mysql",
    "mariadb":    "mysql",
    # "mssql":   "mssql+pyodbc",
    # "oracle":  "oracle+cx_oracle",
}


class DatabaseManager:
    def __init__(self):
        self._databases: dict[str, dict] = {}

    def add_database(self, name: str, db_type: str, connection_string: str) -> None:
        db_type = db_type.lower()
        if db_type not in SUPPORTED_TYPES:
            raise ValueError(f"Unsupported type '{db_type}'. Supported: {list(SUPPORTED_TYPES)}")
        if name in self._databases:
            raise ValueError(f"'{name}' already connected. Remove it first.")

        engine = create_engine(connection_string, pool_pre_ping=True)
        self._verify_connection(engine, name)
        self._databases[name] = {"engine": engine, "type": db_type, "connection_string": connection_string}
        print(f"[DB] Connected: '{name}' ({db_type})")

    def remove_database(self, name: str) -> None:
        if name not in self._databases:
            raise ValueError(f"No database named '{name}'.")
        self._databases[name]["engine"].dispose()
        del self._databases[name]

    def list_databases(self) -> list[str]:
        return list(self._databases.keys())

    def get_engine(self, name: str) -> Engine:
        if name not in self._databases:
            raise ValueError(f"No database named '{name}'.")
        return self._databases[name]["engine"]

    def get_info(self, name: str) -> dict:
        if name not in self._databases:
            raise ValueError(f"No database named '{name}'.")
        e = self._databases[name]
        return {"type": e["type"], "connection_string": e["connection_string"]}

    def execute_query(self, name: str, sql: str) -> list[dict]:
        engine = self.get_engine(name)
        with engine.connect() as conn:
            result  = conn.execute(text(sql))
            columns = list(result.keys())
            return [dict(zip(columns, row)) for row in result.fetchall()]

    @staticmethod
    def _verify_connection(engine: Engine, name: str) -> None:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as e:
            raise ConnectionError(f"Cannot connect to '{name}': {e}") from e
