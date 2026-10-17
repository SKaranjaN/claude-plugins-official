"""Rules load from the project root, not the hook's live working directory."""

import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config_loader import load_rules  # noqa: E402


RULE = """---
name: block-rm
enabled: true
event: bash
pattern: rm -rf
---

Do not run rm -rf.
"""

OTHER_EVENT = """---
name: warn-log
enabled: true
event: file
pattern: console.log
---

Debug logging.
"""

DISABLED = """---
name: disabled-rule
enabled: false
event: bash
pattern: sudo
---

Disabled.
"""


def write_rule(directory: Path, name: str, body: str) -> None:
    folder = directory / ".claude"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(body, encoding="utf-8")


class LoadRulesTests(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self._saved_project = os.environ.get("CLAUDE_PROJECT_DIR")

    def tearDown(self):
        os.chdir(self._cwd)
        if self._saved_project is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = self._saved_project

    @contextmanager
    def project(self, *bodies):
        # Leave the temp dirs before they are removed. On Windows the
        # process cannot delete a directory that is still the cwd.
        project = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        elsewhere = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        previous = os.getcwd()
        try:
            project_path = Path(project.name)
            for name, body in bodies:
                write_rule(project_path, name, body)
            yield project_path, Path(elsewhere.name)
        finally:
            os.chdir(previous)
            elsewhere.cleanup()
            project.cleanup()

    def test_project_dir_is_used_when_cwd_has_moved(self):
        with self.project(("hookify.block-rm.local.md", RULE)) as (project, elsewhere):
            os.environ["CLAUDE_PROJECT_DIR"] = str(project)
            os.chdir(elsewhere)

            rules = load_rules(event="bash")

        self.assertEqual([rule.name for rule in rules], ["block-rm"])

    def test_rules_in_the_drifted_cwd_are_not_loaded(self):
        with self.project(("hookify.block-rm.local.md", RULE)) as (project, elsewhere):
            write_rule(elsewhere, "hookify.other.local.md", OTHER_EVENT.replace("event: file", "event: bash"))
            os.environ["CLAUDE_PROJECT_DIR"] = str(project)
            os.chdir(elsewhere)

            rules = load_rules()

        self.assertEqual([rule.name for rule in rules], ["block-rm"])

    def test_cwd_is_the_fallback_when_project_dir_is_unset(self):
        with self.project(("hookify.block-rm.local.md", RULE)) as (project, _elsewhere):
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
            os.chdir(project)

            rules = load_rules(event="bash")

        self.assertEqual([rule.name for rule in rules], ["block-rm"])

    def test_unusable_project_dir_falls_back_and_warns(self):
        with self.project(("hookify.block-rm.local.md", RULE)) as (project, _elsewhere):
            os.environ["CLAUDE_PROJECT_DIR"] = str(project / "missing")
            os.chdir(project)
            with self._stderr() as err:
                rules = load_rules(event="bash")

        self.assertEqual([rule.name for rule in rules], ["block-rm"])
        self.assertIn("CLAUDE_PROJECT_DIR is not a directory", err.getvalue())

    def test_event_filter_and_disabled_rules_still_apply(self):
        with self.project(
            ("hookify.block-rm.local.md", RULE),
            ("hookify.warn-log.local.md", OTHER_EVENT),
            ("hookify.disabled.local.md", DISABLED),
        ) as (project, elsewhere):
            os.environ["CLAUDE_PROJECT_DIR"] = str(project)
            os.chdir(elsewhere)

            rules = load_rules(event="bash")

        self.assertEqual([rule.name for rule in rules], ["block-rm"])

    @contextmanager
    def _stderr(self):
        import io
        from contextlib import redirect_stderr

        buffer = io.StringIO()
        with redirect_stderr(buffer):
            yield buffer


if __name__ == "__main__":
    unittest.main()
