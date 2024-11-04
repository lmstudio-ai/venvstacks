"""Tests for venvstacks post-install script generation"""
import os

from pathlib import Path

from venvstacks._injected import postinstall

_EXPECTED_PYVENV_CFG = """\
home = {python_home}
include-system-site-packages = false
version = {py_version}
executable = {python_bin}
"""

def test_pyvenv_cfg() -> None:
    example_path = Path("/example/python/bin/python")
    example_version = "6.28"
    expected_pyvenv_cfg = _EXPECTED_PYVENV_CFG.format(
        python_home=str(example_path.parent),
        py_version=example_version,
        python_bin=str(example_path),
    )
    pyvenv_cfg = postinstall.generate_pyvenv_cfg(
        example_path, example_version,
    )
    assert pyvenv_cfg == expected_pyvenv_cfg

def test_sitecustomize_empty() -> None:
    assert postinstall.generate_sitecustomize([], []) is None

def _make_pylib_paths() -> tuple[list[Path], str]:
    pylib_dirs = [f"pylib{n}" for n in range(5)]
    pylib_paths = [Path(d) for d in pylib_dirs]
    expected_lines = "\n".join(f"addsitedir({d!r})" for d in pylib_dirs)
    return pylib_paths, expected_lines

def _make_dynlib_paths() -> tuple[list[Path], str]:
    dynlib_dirs = [f"dynlib{n}" for n in range(5)]
    dynlib_paths = [Path(d) for d in dynlib_dirs]
    expected_lines = "\n".join(f"add_dll_directory({d!r})" for d in dynlib_dirs)
    return dynlib_paths, expected_lines

def test_sitecustomize() -> None:
    pylib_paths, expected_lines = _make_pylib_paths()
    sc_text = postinstall.generate_sitecustomize(pylib_paths, [])
    assert sc_text is not None
    assert sc_text.startswith(postinstall._SITE_CUSTOMIZE_HEADER)
    assert expected_lines in sc_text
    assert "add_dll_directory(" not in sc_text
    assert compile(sc_text, "_sitecustomize.py", "exec") is not None

def test_sitecustomize_with_dynlib() -> None:
    pylib_paths, expected_pylib_lines = _make_pylib_paths()
    dynlib_paths, expected_dynlib_lines = _make_dynlib_paths()
    sc_text = postinstall.generate_sitecustomize(pylib_paths, dynlib_paths)
    assert sc_text is not None
    assert sc_text.startswith(postinstall._SITE_CUSTOMIZE_HEADER)
    assert expected_pylib_lines in sc_text
    if hasattr(os, "add_dll_directory"):
        assert expected_dynlib_lines in sc_text
    else:
        assert "add_dll_directory(" not in sc_text
    assert compile(sc_text, "_sitecustomize.py", "exec") is not None
