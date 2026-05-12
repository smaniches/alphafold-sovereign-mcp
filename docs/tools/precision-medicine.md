# Precision-medicine tools

!!! warning "ACMG mapping is not validated"
    Both `generate_variant_clinical_report` and `classify_variant_acmg`
    use an ACMG/AMP criterion mapping that has **not** been reviewed
    by an independent clinical geneticist. Treat the output as a
    research aid, never as clinical decision support. See
    [Limitations L1](../limitations.md).

!!! warning "Druggability tier is a heuristic"
    `assess_target_druggability` returns a `HOT/WARM/COLD/NOT_DRUGGABLE`
    tier from a 4-line scoring heuristic. The thresholds are not
    calibrated against a benchmark. See
    [Limitations L2](../limitations.md).

::: alphafold_sovereign.tools.precision_medicine
    options:
      show_root_heading: true
      members_order: source
