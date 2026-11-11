# Privacy Policy

## What this software is

AlphaFold Sovereign MCP is local-first, on-premises software. It is
not a SaaS. The software runs on your infrastructure, under your
control.

This document describes what the shipped server does with the values it
is given. It makes no statement about how any law or regulation applies
to a particular deployment.

## Data This Software Processes

The tools accept scientific identifiers and search text:

- **UniProt accessions** (e.g., `P12345`), **gene symbols**, and
  **Ensembl gene IDs**.
- **Variants in HGVS notation.**
- **Disease and phenotype identifiers**: MONDO IDs, HPO IDs, and
  ICD-10 codes.
- **Free-text search terms**, such as a disease name.
- Species names, numeric limits, thresholds, and option flags.

No tool has a field for a person's name, date of birth, contact
details, or record number, and no tool accepts a sequence or a file.
Input validation checks identifier formats and numeric ranges. It does
not look for personal information, so the software cannot tell whether
a variant or a search term relates to an identifiable person. Whatever
is supplied is handled as the sections below describe: it is sent to
the upstream service that answers the query, it can appear in the
server log, and the result is returned to the MCP client that made the
call. Deciding which values may be supplied is left to whoever runs the
server.

## Outbound Network Calls

In online mode (default), the tools that query an upstream service make
HTTPS requests through one shared client. That client contacts the
hosts below and refuses any request or redirect that leaves the
configured origin.

| Host | Service | Used for | Sent in the request |
|---|---|---|---|
| `alphafold.ebi.ac.uk` | AlphaFold DB | Predicted structures, pLDDT, PAE, AlphaMissense scores | UniProt accession |
| `rest.uniprot.org` | UniProtKB | Identity check for an explicitly requested isoform | UniProt accession |
| `rest.ensembl.org` | Ensembl REST | Variant consequences (VEP), gene lookup, orthologs | HGVS variant, gene symbol, Ensembl gene ID |
| `eutils.ncbi.nlm.nih.gov` | ClinVar through NCBI E-utilities | Variant classifications | HGVS variant or gene symbol as the search term |
| `gnomad.broadinstitute.org` | gnomAD | Allele frequencies, gene constraint | Variant ID (chromosome, position, alleles) derived from the HGVS input; gene symbol |
| `api.platform.opentargets.org` | Open Targets Platform | Target-disease evidence, tractability | UniProt accession or gene symbol, Ensembl gene ID, disease ID or name |
| `ontology.jax.org` | HPO | Phenotype terms, disease and gene annotations | HPO term ID, NCBI gene ID |
| `www.ebi.ac.uk` | MONDO through OLS4 | Disease terms, hierarchy, cross-references | MONDO ID, disease search text, ICD-10, OMIM or Orphanet code |
| `www.ebi.ac.uk` | ChEMBL | Drug targets, approved drugs, indications | UniProt accession, ChEMBL ID, disease ID or name |
| `www.ebi.ac.uk` | PDBe | Residue-level literature annotations, only when requested | UniProt accession and residue number |
| `api.disgenet.com` | DisGeNET | Gene-disease association scores | Gene symbol |

Every request carries a `User-Agent` header naming this software, its
version, and its repository URL. If you set `NCBI_API_KEY` or
`DISGENET_API_KEY`, that key is sent to the corresponding service as a
request parameter. As with any HTTPS request, the receiving service
also sees the network address the request comes from.

These services are operated by third parties. This project does not
control how they handle the requests they receive.

### Offline mode

With `ALPHAFOLD_OFFLINE` set to `1`, `true`, or `yes` when the server
starts, the shared client refuses every request before a connection is
opened, except to hosts you list in `ALPHAFOLD_ALLOW_HOSTS`, and the
framework's update check described below is turned off. There is
no bundled data set and no cache of upstream responses. A tool that
needs an upstream service then fails with an error or returns a result
that reports the affected lookups as failed or not assessed; it does
not fall back to stored data. The knowledge-graph tools read only the
local database (see Local Storage) and keep working.

### Update check by the MCP framework

In online mode one start-up request is made outside that client. When
the server starts, FastMCP, the framework it is built on, asks
`pypi.org` whether a newer FastMCP release exists. The request carries
no tool input, and FastMCP keeps the answer for 12 hours in a cache
file in its own data directory. Set `FASTMCP_CHECK_FOR_UPDATES=off` to
turn it off.

In offline mode the server turns this check off itself before it
starts, whatever `FASTMCP_CHECK_FOR_UPDATES` says, and the process
starts without any name lookup or connection. Both paragraphs describe
FastMCP 4.1.4 and 4.1.8, the versions this was observed with.

## Logs

This software writes structured log lines to its standard error stream
and to no file. A line can contain the identifier or search text of the
call it describes (for example a UniProt accession, a gene symbol, an
HGVS variant, or a disease search term), the name of the upstream
service, the request path, and error text. The program that launches
the server decides whether standard error is displayed, stored, or
discarded.

## Local Storage

This software keeps one local SQLite database, the knowledge graph, in
the per-user application data directory or at the path given in
`ALPHAFOLD_KG_PATH`. The server creates it with empty tables: a new
database holds no records, only a schema-version marker. No registered
tool and no start-up step writes records to it. Records exist only if
you, or code you add, write them through the storage API, or if the
database comes from an earlier release that seeded illustrative rows,
which this release leaves untouched. The knowledge-graph tools read the
database and return what they find to the MCP client that calls them.

The database is ordinary SQLite. This software does not encrypt it and
places no access restriction on it beyond the file permissions of your
system.

## Telemetry

**None by default.** The software does not call home, report usage, or
transmit any telemetry, and it contains no telemetry code or exporter
of its own.

FastMCP (4.1.4 and 4.1.8 were examined) includes OpenTelemetry
instrumentation built on the OpenTelemetry API package alone. No
OpenTelemetry SDK or exporter is a dependency of this software, so that
instrumentation exports nothing unless you install an SDK and configure
an exporter yourself. If you do, spans go to the endpoint you
configured, and their content is determined by FastMCP, not by this
project.

## Audit Log

There is no automatic audit log. The database has a `tool_invocations`
table and the storage API has a function,
`KnowledgeGraph.log_tool_invocation`, that writes to it, but the
shipped server never calls that function. In normal operation no tool
call is recorded and the table stays empty.

If code you add calls it, each record holds the tool name, the complete
input parameters and the complete result as JSON text, a SHA-256 hash
of each, the duration, any error text, session and request identifiers,
and timestamps. The records are not limited to hashes.

There is no retention setting. The software contains no expiry, purge,
or rotation code, so whatever is written to the database stays there
until you delete it. Nothing sends the database to another system. The
dataset-export tool returns the tables it is asked for to the MCP
client, and it accepts `tool_invocations` as a table name.

## Personal and Health Data

This software is not designed for data about identifiable people. It
has no de-identification step, no access control of its own, and no
encryption of the local database, and it holds no certification for
regulated use (see
[`STATUS.md`](https://github.com/smaniches/alphafold-sovereign-mcp/blob/main/STATUS.md)).

This document makes no claim about whether GDPR, HIPAA, or any other
law applies to a deployment, or about what such a law would require.

## Contact

Privacy questions: open a
[GitHub Discussion](https://github.com/smaniches/alphafold-sovereign-mcp/discussions)
or, for sensitive issues, follow the coordinated-disclosure process
in [`SECURITY.md`](https://github.com/smaniches/alphafold-sovereign-mcp/blob/main/SECURITY.md).

*Last updated: 2026-11-11*
