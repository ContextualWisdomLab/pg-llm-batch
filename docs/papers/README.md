# Reference papers

These papers motivate the batching and cost model that `pg-llm-batch`
implements: group many requests, respect token/byte/record limits, and submit
them as a single high-throughput job rather than many interactive calls.

Both are redistributed here under **Creative Commons Attribution 4.0
International (CC BY 4.0)** — the license the authors selected on arXiv, which
permits redistribution with attribution. See <https://creativecommons.org/licenses/by/4.0/>.

## 1. PagedAttention / vLLM — `pagedattention-vllm-2309.06180.pdf`

> Kwon, W., Li, Z., Zhuang, S., Sheng, Y., Zheng, L., Yu, C. H., Gonzalez,
> J. E., Zhang, H., & Stoica, I. (2023). *Efficient Memory Management for Large
> Language Model Serving with PagedAttention.* arXiv:2309.06180. CC BY 4.0.
> <https://arxiv.org/abs/2309.06180>

Why it is relevant: establishes why request **batching** and memory-efficient
scheduling dominate LLM serving throughput and cost — the same economics that
make offline Batch APIs (what this component targets) cheaper per token.

## 2. DeepSpeed-FastGen — `deepspeed-fastgen-2401.08671.pdf`

> Holmes, C., Tanaka, M., Wyatt, M., Awan, A. A., Rasley, J., Rajbhandari, S.,
> Aminabadi, R. Y., Qin, H., Bakhtiari, A., Kurilenko, L., & He, Y. (2024).
> *DeepSpeed-FastGen: High-throughput Text Generation for LLMs via MII and
> DeepSpeed-Inference.* arXiv:2401.08671. CC BY 4.0.
> <https://arxiv.org/abs/2401.08671>

Why it is relevant: its Dynamic SplitFuse batching strategy shows how composing
requests into token-budgeted batches raises throughput — mirroring this
component's token/byte/record-bounded `BatchAccumulator`.

## 3. Coverage-guided Tracing — `coverage-guided-tracing-2209.03441.pdf`

> Nagy, S., Nguyen-Tuong, A., Hiser, J. D., Davidson, J. W., & Hicks, M. (2022).
> *Same Coverage, Less Bloat: Accelerating Binary-only Fuzzing with
> Coverage-preserving Coverage-guided Tracing.* arXiv:2209.03441. CC BY 4.0.
> <https://arxiv.org/abs/2209.03441>

Why it is relevant: motivates the **fuzzing** harness added under `fuzz/`. It
explains coverage-guided fuzzing — the technique behind Atheris/libFuzzer — and
why keeping the coverage signal cheap lets a fuzzer explore more input space per
second. `pg-llm-batch` fuzzes its untrusted-input surfaces (the JSONL request
assembler, the Batch API result decoder, and the config (de)serialiser); see
[`fuzz/README.md`](../../fuzz/README.md).

## Tokenization note

Token accounting here is delegated to the `pg_tiktoken` PostgreSQL extension
(OpenAI's `tiktoken` BPE, Apache-2.0). Byte-Pair Encoding itself is described in
Sennrich, Haddow & Birch (2016), *Neural Machine Translation of Rare Words with
Subword Units*, arXiv:1508.07909 — cited here for provenance (not redistributed,
as it does not carry a CC license).
