import contextlib
import enum
import logging
import os
import sys
import warnings
from typing import Any

import rich
from rich.console import Console
from rich.progress import Progress, ProgressColumn
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.theme import Theme

from ._types import RichProtocol, Spinner, SpinnerT

DEFAULT_THEME = {
    "primary": "cyan",
    "success": "green",
    "warning": "yellow",
    "error": "red",
    "info": "blue",
    "req": "bold green",
}
rich.reconfigure(highlight=False, theme=Theme(DEFAULT_THEME))
_err_console = Console(stderr=True, theme=Theme(DEFAULT_THEME))


def is_interactive(console: Console | None = None) -> bool:
    """Check if the terminal is run under interactive mode."""
    if console is None:
        console = rich.get_console()
    return "PDM_NON_INTERACTIVE" not in os.environ and console.is_interactive


def is_legacy_windows(console: Console | None = None) -> bool:
    """Legacy Windows renderer may have problem rendering emojis."""
    if console is None:
        console = rich.get_console()
    return console.legacy_windows


def style(text: str, *args: str, style: str | None = None, **kwargs: Any) -> str:
    """Return text with ansi codes using rich console.

    :param text: message with rich markup, defaults to "".
    :param style: rich style to apply to whole string
    :return: string containing ansi codes
    """
    _console = rich.get_console()
    if _console.legacy_windows or not _console.is_terminal:  # pragma: no cover
        return text
    with _console.capture() as capture:
        _console.print(text, *args, end="", style=style, **kwargs)
    return capture.get()


def confirm(*args: str, **kwargs: Any) -> bool:
    default = bool(kwargs.setdefault("default", False))
    if not is_interactive():
        return default
    return Confirm.ask(*args, **kwargs)


def ask(
    *args: str, prompt_type: type[str] | type[int] | None = None, **kwargs: Any
) -> str:
    """Prompt user and return response.

    :prompt_type: which rich prompt to use, defaults to str.
    :raises ValueError: unsupported prompt type
    :return: str of user's selection
    """
    if not prompt_type or prompt_type is str:
        return Prompt.ask(*args, **kwargs)
    elif prompt_type is int:
        return str(IntPrompt.ask(*args, **kwargs))
    else:
        raise ValueError(f"unsupported {prompt_type}")


class Verbosity(enum.IntEnum):
    QUIET = -1
    NORMAL = 0
    DETAIL = 1
    DEBUG = 2


MAX_VERBOSITY = Verbosity.DEBUG

LOG_LEVELS = {
    Verbosity.NORMAL: logging.WARN,
    Verbosity.DETAIL: logging.INFO,
    Verbosity.DEBUG: logging.DEBUG,
}


class Emoji:
    if is_legacy_windows():
        SUCC = "v"
        FAIL = "x"
        LOCK = " "
        POPPER = " "
        ELLIPSIS = "..."
        ARROW_SEPARATOR = ">"
    else:
        SUCC = ":heavy_check_mark:"
        FAIL = ":heavy_multiplication_x:"
        LOCK = ":lock:"
        POPPER = ":party_popper:"
        ELLIPSIS = "…"
        ARROW_SEPARATOR = "➤"


if is_legacy_windows():
    SPINNER = "line"
else:
    SPINNER = "dots"


class DummySpinner:
    """A dummy spinner class implementing needed interfaces.

    Simply displays text onto screen instead of updating a spinner.
    """

    def __init__(self, text: str) -> None:
        self.text = text

    def _show(self) -> None:
        _err_console.print(f"[primary]STATUS:[/] {self.text}")

    def update(self, status: str) -> None:
        self.text = status
        self._show()

    def __enter__(self: SpinnerT) -> SpinnerT:
        self._show()  # type: ignore[attr-defined]
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class SilentSpinner(DummySpinner):
    def _show(self) -> None:
        pass


class UI:
    """Terminal UI object."""

    def __init__(
        self,
        verbosity: Verbosity = Verbosity.NORMAL,
        *,
        exit_stack: contextlib.ExitStack | None = None,
    ) -> None:
        self.verbosity = verbosity
        self.exit_stack = exit_stack or contextlib.ExitStack()

    def set_verbosity(self, verbosity: int) -> None:
        self.verbosity = Verbosity(min(verbosity, MAX_VERBOSITY))
        if self.verbosity < Verbosity.NORMAL:
            self.exit_stack.enter_context(warnings.catch_warnings())
            warnings.simplefilter("ignore", FutureWarning, append=True)

    def set_theme(self, theme: Theme) -> None:
        """Set theme for rich console.

        :param theme: dict of theme
        """
        rich.get_console().push_theme(theme)
        _err_console.push_theme(theme)

    def echo(
        self,
        message: str | RichProtocol = "",
        err: bool = False,
        verbosity: Verbosity = Verbosity.NORMAL,
        **kwargs: Any,
    ) -> None:
        """Print message using rich console.

        :param message: message with rich markup, defaults to "".
        :param err: if true print to stderr, defaults to False.
        :param verbosity: verbosity level, defaults to NORMAL.
        """
        if self.verbosity >= verbosity:
            console = _err_console if err else rich.get_console()
            if not console.is_interactive:
                kwargs.setdefault("crop", False)
                kwargs.setdefault("overflow", "ignore")
            console.print(message, **kwargs)

    def always_echo(self, message: str) -> None:
        """Print a message to stdout, even in quiet mode."""
        self.echo(message, verbosity=Verbosity.QUIET)

    def configure_app_logging(self) -> None:
        """Set up basic logging configuration for the running application."""
        # In quiet mode, only log actual errors
        if self.verbosity < Verbosity.NORMAL:
            logging.basicConfig(level=logging.ERROR, stream=sys.stderr)
            return
        # Otherwise, log warnings from any module to the console
        logging.basicConfig(level=logging.WARN, stream=sys.stderr)
        if self.verbosity == Verbosity.NORMAL:
            # At normal verbosity, only show warnings and UI messages
            return
        # Otherwise, display the package's own log messages based on the verbosity
        base_package_name = __name__.partition(".")[0]
        app_logger = logging.getLogger(base_package_name)
        app_logger.setLevel(LOG_LEVELS[self.verbosity])
        app_logger.propagate = False
        info_handler = logging.StreamHandler(stream=sys.stdout)
        info_handler.setLevel(logging.DEBUG)
        info_handler.addFilter(lambda record: record.levelno < logging.WARN)
        info_handler.setFormatter(logging.Formatter("%(message)s"))
        app_logger.addHandler(info_handler)
        err_handler = logging.StreamHandler(stream=sys.stderr)
        err_handler.setLevel(logging.WARN)
        app_logger.addHandler(err_handler)

    def open_spinner(self, title: str) -> Spinner:
        """Open a spinner as a context manager."""
        if self.verbosity >= Verbosity.DETAIL or not is_interactive():
            return DummySpinner(title)
        else:
            return _err_console.status(title, spinner=SPINNER, spinner_style="primary")

    def make_progress(self, *columns: str | ProgressColumn, **kwargs: Any) -> Progress:
        """Create a progress instance for indented spinners."""
        return Progress(*columns, disable=self.verbosity >= Verbosity.DETAIL, **kwargs)

    def info(self, message: str, verbosity: Verbosity = Verbosity.NORMAL) -> None:
        """Print an info message to stderr."""
        self.echo(f"[info]INFO:[/] [dim]{message}[/]", err=True, verbosity=verbosity)

    def deprecated(self, message: str, verbosity: Verbosity = Verbosity.NORMAL) -> None:
        """Print a deprecation message to stderr."""
        self.echo(
            f"[warning]DEPRECATED:[/] [dim]{message}[/]", err=True, verbosity=verbosity
        )

    def warn(self, message: str, verbosity: Verbosity = Verbosity.NORMAL) -> None:
        """Print a warning message to stderr."""
        self.echo(f"[warning]WARNING:[/] {message}", err=True, verbosity=verbosity)

    def error(self, message: str, verbosity: Verbosity = Verbosity.QUIET) -> None:
        """Print an error message to stderr."""
        self.echo(f"[error]ERROR:[/] {message}", err=True, verbosity=verbosity)
