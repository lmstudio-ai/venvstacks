"""Sample CLI helper module importing scipy and httpx"""

import scipy
import httpx


def main():
    # The app-scipy-client environment should NOT have access to pip, or sklearn
    from importlib.util import find_spec

    for disallowed in ("pip", "sklearn"):
        if find_spec(disallowed):
            raise RuntimeError(f"Should not be able to import {disallowed!r}!")
    print("Environment launch module executed successfully")
