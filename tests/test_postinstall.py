"""Tests for venvstacks post-install script generation."""

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
    example_path = Path("/example/python/bin/python").absolute()
    example_version = "6.28"
    expected_pyvenv_cfg = _EXPECTED_PYVENV_CFG.format(
        python_home=str(example_path.parent),
        py_version=example_version,
        python_bin=str(example_path),
    )
    pyvenv_cfg = postinstall.generate_pyvenv_cfg(
        example_path,
        example_version,
    )
    assert pyvenv_cfg == expected_pyvenv_cfg


def test_sitecustomize_empty() -> None:
    assert postinstall.generate_sitecustomize([], []) is None


def _make_fake_paths(prefix: str, expected_line_fmt: str) -> tuple[list[Path], str]:
    # Ensure fake paths are absolute (regardless of platform)
    anchor = Path.cwd().anchor
    fake_dirs = [f"{anchor}{prefix}{n}" for n in range(5)]
    fake_paths = [Path(d) for d in fake_dirs]
    # Also report the corresponding block of expected `sitecustomize.py` lines
    expected_lines = "\n".join(expected_line_fmt.format(d) for d in fake_dirs)
    return fake_paths, expected_lines


def _make_pylib_paths() -> tuple[list[Path], str]:
    return _make_fake_paths("pylib", "addsitedir({!r})")


def _make_dynlib_paths() -> tuple[list[Path], str]:
    return _make_fake_paths("dynlib", "add_dll_directory({!r})")


def _make_missing_dynlib_paths() -> tuple[list[Path], str]:
    return _make_fake_paths("dynlib", "# Skipping {!r} (no such directory)")


def test_sitecustomize() -> None:
    pylib_paths, expected_lines = _make_pylib_paths()
    sc_text = postinstall.generate_sitecustomize(pylib_paths, [])
    assert sc_text is not None
    assert sc_text.startswith(postinstall._SITE_CUSTOMIZE_HEADER)
    assert expected_lines in sc_text
    assert "add_dll_directory(" not in sc_text
    assert "# Skipping" not in sc_text
    assert compile(sc_text, "_sitecustomize.py", "exec") is not None


def test_sitecustomize_with_dynlib() -> None:
    pylib_paths, expected_pylib_lines = _make_pylib_paths()
    dynlib_paths, expected_dynlib_lines = _make_dynlib_paths()
    sc_text = postinstall.generate_sitecustomize(
        pylib_paths, dynlib_paths, skip_missing_dynlib_paths=False
    )
    assert sc_text is not None
    assert sc_text.startswith(postinstall._SITE_CUSTOMIZE_HEADER)
    assert expected_pylib_lines in sc_text
    if hasattr(os, "add_dll_directory"):
        assert expected_dynlib_lines in sc_text
    else:
        assert "add_dll_directory(" not in sc_text
        assert "# Skipping" not in sc_text
    assert compile(sc_text, "_sitecustomize.py", "exec") is not None


def test_sitecustomize_with_missing_dynlib() -> None:
    pylib_paths, expected_pylib_lines = _make_pylib_paths()
    dynlib_paths, expected_dynlib_lines = _make_missing_dynlib_paths()
    sc_text = postinstall.generate_sitecustomize(pylib_paths, dynlib_paths)
    assert sc_text is not None
    assert sc_text.startswith(postinstall._SITE_CUSTOMIZE_HEADER)
    assert expected_pylib_lines in sc_text
    if hasattr(os, "add_dll_directory"):
        assert expected_dynlib_lines in sc_text
    else:
        assert "add_dll_directory(" not in sc_text
        assert "# Skipping" not in sc_text
    assert compile(sc_text, "_sitecustomize.py", "exec") is not None
