"""Scope limits (acceptance group F): the server extension starts no processes, drives no
audio tool and does no speech-to-text. The operator CLI (cli.py) is a separate tool that
manages PulseAudio on purpose, so it is exempt."""

import ast
import pathlib
import re

PACKAGE = pathlib.Path(__file__).resolve().parent.parent
EXTENSION_MODULES = sorted(p for p in PACKAGE.glob("*.py") if p.name != "cli.py")
AUDIO_TOOLS = re.compile(r"\b(pactl|pacmd|sox|rec|parec|arecord)\b")
SPEECH_TO_TEXT = {"whisper", "faster_whisper", "vosk", "speech_recognition", "deepgram"}


def _trees():
    return [(p.name, ast.parse(p.read_text())) for p in EXTENSION_MODULES]


def _imported(tree):
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_scan_covers_the_server_modules():
    assert {"__init__.py", "routes.py", "sink.py"} <= {p.name for p in EXTENSION_MODULES}


def test_extension_starts_no_processes():
    # F1/F2: no subprocess import, no os.system / os.exec* / os.spawn* / os.popen call.
    for name, tree in _trees():
        assert "subprocess" not in _imported(tree), name
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "os"
            ):
                assert not re.match(r"(system|exec|spawn|popen)", node.attr), (
                    f"{name}: os.{node.attr}"
                )


def test_extension_names_no_audio_tool():
    # F1/F2: no string in the code names a PulseAudio or recorder command.
    for name, tree in _trees():
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
            ):
                assert not AUDIO_TOOLS.search(node.value), f"{name}: {node.value!r}"


def test_extension_imports_no_speech_to_text():
    # F3: no speech-to-text library is imported.
    for name, tree in _trees():
        assert not (_imported(tree) & SPEECH_TO_TEXT), name
