"""Command line interface implementation"""

import os.path
import sys

from typing import Annotated

import typer

from .stacks import StackSpec, BuildEnvironment, _format_json, PackageIndexConfig

# Inspired by the Python 3.13+ `argparse` feature,
# but reports `python -m venvstacks` whenever `__main__`
# refers to something other than the entry point script,
# rather than trying to infer anything from the main
# module's `__spec__` attributes.
_THIS_PACKAGE = __spec__.parent


def _get_usage_name() -> str:
    exec_name = os.path.basename(sys.argv[0]).removesuffix(".exe")
    if exec_name == _THIS_PACKAGE:
        # Entry point wrapper, suggest direct execution
        return exec_name
    # Could be `python -m`, could be the test suite,
    # could be something else calling `venvstacks.cli.main`,
    # but treat it as `python -m venvstacks` regardless
    py_name = os.path.basename(sys.executable).removesuffix(".exe")
    return f"{py_name} -m {_THIS_PACKAGE}"


_cli = typer.Typer(
    add_completion=False,
    pretty_exceptions_show_locals=False,
    no_args_is_help=True,
)


@_cli.callback(name=_get_usage_name())
def handle_app_options() -> None:
    """Lock, build, and publish Python virtual environment stacks."""
    # TODO: Handle app logging config via main command level options
    #       Part of https://github.com/lmstudio-ai/venvstacks/issues/5


# The shared CLI argument and option annotations have to be module level globals,
# otherwise pylance complains about runtime variable use in type annotations
#
# Defined prefixes:
#
#   * _CLI_ARG: required argument (no option name, arbitrary type accepting a string arg)
#   * _CLI_OPT_FLAG: boolean option, must be True or False
#   * _CLI_OPT_TRISTATE: boolean option, but allows None to indicate "not set"
#   * _CLI_OPT_STR: optional string (defaulting to empty string to indicate "not set")
#   * _CLI_OPT_STRLIST: multi-value list of strings
#
# The unit tests ensure the internal consistency of the CLI command annotations

# Format skips below keep arg annotations from being collapsed onto fewer lines

# Required arguments: where to find the stack spec
_CLI_ARG_spec_path = Annotated[
    str,
    typer.Argument(help="Path to TOML file specifying layers to build")
]  # fmt: skip

# Optional directory arguments: where to put build and output artifacts
_CLI_OPT_STR_build_dir = Annotated[
    str,
    typer.Option(help="Directory (relative to spec) for intermediate build artifacts"),
]  # fmt: skip
_CLI_OPT_STR_output_dir = Annotated[
    str,
    typer.Option(help="Directory (relative to spec) for output artifacts and metadata"),
]  # fmt: skip

# Build pipeline steps: cleaning, locking, building, and publishing archives
_CLI_OPT_FLAG_clean = Annotated[
    bool,
    typer.Option(help="Remove existing environments before building")
]  # fmt: skip
_CLI_OPT_FLAG_lock = Annotated[
    bool,
    typer.Option(help="Update layer lock files before building")
]  # fmt: skip
_CLI_OPT_FLAG_build = Annotated[
    bool,
    typer.Option(help="Build layer environments")
]  # fmt: skip
_CLI_OPT_FLAG_publish = Annotated[
    bool,
    typer.Option(help="Create archives from built environments")
]  # fmt: skip

# Configuring the input artifact retrieval process
_CLI_OPT_FLAG_index = Annotated[
    bool,
    typer.Option(
        help="Query the default package index (PyPI) for installation artifacts"
    ),
]  # fmt: skip
_CLI_OPT_FLAG_allow_source = Annotated[
    bool,
    typer.Option(
        help="Allow implicit source builds (may affect archive reproducibility)"
    ),
]  # fmt: skip
_CLI_OPT_STRLIST_local_wheels = Annotated[
    list[str] | None,
    typer.Option(
        help="Additional directory (relative to spec) for locally built wheel archives"
    ),
]  # fmt: skip

# Adjust naming of published archives and metadata files
_CLI_OPT_FLAG_tag_outputs = Annotated[
    bool,
    typer.Option(help="Include platform and other details in published names")
]  # fmt: skip

# Archive publication options for the publish subcommand
_CLI_OPT_FLAG_force = Annotated[
    bool,
    typer.Option(help="Publish archive even if input metadata is unchanged")
]  # fmt: skip
_CLI_OPT_FLAG_dry_run = Annotated[
    bool,
    typer.Option(help="List archives that would be published")
]  # fmt: skip

# Selective processing of defined layers
_CLI_OPT_STRLIST_include = Annotated[
    list[str] | None,
    typer.Option(
        help="Include specified layer in requested operations.\n"
        "Option may be supplied multiple times to match multiple layer names.\n"
        "Also accepts Python 'fnmatch' syntax to match multiple layer names.\n"
        "If this option is omitted, all defined layers are included."
    ),
]
_CLI_OPT_FLAG_allow_missing = Annotated[
    bool,
    typer.Option(help="Allow '--include' entries that do not match any layers")
]  # fmt: skip

# Handling layers that included layers depend on
_CLI_OPT_FLAG_lock_dependencies = Annotated[
    bool,
    typer.Option(help="Also lock dependencies of included layers")
]  # fmt: skip
_CLI_OPT_FLAG_build_dependencies = Annotated[
    bool,
    typer.Option(help="Also build dependencies of included layers")
]  # fmt: skip
_CLI_OPT_FLAG_publish_dependencies = Annotated[
    bool,
    typer.Option(help="Also publish dependencies of included layers")
]  # fmt: skip
_CLI_OPT_TRISTATE_include_dependencies = Annotated[
    bool | None,
    typer.Option(help="All operations include dependencies of included layers"),
]  # fmt: skip

# Handling layers that depend on included layers
# Note: when locking, layers that depend on included layers are *always* relocked
_CLI_OPT_FLAG_build_derived = Annotated[
    bool,
    typer.Option(help="Also build environments that depend on included layers")
]  # fmt: skip
_CLI_OPT_FLAG_publish_derived = Annotated[
    bool,
    typer.Option(help="Also publish archives that depend on included layers")
]  # fmt: skip


def _define_build_environment(
    spec_path: str,
    build_path: str,
    *,
    index: bool,
    allow_source: bool,
    local_wheels: list[str] | None,
) -> BuildEnvironment:
    """Load given stack specification and define a build environment"""
    stack_spec = StackSpec.load(spec_path)
    index_config = PackageIndexConfig(
        query_default_index=index,
        allow_source_builds=allow_source,
        local_wheel_dirs=local_wheels,
    )
    return stack_spec.define_build_environment(build_path, index_config)


def _handle_layer_include_options(
    build_env: BuildEnvironment,
    include: list[str],
    allow_missing: bool,
    lock: bool,
    build: bool,
    publish: bool,
    lock_dependencies: bool,
    build_dependencies: bool,
    publish_dependencies: bool,
    build_derived: bool,
    publish_derived: bool,
) -> None:
    unmatched_patterns = build_env.get_unmatched_patterns(include)
    if unmatched_patterns:
        err_details = f"No matching layers found for: {unmatched_patterns!r}"
        if allow_missing:
            print(f"WARNING: {err_details}")
        else:
            warning_hint = "Pass '--allow-missing' to convert to warning"
            print(f"ERROR: {err_details}\n  {warning_hint}")
            raise typer.Exit(code=1)
    build_env.select_layers(
        include,
        lock=lock,
        build=build,
        publish=publish,
        lock_dependencies=lock_dependencies,
        build_dependencies=build_dependencies,
        publish_dependencies=publish_dependencies,
        build_derived=build_derived,
        publish_derived=publish_derived,
    )


def _publication_dry_run(
    build_env: BuildEnvironment,
    output_dir: str,
    tag_outputs: bool,
) -> None:
    base_output_path, dry_run_result = build_env.publish_artifacts(
        output_dir,
        dry_run=True,
        tag_outputs=tag_outputs,
    )
    print("Archive creation skipped, reporting publishing request details:")
    print(_format_json(dry_run_result))
    print(f"Archives and metadata will be published to {base_output_path}")
    print("Archive creation skipped (specify --publish to request archive build)")


def _publish_artifacts(
    build_env: BuildEnvironment,
    output_dir: str,
    force: bool,
    dry_run: bool,
    tag_outputs: bool,
) -> None:
    if dry_run:
        _publication_dry_run(build_env, output_dir, tag_outputs=tag_outputs)
        return
    manifest_path, snippet_paths, archive_paths = build_env.publish_artifacts(
        output_dir,
        force=force,
        tag_outputs=tag_outputs,
    )
    base_output_path = os.path.commonpath(
        [manifest_path, *snippet_paths, *archive_paths]
    )
    print(manifest_path.read_text(encoding="utf-8"))
    print(
        f"Full stack manifest saved to: {manifest_path.relative_to(base_output_path)}"
    )
    print("Individual layer manifests:")
    for snippet_path in snippet_paths:
        print(f"  {snippet_path.relative_to(base_output_path)}")
    print("Generated artifacts:")
    for archive_path in archive_paths:
        print(f"  {archive_path.relative_to(base_output_path)}")
    print(f"All paths reported relative to {base_output_path}")


def _export_dry_run(
    build_env: BuildEnvironment,
    output_dir: str,
) -> None:
    base_output_path, dry_run_result = build_env.export_environments(
        output_dir,
        dry_run=True,
    )
    print("Environment export skipped, reporting local export request details:")
    print(_format_json(dry_run_result))
    print(f"Environments will be exported to {base_output_path}")
    print("Environment export skipped (specify --publish to request local export)")


def _export_environments(
    build_env: BuildEnvironment,
    output_dir: str,
    force: bool,
    dry_run: bool,
) -> None:
    if dry_run:
        _export_dry_run(build_env, output_dir)
        return
    manifest_path, snippet_paths, env_paths = build_env.export_environments(
        output_dir,
        force=force,
    )
    base_output_path = os.path.commonpath([manifest_path, *snippet_paths, *env_paths])
    print(manifest_path.read_text(encoding="utf-8"))
    print(
        f"Full export manifest saved to: {manifest_path.relative_to(base_output_path)}"
    )
    print("Individual manifests:")
    for snippet_path in snippet_paths:
        print(f"  {snippet_path.relative_to(base_output_path)}")
    print("Exported environments:")
    for env_path in env_paths:
        print(f"  {env_path.relative_to(base_output_path)}")
    print(f"All paths reported relative to {base_output_path}")


@_cli.command()
def build(
    # Required arguments: where to find the stack spec
    spec_path: _CLI_ARG_spec_path,
    # Optional directory arguments: where to put build and output artifacts
    build_dir: _CLI_OPT_STR_build_dir = "_build",
    output_dir: _CLI_OPT_STR_output_dir = "_artifacts",
    # Pipeline steps: cleaning, locking, building, and publishing archives
    clean: _CLI_OPT_FLAG_clean = False,
    lock: _CLI_OPT_FLAG_lock = False,
    build: _CLI_OPT_FLAG_build = True,
    publish: _CLI_OPT_FLAG_publish = False,
    # Package index access configuration
    index: _CLI_OPT_FLAG_index = True,
    allow_source: _CLI_OPT_FLAG_allow_source = False,
    local_wheels: _CLI_OPT_STRLIST_local_wheels = None,
    # Adjust naming of published archives and metadata files
    tag_outputs: _CLI_OPT_FLAG_tag_outputs = False,
    # Selective processing of defined layers
    include: _CLI_OPT_STRLIST_include = None,
    allow_missing: _CLI_OPT_FLAG_allow_missing = False,
    # Handling layers that included layers depend on
    lock_dependencies: _CLI_OPT_FLAG_lock_dependencies = False,
    build_dependencies: _CLI_OPT_FLAG_build_dependencies = False,
    publish_dependencies: _CLI_OPT_FLAG_publish_dependencies = False,
    include_dependencies: _CLI_OPT_TRISTATE_include_dependencies = None,
    # Handling layers that depend on included layers
    # Note: when locking, layers that depend on included layers are *always* relocked
    build_derived: _CLI_OPT_FLAG_build_derived = False,
    publish_derived: _CLI_OPT_FLAG_publish_derived = False,
) -> None:
    """Build (/lock/publish) Python virtual environment stacks."""
    if include_dependencies is not None:
        # Override the per-operation settings
        lock_dependencies = build_dependencies = publish_dependencies = (
            include_dependencies
        )
    build_env = _define_build_environment(
        spec_path,
        build_dir,
        index=index,
        allow_source=allow_source,
        local_wheels=local_wheels,
    )
    # Update the various `want_*` flags on each environment
    # Note: CLI `publish` controls the `dry_run` flag on the `publish_artifacts` method call
    if include:
        _handle_layer_include_options(
            build_env,
            include,
            allow_missing=allow_missing,
            lock=lock,
            build=build,
            publish=True,
            lock_dependencies=lock_dependencies,
            build_dependencies=build_dependencies,
            publish_dependencies=publish_dependencies,
            build_derived=build_derived,
            publish_derived=publish_derived,
        )
    else:
        build_env.select_operations(
            lock=lock,
            build=build,
            publish=True,
        )
    build_env.create_environments(clean=clean, lock=lock)
    _publish_artifacts(
        build_env, output_dir, dry_run=not publish, force=clean, tag_outputs=tag_outputs
    )


@_cli.command()
def lock(
    # Required arguments: where to find the stack spec, and where to emit any output files
    spec_path: _CLI_ARG_spec_path,
    # Optional directory arguments: where to put build artifacts (must create envs to lock them)
    build_dir: _CLI_OPT_STR_build_dir = "_build",
    # Pipeline steps: cleaning is the only optional step for this subcommand
    clean: _CLI_OPT_FLAG_clean = False,
    # Package index access configuration
    index: _CLI_OPT_FLAG_index = True,
    allow_source: _CLI_OPT_FLAG_allow_source = False,
    local_wheels: _CLI_OPT_STRLIST_local_wheels = None,
    # Selective processing of defined layers
    include: _CLI_OPT_STRLIST_include = None,
    allow_missing: _CLI_OPT_FLAG_allow_missing = False,
    # Whether to lock the layers that the included layers depend on
    lock_dependencies: _CLI_OPT_FLAG_lock_dependencies = False,
    # When locking, layers that depend on included layers are *always* relocked
) -> None:
    """Lock layer requirements for Python virtual environment stacks."""
    build_env = _define_build_environment(
        spec_path,
        build_dir,
        index=index,
        allow_source=allow_source,
        local_wheels=local_wheels,
    )
    # Update the various `want_*` flags on each environment
    if include:
        _handle_layer_include_options(
            build_env,
            include,
            allow_missing=allow_missing,
            lock=True,
            build=False,
            publish=False,
            lock_dependencies=lock_dependencies,
            build_dependencies=False,
            publish_dependencies=False,
            build_derived=False,
            publish_derived=False,
        )
    else:
        build_env.select_operations(
            lock=True,
            build=False,
            publish=False,
        )
    lock_results = build_env.lock_environments(clean=clean)
    if not lock_results:
        print("No environments found to lock")
    else:
        base_output_path = os.path.commonpath(
            [env.requirements_path for env in lock_results]
        )
        print("Locked environments:")
        for env_lock in lock_results:
            relative_path = env_lock.requirements_path.relative_to(base_output_path)
            print(f"  {relative_path} (locked at: {env_lock.locked_at})")
        print(f"All paths reported relative to {base_output_path}")


@_cli.command()
def publish(
    # Required arguments: where to find the stack spec, and where to emit any output files
    spec_path: _CLI_ARG_spec_path,
    # Optional directory arguments: where to find build artifacts and put output artifacts
    build_dir: _CLI_OPT_STR_build_dir = "_build",
    output_dir: _CLI_OPT_STR_output_dir = "_artifacts",
    # Optional behaviour
    force: _CLI_OPT_FLAG_force = False,
    dry_run: _CLI_OPT_FLAG_dry_run = False,
    # Adjust naming of published archives and metadata files
    tag_outputs: _CLI_OPT_FLAG_tag_outputs = False,
    # Selective processing of defined layers
    include: _CLI_OPT_STRLIST_include = None,
    allow_missing: _CLI_OPT_FLAG_allow_missing = False,
    # Handling layers that included layers depend on
    publish_dependencies: _CLI_OPT_FLAG_publish_dependencies = False,
    # Handling layers that depend on included layers
    publish_derived: _CLI_OPT_FLAG_publish_derived = False,
) -> None:
    """Publish layer archives for Python virtual environment stacks."""
    build_env = _define_build_environment(
        spec_path,
        build_dir,
        # No locking or build steps will be invoked on the environment
        index=False,
        allow_source=False,
        local_wheels=None,
    )
    # Update the various `want_*` flags on each environment
    # Note: CLI `publish` controls the `dry_run` flag on the `publish_artifacts` method call
    if include:
        _handle_layer_include_options(
            build_env,
            include,
            allow_missing=allow_missing,
            lock=False,
            build=False,
            publish=True,
            lock_dependencies=False,
            build_dependencies=False,
            publish_dependencies=publish_dependencies,
            build_derived=False,
            publish_derived=publish_derived,
        )
    else:
        build_env.select_operations(
            lock=False,
            build=False,
            publish=True,
        )
    _publish_artifacts(
        build_env, output_dir, force=force, dry_run=dry_run, tag_outputs=tag_outputs
    )


@_cli.command()
def local_export(
    # Required arguments: where to find the stack spec, and where to emit any output files
    spec_path: _CLI_ARG_spec_path,
    # Optional directory arguments: where to find build artifacts and put output artifacts
    build_dir: _CLI_OPT_STR_build_dir = "_build",
    output_dir: _CLI_OPT_STR_output_dir = "_export",
    # Optional behaviour
    force: _CLI_OPT_FLAG_force = False,
    dry_run: _CLI_OPT_FLAG_dry_run = False,
    # Selective processing of defined layers
    include: _CLI_OPT_STRLIST_include = None,
    allow_missing: _CLI_OPT_FLAG_allow_missing = False,
    # Handling layers that included layers depend on
    publish_dependencies: _CLI_OPT_FLAG_publish_dependencies = False,
    # Handling layers that depend on included layers
    publish_derived: _CLI_OPT_FLAG_publish_derived = False,
) -> None:
    """Export layer environments for Python virtual environment stacks."""
    build_env = _define_build_environment(
        spec_path,
        build_dir,
        # No locking or build steps will be invoked on the environment
        index=False,
        allow_source=False,
        local_wheels=None,
    )
    # Update the various `want_*` flags on each environment
    # Note: CLI `publish` controls the `dry_run` flag on the `publish_artifacts` method call
    if include:
        _handle_layer_include_options(
            build_env,
            include,
            allow_missing=allow_missing,
            lock=False,
            build=False,
            publish=True,
            lock_dependencies=False,
            build_dependencies=False,
            publish_dependencies=publish_dependencies,
            build_derived=False,
            publish_derived=publish_derived,
        )
    else:
        build_env.select_operations(
            lock=False,
            build=False,
            publish=True,
        )
    _export_environments(
        build_env,
        output_dir,
        force=force,
        dry_run=dry_run,
    )


def main(args: list[str] | None = None) -> None:
    # Indirectly calls the relevant click.Command variant's `main` method
    # See https://click.palletsprojects.com/en/8.1.x/api/#click.BaseCommand.main
    _cli(args)
