import venvstacks_testing_dynlib_consumer as dynlib_consumer

if __name__ == "__main__":
    # The app environment should NOT have access to pip
    from importlib.util import find_spec

    for disallowed in ("pip",):
        if find_spec(disallowed):
            raise RuntimeError(f"Should not be able to import {disallowed!r}!")

    dynlib_consumer.access_linked_lib()

    print("Environment launch module executed successfully")
