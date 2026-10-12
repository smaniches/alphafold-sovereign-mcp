FROM gcr.io/oss-fuzz-base/base-builder-python@sha256:21f6fab17ace4dc76e1c56de91ee95d3d03da021df94b41056ba036f6c6f55e9

COPY .clusterfuzzlite/atheris.txt /tmp/atheris.txt
RUN pip3 install --require-hashes -r /tmp/atheris.txt

COPY . $SRC/alphafold-sovereign-mcp
WORKDIR $SRC/alphafold-sovereign-mcp

COPY .clusterfuzzlite/build.sh $SRC/build.sh
