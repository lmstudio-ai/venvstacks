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

      LayerExportRequest
      ExportMetadata
      ExportedEnvironmentPaths
      StackExportRequest

   .. rubric:: Layer Specifications

   .. autosummary::
      :toctree:
      :nosignatures:

      LayerSpecBase
      RuntimeSpec
      LayeredSpecBase
      FrameworkSpec
      ApplicationSpec

   .. rubric:: Layer Build Environments

   .. autosummary::
      :toctree:
      :nosignatures:

      LayerEnvBase
      RuntimeEnv
      LayeredEnvBase
      FrameworkEnv
      ApplicationEnv
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
