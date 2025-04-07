import dynlib_publisher  # Needed for os.add_dll_directory on Windows
import dynlib_consumer

if __name__ == "__main__":
    # The app environment should NOT have access to pip
    from importlib.util import find_spec

    for disallowed in ("pip",):
        if find_spec(disallowed):
            raise RuntimeError(f"Should not be able to import {disallowed!r}!")

    result = dynlib_consumer.checkdynlib_sum(1, 2)
    if result != 3:
        raise RuntimeError(f"Expected 1+2=3, got {result}")

    print("Environment launch module executed successfully")
