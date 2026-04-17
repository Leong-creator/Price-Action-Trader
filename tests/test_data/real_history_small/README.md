# Real History Small Samples

This directory holds repo-safe small manifests used to validate the M8D framework itself.

Rules:

- keep samples local, small, and auditable
- do not present them as real profitability evidence
- keep output in `paper / simulated`
- use `dataset.manifest.json` per dataset directory

Recommended layout:

- `sample_<slug>/dataset.manifest.json`
- `sample_<slug>/README.md`

The actual CSV/JSON payload may point to existing local fixtures when the goal is only to validate the M8D framework.
