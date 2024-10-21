#!/bin/python3
"""Utility library to convert Python virtual environments to portable archives"""

# This is conceptually inspired by conda-pack (but structured somewhat differently).
# venv-pack and venv-pack2 were considered, and may still be an option in the future,
# but for now, something narrowly focused on the needs of the venvstacks project
# is the preferred option.
#
# This is primarily about reducing the number of potential sources of bugs - while
# conda-pack appears to be reasonably well used, venv-pack/venv-pack2 are much less
# popular, as there's a competing approach for regular virtual environments in
# https://github.com/cloudify-cosmo/wagon (where an archive of pre-built wheels is
# shipped to target systems, and then `venv` and `pip` in `--no-index` mode are run
# directly on the target to create the deployed virtual environments).

# Requirements:
#
# * must work on Linux, Windows, macOS
# * internal symlinks are permitted but not required (e.g. on Windows)
# * relative external symlinks to adjacent folders are similarly permitted
# * external symlinks beyond that boundary are converted to hard links
# * zip archives are used on Windows, tar.xz archives on other platforms

# Allowances/limitations:
#
# * archives for a given target platform are built on the same platform
# * all entry point scripts are removed, as Python is explicitly invoked on target systems
# * environment activation scripts are dropped from the archives rather than fixed on target
# * all RECORD files are removed, as they may reference files with build dependent hashes
#   (specifically, scripts that have their shebang lines rewritten at install time)
# * all __pycache__ folders are omitted (as their contents incorporate absolute paths)
#
# Note: stacks.py covers dropping the activation scripts and files with shebang lines
#

import os
import shutil
import sys
import tempfile
import time

from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import cast, Any, Callable, TextIO

from ._util import as_normalized_path, StrPath, WINDOWS_BUILD as _WINDOWS_BUILD

_PRECOMPILATION_COMMANDS = """\
# Precompile Python library modules
from compileall import compile_dir
venv_pylib_path = venv_path / "lib"  # "Lib" on Windows, but Windows is not case sensitive
compile_dir(venv_pylib_path, optimize=0, quiet=True)
"""

_BASE_RUNTIME_POST_INSTALL_SCRIPT = (
    '''\
"""Base runtime post-installation script

* Precompiles all Python files in the library folder

This post-installation script is automatically injected when packing environments that
do NOT include a `pyvenv.cfg` file (i.e. base runtime environments)
"""
from pathlib import Path
venv_path = Path(__file__).parent

'''
    + _PRECOMPILATION_COMMANDS
)

_LAYERED_ENV_POST_INSTALL_SCRIPT = (
    '''\
"""Layered environment post-installation script

* Generates pyvenv.cfg based on the Python runtime executing this script
* Precompiles all Python files in the library folder

This post-installation script is automatically injected when packing environments that
would otherwise include a `pyvenv.cfg` file (as `pyvenv.cfg` files are not relocatable)
"""
from pathlib import Path
venv_path = Path(__file__).parent

# Generate `pyvenv.cfg` based on the deployed runtime location
import sys
venv_config_path = venv_path / "pyvenv.cfg"
runtime_executable_path = Path(sys.executable).resolve()
runtime_version = ".".join(map(str, sys.version_info[:3]))
venv_config = f"""\
home = {runtime_executable_path.parent}
include-system-site-packages = false
version = {runtime_version}
executable = {runtime_executable_path}
"""
venv_config_path.write_text(venv_config, encoding="utf-8")

'''
    + _PRECOMPILATION_COMMANDS
)

SymlinkInfo = tuple[Path, Path]


def convert_symlinks(
    env_dir: StrPath,
    containing_dir: StrPath | None = None,
) -> tuple[list[SymlinkInfo], list[SymlinkInfo]]:
    """Make env portable by making internal symlinks relative and external links hard

    If set, containing path must be a parent directory of the environment path and is
    used as the boundary for creating relative symlinks instead of hardlinks. If not set,
    the environment path itself is used as the boundary for creating relative symlinks.

    Returns a 2-tuple containing lists of internal relative link conversions and
    external hard link conversions. Each list contains source/target Path pairs.
    """
    env_path = as_normalized_path(env_dir)
    if containing_dir is None:
        containing_path = env_path
    else:
        containing_path = as_normalized_path(containing_dir)
        if not env_path.is_relative_to(containing_path):
            raise ValueError(
                f"{str(env_path)!r} is not within {str(containing_path)!r}"
            )

    relative_links = []
    external_links = []
    # Ensure internal symlinks are relative, collect external links for hardlink conversion.
    # The external links are *not* eagerly converted, so only the final link in any internal
    # symlink chains gets converted to a hard link.
    for file_path in env_path.rglob("*"):
        if not file_path.is_symlink():
            continue
        target_path = file_path.readlink()
        absolute_target_path = file_path.parent / target_path
        if not absolute_target_path.is_relative_to(containing_path):
            # Link target is outside the environment being packed,
            # so replace it with a hard link to the actual underlying file
            resolved_target_path = file_path.resolve()
            external_links.append((file_path, resolved_target_path))
            continue
        # Ensure symlinks within the containing path are relative
        expected_path = Path(
            os.path.relpath(str(absolute_target_path), start=str(file_path.parent))
        )
        if target_path == expected_path:
            # Symlink is already relative as desired
            continue
        # Convert absolute symlink to relative symlink
        file_path.unlink()
        file_path.symlink_to(expected_path)
        relative_links.append((file_path, file_path.readlink()))
    # Convert any external symlinks to a hard link instead
    for file_path, resolved_target_path in external_links:
        file_path.unlink()
        file_path.hardlink_to(resolved_target_path)
    return relative_links, external_links


def get_archive_path(archive_base_name: StrPath) -> Path:
    """Report the name of the archive that will be created for the given base name"""
    extension = ".zip" if _WINDOWS_BUILD else ".tar.xz"
    return Path(os.fspath(archive_base_name) + extension)


def _inject_postinstall_script(
    env_path: Path, script_name: str = "postinstall.py"
) -> Path:
    venv_config_path = env_path / "pyvenv.cfg"
    if venv_config_path.exists():
        # The venv config contains absolute paths referencing the base runtime environment
        # Remove it here, let the post-install script recreate it
        venv_config_path.unlink()
        script_contents = _LAYERED_ENV_POST_INSTALL_SCRIPT
    else:
        script_contents = _BASE_RUNTIME_POST_INSTALL_SCRIPT
    script_path = env_path / script_name
    script_path.write_text(script_contents, encoding="utf-8")
    return script_path


def _supports_symlinks(target_path: Path) -> bool:
    with tempfile.TemporaryDirectory(dir=target_path) as link_check_dir:
        link_check_path = Path(link_check_dir)
        link_path = link_check_path / "dest"
        try:
            os.symlink("src", link_path)
        except OSError:
            # Failed to create symlink under the target path
            return False
    # Successfully created a symlink under the target path
    return True


def export_venv(
    source_dir: StrPath,
    target_dir: StrPath,
    run_postinstall: Callable[[Path, Path], None] | None = None,
) -> Path:
    """Export the given build environment, skipping archive creation and unpacking

    * injects a suitable `postinstall.py` script for the environment being exported
    * excludes __pycache__ folders and package metadata RECORD files
    * replaces symlinks with copies on Windows or if the target doesn't support symlinks

    If supplied, *run_postinstall* is called with the path to the environment's Python
    interpreter and its postinstall script, allowing execution of the post-install
    script by the calling application. The post-install script is NOT implicitly
    executed by the export process.

    Returns the path to the exported environment.
    """
    source_path = as_normalized_path(source_dir)
    target_path = as_normalized_path(target_dir)
    excluded = shutil.ignore_patterns("__pycache__", "RECORD")
    # Avoid symlinks on Windows, as they need elevated privileges to create
    # Also avoid them if the target folder doesn't support symlink creation
    # (that way exports to FAT/FAT32/VFAT file systems should work, even if
    # it means some files end up getting duplicated on the target)
    # Otherwise, assume symlinks have already been converted with convert_symlinks
    target_path.mkdir(parents=True, exist_ok=True)
    publish_symlinks = not _WINDOWS_BUILD and _supports_symlinks(target_path)
    shutil.copytree(
        source_path,
        target_path,
        ignore=excluded,
        symlinks=publish_symlinks,
        dirs_exist_ok=True,
    )
    postinstall_path = _inject_postinstall_script(target_path)
    if run_postinstall is not None:
        run_postinstall(target_path, postinstall_path)
    return target_path


def create_archive(
    source_dir: StrPath,
    archive_base_name: StrPath,
    *,
    install_target: str | None = None,
    clamp_mtime: datetime | None = None,
    work_dir: StrPath | None = None,
    show_progress: bool = True,
) -> Path:
    """shutil.make_archive replacement, tailored for Python virtual environments

    * injects a suitable `postinstall.py` script for the environment being archived
    * always creates zipfile archives on Windows and xztar archives elsewhere
    * excludes __pycache__ folders and package metadata RECORD files
    * replaces symlinks with copies on Windows and allows external symlinks elsewhere
    * discards owner and group information for tar archives
    * clamps mtime of archived files to the given clamp mtime at the latest
    * shows progress reporting by default (archiving built ML/AI libs is *slooooow*)

    Set `work_dir` if /tmp is too small for archiving tasks
    """
    archive_path = as_normalized_path(archive_base_name)
    source_path = Path(source_dir)
    if install_target is None:
        install_target = source_path.name
    with tempfile.TemporaryDirectory(dir=work_dir) as tmp_dir:
        target_path = Path(tmp_dir) / install_target
        env_path = export_venv(source_path, target_path)
        if not show_progress:

            def report_progress(_: Any) -> None:
                pass
        else:
            progress_bar = ProgressBar()
            progress_bar.show(0.0)
            num_archive_entries = 0
            total_entries_to_archive = sum(1 for __ in env_path.rglob("*"))

            def report_progress(_: Any) -> None:
                nonlocal num_archive_entries
                num_archive_entries += 1
                progress_bar.show(num_archive_entries / total_entries_to_archive)

        max_mtime: int | None = None
        if clamp_mtime is not None:
            # We force UTC here as all builds should be happening on a filesystem that uses
            # UTC timestamps (i.e. no FAT/FAT32/VFAT allowed).
            # That means NTFS on Windows and any vaguely modern POSIX filesystem elsewhere.
            # To avoid filesystem time resolution quirks without relying on the resolution
            # details of the various archive formats, truncate mtime to exact seconds
            max_mtime = int(clamp_mtime.astimezone(timezone.utc).timestamp())
        archive_with_extension = _make_archive(
            archive_path, env_path.parent, env_path.name, max_mtime, report_progress
        )
        if show_progress:
            # Ensure progress bar completion is reported, even if there's a discrepancy
            # between the number of paths found by `rglob` and the number of archive entries
            progress_bar.show(1.0)
    # The name query and the archive creation should always report the same archive name
    assert archive_with_extension == os.fspath(get_archive_path(archive_base_name))
    return Path(archive_with_extension)


# Would prefer to use shutil.make_archive, but the way it works doesn't quite fit this case
# _make_tar_archive below is adjusted to be similar to make_archive, but adapted from
# https://github.com/python/cpython/blob/99d945c0c006e3246ac00338e37c443c6e08fc5c/Lib/shutil.py#L930
# to work around the limitations mentioned in https://github.com/python/cpython/issues/120036
# Puts this utility module under the Python License, but the runtime layers already include
# CPython, so also using it in the build utility doesn't introduce any new licensing concerns
ProgressCallback = Callable[[str], None]


def _make_tar_archive(
    base_name: StrPath,
    root_dir: StrPath,
    base_dir: StrPath,
    max_mtime: float | None = None,
    progress_callback: ProgressCallback | None = None,
    *,
    compress: str = "xz",
) -> str:
    """Create a (possibly compressed) tar file from all the files under
    'base_dir'.

    'compress' must be "gzip", "bzip2", "xz", or None.

    Owner and group info is always set to 0/"root" as per
    https://reproducible-builds.org/docs/archives/.

    The output tar file will be named 'base_name' +  ".tar", possibly plus
    the appropriate compression extension (".gz", ".bz2", or ".xz").

    Returns the output filename.
    """
    import tarfile  # lazy import since ideally shutil would handle everything

    # pylance complains if the tar_mode string is built dynamically
    if compress is None or compress == "":
        tar_mode = "w"
        compress_ext = ""
    elif compress == "gzip":
        tar_mode = "w:gz"
        compress_ext = ".gz"
    elif compress == "bzip2":
        tar_mode = "w:bz2"
        compress_ext = ".gz"
    elif compress == "xz":
        tar_mode = "w:xz"
        compress_ext = ".xz"
    else:
        raise ValueError(
            "bad value for 'compress', or compression format not "
            "supported : {0}".format(compress)
        )

    archive_name = os.fspath(base_name) + ".tar" + compress_ext
    archive_dir = os.path.dirname(archive_name)

    if archive_dir and not os.path.exists(archive_dir):
        os.makedirs(archive_dir)

    # Clamp mtime only if requested
    # Force to an int to keep mypy happy: https://github.com/python/typeshed/issues/12520
    # Once a mypy update is published with that issue fixed, this workaround can
    # be replaced by a minimum mypy version requirement in the dev dependencies.
    if max_mtime is None:
        _clamp_mtime = None
    else:
        truncated_max_mtime = int(max_mtime)

        def _clamp_mtime_impl(mtime: int | float) -> int:
            # pyright has a newer typeshed than mypy, so resort to a cast
            # on the input value until this entire workaround can be dropped
            return min(truncated_max_mtime, cast(int, mtime))

        # Work around for https://github.com/microsoft/pyright/issues/9114
        _clamp_mtime = _clamp_mtime_impl

    # Ensure archive entries are reproducible across repeated builds
    def _process_archive_entry(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo:
        # Omit owner & group info from build system
        tarinfo.uid = tarinfo.gid = 0
        tarinfo.uname = tarinfo.gname = "root"
        if _clamp_mtime is not None:
            tarinfo.mtime = _clamp_mtime(tarinfo.mtime)
        # Report progress if requested
        if progress_callback is not None:
            progress_callback(tarinfo.name)
        return tarinfo

    # creating the tarball
    tar = tarfile.open(archive_name, tar_mode)
    arcname = base_dir
    if root_dir is not None:
        base_dir = os.path.join(root_dir, base_dir)
    try:
        # In Python 3.7+, tar.add inherently adds entries in sorted order
        tar.add(base_dir, arcname, filter=_process_archive_entry)
    finally:
        tar.close()

    if root_dir is not None:
        archive_name = os.path.abspath(archive_name)
    return archive_name


# _make_zipfile below is adjusted to be similar to make_archive, but adapted from
# https://github.com/python/cpython/blob/99d945c0c006e3246ac00338e37c443c6e08fc5c/Lib/shutil.py#L1000

if _WINDOWS_BUILD:

    def set_mtime(fspath: str, mtime: int | float) -> None:
        # There's no `follow_symlinks` option available on Windows
        os.utime(fspath, (mtime, mtime))
else:

    def set_mtime(fspath: str, mtime: int | float) -> None:
        os.utime(fspath, (mtime, mtime), follow_symlinks=False)


def _make_zipfile(
    base_name: StrPath,
    root_dir: StrPath,
    base_dir: StrPath,
    max_mtime: float | None = None,
    progress_callback: ProgressCallback | None = None,
) -> str:
    """Create a zip file from all the files under 'base_dir'.

    The output zip file will be named 'base_name' + ".zip".  Returns the
    name of the output zip file.
    """
    import zipfile  # lazy import since ideally shutil would handle everything

    zip_filename = os.fspath(base_name) + ".zip"
    archive_dir = os.path.dirname(base_name)

    if archive_dir and not os.path.exists(archive_dir):
        os.makedirs(archive_dir)

    # Unlike _make_tar_archive, progress is reported from multiple places,
    # so define a dummy callback if no actual callback is given
    if progress_callback is None:

        def _default_progress_callback(_: Any) -> None:
            pass

        # Work around for https://github.com/microsoft/pyright/issues/9114
        progress_callback = _default_progress_callback

    # zipfile stores local timestamps: https://github.com/python/cpython/issues/123059
    # We don't want that, but zipfile doesn't currently provide a nice API to adjust the
    # timestamps when adding files to the archive, so we instead intentionally make the
    # filesystem timestamps *wrong* such that calling `time.localtime` reports a UTC time
    need_mtime_adjustment = time.localtime().tm_gmtoff != 0
    if not need_mtime_adjustment:
        # Local time is UTC anyway, so no timezone adjustment is needed
        def adjust_mtime(mtime: float) -> float:
            return mtime
    else:
        # Adjust filesystem mtime so `zipfile` sets the desired value in the archive entry
        # casts are needed due to https://github.com/python/mypy/issues/10067
        local_tz = cast(tzinfo, datetime.now().astimezone().tzinfo)
        local_tz_offset = cast(timedelta, local_tz.utcoffset(None))

        def adjust_mtime(mtime: float) -> float:
            # mtime is given here in UTC time. To get `zipfile` to see that time value
            # when calling `time.localtime`, we need to do a local -> UTC conversion on the
            # UTC timestamp, so `zipfile`'s UTC -> local conversion gives back the UTC time
            local_mtime = datetime.fromtimestamp(mtime).astimezone()
            adjusted_mtime = local_mtime - local_tz_offset
            return adjusted_mtime.timestamp()

    with zipfile.ZipFile(zip_filename, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if max_mtime is None:
            # Clamp mtime only if requested
            max_mtime = float("inf")

        def _add_zip_entry(fspath: str, arcname: str) -> None:
            fs_mtime = os.lstat(fspath).st_mtime
            zip_entry_mtime = adjust_mtime(min(fs_mtime, max_mtime))
            if zip_entry_mtime != fs_mtime:
                set_mtime(fspath, zip_entry_mtime)
            zf.write(fspath, arcname)

        arcname = os.path.normpath(base_dir)
        if root_dir is not None:
            base_dir = os.path.join(root_dir, base_dir)
        base_dir = os.path.normpath(base_dir)
        if arcname != os.curdir:
            _add_zip_entry(base_dir, arcname)
        for dirpath, dirnames, filenames in os.walk(base_dir):
            arcdirpath = dirpath
            if root_dir is not None:
                arcdirpath = os.path.relpath(arcdirpath, root_dir)
            arcdirpath = os.path.normpath(arcdirpath)
            dirnames.sort()  # Ensure recursion occurs in a consistent order
            for name in dirnames:
                path = os.path.join(dirpath, name)
                arcname = os.path.join(arcdirpath, name)
                _add_zip_entry(path, arcname)
                progress_callback(name)
            for name in sorted(filenames):
                path = os.path.join(dirpath, name)
                path = os.path.normpath(path)
                if os.path.isfile(path):
                    arcname = os.path.join(arcdirpath, name)
                    _add_zip_entry(path, arcname)
                    progress_callback(name)

    if root_dir is not None:
        zip_filename = os.path.abspath(zip_filename)
    return zip_filename


if _WINDOWS_BUILD:
    # No tar unpacking by default on windows, so use zipfile instead
    _make_archive = _make_zipfile
else:
    # Everywhere else, create XZ compressed tar archives
    _make_archive = _make_tar_archive

# Basic progress bar support, taken from my SO answer at
# https://stackoverflow.com/questions/3160699/python-progress-bar/78590319#78590319
# (since the code originated with me, it isn't subject to Stack Overflow's CC-BY-SA terms)
#
# I originally skipped this, but archiving pytorch (and similarly large AI/ML libraries)
# takes a long time, so you really need some assurance that progress is being made.
#
# If compression times are a significant problem, it would be worth moving in the same
# direction as conda-pack did, and implementing support for parallel compression (the
# compression libraries all drop the GIL when compressing data chunks, so this approach
# scales effectively up to the number of available CPUs)
ProgressSummary = tuple[int, str]
ProgressReport = tuple[str, ProgressSummary]


class ProgressBar:
    """Display & update a progress bar"""

    TEXT_ABORTING = "Aborting..."
    TEXT_COMPLETE = "Complete!"
    TEXT_PROGRESS = "Archiving"

    bar_length: int
    stream: TextIO
    _last_displayed_text: str | None
    _last_displayed_summary: ProgressSummary | None

    def __init__(self, bar_length: int = 25, stream: TextIO = sys.stdout) -> None:
        self.bar_length = bar_length
        self.stream = stream
        self._last_displayed_text = None
        self._last_displayed_summary = None

    def reset(self) -> None:
        """Forget any previously displayed text (affects subsequent call to show())"""
        self._last_displayed_text = None
        self._last_displayed_summary = None

    def _format_progress(self, progress: float, aborting: bool) -> ProgressReport:
        """Internal helper that also reports the number of completed increments"""
        bar_length = self.bar_length
        progress = float(progress)
        if progress >= 1:
            # Report task completion
            completed_increments = bar_length
            status = " " + self.TEXT_COMPLETE
            progress = 1.0
        else:
            # Truncate progress to ensure bar only fills when complete
            completed_increments = int(progress * bar_length)
            status = (" " + self.TEXT_ABORTING) if aborting else ""
        remaining_increments = bar_length - completed_increments
        bar_content = f"{'#'*completed_increments}{'-'*remaining_increments}"
        percentage = f"{progress*100:.2f}"
        progress_text = f"{self.TEXT_PROGRESS}: [{bar_content}] {percentage}%{status}"
        return progress_text, (completed_increments, status)

    def format_progress(self, progress: float, *, aborting: bool = False) -> str:
        """Format progress bar, percentage, and status for given fractional progress"""
        return self._format_progress(progress, aborting)[0]

    def show(self, progress: float, *, aborting: bool = False) -> None:
        """Display the current progress on the console"""
        progress_text, progress_summary = self._format_progress(progress, aborting)
        if progress_text == self._last_displayed_text:
            # No change to display output, so skip writing anything
            # (this reduces overhead on both interactive and non-interactive streams)
            return
        interactive = self.stream.isatty()
        if not interactive and progress_summary == self._last_displayed_summary:
            # For non-interactive streams, skip output if only the percentage has changed
            # (this avoids flooding the output on non-interactive streams that ignore '\r')
            return
        if not interactive or aborting or progress >= 1:
            # Final output or non-interactive output, so advance to next line
            line_end = "\n"
        else:
            # Interactive progress output, so try to return to start of current line
            line_end = "\r"
        sys.stdout.write(progress_text + line_end)
        sys.stdout.flush()
        self._last_displayed_text = progress_text
        self._last_displayed_summary = progress_summary
