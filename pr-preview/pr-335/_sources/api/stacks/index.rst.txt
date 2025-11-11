venvstacks.stacks
=================

.. meta::
   :og:title: venvstacks.stacks API - venvstacks Documentation
   :og:type: website
   :og:url: https://venvstacks.lmstudio.ai/api/stacks/
   :og:description: venvstacks.stacks Python API - venvstacks Documentation

.. TODO: Replace the autosummary tables with:
           * inline docs for the high level interface and the exceptions
           * a stacks/metadata-details/ page
           * a stacks/archive-publication/ page
           * a stacks/local-exports/ page
           * a stacks/layer-specifications/ page
           * a stacks/layer-build-environments/ page
           * a stacks/build-configuration/ page

         Dedicated pages correspond to the sections below (except as noted).
         Page names contain hyphens to ensure they're not valid submodule names.

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
      LayerCategory
      LayerSpecMetadata
      LayerVariant
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
