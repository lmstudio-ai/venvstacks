#!/bin/bash

# See http://redsymbol.net/articles/unofficial-bash-strict-mode/ for benefit of these options
set -euo pipefail
IFS=$'\n\t'

output_folder="${1:?}"

mkdir -p "$output_folder"
export VENVSTACKS_EXPORT_TEST_ARTIFACTS="$output_folder"
export VENVSTACKS_FORCE_TEST_EXPORT=1

# Test the sample project with stdout display enabled
tox -m test -- -k test_build_is_reproducible -rA
