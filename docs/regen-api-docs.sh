#!/bin/bash

# See http://redsymbol.net/articles/unofficial-bash-strict-mode/ for benefit of these options
set -euo pipefail
IFS=$'\n\t'

echo "API docs regen disabled by default (as it overwrites existing edits)"
exit 1

# sphinx-autogen -o docs/api docs/api/venvstacks.*.rst
