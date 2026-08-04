# PEP 639 License Metadata Red Evidence

Pre-implementation head: `f50cbd5630286fbd91e0e9fd43ca2727bcb32210`

The source and installed-distribution contract tests were added before changing production packaging metadata. The focused test command returned a non-zero status for the intended reasons:

- the build-backend floor was still `setuptools>=68`;
- `project.license` was still the deprecated table form;
- `project.license-files` was not declared explicitly;
- installed metadata did not expose `License-Expression: Apache-2.0`.

The one-shot workflow required both the source-floor and installed-metadata failure signatures before recording this evidence.
