----------------------------
Essential Terms and Concepts
----------------------------

.. glossary::

   archive
      A packed environment layer for distribution and deployment. Contains
      either a fully built base runtime environment :term:`layer`, or
      else a built layered environment that depends on the other
      layers specified in its metadata.

   environment
   build environment
   deployed environment
   layered environment
      A base runtime environment (built from a base runtime layer definition),
      or a layered virtual environment (built from an application or framework
      layer definition).
      May be a build environment, or a deployed environment.
      Deployed environments may be created either directly (via local export),
      or indirectly (via archive creation and unpacking).
      Exported environments and archive deployments contain slightly
      different metadata (since there are no archive details in the
      exported environment metadata).

   export
   local export
      Locally publishing an environment on the same machine,
      skipping the archive-and-unpack step, and automatically
      running the post-installation step. Primarily intended
      to speed up development iteration cycles when testing
      stack builds and application layer launch modules, but may
      also be used to export environments that normally use symlinks
      to target filesystems which don't support them (such as USB keys).
      (Note that transferring USB keys between systems is still likely
      to run into problems related to absolute paths no longer being
      correct, as Windows drive letters and POSIX mount points are
      highly likely to differ across machines).

   layer
   application layer
   base runtime layer
   framework layer
      A definition of a set of Python requirements which will be pinned
      for building and publication as a single consolidated :term:`archive`.
      Layer definitions are categorised as follows:

      * *base runtime layers*: these layers specify a base Python runtime which
        is used as a foundation for one or more environment stacks. Any
        requirements specified as part of a base runtime layer are installed
        directly into the base runtime (there is no virtual environment defined).
      * *framework layers*: these layers primarily contain large dependencies
        (such as :pypi:`PyTorch <torch>`) which should not be published multiple times,
        even when they are used by multiple applications. Applications are
        constrained to use the versions of any packages installed in the
        framework layers they depend on. Each framework layer depends on a
        specific runtime layer.
      * *application layers*: these layers specify the actual deployed Python
        applications which embedding applications will invoke. Applications
        depend on one or more framework layers

   stack
   environment stack
      An application layer with its supporting framework and base runtime layers.

   stack specification
      A ``venvstacks.toml`` file that defines one or more environment stacks.
