"""Tests for repository validation, environment helpers, and small CLIs."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import bumpversion
import check_staged_files
import pre_commit
import project_env
import validate_json
import validate_yaml


class TrackedValidatorsTests(unittest.TestCase):
    """Exercise Git-index path discovery and command results."""

    def test_json_and_yaml_tracked_paths_and_validation(self) -> None:
        with patch("validate_json.subprocess.run", return_value=subprocess.CompletedProcess([], 0, b"one.json\0settings.jsonc\0")):
            self.assertEqual(validate_json.tracked_json_paths(Path(".")), ["one.json"])
        with patch("validate_yaml.subprocess.run", return_value=subprocess.CompletedProcess([], 0, b"workflow.yml\0config.yaml\0")):
            self.assertEqual(validate_yaml.tracked_yaml_paths(Path(".")), ["workflow.yml", "config.yaml"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ok.json").write_text('{"valid": true}', encoding="utf-8")
            (root / "bad.yml").write_text("item: [", encoding="utf-8")
            with patch("validate_json.tracked_json_paths", return_value=["ok.json"]):
                self.assertEqual(validate_json.validate_tracked_json(root), [])
            with patch("validate_yaml.tracked_yaml_paths", return_value=["bad.yml"]):
                self.assertIn("bad.yml", validate_yaml.validate_tracked_yaml(root)[0])

    def test_validator_mains_report_clean_or_invalid_repository(self) -> None:
        with patch("validate_json.validate_tracked_json", return_value=[]), patch("builtins.print"):
            self.assertEqual(validate_json.main(), 0)
        with patch("validate_json.validate_tracked_json", return_value=["bad.json"]), patch("builtins.print") as output:
            self.assertEqual(validate_json.main(), 1)
            output.assert_called_with("bad.json", file=sys.stderr)
        with patch("validate_yaml.validate_tracked_yaml", return_value=[]), patch("builtins.print"):
            self.assertEqual(validate_yaml.main(), 0)
        with patch("validate_yaml.validate_tracked_yaml", return_value=["bad.yml"]), patch("builtins.print") as output:
            self.assertEqual(validate_yaml.main(), 1)
            output.assert_called_with("bad.yml", file=sys.stderr)


class StagedFileContentTests(unittest.TestCase):
    """Check staged and tracked scanners skip unsuitable content paths."""

    def test_binary_and_secret_pattern_content(self) -> None:
        self.assertFalse(check_staged_files.contains_sensitive_content(b"binary\x00credential"))
        self.assertTrue(check_staged_files.contains_sensitive_content(b"password=long-secret-value-1234"))

    def test_staged_and_tracked_scanners_use_index_blob(self) -> None:
        completed = subprocess.CompletedProcess([], 0, b"api_key=12345678901234567890")
        with patch("check_staged_files.subprocess.run", return_value=completed) as run:
            found = check_staged_files.staged_content_findings(
                ["notes.md", "tests/test_safe.py", "refs/data.csv", "image.png"], Path(".")
            )
            self.assertEqual(found, ["notes.md"])
            self.assertEqual(run.call_count, 1)
        with patch("check_staged_files.subprocess.run", return_value=completed):
            self.assertEqual(check_staged_files.tracked_content_findings(["settings.toml"], Path(".")), ["settings.toml"])

    def test_path_discovery_and_guard_cli_success_and_failure(self) -> None:
        output = b"scripts/a.py\0references/private.csv\0"
        with patch("check_staged_files.subprocess.run", return_value=subprocess.CompletedProcess([], 0, output)):
            self.assertEqual(check_staged_files.staged_paths(), ["scripts/a.py", "references/private.csv"])
            self.assertEqual(check_staged_files.tracked_paths(), ["scripts/a.py", "references/private.csv"])
        with patch("sys.argv", ["guard"]), patch("check_staged_files.staged_paths", return_value=[]), \
             patch("check_staged_files.staged_content_findings", return_value=[]), patch("builtins.print"):
            self.assertEqual(check_staged_files.main(), 0)
        with patch("sys.argv", ["guard", "--tracked"]), patch("check_staged_files.tracked_paths", return_value=["output/file.db"]), \
             patch("check_staged_files.tracked_content_findings", return_value=[]), patch("builtins.print") as output_print:
            self.assertEqual(check_staged_files.main(), 1)
            output_print.assert_called()


class EnvironmentAndHookTests(unittest.TestCase):
    """Cover environment bootstrap helpers and staged Python hook flow."""

    def test_project_environment_helpers(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(project_env.repo_root(), root)
        self.assertEqual(project_env.venv_python(root), root / ".venv" / "bin" / "python")
        self.assertTrue(project_env.running_in_venv(root))
        self.assertFalse(project_env.module_available(root / ".venv/bin/python", "not_a_real_module"))
        with patch("project_env.module_available", return_value=True), patch("project_env.subprocess.run") as run:
            project_env.ensure_pip(Path("python"))
            run.assert_not_called()
        with patch("project_env.module_available", return_value=False), patch("project_env.subprocess.run") as run:
            project_env.ensure_pip(Path("python"))
            run.assert_called_once()
        with tempfile.TemporaryDirectory() as directory:
            temp_root = Path(directory)
            (temp_root / ".bumpversion.cfg").touch()
            with patch("project_env.venv.EnvBuilder.create") as create, \
                 patch("project_env.module_available", side_effect=[True, False, True]), \
                 patch("project_env.subprocess.run") as run:
                self.assertEqual(project_env.ensure_venv(temp_root), temp_root / ".venv" / "bin" / "python")
                create.assert_called_once()
                run.assert_called_once()

    def test_pre_commit_normalizes_paths_and_runs_checks(self) -> None:
        self.assertEqual(pre_commit.normalize("./scripts\\tool.py"), "scripts/tool.py")
        for path, expected in (("script.py", True), ("tests/test.py", False), ("scripts/x.py", True), (".opencode/x.py", False), ("scripts/data.txt", False)):
            self.assertEqual(pre_commit.is_project_python(path), expected)
        root = Path(__file__).resolve().parents[1]
        with patch("pre_commit.subprocess.run", return_value=subprocess.CompletedProcess([], 0, stdout="scripts/x.py\n")):
            self.assertEqual(pre_commit.staged_project_python(root), ["scripts/x.py"])
        with patch("pre_commit.subprocess.run", return_value=subprocess.CompletedProcess([], 7)) as run:
            self.assertEqual(pre_commit.run_mypy(root, root / ".venv/bin/python"), 7)
            run.assert_called_once()
        with patch("pre_commit.repo_root", return_value=root), patch("pre_commit.staged_paths", return_value=[]), patch("builtins.print"):
            self.assertEqual(pre_commit.main(), 0)
        with patch("pre_commit.repo_root", return_value=root), patch("pre_commit.staged_paths", return_value=["scripts/x.py"]), \
             patch("pre_commit.find_forbidden_paths", return_value=[]), patch("pre_commit.staged_project_python", return_value=["scripts/x.py"]), \
             patch("pre_commit.ensure_venv", return_value=Path("python")), patch("pre_commit.run_mypy", return_value=3):
            self.assertEqual(pre_commit.main(), 3)


class BumpVersionHelpersTests(unittest.TestCase):
    """Exercise bump command dispatch without changing project version files."""

    def test_bumpversion_root_and_venv_helpers(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(bumpversion.repo_root(), root)
        self.assertEqual(bumpversion.venv_python(root), root / ".venv/bin/python")
        self.assertEqual(bumpversion.current_version(root), (root / "version.txt").read_text().strip())
        self.assertTrue(bumpversion.running_in_venv(root))
        with patch("bumpversion.module_available", return_value=True), patch("bumpversion.subprocess.run") as run:
            bumpversion.ensure_pip(Path("python"))
            run.assert_not_called()
            bumpversion.ensure_venv(root)
            run.assert_not_called()

    def test_main_dry_run_and_failure_paths(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with patch("bumpversion.repo_root", return_value=root), patch("bumpversion.ensure_venv", return_value=Path("python")), \
             patch("bumpversion.running_in_venv", return_value=True), patch("bumpversion.current_version", side_effect=["1.0.0", "1.0.0"]), \
             patch("bumpversion.subprocess.run", return_value=subprocess.CompletedProcess([], 0)):
            self.assertEqual(bumpversion.main(["patch", "--dry-run"]), 0)
        with patch("bumpversion.repo_root", return_value=root), patch("bumpversion.ensure_venv", return_value=Path("python")), \
             patch("bumpversion.running_in_venv", return_value=True), patch("bumpversion.current_version", return_value="1.0.0"), \
             patch("bumpversion.subprocess.run", return_value=subprocess.CompletedProcess([], 4)):
            self.assertEqual(bumpversion.main(["patch"]), 4)
        with patch("bumpversion.repo_root", return_value=root), patch("bumpversion.ensure_venv", return_value=Path(".venv/bin/python")), \
             patch("bumpversion.running_in_venv", return_value=False), patch("bumpversion.subprocess.run", return_value=subprocess.CompletedProcess([], 5)) as run:
            self.assertEqual(bumpversion.main(["minor"]), 5)
            self.assertEqual(run.call_args.args[0][0], ".venv/bin/python")


if __name__ == "__main__":
    unittest.main()
