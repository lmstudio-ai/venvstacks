Virtual Environment Stacks for Python
=====================================

Machine learning and AI libraries for Python are big. Really big. Nobody wants to download
and install multiple copies of [PyTorch](https://pypi.org/project/torch/) or
[CUDA](https://pypi.org/project/cuda-python/) if they can reasonably avoid it.

``venvstacks`` allows you to package Python applications and all their dependencies into a
portable, deterministic format, *without* needing to include copies of these large Python
frameworks in every application archive.

It achieves this by using Python's `sitecustomize.py` environment setup feature to
chain together three layers of Python virtual environments:

* "Runtime" layers: environment containing the desired version of a specific Python runtime
* "Framework" layers: environments containing desired versions of key Python frameworks
* "Application" layers: environments containing components to be launched directly

Application layer environments may include additional unpackaged Python launch modules or
packages for invocation with `python`'s `-m` switch.

While the layers are archived and published separately, their dependency locking is integrated,
allowing the application layers to share dependencies installed in the framework layers,
and the framework layers to share dependencies installed in the runtime layers.

Refer to the [Project Overview](https://venvstacks.lmstudio.ai/overview/) for an
example of specifying, locking, building, and publishing a set of environment stacks.


Installing
----------

`venvstacks` is available from the [Python Package Index](https://pypi.org/project/venvstacks/),
and can be installed with [pipx](https://pypi.org/project/pipx/):

    $ pipx install venvstacks

Alternatively, it can be installed as a user level package (although this may
make future Python version upgrades more irritating):

    $ pip install --user venvstacks


Interactions with other packaging tools
---------------------------------------

The base runtime environment layers are installed with `pdm` (with the installed runtimes coming
from the `python-build-standalone` project). `pdm` is also used to manage the development
of the `venvstacks` project itself.

The layered framework and app environments are created with the standard library's `venv` module.

Platform-specific environment locking for each layer is performed using `uv pip compile`,
with the locked requirements for lower layers being used as constraints files when
locking layers that depend on them.

The Python packages in each layer are installed with `uv pip install`, with the override mechanism
being used to prevent installation of the packages provided by lower layers.

`venvstacks` expects precompiled `wheel` archives to be available for all included
Python distribution packages. When this is not the case, other projects like
[`wagon`](https://pypi.org/project/wagon/#files) or
[`fromager`](https://pypi.org/project/fromager/)
may be useful in generating the required input archives.


Caveats and Limitations
-----------------------

* This project does NOT support combining arbitrary virtual environments with each other.
  Instead, it allows larger integrated applications to split up their Python dependencies into
  distinct layers, without needing to download and install multiple copies of large
  dependencies (such as the PyTorch ML/AI framework). The environment stack specification
  and build process helps ensure that shared dependencies are kept consistent across layers,
  while unshared dependencies are free to vary across the application components that need them.
* The `venvstacks` Python API is *not yet stable*. Any interface not specifically
  declared as stable in the documentation may be renamed or relocated without a
  deprecation period. API stabilisation (mostly splitting up the overly large
  `venvstacks.stacks` namespace) will be the trigger for the 1.0 milestone release.
* While the `venvstacks` CLI is broadly stable, there are still some specific areas
  where changes may occur (such as in the handling of relative paths).
* Local exports to filesystems which do not support symlinks (such as `VFAT` and
  `FAT32`) are nominally supported (with symlinks being replaced by the files
  they refer to), but this support is *not* currently tested.
* To avoid relying on the Python ecosystem's still limited support for cross-platform
  component installation, the stack build processes need to be executed on the target
  platform (for example, by using an OS matrix in GitHub Actions).


Project History
---------------

The initial (and ongoing) development of the `venvstacks` project is being funded
by [LM Studio](https://lmstudio.ai/), where it serves as the foundation of
LM Studio's support for local execution of Python AI frameworks such as
[Apple's MLX](https://lmstudio.ai/blog/lmstudio-v0.3.4).

The use of "🐸" (frog) and "🦎" (newts are often mistaken for lizards and
vice-versa!) as the Unicode support test characters is a reference to the
internal LM Studio project that initially built and continues to maintain
`venvstacks`: Project Amphibian.
