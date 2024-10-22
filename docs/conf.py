# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = "venvstacks"
copyright = "2024, LM Studio"
author = "LM Studio"
release = "0.1"


# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    # first-party extensions
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.duration",
    "sphinx.ext.extlinks",
    "sphinx.ext.intersphinx",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "furo"
html_static_path = ["_static"]

# Disable the generation of the various indexes
html_use_modindex = False
html_use_index = False


# -- Options for intersphinx ----------------------------------------------------------

# Run `tox -e regen-apidocs` to regenerate the API stub pages
autosummary_generate = False

# -- Options for intersphinx ----------------------------------------------------------

intersphinx_mapping = {
    "py": ("https://docs.python.org/3", None),
}


# -- Options for extlinks -------------------------------------------------------------

extlinks = {
    "issue": ("https://github.com/lmstudio/venvstacks/issues/%s", "#%s"),
    "pr": ("https://github.com/lmstudio/venvstacks/pull/%s", "PR #%s"),
    "pypi": ("https://pypi.org/project/%s/", "%s"),
}
