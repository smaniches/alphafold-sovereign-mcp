# Privacy Policy

## What this software is

AlphaFold Sovereign MCP is local-first, on-premises software. It is
not a SaaS. The software runs on your infrastructure, under your
control.

## Data This Software Processes

The MCP server processes:

- **UniProt accession IDs** (e.g., `P12345`) — identifiers for
  protein sequences. These are not personal data.
- **Amino acid sequences** submitted to `screen_sequence_of_concern`
  or similar tools. These are not personal data.
- **Gene symbols, variant identifiers (HGVS notation), disease
  terms, and ontology identifiers.** These are scientific identifiers,
  not personal data.
- **Tool-call parameters and results** that may be persisted in the
  audit log.

**This software does not process, store, or transmit any data that
constitutes Personal Health Information (PHI) under HIPAA, or
personal data under GDPR, by design.** If you extend it to do so,
that is your responsibility and you must conduct a DPIA.

## Outbound Network Calls

In online mode (default), the software makes outbound HTTPS requests
to the following upstream services:

| Service | Purpose | Data sent | Privacy policy |
|---|---|---|---|
| `alphafold.ebi.ac.uk` | Fetch predicted structures | UniProt accession ID | [EMBL-EBI](https://www.ebi.ac.uk/data-protection/privacy-notice/alphafold) |
| `rest.uniprot.org` | Fetch protein metadata | UniProt accession ID | [UniProt](https://www.uniprot.org/help/privacy) |
| `www.ebi.ac.uk/ols4` | Fetch ontology terms (MONDO, HPO, etc.) | Ontology term ID | [EMBL-EBI](https://www.ebi.ac.uk/data-protection) |
| `open.fda.gov` | Drug label and adverse-event queries | Drug/compound identifier | [openFDA](https://open.fda.gov/about/privacy/) |
| `api.opentargets.org` | Disease-target evidence | Gene/disease identifier | [Open Targets](https://platform.opentargets.org/privacy) |
| `clinicaltrials.gov` | Clinical trial data | Search terms | [ClinicalTrials.gov](https://clinicaltrials.gov/about-site/privacy) |
| `eutils.ncbi.nlm.nih.gov` | PubMed/Gene queries | Search terms | [NCBI](https://www.ncbi.nlm.nih.gov/home/about/policies/) |
| `clinicaltables.nlm.nih.gov` | ICD-10 code lookup | Code string | [NLM](https://www.nlm.nih.gov/privacy.html) |
| `gnomad.broadinstitute.org` | Population allele frequencies | HGVS variant string | [gnomAD](https://gnomad.broadinstitute.org/privacy) |

In **offline mode** (`ALPHAFOLD_OFFLINE=1`), no outbound requests are
made. All data is served from the local cache and the air-gap bundle.

## Telemetry

**None by default.** The software does not call home, report usage,
or transmit any telemetry.

If you enable the optional OpenTelemetry exporter
(`OTEL_EXPORTER_OTLP_ENDPOINT`), spans and metrics are sent to the
endpoint you configure. You control that endpoint.

## Audit Log

The audit log is stored locally (or in the backend you configure). It
contains tool names, timestamps, input hashes, and response hashes —
not raw inputs or outputs. Retention policy is configurable; default
is 90 days. The audit log does not leave the deployment environment
unless you explicitly configure an exporter.

## GDPR

If you deploy this software in the European Economic Area, you are
the data controller for any personal data that passes through it.
This software, by itself, does not constitute a data processor — the
software runs on your infrastructure and the upstream APIs it calls
(EBI, NIH, NCBI, etc.) have their own privacy notices (linked above).

## HIPAA

This software does not process Protected Health Information.

## Contact

Privacy questions: open a
[GitHub Discussion](https://github.com/smaniches/alphafold-sovereign-mcp/discussions)
or, for sensitive issues, follow the coordinated-disclosure process
in [`SECURITY.md`](https://github.com/smaniches/alphafold-sovereign-mcp/blob/main/SECURITY.md).

*Last updated: 2026-05-11*
