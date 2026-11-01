#!/bin/bash -eu
# This hash-locked export is committed intentionally: ClusterFuzzLite
# performs a fresh Git checkout inside its build container, not a mount of
# runner-generated files. CI verifies the export exactly matches uv.lock.
# To refresh after changing uv.lock, run:
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
