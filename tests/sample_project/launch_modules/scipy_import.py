"""Sample launch module importing scipy"""

import scipy

if __name__ == "__main__":
    # The app-scipy-import environment should NOT have access to pip, sklearn or httpx
    from importlib.util import find_spec

    for disallowed in ("pip", "sklearn", "httpx"):
        if find_spec(disallowed):
            raise RuntimeError(f"Should not be able to import {disallowed!r}!")

    print("Environment launch module executed successfully")
