==========================
Virtual Environment Stacks
==========================

``venvstacks`` uses Python's ``sitecustomize.py`` environment setup feature
to chain together three layers of Python virtual environments:

* "Runtime" layers: environments containing the desired version of a specific Python interpreter
* "Framework" layers: environments containing desired versions of key Python frameworks
* "Application" layers: environments containing components to be launched directly

Application layer environments may include additional unpackaged Python launch modules or
packages for invocation with ``python``'s :external+py:option:`-m` switch.

While the layers are archived and published separately, their dependency locking is integrated,
allowing the application layers to share dependencies installed in the framework layers,
and the framework layers to share dependencies installed in the runtime layers.

Refer to the :ref:`overview` for an example of
specifying, locking, building, and publishing a set of environment stacks.

.. _installing:

``venvstacks`` is available from the :pypi:`Python Package Index <venvstacks>`,
and can be installed with :pypi:`pipx` (or similar tools):

.. code-block:: console

   $ pipx install venvstacks

Alternatively, it can be installed as a user level package (although this may
make future Python version upgrades more irritating):

.. code-block:: console

   $ pip install --user venvstacks

.. toctree::
   :maxdepth: 2

   overview
   glossary
   design
   api/index
   development/index
   changelog
