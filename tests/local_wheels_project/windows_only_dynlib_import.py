import sys
import dynlib_publisher  # Needed for os.add_dll_directory on Windows

EXPECT_CONSUMER_IMPORT = sys.platform == "win32"

try:
    import dynlib_consumer
except ImportError:
    if EXPECT_CONSUMER_IMPORT:
        raise
else:
    if not EXPECT_CONSUMER_IMPORT:
        sys.exit("Successful import when it wasn't expected")


if __name__ == "__main__":
    # The app environment should NOT have access to pip
    from importlib.util import find_spec

    for disallowed in ("pip",):
        if find_spec(disallowed):
            raise RuntimeError(f"Should not be able to import {disallowed!r}!")

    if EXPECT_CONSUMER_IMPORT:
        result = dynlib_consumer.checkdynlib_sum(1, 2)
        if result != 3:
            raise RuntimeError(f"Expected 1+2=3, got {result}")

    print("Environment launch module executed successfully")
