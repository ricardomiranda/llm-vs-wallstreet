"""Tests for the staged private-data and secret guard."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from check_staged_files import (
    contains_sensitive_content,
    find_forbidden_paths,
    is_forbidden_path,
)


class StagedFileGuardTests(unittest.TestCase):
    """Verify local portfolio data and common secret files are rejected."""

    def test_local_data_paths_are_blocked_except_placeholders(self) -> None:
        self.assertTrue(is_forbidden_path("references/account.xlsx"))
        self.assertTrue(is_forbidden_path("output/portfolio_buy_plan.json"))
        self.assertFalse(is_forbidden_path("references/.gitkeep"))
        self.assertFalse(is_forbidden_path("output/.gitkeep"))

    def test_common_secret_and_database_files_are_blocked(self) -> None:
        for path in (
            ".env",
            ".env.production",
            ".streamlit/secrets.toml",
            "private/id_ed25519",
            "backup/account.sqlite3",
            "certs/client.pem",
            "certs/private.key",
            "credentials.json",
            "config/cloud-token.json",
            "auth/user-credentials.json",
            "plans/custom_buy_plan.json",
            "imports/statement.degiro.xlsx",
            "downloads/statement.interactive-brokers.csv",
            "imports/statement.csv",
            "downloads/export.xlsx",
            "archive/20261107.interactive-brokers.csv",
        ):
            with self.subTest(path=path):
                self.assertTrue(is_forbidden_path(path))

    def test_safe_paths_and_example_environment_file_are_allowed(self) -> None:
        self.assertFalse(is_forbidden_path("scripts/dashboard.py"))
        self.assertFalse(is_forbidden_path("scripts/sample_module.py"))
        self.assertFalse(is_forbidden_path("tests/fixtures/synthetic_positions.csv"))
        self.assertFalse(is_forbidden_path(".env.example"))

    def test_finds_all_forbidden_paths(self) -> None:
        paths: list[str] = [
            "references/private.csv",
            "output/private.db",
            "README.md",
        ]
        self.assertEqual(find_forbidden_paths(paths), paths[:2])

    def test_detects_high_confidence_credentials_and_account_ids(self) -> None:
        for value in (
            "-" * 5 + "BEGIN " + "OPENSSH " + "PRIVATE KEY" + "-" * 5,
            "ghp_" + "a" * 30,
            "AKIA" + "1234567890ABCDEF",
            "sk-ant-" + "a" * 32,
            "U" + "1234" + "5678",
            "client_secret" + '="this-is-a-long-test-secret"',
        ):
            with self.subTest(value=value):
                self.assertTrue(contains_sensitive_content(value.encode("utf-8")))

    def test_non_secret_prose_is_allowed(self) -> None:
        self.assertFalse(
            contains_sensitive_content(
                b"Never commit brokerage exports, credentials, or account identifiers."
            )
        )


if __name__ == "__main__":
    unittest.main()
