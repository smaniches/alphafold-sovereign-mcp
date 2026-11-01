#!/bin/bash -eu
# The CI workflow derives this hash-locked runtime closure from uv.lock,
# avoiding a second committed dependency snapshot. For standalone builds run:
# uv export --locked --no-dev --no-emit-project --format requirements-txt \
#   --output-file .clusterfuzzlite/requirements.txt
if [ ! -s .clusterfuzzlite/requirements.txt ]; then
    echo "Missing generated fuzzer dependencies: run uv export from uv.lock first" >&2
    exit 1
fi
pip3 install --require-hashes -r .clusterfuzzlite/requirements.txt
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
for fuzzer in fuzz/fuzz_*.py; do
    compile_python_fuzzer "$fuzzer"
done
