"""Allow execution of the package as a script."""

from .cli import main

# Handle multiprocessing potentially re-running this module with a name other than `__main__`
if __name__ == "__main__":
    main()
