import json
import tempfile
import unittest
from pathlib import Path

from app.analyzer import analyze_project
from app.knowledge import build_chunks


class NotebookAnalyzerTests(unittest.TestCase):
    def test_python_notebook_functions_emit_call_graph_evidence(self):
        notebook = {
            "metadata": {"kernelspec": {"language": "python"}},
            "cells": [
                {
                    "cell_type": "code",
                    "source": [
                        "def refresh_filters(records):\n",
                        "    return normalize(records)\n",
                    ],
                },
                {
                    "cell_type": "code",
                    "source": [
                        "def update_dashboard(records):\n",
                        "    refresh_filters(records)\n",
                        "    render_table(records)\n",
                    ],
                },
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dashboard.ipynb"
            path.write_text(json.dumps(notebook), encoding="utf-8")
            analysis = analyze_project(Path(directory))

        self.assertIn(
            ("dashboard.ipynb::update_dashboard", "refresh_filters"),
            analysis["calls"],
        )
        chunks = build_chunks(analysis, "test123")
        self.assertTrue(any(chunk["kind"] == "callgraph" for chunk in chunks))
        self.assertTrue(any(chunk["kind"] == "flow" for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
