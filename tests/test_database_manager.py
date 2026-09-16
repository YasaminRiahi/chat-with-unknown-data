import unittest
from unittest.mock import MagicMock, patch

from api.database_manager import DatabaseManager


class DatabaseManagerTests(unittest.TestCase):
    def test_rejects_non_mssql_connections(self):
        cases = [
            ("sqlite", "sqlite:///local.db"),
            ("postgresql", "postgresql://user:password@localhost/database"),
            ("mysql", "mysql+pymysql://user:password@localhost/database"),
            ("mssql", "sqlite:///local.db"),
        ]

        for db_type, connection_string in cases:
            with self.subTest(db_type=db_type, connection_string=connection_string):
                manager = DatabaseManager()
                with patch("api.database_manager.create_engine") as create_engine:
                    with self.assertRaisesRegex(ValueError, "Only Microsoft SQL Server"):
                        manager.add_database("test", db_type, connection_string)
                create_engine.assert_not_called()

    def test_accepts_mssql_connection_string(self):
        manager = DatabaseManager()
        engine = MagicMock()
        connection = engine.connect.return_value.__enter__.return_value

        with patch("api.database_manager.create_engine", return_value=engine):
            manager.add_database(
                "test",
                "mssql",
                "mssql+pyodbc://sa:password@localhost/database?driver=ODBC+Driver+18+for+SQL+Server",
            )

        connection.execute.assert_called_once()
        self.assertEqual(manager.get_info("test")["type"], "mssql")


if __name__ == "__main__":
    unittest.main()
