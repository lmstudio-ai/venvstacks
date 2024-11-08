"""Sample launch module importing sklearn."""

import numpy
import scipy
import sklearn

if __name__ == "__main__":
    # The app-sklearn-import environment should NOT have access to pip or httpx
    from importlib.util import find_spec

    for disallowed in ("pip", "httpx"):
        if find_spec(disallowed):
            raise RuntimeError(f"Should not be able to import {disallowed!r}!")

    for module in (numpy, scipy, sklearn):
        # This is just here to allow the launch modules to pass lint checks
        assert module.__spec__ is not None
        assert find_spec(module.__spec__.name) is not None

    print("Environment launch module executed successfully")
