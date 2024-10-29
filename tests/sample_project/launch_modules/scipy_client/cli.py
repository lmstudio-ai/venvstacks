"""Sample CLI helper module importing scipy and httpx"""

import numpy
import scipy
import httpx


def main():
    # The app-scipy-client environment should NOT have access to pip, or sklearn
    from importlib.util import find_spec

    for disallowed in ("pip", "sklearn"):
        if find_spec(disallowed):
            raise RuntimeError(f"Should not be able to import {disallowed!r}!")

    for module in (numpy, scipy, httpx):
        # This is just here to allow the launch modules to pass lint checks
        assert module.__spec__ is not None
        assert find_spec(module.__spec__.name) is not None

    print("Environment launch module executed successfully")
