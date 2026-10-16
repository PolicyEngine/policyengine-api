"""Metaclass for classes that have a single shared instance per process."""

from typing import ClassVar


class Singleton(type):
    """Metaclass whose classes build one instance and return it on every later call."""

    _instances: ClassVar[dict[type, object]] = {}

    def __call__(cls, *args: object, **kwargs: object) -> object:
        """Return the shared instance, creating it on the first call.

        Arguments to later calls are ignored.
        """
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]
