from typing import Any, Protocol, TypeVar

SpinnerT = TypeVar("SpinnerT", bound="Spinner")


class Spinner(Protocol):
    def update(self, status: str) -> None: ...

    def __enter__(self: SpinnerT) -> SpinnerT: ...

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any, /) -> Any: ...


class RichProtocol(Protocol):
    def __rich__(self) -> str: ...
