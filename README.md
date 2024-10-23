Layered Virtual Environment Stacks for Python
=============================================

The `venvstacks` project uses Python's `sitecustomize.py` environment setup feature to
chain together three layers of Python virtual environments:

* "Runtime" layers: environment containing the desired version of a specific Python runtime
* "Framework" layers: environments containing desired versions of key Python frameworks
* "Application" layers: environments containing components to be launched directly

Application layer environments may include additional unpackaged Python launch modules or
packages for invocation with `python`'s `-m` switch.

This project does NOT support combining arbitrary virtual environments with each other.
Instead, it allows larger integrated applications to split up their Python dependencies into
distinct layers, without needing to download and install multiple copies of large
dependencies (such as the `pytorch` ML/AI framework). The environment stack specification
and build process helps ensure that shared dependencies are kept consistent across layers,
while unshared dependencies are free to vary across the application components that need them.

As an example, the main sample project used in the test suite defines the following layers:

* `cpython@3.11`: CPython 3.11 base runtime
* `cpython@3.12`: CPython 3.12 base runtime
* `framework-scipy`: example framework layer (based on 3.11 runtime)
* `framework-sklearn` example framework layer (based on 3.12 runtime)
* `framework-http-client`: example framework layer (based on 3.11 runtime)
* `app-scipy-import`: example app layer with a single framework and a simple launch module
* `app-scipy-client`: example app layer with two frameworks and a multi-file launch package
* `app-sklearn-import`: example of defining a platform specific app layer

Refer to `tests\sample_project\venvstacks.toml` for the full definition of this example.

To avoid relying on the Python ecosystem's still limited support for cross-platform
component installation, the stack build processes need to be executed on the target
platform (for example, by using an OS matrix in GitHub Actions).


Interactions with other packaging tools
---------------------------------------

The base runtime environment layers are installed with `pdm` (with the installed runtimes coming
from the `python-build-standalone` project). `pdm` is also used to manage the development
of the `venvstacks` project itself.

The layered framework and app environments are created with the standard library's `venv` module.

The Python packages in each layer are currently being installed directly with `pip`, but
are expected to eventually move to being installed with `uv` to reduce environment
setup times during builds.

Platform-specific environment locking for each layer is performed using
`uv pip compile`. Refer to `pyproject.toml` for the specific issues preventing
the adoption of `uv` for additional purposes.

`venvstacks` expects precompiled `wheel` archives to be available for all included
Python distribution packages. When this is not the case, other projects like
[`wagon`](https://pypi.org/project/wagon/#files) or
[`fromager`](https://pypi.org/project/fromager/)
may be useful in generating the required input archives.


Caveats and Limitations
-----------------------

* the `venvstacks` Python API is *not yet stable*. Any interface not specifically
  declared as stable in the documentation may be renamed or relocated without a
  deprecation period. API stabilisation (mostly splitting up the overly large
  `venvstacks.stacks` namespace) will be the trigger for the 1.0 milestone release.
* while the `venvstacks` CLI is broadly stable, there are still some specific areas
  where changes may occur (such as in the handling of relative paths).
* dynamic library dependencies across layers currently only work on Windows.
  There is a [proposal](https://github.com/lmstudio-ai/venvstacks/issues38) in
  place for resolving that limitation, but it has not yet been implemented.
* local exports to filesystems which do not support symlinks (such as `VFAT` and
  `FAT32`) are nominally supported (with symlinks being replaced by the files
  they refer to), but this support is *not* currently tested.


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
