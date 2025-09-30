#!/bin/bash

# See http://redsymbol.net/articles/unofficial-bash-strict-mode/ for benefit of these options
set -euo pipefail
IFS=$'\n\t'

# Note: `readlink -f` (long available in GNU coreutils) is available on macOS 12.3 and later
script_dir="$(cd -- "$(dirname -- "$(readlink -f "${BASH_SOURCE[0]}")")" &> /dev/null && pwd)"

lock_stack () {
    local stack_spec=${1:?}
    pdm run venvstacks lock --reset-lock='*' "$stack_spec"
}

for entry in "$script_dir/../examples/"*; do
    if [ -d "$entry" ]; then
        lock_stack "$entry/venvstacks.toml"
    fi
done
