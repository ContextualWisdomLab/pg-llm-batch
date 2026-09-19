# BatchInferencePort convergence doctoring

## Purpose

`pg-llm-batch` owns durable asynchronous batch lifecycle, token/size accounting, tenant-scoped persistence, checkpoint/result application, and the provider-neutral `BatchInferencePort` boundary. `contextual-orchestrator` owns provider/model discovery, routing/fallback, credential discovery and concrete LLM execution authority. This note prevents a structural Python `Protocol` or a renamed direct HTTP client from being mistaken for that completed authority split.

This is a doctoring/evidence surface. Mutable branch heads below are dated candidate evidence only and must be refreshed before integration or release decisions.

## Current evidence snapshot — 2026-09-16

Protected `main` remains on the pre-convergence implementation and does not establish a released Contextual-Orchestrator-backed batch adapter.

Draft #319 at `7b1864028d952c233abf1318e8b8b0c3351c5b65` already contains `pg_llm_batch/batch_inference_port.py` and `tests/test_batch_inference_port.py`. The candidate `BatchInferencePort` exposes upload, create, status, cancel, result-download and file-delete lifecycle operations. Its tests prove that the shipped `BatchAPIClient` and a non-HTTP adapter can satisfy the protocol while discovery/routing methods remain outside the port.

That is useful candidate evidence, but it is not the end state required by #318:

- `BatchAPIClient` remains a conforming implementation and still owns direct OpenAI-compatible `/files` + `/batches` HTTP behavior on its active source lineage;
- `create_batch_job` still accepts a host-selected `endpoint` string, so the candidate protocol alone does not prove semantic operation identity is separated from provider wire routing;
- the protocol deliberately permits an arbitrary host adapter and therefore does not itself bind execution to a versioned immutable `contextual-orchestrator` API/client/schema;
- a mutable #319 head is neither protected product truth nor immutable dependency identity.

Draft #317 remains the active `batch_api_client.py` writer for #301/#302/#347. Issue #201 owns first-class endpoint preparation/accounting. Issue #318 owns the released-contract/ACL convergence. Canonical product documentation remains separated across #229 and #324. No parallel source writer should be created while those paths overlap.

## Required authority split

The final boundary must make the following ownership executable rather than descriptive:

| Concern | Canonical owner |
| --- | --- |
| PostgreSQL durable lifecycle, tenant/RLS, token/size accounting, idempotency, checkpoint/result application | `pg-llm-batch` |
| Provider/model discovery and selection | `contextual-orchestrator` |
| Provider credentials/key discovery | `contextual-orchestrator` |
| Routing, fallback and provider-specific execution semantics | `contextual-orchestrator` |
| Versioned batch lifecycle ACL consumed by pg | pg-owned adapter over an immutable released CO API/client/schema |
| Provider wire identifiers returned as evidence | adapter boundary only; never pg domain authority by themselves |

No implementation may copy CO source, query another service database, pin a mutable CO branch, hard-code provider/model/group authority, or treat a protected source SHA as a released contract.

## RED-to-GREEN acceptance

Before replacing or restricting direct-provider authority, the serialized owner must establish realistic REDs for all of these conditions and then make the minimum causal repair:

1. **Released-contract admission.** A pg adapter must reject missing, mutable, incompatible or unverifiable CO contract identity and admit only an explicitly supported immutable released API/client/schema identity.
2. **No hidden provider authority.** Durable pg lifecycle callers must not need provider/model/group/key discovery. Provider wire endpoints or route selection must not become hidden authority merely because they are passed through a `Protocol` method.
3. **Primitive authority before transport.** The #347 invariant survives migration: behavior-bearing caller identifiers are rejected before URL formatting, credential resolution, transport preparation, comparison, logging, persistence or evidence retention.
4. **Usage honesty.** Measured, estimated and unavailable usage remain distinguishable. Unknown usage or unknown price is never coerced to zero or an authoritative complete measured total; zero usage remains distinct from unknown price.
5. **Lifecycle semantics.** Submit/status/cancel/result retrieval preserve idempotency, bounded response handling and provider-neutral lifecycle state without inventing unsupported provider behavior.
6. **Termination semantics.** User cancellation, provider terminal state and any administrator policy timeout remain distinguishable. Reasoning, streaming or tool execution is not terminated merely because elapsed time crossed an arbitrary default.
7. **Database transaction boundary.** Remote inference, provider queue wait, retry backoff and long CPU/GPU/tokenization work occur outside avoidable explicit PostgreSQL transactions and locks. Transactions cover only the minimal durable aggregate transition before or after external work.
8. **Standalone compatibility is explicit.** If a direct provider adapter is retained for standalone use, it is a deliberately bounded compatibility adapter with the same security/accounting invariants. It is not silently treated as the production CO-backed authority.

GREEN requires exact-head repository tests plus the then-live security/SAST/review gates. A predecessor GREEN does not transfer after source/base movement.

## Migration order

Use the existing serialized owners rather than creating a sibling implementation:

1. settle #317/#347 and the overlapping endpoint/accounting writers with their own RED→repair→exact-head evidence;
2. repeat #316's open-PR and no-PR path census for `batch_inference_port.py`, `batch_api_client.py`, endpoint preparation/accounting, package exports and tests;
3. obtain an eligible immutable CO release from the current CO release owner and verify API/client/schema identity, SBOM/provenance/reproducibility and rollback evidence;
4. author the pg ACL REDs against that released boundary, then implement the minimum adapter/port repair without source copying or cross-service SQL;
5. ordinary/non-force reconcile descendants, reacquire exact-final-head evidence, converge #229/#324 documentation, and only then promote an immutable pg release and consumer canary.

## Release claim boundary

A protocol class, branch-local test, protected commit, successful Release Acceptance workflow, package build or documentation statement is not an immutable release. Completion requires a normally integrated protected exact head and verified version/CHANGELOG/tag/package/SBOM/provenance/reproducibility/rollback artifacts. The consuming pg release must bind to the eligible immutable CO contract it actually uses.