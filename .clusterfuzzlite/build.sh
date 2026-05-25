#!/bin/bash -eu
pip3 install .
for fuzzer in fuzz/fuzz_*.py; do
    compile_python_fuzzer "$fuzzer"
done
