"""Command line interface implementation."""

import os.path
import sys

from typing import Annotated, Iterable, Sequence

import typer

from .stacks import (
    BuildEnvironment,
    EnvStackError,
    EnvNameBuild,
    PackageIndexConfig,
    StackSpec,
    _format_json,
    _UI,
)
from ._ui.render import format_stack_status

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
    name=_get_usage_name(),
    add_completion=False,
    pretty_exceptions_show_locals=False,
    no_args_is_help=False,
)


@_cli.callback(no_args_is_help=True)
def handle_app_options(
    ctx: typer.Context,
    version: Annotated[bool, typer.Option("--version", "-V", is_eager=True)] = False,
    verbose: Annotated[int, typer.Option("--verbose", "-v", count=True)] = 0,
    quiet: Annotated[bool, typer.Option("--quiet", "-q")] = False,
) -> None:
    """Lock, build, and publish Python virtual environment stacks."""
    if version:
        from importlib.metadata import version as get_version

        # Distribution name is the same as the top level package import name
        package_name = __name__.partition(".")[0]
        version_info = get_version(package_name)
        print(f"{package_name}: {version_info}")
        raise typer.Exit()
    _UI.set_verbosity(-1 if quiet else verbose)
    _UI.configure_app_logging()


_cli_subcommand = _cli.command(no_args_is_help=False)

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
_CLI_OPT_FLAG_if_needed = Annotated[
    bool,
    typer.Option(help="Skip locking layers that already have valid layer locks")
]  # fmt: skip
_CLI_OPT_FLAG_lock_if_needed = Annotated[
    bool,
    typer.Option(help="Update outdated layer lock files before building")
]  # fmt: skip
_CLI_OPT_FLAG_lock = Annotated[
    bool,
    typer.Option(help="(DEPRECATED) Compatibility alias for --lock-if-needed")
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
_CLI_OPT_STRLIST_reset_lock = Annotated[
    list[str] | None,
    typer.Option(
        help="Delete existing layer lock file before locking specified layer.\n"
        "Option may be supplied multiple times to match multiple layer names.\n"
        "Also accepts Python 'fnmatch' syntax to match multiple layer names.\n"
        "Only layers selected for locking will have their lock files reset.\n"
        "If this option is omitted, packages are only updated as necessary."
    ),
]
_CLI_OPT_FLAG_allow_missing = Annotated[
    bool,
    typer.Option(help="Allow layer filtering entries that do not match any layers"),
]  # fmt: skip

# Handling layers that included layers depend on
_CLI_OPT_FLAG_lock_dependencies = Annotated[
    bool,
    typer.Option(help="Also lock dependencies of included layers"),
]  # fmt: skip
_CLI_OPT_FLAG_build_dependencies = Annotated[
    bool,
    typer.Option(help="Also build dependencies of included layers"),
]  # fmt: skip
_CLI_OPT_FLAG_publish_dependencies = Annotated[
    bool,
    typer.Option(help="Also publish dependencies of included layers"),
]  # fmt: skip
_CLI_OPT_TRISTATE_include_dependencies = Annotated[
    bool | None,
    typer.Option(help="All operations include dependencies of included layers"),
]  # fmt: skip

# Handling layers that depend on included layers
# Note: when locking, layers that depend on included layers are *always* relocked
_CLI_OPT_FLAG_build_derived = Annotated[
    bool,
    typer.Option(help="Also build environments that depend on included layers"),
]  # fmt: skip
_CLI_OPT_FLAG_publish_derived = Annotated[
    bool,
    typer.Option(help="Also publish archives that depend on included layers"),
]  # fmt: skip

# Additional console output control
_CLI_OPT_FLAG_show = Annotated[
    bool,
    typer.Option(help="Show stack specification and selected operations"),
]  # fmt: skip
_CLI_OPT_FLAG_show_only = Annotated[
    bool,
    typer.Option(help="*Only* show stack specification and selected operations"),
]  # fmt: skip
_CLI_OPT_FLAG_json = Annotated[
    bool,
    typer.Option(help="Emit stack info as JSON rather than as formatted text"),
]  # fmt: skip


def _define_build_environment(
    spec_path: str,
    build_path: str,
    *,
    index: bool = False,
    local_wheels: Sequence[str] | None = None,
) -> BuildEnvironment:
    """Load given stack specification and define a build environment."""
    index_config = PackageIndexConfig(
        query_default_index=index,
        local_wheel_dirs=local_wheels,
    )
    stack_spec = StackSpec.load(spec_path, index_config)
    return stack_spec.define_build_environment(build_path)


def _handle_layer_include_options(
    build_env: BuildEnvironment,
    include: Sequence[str] | None,
    *,
    allow_missing: bool,
    lock: bool | None,
    build: bool,
    publish: bool,
    lock_dependencies: bool,
    build_dependencies: bool,
    publish_dependencies: bool,
    build_derived: bool,
    publish_derived: bool,
    reset_locks: Sequence[str] | None,
) -> None:
    included_layers: Iterable[EnvNameBuild]
    if not include:
        # Include all layers (helper invocation is for lock reset filtering)
        included_layers = [env.env_name for env in build_env.all_environments()]
    else:
        included_layers, unmatched_patterns = build_env.filter_layers(include)
        if unmatched_patterns:
            err_details = f"No matching layers found for: {unmatched_patterns!r}"
            if allow_missing:
                _UI.warn(err_details)
            else:
                warning_hint = "Pass '--allow-missing' to convert to warning"
                _UI.error(f"{err_details}\n  {warning_hint}")
                raise typer.Exit(code=1)
    layers_to_reset: Iterable[EnvNameBuild]
    if not reset_locks:
        # No lock reset patterns -> don't reset any layers
        layers_to_reset = ()
    else:
        layers_to_reset, unmatched = build_env.filter_layers(reset_locks)
        if unmatched:
            err_details = f"No matching layers found for upgrade: {unmatched!r}"
            if allow_missing:
                _UI.warn(err_details)
            else:
                warning_hint = "Pass '--allow-missing' to convert to warning"
                _UI.error(f"{err_details}\n  {warning_hint}")
                raise typer.Exit(code=1)
    # Layer lock files are only reset if the layer actually gets locked,
    # so there's no explicit cross-check between included and reset layers
    build_env.select_layers(
        included_layers,
        lock=lock,
        build=build,
        publish=publish,
        lock_dependencies=lock_dependencies,
        build_dependencies=build_dependencies,
        publish_dependencies=publish_dependencies,
        build_derived=build_derived,
        publish_derived=publish_derived,
        reset_locks=layers_to_reset,
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
    _UI.echo("Archive creation skipped, reporting publishing request details:")
    _UI.echo(_format_json(dry_run_result))
    _UI.echo(f"Archives and metadata will be published to {base_output_path}")
    _UI.echo("Archive creation skipped (specify --publish to request archive build)")


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
    _UI.echo(manifest_path.read_text(encoding="utf-8"))
    _UI.echo(
        f"Full stack manifest saved to: {manifest_path.relative_to(base_output_path)}"
    )
    _UI.echo("Individual layer manifests:")
    for snippet_path in snippet_paths:
        _UI.echo(f"  {snippet_path.relative_to(base_output_path)}")
    _UI.echo("Generated artifacts:")
    for archive_path in archive_paths:
        _UI.echo(f"  {archive_path.relative_to(base_output_path)}")
    _UI.echo(f"All paths reported relative to {base_output_path}")


def _export_dry_run(
    build_env: BuildEnvironment,
    output_dir: str,
) -> None:
    base_output_path, dry_run_result = build_env.export_environments(
        output_dir,
        dry_run=True,
    )
    _UI.echo("Environment export skipped, reporting local export request details:")
    _UI.echo(_format_json(dry_run_result))
    _UI.echo(f"Environments will be exported to {base_output_path}")
    _UI.echo("Environment export skipped (specify --publish to request local export)")


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
    _UI.echo(manifest_path.read_text(encoding="utf-8"))
    _UI.echo(
        f"Full export manifest saved to: {manifest_path.relative_to(base_output_path)}"
    )
    _UI.echo("Individual manifests:")
    for snippet_path in snippet_paths:
        _UI.echo(f"  {snippet_path.relative_to(base_output_path)}")
    _UI.echo("Exported environments:")
    for env_path in env_paths:
        _UI.echo(f"  {env_path.relative_to(base_output_path)}")
    _UI.echo(f"All paths reported relative to {base_output_path}")


def _show_status(
    build_env: BuildEnvironment,
    *,
    show: bool = True,
    show_only: bool = False,
    json: bool = False,
    report_ops: bool = True,
    include_deps: bool = False,
) -> bool:
    if not (show or show_only or json):
        # Skip showing the stack, continue processing the running command
        return False
    stack_status = build_env.get_stack_status(
        report_ops=report_ops, include_deps=include_deps
    )
    _UI.echo(format_stack_status(stack_status, json=json))
    # Indicate whether the running command should terminate without further processing
    # json implies show_only if show is not set
    return show_only or (json and not show)


@_cli_subcommand
def show(
    # Required arguments: where to find the stack spec
    spec_path: _CLI_ARG_spec_path,
    # Optional directory arguments: where to find build artifacts
    build_dir: _CLI_OPT_STR_build_dir = "_build",
    # Selective processing of defined layers
    include: _CLI_OPT_STRLIST_include = None,
    allow_missing: _CLI_OPT_FLAG_allow_missing = False,
    # Additional console output control
    json: _CLI_OPT_FLAG_json = False,
) -> None:
    """Show summary of given virtual environment stack."""
    build_env = _define_build_environment(
        spec_path,
        build_dir,
    )
    # Update the various `want_*` flags on each environment
    # Note: CLI `publish` controls the `dry_run` flag on the `publish_artifacts` method call
    # We specify this as a `lock` command so both dependencies and derived layers are included,
    # but suppress actually displaying the enabled operations when reporting the stack status
    if include:
        _handle_layer_include_options(
            build_env,
            include,
            allow_missing=allow_missing,
            lock=True,
            build=False,
            publish=False,
            lock_dependencies=True,
            build_dependencies=False,
            publish_dependencies=False,
            build_derived=False,
            publish_derived=False,
            reset_locks=None,
        )
    else:
        build_env.select_operations(
            lock=True,
            build=False,
            publish=False,
        )
    # Some layers may implicitly have "lock-if-needed" and/or "build-if-needed" set
    # Explicitly skip displaying those for the dedicated "show" subcommand
    _show_status(build_env, json=json, report_ops=False, include_deps=True)


@_cli_subcommand
def build(
    # Required arguments: where to find the stack spec
    spec_path: _CLI_ARG_spec_path,
    # Optional directory arguments: where to put build and output artifacts
    build_dir: _CLI_OPT_STR_build_dir = "_build",
    output_dir: _CLI_OPT_STR_output_dir = "_artifacts",
    # Pipeline steps: cleaning, locking, building, and publishing archives
    clean: _CLI_OPT_FLAG_clean = False,
    lock_if_needed: _CLI_OPT_FLAG_lock_if_needed = False,
    build: _CLI_OPT_FLAG_build = True,
    publish: _CLI_OPT_FLAG_publish = False,
    # Package index access configuration
    index: _CLI_OPT_FLAG_index = True,
    local_wheels: _CLI_OPT_STRLIST_local_wheels = None,
    # Adjust naming of published archives and metadata files
    tag_outputs: _CLI_OPT_FLAG_tag_outputs = False,
    # Selective processing of defined layers
    include: _CLI_OPT_STRLIST_include = None,
    reset_lock: _CLI_OPT_STRLIST_reset_lock = None,
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
    # Additional console output control
    show: _CLI_OPT_FLAG_show = False,
    show_only: _CLI_OPT_FLAG_show_only = False,
    json: _CLI_OPT_FLAG_json = False,
    # Deprecated options
    lock: _CLI_OPT_FLAG_lock = False,
) -> None:
    """Build (/lock/publish) Python virtual environment stacks."""
    # Only update layer locks if the current lock is outdated
    # While "--lock" is deprecated, it's a soft deprecation, so no warning is emitted
    want_lock = None if lock_if_needed or lock else False
    if include_dependencies is not None:
        # Override the per-operation settings
        lock_dependencies = build_dependencies = publish_dependencies = (
            include_dependencies
        )
    build_env = _define_build_environment(
        spec_path,
        build_dir,
        index=index,
        local_wheels=local_wheels,
    )
    # Update the various `want_*` flags on each environment
    # Note: CLI `publish` controls the `dry_run` flag on the `publish_artifacts` method call
    if include or reset_lock:
        _handle_layer_include_options(
            build_env,
            include,
            allow_missing=allow_missing,
            lock=want_lock,
            build=build,
            publish=True,
            lock_dependencies=lock_dependencies,
            build_dependencies=build_dependencies,
            publish_dependencies=publish_dependencies,
            build_derived=build_derived,
            publish_derived=publish_derived,
            reset_locks=reset_lock,
        )
    else:
        build_env.select_operations(
            lock=want_lock,
            build=build,
            publish=True,
        )
    if _show_status(build_env, show=show, show_only=show_only, json=json):
        return
    build_env.create_environments(clean=clean, lock=want_lock)
    _publish_artifacts(
        build_env, output_dir, dry_run=not publish, force=clean, tag_outputs=tag_outputs
    )


@_cli_subcommand
def lock(
    # Required arguments: where to find the stack spec, and where to emit any output files
    spec_path: _CLI_ARG_spec_path,
    # Optional directory arguments: where to put build artifacts (must create envs to lock them)
    build_dir: _CLI_OPT_STR_build_dir = "_build",
    # Pipeline steps: cleaning is optional, locking may be skipped for layers with valid locks
    clean: _CLI_OPT_FLAG_clean = False,
    if_needed: _CLI_OPT_FLAG_if_needed = False,
    # Package index access configuration
    index: _CLI_OPT_FLAG_index = True,
    local_wheels: _CLI_OPT_STRLIST_local_wheels = None,
    # Selective processing of defined layers
    include: _CLI_OPT_STRLIST_include = None,
    reset_lock: _CLI_OPT_STRLIST_reset_lock = None,
    allow_missing: _CLI_OPT_FLAG_allow_missing = False,
    # Whether to lock the layers that the included layers depend on
    lock_dependencies: _CLI_OPT_FLAG_lock_dependencies = False,
    # When locking, layers that depend on included layers are *always* relocked
    # Additional console output control
    show: _CLI_OPT_FLAG_show = False,
    show_only: _CLI_OPT_FLAG_show_only = False,
    json: _CLI_OPT_FLAG_json = False,
) -> None:
    """Lock layer requirements for Python virtual environment stacks."""
    want_lock = None if if_needed else True
    build_env = _define_build_environment(
        spec_path,
        build_dir,
        index=index,
        local_wheels=local_wheels,
    )
    # Update the various `want_*` flags on each environment
    if include or reset_lock:
        _handle_layer_include_options(
            build_env,
            include,
            allow_missing=allow_missing,
            lock=want_lock,
            build=False,
            publish=False,
            lock_dependencies=lock_dependencies,
            build_dependencies=False,
            publish_dependencies=False,
            build_derived=False,
            publish_derived=False,
            reset_locks=reset_lock,
        )
    else:
        build_env.select_operations(
            lock=want_lock,
            build=False,
            publish=False,
        )
    if _show_status(build_env, show=show, show_only=show_only, json=json):
        return
    lock_results = build_env.lock_environments(clean=clean)
    if not lock_results:
        _UI.echo("No environments found to lock")
    else:
        base_output_path = os.path.commonpath(
            [env.locked_requirements_path for env in lock_results]
        )
        _UI.echo("Locked environments:")
        for env_lock in lock_results:
            relative_path = env_lock.locked_requirements_path.relative_to(
                base_output_path
            )
            _UI.echo(f"  {relative_path} (locked at: {env_lock.locked_at})")
        _UI.echo(f"All paths reported relative to {base_output_path}")


@_cli_subcommand
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
    # Additional console output control
    show: _CLI_OPT_FLAG_show = False,
    show_only: _CLI_OPT_FLAG_show_only = False,
    json: _CLI_OPT_FLAG_json = False,
) -> None:
    """Publish layer archives for Python virtual environment stacks."""
    build_env = _define_build_environment(
        spec_path,
        build_dir,
        # No locking or build steps will be invoked on the environment
        index=False,
        local_wheels=None,
    )
    # Update the various `want_*` flags on each environment
    # Note: CLI `publish` controls the `dry_run` flag on the `publish_artifacts` method call
    if include:
        _handle_layer_include_options(
            build_env,
            include,
            reset_locks=None,
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
    if _show_status(build_env, show=show, show_only=show_only, json=json):
        return
    _publish_artifacts(
        build_env, output_dir, force=force, dry_run=dry_run, tag_outputs=tag_outputs
    )


@_cli_subcommand
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
    # Additional console output control
    show: _CLI_OPT_FLAG_show = False,
    show_only: _CLI_OPT_FLAG_show_only = False,
    json: _CLI_OPT_FLAG_json = False,
) -> None:
    """Export layer environments for Python virtual environment stacks."""
    build_env = _define_build_environment(
        spec_path,
        build_dir,
        # No locking or build steps will be invoked on the environment
        index=False,
        local_wheels=None,
    )
    # Update the various `want_*` flags on each environment
    # Note: CLI `publish` controls the `dry_run` flag on the `publish_artifacts` method call
    if include:
        _handle_layer_include_options(
            build_env,
            include,
            reset_locks=None,
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
    if _show_status(build_env, show=show, show_only=show_only, json=json):
        return
    _export_environments(
        build_env,
        output_dir,
        force=force,
        dry_run=dry_run,
    )


def main(args: Sequence[str] | None = None) -> None:
    """Run the ``venvstacks`` CLI.

    If *args* is not given, defaults to using ``sys.argv``.
    """
    try:
        # Indirectly calls the relevant click.Command variant's `main` method
        # See https://click.palletsprojects.com/en/8.1.x/api/#click.BaseCommand.main
        _cli(args, windows_expand_args=False)
    except EnvStackError as exc:
        exc_type = type(exc)
        print(f"{exc_type.__name__}: {exc}")
        sys.exit(1)
