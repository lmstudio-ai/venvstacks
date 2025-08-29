"""Sphinx configuration for venvstacks documentation."""

# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = "venvstacks"
copyright = "2024, Element Labs Inc."
author = "LM Studio"
release = "latest" # Docs are currently unversioned


# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    # first-party extensions
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.duration",
    "sphinx.ext.extlinks",
    "sphinx.ext.intersphinx",
    "sphinx.ext.napoleon",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# Allow Markdown-style single backtick syntax for inline literals
default_role = "literal"

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "furo"
html_static_path: list[str] = []
pygments_style = "sphinx"
pygments_dark_style = "monokai"

# Docs are published directly to GitHub pages, consider them to be unversioned
html_title = "venvstacks documentation"
html_baseurl = "https://venvstacks.lmstudio.ai/"

# Disable the generation of the various indexes
html_use_modindex = False
html_use_index = False

# Show GitHub source icons
html_theme_options = {
    "source_repository": "https://github.com/lmstudio-ai/venvstacks/",
    "source_branch": "main",
    "source_directory": "docs/",
}

# -- Options for autosummary ----------------------------------------------------------

# API docs are being migrated over to custom narrative documentation
# (still using autodoc, but no generated stub files)
autosummary_generate = False


# -- Options for extlinks -------------------------------------------------------------

extlinks = {
    "issue": ("https://github.com/lmstudio-ai/venvstacks/issues/%s", "#%s"),
    "pr": ("https://github.com/lmstudio-ai/venvstacks/pull/%s", "PR #%s"),
    "pypi": ("https://pypi.org/project/%s/", "%s"),
    "toml": ("https://toml.io/en/v1.0.0#%s", "%s"),
    "uv-config": ("https://docs.astral.sh/uv/reference/settings/#%s", "%s"),
}
extlinks_detect_hardcoded_links = True

# -- Options for intersphinx ----------------------------------------------------------

intersphinx_mapping = {
    "pystd": ("https://docs.python.org/3", None),
    "packaging": ("https://packaging.python.org/en/latest/", None),
}


# -- Options for napoleon ------------------------------------------------------------

napoleon_google_docstring = True
napoleon_numpy_docstring = False
