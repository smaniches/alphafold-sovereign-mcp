# Commercial Enterprise Edition

The code in this repository is, and will remain, released under the
**Apache License, Version 2.0**. The Apache 2.0 release is the
*Community Edition* and is fully featured for the research,
educational, and commercial uses described in `LICENSE` and `NOTICE`.

This document is **not** a license document. It is a description of
the optional commercial relationship TOPOLOGICA LLC offers on top of
the Community Edition, for organizations that need contractual
guarantees Apache 2.0 cannot provide by itself.

If you are a researcher, hobbyist, startup, academic lab, or
non-regulated commercial user, you do **not** need to read further —
Apache 2.0 covers you.

If you are a regulated enterprise (pharmaceuticals, clinical research,
medical devices, defense, intelligence, federal civilian agencies,
banking, or critical infrastructure), the Enterprise Edition exists
for you. Reach out: `enterprise@topologica.ai`.

---

## What the Enterprise Edition Adds

The Enterprise Edition is a **contractual wrapper** around the same
open-source code, plus a small set of additive components and
guarantees that regulated buyers consistently ask for.

### Contractual guarantees

- **Commercial warranty** with defined remedies, replacing the Apache
  2.0 "AS IS" disclaimer.
- **IP indemnification** against third-party copyright, patent, and
  trade-secret claims arising from your use of the software, subject
  to standard carve-outs.
- **Defined Support SLA** — 24×7×365 for Severity 1, with response
  times escalating from minutes to hours by severity.
- **Long-Term Support (LTS) branch** with a published security-patch
  window of at least 24 months per release line.
- **Coordinated CVE disclosure preview** — Enterprise customers
  receive notice of upcoming security advisories ahead of public
  disclosure, with patched builds available on Day 0.

### Compliance & regulated-industry features

- **FedRAMP-aligned FIPS 140-3 build** with attestation evidence.
- **SOC 2 Type II report** for the TOPOLOGICA managed service (the
  optional hosted offering).
- **21 CFR Part 11 audit-trail export** — schema, retention policy,
  and verification tooling pre-built and validated.
- **Signed compliance packets** mapped to NIST SP 800-53 (HIGH
  baseline), NIST SP 800-171, ISO 27001 Annex A, and HHS biosecurity
  framework guidance.
- **Business Associate Agreement (BAA)** template for HIPAA-adjacent
  deployments (this product does not process PHI by design; the BAA
  formalizes the boundary).
- **Software Bill of Materials (SBOM)** delivered as both CycloneDX
  and SPDX, signed and accompanied by SLSA Level 3 provenance
  attestations.

### Enterprise integrations

- **SSO/SAML, OIDC, and SCIM 2.0** identity-provider integrations
  with Okta, Azure AD/Entra ID, PingFederate, Auth0, and Google
  Workspace.
- **Audit-log export** to Splunk, Elastic, Datadog, Sumo Logic, and
  Microsoft Sentinel.
- **Private package registry** mirroring (Artifactory, Nexus, AWS
  CodeArtifact, GCP Artifact Registry, Azure DevOps).
- **Air-gap installation bundles** signed with TOPOLOGICA's
  cosign/Sigstore release key, including the 50 GB curated structure
  snapshot for offline operation.
- **Federation gateway** for multi-tenant, cross-organization
  Sovereign Mesh deployments (see Wave 7 of the project roadmap).

### Professional services

- Architecture review and reference-implementation deployments.
- Custom upstream integrations against private databases.
- Validation packages for GxP environments.
- Training, enablement, and runbook authoring for your SRE org.

---

## What Stays Open

The Apache 2.0 Community Edition is the complete, runnable system.
TOPOLOGICA LLC commits to the following principles for as long as the
project exists:

1. **No feature flags hide existing functionality** behind a paywall.
   Anything that runs today under Apache 2.0 will continue to run
   tomorrow under Apache 2.0.
2. **No telemetry phones home by default.** All telemetry endpoints
   are opt-in, configurable, and document where data goes.
3. **No vendor lock-in.** Configuration is portable, data formats are
   open, and the wire protocol is the MCP standard.
4. **Patches, security fixes, and bug fixes ship to the open-source
   release first**, then to LTS branches consumed by Enterprise
   customers.

The Enterprise Edition is, deliberately, a **better customer
experience**, not a feature gate.

---

## How to Reach Us

| You are… | Write to |
|---|---|
| Procurement, legal, or contracts | `legal@topologica.ai` |
| Pharma, biotech, or clinical-research engineering | `enterprise@topologica.ai` |
| Federal civilian, defense, or intelligence | `gov@topologica.ai` |
| Press, analysts, conference organizers | `press@topologica.ai` |
| Security researchers (coordinated disclosure) | `security@topologica.ai` |

We respond to all inbound inquiries within 5 business days. For
Severity-1 security reports we respond within 24 hours.
