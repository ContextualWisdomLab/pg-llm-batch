# PEP 639 License Metadata Green Evidence

Verified implementation head before this evidence commit: `c5efe0b5ae4f8ed7c650679fc57384a681b4f6b3`.

The one-shot implementation workflow completed successfully on Python 3.14.6 and removed itself before publishing the implementation. It produced the following evidence:

- focused packaging metadata tests: `2 passed`;
- complete non-integration suite: `238 passed, 3 deselected`;
- Ruff: no findings;
- production docstring coverage: 100%;
- production statements: `1171/1171`, 100%;
- production branches: `324/324`, 100%;
- lockfile freshness: verified;
- source and wheel distributions: built successfully without the legacy license-table deprecation warning;
- wheel `METADATA`: `License-Expression: Apache-2.0` plus exactly `License-File: LICENSE` and `License-File: NOTICE`;
- wheel contents: both files present under `.dist-info/licenses/`;
- source distribution: root `LICENSE` and `NOTICE` present;
- Docker Compose configuration: valid;
- component and PostgreSQL runtime images: built successfully.

This implementation evidence does not replace exact-head repository CI, SAST, Security Scan, and review gates. Those hosted gates must succeed on the final reviewed head before merge.
