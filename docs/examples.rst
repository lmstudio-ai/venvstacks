.. _example-stacks:

--------------
Example Stacks
--------------

.. meta::
   :og:title: venvstacks Examples - venvstacks Documentation
   :og:type: website
   :og:url: https://venvstacks.lmstudio.ai/examples/
   :og:description: venvstacks Example Stacks - venvstacks Documentation

All of the examples shown on this page can be found in the `examples directory`_
on GitHub, together with their launch modules and their layer lock files.

.. _examples directory: https://github.com/lmstudio-ai/venvstacks/tree/main/examples

scikit-learn
============

This example is the one used in the :ref:`overview`. It illustrates sharing
two different framework layers between a pair of application layers.

The included scikit-learn demonstrations can be executed by running
``python -m sklearn_classification`` in the ``app-classification-demo``
environment or ``python -m sklearn_clustering`` in the
``app-clustering-demo`` environment.

.. literalinclude:: ../examples/sklearn/venvstacks.toml
  :language: TOML

The generated layer lock files, lock metadata files, and layer package summaries
for this stack can be found in the
`scikit-learn example stack's requirements folder <https://github.com/lmstudio-ai/venvstacks/tree/main/examples/sklearn/requirements>`__

JupyterLab
==========

This example illustrates the simplest possible usable stack definition:
a runtime layer with a single application layer.

Running ``python -m run_jupyterlab`` in the ``app-jupyterlab`` environment
will execute JupyterLab.

.. literalinclude:: ../examples/jupyterlab/venvstacks.toml
  :language: TOML

The generated layer lock files, lock metadata files, and layer package summaries
for this stack can be found in the
`JupyterLab example stack's requirements folder <https://github.com/lmstudio-ai/venvstacks/tree/main/examples/jupyterlab/requirements>`__

Apple MLX
=========

This example illustrates using the ``platforms`` field and ``uv`` configuration
to lock and build only for a subset of potential platforms, as well as using
the ``macosx_target`` and ``linux_target`` fields to indicate that wheels
targeting newer OS versions should be used than those that would otherwise
be selected by default.

This stack also demonstrates the way that ``venvstacks`` eliminates redundant
packages from the layer lock files when they have environment markers that will
never be true on the platforms targeted by that layer, as well as removing
environment markers that are always true for all of the targeted platforms.

Running ``python -m report_mlx_version`` in the ``app-mlx-example``,
``app-mlx-cuda-linux`` (Linux-only) or ``app-mlx-cuda-macos`` (macOS-only)
environments will report the MLX version available in that environment.
(Despite the name, ``app-mlx-cuda-macos`` does not actually use CUDA to run
MLX. The stack is set up to *attempt* to define and use an ``mlx[cuda]``
dependency on macOS in order to demonstrate irrelevant dependencies being
filtered out of the layer lock file).

.. literalinclude:: ../examples/mlx/venvstacks.toml
  :language: TOML

The generated layer lock files, lock metadata files, and layer package summaries
for this stack can be found in the
`Apple MLX example stack's requirements folder <https://github.com/lmstudio-ai/venvstacks/tree/main/examples/mlx/requirements>`__

PyTorch
=======

This example illustrates using the ``package_index`` field to install a
specific package (``torch``) from a non-default named package index in the
``uv`` configuration, with different layers specifying different indexes
to produce parallel application stacks running on the CPU and on CUDA 12.8.

This stack also demonstrates the use of ``index_overrides`` to allow a layer
to declare a dependency on two nominally conflicting framework layers such
that it will run with *either* of the layers installed.

Running ``python -m report_torch_cuda_version`` in the ``app-cpu``,
``app-cu128``or ``app-cu128-or-cpu`` environments will report the CUDA version
being used by PyTorch in that environment (``None`` indicates the use of the
CPU).

.. literalinclude:: ../examples/pytorch/venvstacks.toml
  :language: TOML

The generated layer lock files, lock metadata files, and layer package summaries
for this stack can be found in the
`PyTorch example stack's requirements folder <https://github.com/lmstudio-ai/venvstacks/tree/main/examples/pytorch/requirements>`__
