# -*- coding: utf-8 -*-
# Copyright (c) 2020 Nekokatt
# Copyright (c) 2021-present davfsa
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from pipelines import config
from pipelines import nox

STUBGEN_GENERATE = [
    "hikari/__init__.py",
    "hikari/api/__init__.py",
    "hikari/events/__init__.py",
    "hikari/impl/__init__.py",
    "hikari/interactions/__init__.py",
]


@nox.session(reuse_venv=True)
def mypy(session: nox.Session) -> None:
    """Perform static type analysis on Python source code using mypy."""
    session.install(
        "-r",
        "requirements.txt",
        "-r",
        "speedup-requirements.txt",
        "-r",
        "server-requirements.txt",
        *nox.dev_requirements("mypy", "formatting"),
    )

    _generate_stubs(session)

    session.run("mypy", "-p", config.MAIN_PACKAGE, "--config", config.PYPROJECT_TOML)
    session.run("mypy", "-p", config.EXAMPLE_SCRIPTS, "--config", config.PYPROJECT_TOML)


@nox.session(reuse_venv=True)
def generate_stubs(session: nox.Session) -> None:
    """Generate the stubs for the package."""
    session.install(*nox.dev_requirements("mypy", "formatting"))
    _generate_stubs(session)


def _generate_stubs(session: nox.Session) -> None:
    session.run("stubgen", *STUBGEN_GENERATE, "-o", ".", "--include-private", "--no-import")

    stub_paths = [f"{path}i" for path in STUBGEN_GENERATE]

    session.run("isort", *stub_paths)
    session.run("black", *stub_paths)

    for stub_path in stub_paths:
        with open(stub_path, "r") as fp:
            content = fp.read()

        with open(stub_path, "w") as fp:
            fp.write("# DO NOT MANUALLY EDIT THIS FILE!\n")
            fp.write("# This file was automatically generated by `nox -s generate-stubs`\n\n")
            fp.write(content)
