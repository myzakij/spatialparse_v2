import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import auth_store
from backend.main import app


class AuthConsentStoreTests(unittest.TestCase):
    def test_init_db_migrates_and_records_user_consent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "spatialparse_test.db"
            with patch.object(auth_store, "DB_PATH", db_path):
                auth_store.init_db()
                user = auth_store.create_user("audit@example.com", "strong-password", "Audit User")
                consent = auth_store.record_user_consent(
                    user_id=user["id"],
                    consent_type="registration_terms_privacy_personal_data",
                    document_version="2026-08-03",
                    accepted=True,
                    ip_address="127.0.0.1",
                    user_agent="SpatialParseTest/1.0",
                )

                self.assertEqual(consent["user_id"], user["id"])
                self.assertTrue(consent["accepted"])

                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                try:
                    row = conn.execute(
                        """
                        SELECT user_id, consent_type, document_version, accepted, ip_address, user_agent
                        FROM user_consents
                        WHERE user_id = ?
                        """,
                        (user["id"],),
                    ).fetchone()
                finally:
                    conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row["consent_type"], "registration_terms_privacy_personal_data")
        self.assertEqual(row["document_version"], "2026-08-03")
        self.assertEqual(row["accepted"], 1)
        self.assertEqual(row["ip_address"], "127.0.0.1")
        self.assertEqual(row["user_agent"], "SpatialParseTest/1.0")

    def test_register_rejects_blank_consent_version_before_creating_user(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "spatialparse_test.db"
            with patch.object(auth_store, "DB_PATH", db_path):
                auth_store.init_db()
                client = TestClient(app)
                response = client.post(
                    "/api/auth/register",
                    json={
                        "email": "blank-version@example.com",
                        "password": "strong-password",
                        "name": "Blank Version",
                        "consent_accepted": True,
                        "consent_version": "   ",
                    },
                )

                conn = sqlite3.connect(db_path)
                try:
                    user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
                    consent_count = conn.execute("SELECT COUNT(*) FROM user_consents").fetchone()[0]
                finally:
                    conn.close()

        self.assertEqual(response.status_code, 422)
        self.assertEqual(user_count, 0)
        self.assertEqual(consent_count, 0)


if __name__ == "__main__":
    unittest.main()
