from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]

import run_demo


class DemoWorkflowTests(unittest.TestCase):
    def test_one_command_demo_runs_profile_driven_preview(self) -> None:
        with tempfile.TemporaryDirectory(prefix="taira-demo-") as temporary:
            work_dir = Path(temporary)
            self.assertEqual(run_demo.main(["--work-dir", str(work_dir)]), 0)
            scenario = work_dir / "japan"
            result = json.loads(
                (scenario / "candidates.json").read_text(encoding="utf-8")
            )
            self.assertEqual(result["mode"], "research-findings")
            self.assertTrue(result["final"])
            self.assertTrue((scenario / "index.sqlite3").is_file())
            self.assertTrue((scenario / "candidates.editorial.json").is_file())

    def test_demo_is_explicitly_profile_driven(self) -> None:
        source = (PROJECT / "run_demo.py").read_text(encoding="utf-8")
        self.assertIn("run_scenario", source)
        self.assertNotIn("daily-five", source)


if __name__ == "__main__":
    unittest.main()
