#!/bin/bash

# See http://redsymbol.net/articles/unofficial-bash-strict-mode/ for benefit of these options
set -euo pipefail
IFS=$'\n\t'

# Where to save the list of changed filenames
output_target="${1:?}"

# Running the test suite updates the committed output files in place,
# allowing any discrepancies to be detected via "git status".
# Tests that update output files are specifically marked.
# Ignore return code, as the tests will fail when updates are needed.
# Make the tests explicitly chatting to allow debugging when they pass
# unexpectedly (failing to update the output when updates are expected)
tox -m test -- -m "expected_output" -vvs || true

# Emit the list of changed files (if any) to the specified output file
# Avoids setting a non-zero return code if `grep` doesn't match any lines
project_dir="tests/sample_project"
requirements_dir="$project_dir/requirements"
metadata_dir="$project_dir/expected_manifests"
changed_files="$(git status -uall --porcelain=1 -- "$requirements_dir" "$metadata_dir" | (grep -v '^ D' || true))"
if [ -n "$changed_files" ]; then
    echo "$changed_files" | sed -E 's/^ ?[^ ]* //' | tee "$output_target"
    path_anchor="tests/expected-output-config.toml"
    echo "Including '$path_anchor' to ensure paths are relative to test folder"
    echo "$path_anchor" >> "$output_target"
else
  echo "No changes to expected output detected"
  echo > "$output_target"
fi
