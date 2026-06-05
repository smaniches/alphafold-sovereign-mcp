# Known Limitations

This document enumerates the specific, named limitations of the project
as of v1.1.10. It complements ``STATUS.md`` (which gives the
high-level posture) by listing concrete, addressable items.

If you find a limitation that is not listed here, please open an issue
labelled ``limitation``.

---

## L1 — ACMG criterion mapping is not independently validated

**Module:** ``src/alphafold_sovereign/tools/precision_medicine.py``
(``_am_to_acmg_evidence``, ``_gnomad_to_acmg``, ``_vep_to_acmg``, and
related helpers).

**Description:** The mapping from AlphaMissense scores, gnomAD allele
frequencies, and VEP consequence terms onto ACMG criteria (PVS1, PS1,
PM1, …) is implemented from a reading of Richards et al. 2015 by the
project author. No clinical geneticist has signed off on the
criterion-by-criterion mapping.

**Impact:** Variant classifications produced by
``generate_variant_clinical_report`` and ``classify_variant_acmg``
may be **incorrect** in ways that unit tests cannot catch.

**Mitigation:** Treat the report as a literature aggregator, not as a
clinical call. Re-derive each ACMG criterion from the cited primary
source before any clinical use.

**Planned resolution:** Roadmap step 2 (traceability matrix) and step 3
(external review). See ``STATUS.md``.

---

## L2 — Druggability tier thresholds are unvalidated heuristics

**Module:** ``src/alphafold_sovereign/tools/precision_medicine.py``
(``_druggability_tier``).

**Description:** The mapping from (``drug_count``, ``tractability``,
``LOEUF``, ``pLDDT``) to (HOT, WARM, COLD, NOT_DRUGGABLE) uses
integer score cut-offs (≥4, ≥2, ≥1, 0) chosen by the author. The
score itself is the sum of small literature-informed weights. No
calibration against a benchmark of approved-drug vs. failed-drug
targets has been performed.

**Impact:** A target classified as HOT here may not be druggable in
practice. A target classified as COLD here may have an approved drug.

**Mitigation:** Use the tier only as a triage signal alongside expert
review.

**Planned resolution:** Roadmap step 4 (benchmark calibration).

---

## L3 — Upstream API schemas are not pinned

**Modules:** all of ``src/alphafold_sovereign/clients/``.

**Description:** We call live APIs (Ensembl REST, Open Targets GraphQL,
ClinVar VCV JSON, gnomAD GraphQL, AlphaFold DB, MONDO, HPO, DisGeNET,
ChEMBL) at their current schema. If an upstream changes shape,
serialisation may break.

**Impact:** Reproducibility is limited. A run today may produce
different results from a run a year from now.

**Mitigation:** We pin our own response schemas as Pydantic models;
schema drift becomes a deserialisation error rather than silent data
corruption.

**Planned resolution:** Roadmap step 5 (schema pinning with refresh
policy).

---

## L4 — No production deployment experience

**Description:** This server has never been run for real users in a
long-lived process. We do not know the actual memory footprint of the
SQLite knowledge graph after a month of use, the actual rate of
upstream 429 throttling, or the actual latency of the slowest tool.

**Impact:** Performance and reliability claims should be assumed to be
"works on a laptop" rather than "works at scale".

**Mitigation:** ``CircuitBreaker`` and ``UpstreamConfig`` provide
defensive primitives, but they have only been tested in unit tests
with mocked time.

**Planned resolution:** First real deployment will produce real
observations to publish back to this document.

---

## L5 — macOS Python 3.11 test flake

**Description:** On the GitHub Actions ``macos-latest`` runner with
Python 3.11, the test suite has intermittently failed even though
identical code passes on every other matrix entry. The failure is
non-deterministic; the root cause has not been isolated.

**Impact:** CI may be red on a benign push.

**Mitigation:** Re-running the workflow has so far always produced a
green run.

**Planned resolution:** Identify the specific timing-sensitive test
and stabilise it (track via issue ``flaky-macos-3.11``).

---

## L6 — Single-maintainer bus factor

**Description:** This is currently a single-person project. There is
no co-maintainer, no governance body, and no funded continuity plan.

**Impact:** If the maintainer becomes unavailable, the project stalls.

**Mitigation:** The Apache 2.0 licence ensures any user can fork; the
code is small enough (2,955 statements as of v1.1.10, verified via
`pytest --cov`) to be picked up by a reasonably motivated successor.

**Planned resolution:** Recruit co-maintainers (see
``GOVERNANCE.md``).

---

## L7 — No telemetry on real-world correctness

**Description:** We do not collect any data on tool invocations,
arguments, or outputs from users. We therefore cannot say "in N
real-world variant reports, the ACMG call agreed with a geneticist M%
of the time."

**Impact:** Quality claims are based on unit tests, not field data.

**Mitigation:** None for this release. Intentional — we will not add
telemetry without explicit opt-in.

**Planned resolution:** An opt-in, locally-stored "quality journal"
that lets users mark each report as "matches expert / disagrees /
unsure", aggregated only with explicit upload consent.

---

## How to add a new entry

When you find a new limitation:

1. Open a GitHub issue with the ``limitation`` label.
2. Add a new ``L<N>`` section here in the next PR. Include: module,
   description, impact, mitigation, planned resolution.
3. If the limitation rises to the level of a safety concern, also
   add a clear note in the relevant tool's docstring.

---

Last updated: 2026-05-28.
