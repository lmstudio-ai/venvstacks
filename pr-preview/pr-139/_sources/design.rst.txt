-----------------
Design Discussion
-----------------

.. meta::
   :og:title: venvstacks Design - venvstacks Documentation
   :og:type: website
   :og:url: https://venvstacks.lmstudio.ai/design/
   :og:description: venvstacks Design Discussion - venvstacks Documentation

Project
=======

Why does ``venvstacks`` exist?
------------------------------

``venvstacks`` exists because LM Studio were looking for a way
to integrate Python based AI projects into their cross-platform
desktop application, and after trialling other potential mechanisms,
decided that there was a genuine gap in the Python packaging tooling
landscape, and invested in building something new to fill that need.


What other existing projects were considered?
---------------------------------------------

There were two primary existing projects considered as potential
solutions:

* :pypi:`wagon`
* :pypi:`conda-pack`

Similar to ``venvstacks``, ``wagon`` aims to avoid needing to download
Python packages on the target deployment system. However, it does
this by shipping the individual packages and creating fresh virtual
environments on the target system, which means much more work has to
happen at installation time. While ``venvstacks`` isn't able to completely
eliminate the need to adjust the deployed environments post-installation,
the amount of work needed is substantially less than if the environments
were being assembled from individual wheels on the target systems.

``conda-pack`` proved unsuitable not because of any limitations in
``conda-pack`` itself, but because ``conda``'s notion of
`environment stacking <https://docs.conda.io/projects/conda/en/latest/user-guide/tasks/manage-environments.html#nested-activation>`__
refers specifically to accessing the ``PATH`` entries for other
environments, it doesn't refer to being able combine ``sys.path``
across multiple environments.

Splitting environments into layers the way ``venvstacks`` does
also doesn't align well with the way the ``conda`` dependency
resolver works, so it ended up making more sense to design
``venvstacks`` to work with ``venv`` and ``pip``-style dependency
resolution.

The assorted "Python application packaging" utilities that produce
standalone platform native executables or Python :py:mod:`zipapp`
archives were eliminated from consideration as they lacked the ability
to readily share the large common framework components that feature
heavily in the Python AI ecosystem across different applications.


Technical
=========

Why use ``python-build-standalone`` for the base runtimes?
----------------------------------------------------------

The short answer to this question is "Because that's what :pypi:`pdm` uses,
and ``venvstacks`` was already using ``pdm`` as its project management tool".

The longer answer is that there's a genuinely strong alignment between the
properties that the ``python-build-standalone`` maintainers aim to provide
in their published binaries, and the characteristics that ``venvstacks``
needs in its base runtime layers.

Supporting additional base runtime layer providers (such as :pypi:`conda`)
could be a genuinely interesting capability, but there are no current
plans to implement such a mechanism.


.. _dynamic-linking:

How does dynamic linking work across layers?
--------------------------------------------

In some cases, binary extension modules in a Python package may depend
on dynamically linked libraries that are provided by a different Python
package. For example, :pypi:`PyTorch <torch>` supports using the nVidia
CUDA libraries published through the :pypi:`nvidia` PyPI project.

On Windows, finding these dependencies at runtime generally relies on the
package publishing them calling :func:`os.add_dll_directory` with the
relevant package subdirectory.

On Linux and macOS, making this example case work typically requires that
the nVidia CUDA libraries be installed into the *same* ``site-packages``
directory as the PyTorch extension modules, so they can be found via
the relative rpath added to the extension modules when they are built.

To allow for dynamic linking across layers (without relying on the use of
tools like :pypi:`dynamic-library` that require changes to the projects
involved), ``venvstacks`` does the following on Linux and macOS:

* when building environments, symbolic links to all shared object files
  that do not appear to be Python extension modules are added to a
  ``share/venv/dynlib`` folder inside the built environment.
* when building environments, the symlink to the base environment's
  Python runtime is renamed and replaced with a wrapper script that
  ensures the ``share/venv/dynlib`` folders of the linked layers are on
  the shared object loading path (``LD_LIBRARY_PATH`` on Linux,
  ``DYLD_LIBRARY_PATH`` on macOS) before invoking the Python runtime.

The additional library path entries are appended after any existing
entries, so these environment variables may still be set as normal
to indicate that alternative copies of the linked libraries should be
preferred.

.. versionchanged:: 0.4.0
   Added support for dynamic linking across layers on Linux and macOS
   (:ref:`release details <changelog-0.4.0>`).


Are there limitations on the permitted depth of layer dependency chains?
------------------------------------------------------------------------

There are no specifically enforced limits on how many framework layers are
added between an application environment and its underlying runtime environment.

However, each framework layer does add an extra ``sys.path`` entry on all platforms,
and an extra dynamic library loading path entry on Linux and macOS.

These additions may encounter Python runtime or platform limitations that make
it desirable to keep the dependency chains relatively short (no more than 5-10
total layers) rather than making the individual layers excessively granular.
If that kind of granularity in dependency declarations is desired, it may
be better to dynamically construct suitable virtual environments on the target
systems, rather than using ``venvstacks`` with a large number of framework layers.

.. versionchanged:: 0.4.0
   Added the ability for framework layers to depend on other framework layers
   instead of depending directly on a runtime layer
   (:ref:`release details <changelog-0.4.0>`).
