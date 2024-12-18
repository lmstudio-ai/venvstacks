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
``venvstacks`` to work with ``venv`` and ``pip``.

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
