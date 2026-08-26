# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""Every .py in this repository has to compile. Frappe Cloud says so.

The release check compiles the whole tree, and a file it cannot parse fails
the build with "Validation Failed: Invalid app release" -- no deploy, for
anybody, until it is fixed.

That is not hypothetical. A patch for the Finanzübersicht was committed as
docs/finanzuebersicht/1-server-script-fc_cockpit_data.py. A patch is made of
fragments from the middle of a function, so the file starts on an indented
line; as a module that is an IndentationError, and it blocked a release. The
fragments live in Markdown now.

So the test covers the WHOLE repository, not just the app package: the file
that broke it was under docs/, which no test would otherwise have looked at.
"""

import os
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

#: Directories the release check has no business in either.
SKIP = {".git", "__pycache__", "node_modules", ".github", "env", "venv"}


def _python_files():
    for base, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIP]
        for name in files:
            if name.endswith(".py"):
                yield os.path.join(base, name)


class TestTheReleaseCanBeBuilt(unittest.TestCase):

    def test_every_python_file_parses(self):
        import ast

        broken = []
        for path in _python_files():
            with open(path, encoding="utf-8") as handle:
                source = handle.read()
            try:
                ast.parse(source, filename=path)
            except SyntaxError as exc:
                broken.append("{0}: {1}".format(
                    os.path.relpath(path, REPO), exc))

        self.assertEqual(
            broken, [],
            "Frappe Cloud compiles the whole repository at release time and "
            "refuses the build over any one of these. A file that is not "
            "meant to be a module -- a patch, a snippet, an example -- must "
            "not carry the .py extension.")

    def test_the_walk_actually_reaches_the_app(self):
        """A guard that walks nothing passes everything."""
        found = {os.path.relpath(p, REPO) for p in _python_files()}
        self.assertIn(os.path.join("kefiya", "hooks.py"), found)
        self.assertIn(os.path.join("kefiya", "utils", "client.py"), found)
        self.assertGreater(len(found), 50, found)
