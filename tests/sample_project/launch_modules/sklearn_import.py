"""Sample launch module importing sklearn"""

import sklearn

if __name__ == "__main__":
    # The app-sklearn-import environment should NOT have access to pip or httpx
    from importlib.util import find_spec

    for disallowed in ("pip", "httpx"):
        if find_spec(disallowed):
            raise RuntimeError(f"Should not be able to import {disallowed!r}!")

    print("Environment launch module executed successfully")
