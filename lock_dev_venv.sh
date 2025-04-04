#!/bin/bash
if [ "$1" != "--skip-lock" ]; then
    # pdm doesn't offer a shorthand that says "update lock for all targets",
    # so we list out all the potential target testing platforms here
    pdm lock --dev          --platform=manylinux_2_17_x86_64
    pdm lock --dev --append --platform=manylinux_2_17_aarch64
    pdm lock --dev --append --platform=musllinux_1_1_x86_64
    pdm lock --dev --append --platform=windows_amd64
    pdm lock --dev --append --platform=windows_arm64
    pdm lock --dev --append --platform=macos_x86_64
    pdm lock --dev --append --platform=macos_arm64
fi
# Allow bootstrapping `pdm` in CI environments
# with the command `pip install --upgrade -r ci-bootstrap-requirements.txt`
ci_bootstrap_file="ci-bootstrap-requirements.txt"
pdm export --dev --no-default --group bootstrap -o "$ci_bootstrap_file"
echo "Exported $ci_bootstrap_file"
# Also support passing the CI version pins as constraints to any `pip install` command
ci_constraints_file="ci-constraints.txt"
pdm export --dev --no-extras -o "$ci_constraints_file"
echo "Exported $ci_constraints_file"
# Export the docs build dependencies for the sphinx build (no hashes due to the self install)
docs_requirements_file="docs/requirements.txt"
pdm export --dev --no-default --group docs --self --no-hashes -o "$docs_requirements_file"
echo "Exported $docs_requirements_file"
# Export the docs build dependencies for the dynlib wheel building environment
wheel_build_requirements_file="tests/local_wheel_project/build-requirements.txt"
pdm export --dev --no-default --group dynlib-wheel-build -o "$wheel_build_requirements_file"
echo "Exported $wheel_build_requirements_file"
