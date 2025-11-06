-----------------------------
Building Packages from Source
-----------------------------

.. meta::
   :og:title: venvstacks Package Source Builds - venvstacks Documentation
   :og:type: website
   :og:url: https://venvstacks.lmstudio.ai/source-builds/
   :og:description: venvstacks Package Source Builds - venvstacks Documentation

Reproducible Builds
===================

``venvstacks`` is designed around ensuring that the layer archives that it
produces are `reproducible <https://reproducible-builds.org/>`__: if the same
stack definition is built again later with the same
`build environment <https://reproducible-builds.org/docs/perimeter/>`__,
then the resulting layer archives will be byte-for-byte identical with
those produced by the original stack build.

One of the ways this is achieved is by requiring that all Python packages
included in a stack build be provided as pre-built
`binary wheels <https://packaging.python.org/en/latest/specifications/binary-distribution-format/>`__.
This allows the layer lock files to record the exact binary hashes of their
expected inputs, while the deterministic installation process for binary wheels
avoids introducing variation into the layer archive output (avoiding the
potentially build location dependent aspects of wheel installation is the reason
some package features, such as direct execution scripts, are not available in
the layer environments created by ``venvstacks``).

While ``venvstacks`` does not natively support building components from source
references, some users may not wish to use publicly available binary artifacts,
or may depend on projects that don't provide such artifacts. This section
provides some suggestions and recommendations for handling these situations.

Building artifacts from source
==============================

The first task is determining which artifacts need to be built and then
actually building them.

Systematic builds of entire dependency trees
--------------------------------------------

The `Fromager <https://github.com/python-wheel-build/fromager>`__ project
is designed specifically for this task. Quoting the project's goals,
Fromager is designed to guarantee that:

* Every binary package you install was built from source in a reproducible
  environment compatible with your own.
* All dependencies are also built from source, no prebuilt binaries.
* The build tools themselves are built from source, ensuring a fully transparent toolchain.
* Builds can be customized for your needs:
  applying patches, adjusting compiler options, or producing build variants.

That last point includes ensuring that built components with external dynamic
library dependencies are linked against the desired versions of those libraries.

Note that building complex stacks with Fromager may require passing ``--skip-constraints``,
as ``venvstacks`` intentionally allows layers that don't depend on each other
to specify conflicting package version constraints.

Selective builds of required packages
-------------------------------------

If appropriately configured, Fromager can technically support this approach as
well. However, providing details of such a configuration is use case dependent
and hence beyond the scope of these build suggestions.

More commonly, the components that require building are found by repeatedly
running venvstacks and recording the list of projects that the locking failures
indicate do not have binary wheels available for installation.

Once that list of projects is available, a use case dependent mechanism can
then be used to coordinate downloading the source artifacts and producing
appropriately built wheels for the platforms of interest (essentially
undertaking an ad hoc approach to the problem that Fromager approaches
systematically).

Including private artifacts in layer builds
===========================================

Once the binary wheels are available, the second task is then to actually
include those wheels into the layer locking and building process.

Private index servers
---------------------

The primary recommended approach is to run the stack builds against a private
index server such as a self-hosted `depvi <https://doc.devpi.net/>`__ instance,
or a cloud-hosted repository service such as
JFrog's `Artifactory <https://jfrog.com/help/r/jfrog-artifactory-documentation/pypi-repositories>`__
or Astral's `pyx <https://astral.sh/pyx>`__.

These can be set up to serve as both a caching proxy for publicly available packages
*and* a host for privately built packages, allowing the stack builds to be
appropriately configured with a single ``tool.uv.index`` entry in the stack
definition file:

.. code:: toml

   [[tool.uv.index]]
   url = "https://internal.example.com/pyindex/"
   default = true

More complex arrangements using the 
:ref:`package_indexes <package-indexes>` and
:ref:`priority_indexes <priority-indexes>` layer specification settings are
also possible. The
`published examples <https://github.com/lmstudio-ai/venvstacks/tree/main/examples>`__
demonstrate such configurations using the public PyTorch repositories,
as those are the kinds of parallel build scenarios where the simple caching
proxy override approach may be insufficient.

.. _versionadded: 0.8.0
   Added support for ``uv`` configuration with layer specific adjustments
   (:ref:`release details <changelog-0.8.0>`).

Local wheel directories
-----------------------

Prior to the addition of index server configuration support, the only provided
mechanism for providing additional wheels to the layer locking and building
process was to pass the ``--local-wheels`` option to the ``venvstacks`` CLI.

This mechanism is still supported, with no plans to remove it, but there may
be some situations where ``uv`` will be unable to lock a stack defined this way,
while being able to successfully lock a stack that uses an appropriate index
server configuration instead.

.. _versionchanged: 0.8.0
   With the introduction of cross-platform layer lock files,
   wheels for all platforms should be present on the system
   used to lock the layers (:ref:`release details <changelog-0.8.0>`).
