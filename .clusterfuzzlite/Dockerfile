FROM gcr.io/oss-fuzz-base/base-builder-python

RUN pip3 install atheris

COPY . $SRC/alphafold-sovereign-mcp
WORKDIR $SRC/alphafold-sovereign-mcp

COPY .clusterfuzzlite/build.sh $SRC/build.sh
