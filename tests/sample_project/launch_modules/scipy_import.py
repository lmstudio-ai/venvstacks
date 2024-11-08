"""Sample launch module importing scipy."""

import numpy
import scipy

if __name__ == "__main__":
    # The app-scipy-import environment should NOT have access to pip, sklearn or httpx
    from importlib.util import find_spec

    for disallowed in ("pip", "sklearn", "httpx"):
        if find_spec(disallowed):
            raise RuntimeError(f"Should not be able to import {disallowed!r}!")

    for module in (numpy, scipy):
        # This is just here to allow the launch modules to pass lint checks
        assert module.__spec__ is not None
        assert find_spec(module.__spec__.name) is not None

    print("Environment launch module executed successfully")
