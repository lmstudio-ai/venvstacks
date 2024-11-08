venvstacks.stacks
=================

.. warning::

   The Python API is *NOT YET STABLE*.
   Function, class, and method names may change between releases
   without any deprecation period.

.. automodule:: venvstacks.stacks

   .. rubric:: High Level Interface

   .. autosummary::
      :toctree:
      :nosignatures:

      StackSpec
      BuildEnvironment

   .. rubric:: Layer Metadata Components

   .. autosummary::
      :toctree:
      :nosignatures:

      LayerCategories
      LayerSpecMetadata
      LayerVariants
      TargetPlatform
      TargetPlatforms

   .. rubric:: Archive Publishing Results

   .. autosummary::
      :toctree:
      :nosignatures:

      ArchiveBuildMetadata
      ArchiveBuildRequest
      ArchiveHashes
      ArchiveMetadata
      PublishedArchivePaths
      StackPublishingRequest
      StackPublishingResult

   .. rubric:: Layer Export Results

   .. autosummary::
      :toctree:
      :nosignatures:

      EnvironmentExportRequest
      ExportMetadata
      ExportedEnvironmentPaths
      StackExportRequest

   .. rubric:: Layer Specifications

   .. autosummary::
      :toctree:
      :nosignatures:

      RuntimeSpec
      FrameworkSpec
      ApplicationSpec

   .. rubric:: Layer Build Environments

   .. autosummary::
      :toctree:
      :nosignatures:

      ApplicationEnv
      FrameworkEnv
      RuntimeEnv
      EnvironmentLock
      EnvironmentLockMetadata

   .. rubric:: Build Process Configuration

   .. autosummary::
      :toctree:
      :nosignatures:

      PackageIndexConfig

   .. rubric:: Exceptions

   .. autosummary::
      :toctree:
      :nosignatures:

      BuildEnvError
      EnvStackError
      LayerSpecError
