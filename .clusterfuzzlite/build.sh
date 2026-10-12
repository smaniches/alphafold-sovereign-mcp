#!/bin/bash -eu
# Hash-locked runtime dependencies (regenerate with
# `uv export --no-dev --no-emit-project --frozen -o .clusterfuzzlite/requirements.txt`);
# the project itself is imported from the source tree.
pip3 install --require-hashes -r .clusterfuzzlite/requirements.txt
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
for fuzzer in fuzz/fuzz_*.py; do
    compile_python_fuzzer "$fuzzer"
done
