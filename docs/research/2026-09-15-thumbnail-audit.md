# Thumbnail audit: a cheap, fast path

Date: 2026-09-15. Reviewed commit: `96ae605b6a006f37b90eda09207460f48a91e415`.

Historical snapshot before implementation. For current behavior and repaired
findings, see the [CLI README](../../README.md).

## Recommendation

**Keep the single-file CLI and Pillow output pipeline. Repair the provider contract, avoid regenerating existing artwork, and make saved prompts reusable.** For routine new artwork, trial a small curated prompt library that needs just one image-generation request. Keep Claude available for tracks needing a bespoke concept.

The current default model is a more immediate problem than cost: Together's live catalog omits FLUX Schnell, and its model page explicitly marks it unavailable on the serverless API. Older indexed documentation still lists it. Do not build the next iteration around that stale listing. This is a documentation-backed availability finding; this audit did not make an authenticated generation request. [Together model page](https://www.together.ai/models/flux-1-schnell-2), [live catalog](https://docs.together.ai/docs/serverless/models).

**First replacement to trial:** Together `Rundiffusion/Juggernaut-Lightning-Flux`, because it retains the existing provider and SDK and has a low published rate. **If keeping the Schnell model is more important:** Replicate hosts it at $0.003 per output image. Neither option's quality or end-to-end latency was benchmarked here. [Together Lightning](https://www.together.ai/models/juggernaut-lightning-flux), [Replicate Schnell pricing and API](https://replicate.com/black-forest-labs/flux-schnell/api).

This report proposes changes; it does not implement them. No paid generation requests were made, no credentials were printed, and no real track files were modified.

## Scope and current behavior

Reviewed [generate.py](../../src/generate.py), [wrapper](../../bin/thumbnail.sh), [dependencies](../../pyproject.toml), lockfile, README, and the sibling app's import wrapper and thumbnail URL contract. Read metadata and thumbnail dimensions for the three local tracks. Checked current primary provider documentation and ran isolated offline reproductions.

Current path:

1. Resolve track directory and read `metadata.json`.
2. Ask Claude Haiku 4.5 for a visual prompt, capped at 300 output tokens.
3. Ask Together for one 512×512 image.
4. Write `thumb.webp`, then 256, 128 and 64 pixel WebP derivatives.

Good choices already present: one image generates all four outputs; no audio is sent to either provider; small WebP files; a committed dependency lockfile; a simple CLI. All 12 existing thumbnail files have the expected dimensions. Existing 128px files are about 4–6 KB, and 512px masters about 41–59 KB.

The parent [`import.sh`](../../../paincave/bin/import.sh), lines 189–200, already skips thumbnail generation for existing tracks and staged analysis revisions. The repeat-charge finding below applies to direct thumbnail runs. A new track's thumbnail failure also needs an explicit thumbnail retry: repeating the whole import skips an existing track, even if its thumbnail is missing.

## Findings, ordered by practical impact

### A01 — High: the default image endpoint is no longer listed as available

**Location:** `src/generate.py:68` and `:116`; shared environment documentation repeats this default.

Together's current Schnell page says it is unavailable on serverless, and a fresh open of the serverless catalog no longer includes it. Search snippets retained the older $0.0027/MP listing, illustrating why cached search results alone are insufficient. No account-specific availability was tested. [Model status](https://www.together.ai/models/flux-1-schnell-2), [current catalog](https://docs.together.ai/docs/serverless/models).

**Impact:** a default run can pay for Claude and then fail at the image step. An `IMAGE_MODEL` override may avoid this; effective values in the user's private environment were not inspected.

**Action:** select and smoke-test a supported replacement before changing the default. Update source, README and shared environment docs together. Treat resolution, steps and response shape as model-specific settings. Do not silently fall back to a more expensive model.

### A02 — High: image response-format request violates the documented contract

**Location:** `src/generate.py:76`.

The code sends `response_format="b64_json"`. Installed Together **2.0.0a18** declares request values `"base64"` or `"url"`, matching the current API documentation. `b64_json` is the response data field, which the code correctly reads at line 78. [Together image API](https://docs.together.ai/reference/post-images-generations).

**Evidence:** an `httpx.MockTransport` around the actual installed SDK captured `"response_format": "b64_json"` on the wire. The SDK passes it through; Python type annotations do not reject it. A mock response decoded successfully, so the issue is the request enum, not the response field.

**Impact:** possible provider validation failure. A live rejection was not tested; an undocumented compatibility alias could exist.

**Action:** use `response_format="base64"` for the Together adapter and keep reading `data[0].b64_json`. Add a transport-level regression check for the request body and successful decoding.

### A03 — Medium: reruns repeat both paid calls and cannot reuse an approved prompt

**Location:** `src/generate.py:108–119`, `:149–153`.

Every direct generation run asks Claude again and generates another image, even when all output files already exist. `--prompt-only` prints a new paid prompt but does not save it, and there is no way to pass that approved prompt into generation.

**Evidence:** two calls with the same temporary track and `seed=42` invoked both mocked generation stages twice. The first render received `("A red moon", 42)` and the second `("A blue moon", 42)`.

**Action:** skip complete valid thumbnail sets by default; require an explicit `--regenerate` to spend again. Add a saved-prompt input and a small generation manifest. If only a derivative is missing, regenerate it locally from the valid master. Avoid automatic regeneration solely because track metadata changed: approved art should remain stable until requested.

### A04 — Medium: `--seed` does not make the full pipeline reproducible

**Location:** `src/generate.py:110–115`, `:144`; README's reproducibility claim.

The seed controls only image generation. Claude's prompt is regenerated independently, and neither exact prompt nor model settings are persisted. A seed alone cannot recover the original art.

**Action:** persist the exact prompt, prompt origin/version, effective provider/model, image seed, dimensions, steps, generation timestamp and request ID when available. Save the prompt before rendering so image retries reuse it. Retain the accepted master: even identical settings may not guarantee identical pixels across provider model updates. Clarify the CLI help and README.

### A05 — Medium: sequential overwrites can leave a mixed or damaged set

**Location:** `src/generate.py:121–130`.

The master and each derivative are written directly to their final paths. A disk/encoding failure can leave new large thumbnails alongside old small thumbnails; interruption during a write can damage an individual file.

**Evidence:** injecting a save failure at `thumb_128.webp` replaced the master and 256px file while leaving the 128px and 64px files unchanged.

**Action:** fully decode and validate the image, encode all outputs to temporary files in the same directory, verify them, then replace destinations. This prevents encoding failures from damaging current art and makes each replacement atomic. Four separate renames are **not** an atomic transaction for the entire set: a kill during promotion can still mix versions. Keep a completion manifest/checksums and repair from the master on retry; prevent concurrent writers to the same track. Full set-level atomic publication would need a versioned-directory/pointer design coordinated with the consumer, which is unnecessary for the first repair.

### A06 — Medium: actual genres never reach the prompt

**Location:** `src/generate.py:47`.

The CLI reads `styleTags`; the metadata schema uses `genres`. All three local metadata files lack `styleTags`; one contains `genres: ["tech-house", "house"]`. The README already records this unresolved bug.

**Evidence:** a fixture with `genres: ["tech-house"]` produced a Claude message containing `styleTags: []`.

**Action:** send `genres`, validating it as a list of strings. If historical `styleTags` support is needed, use it only as a documented fallback. Test an actual schema-shaped fixture.

### A07 — Medium: predictable failures are detected after spending; retries lack a deliberate budget

**Location:** `src/generate.py:55–62`, `:67–79`, `:108–123`.

The Together client is constructed after Claude runs. Missing image credentials are therefore discovered too late. Metadata object shape, writable destination, image response contents and returned dimensions also lack explicit validation. Errors generally become tracebacks.

**Evidence:** with the environment cleared and prompt generation mocked, `TogetherError` occurred after the prompt function had been called once. A mocked 768×512 result was saved unchanged as `thumb.webp`, violating the 512×512 contract. Empty/invalid provider responses have no handling before indexing and decoding.

Installed SDK defaults already include retries: both use `max_retries=2`. Anthropic's default read timeout is 600 seconds; Together's is 60 seconds. The problem is not an absence of retries, but implicit retry/time budgets and no resumable workflow.

**Action:** validate inputs and required credentials before paid calls; check nonempty prompt and completion status; validate/decode the image before publication. Set explicit stage timeouts and a small retry policy. Reuse the saved prompt on image failure. For an ambiguous image timeout, resume by request ID if supported rather than blindly submitting another paid generation. Record per-stage elapsed time, token usage and request IDs without secrets. `--prompt-only` should still require only the prompt-provider key.

### A08 — Low: regeneration uses initial file metadata, not current admin edits

**Location:** `src/generate.py:108`; sibling [source-of-truth architecture](../../../paincave/docs/architecture.md#source-of-truth).

The parent app stores admin edits in SQLite; `metadata.json` contains initial analysis values. New-import artwork can use these values, but later generation may ignore renamed titles and edited genres/BPM.

**Action:** document this limitation now. When generation becomes an admin action, pass a validated metadata snapshot from the app rather than adding direct SQLite access to this small CLI.

## Cost comparison

Published USD rates checked on 2026-09-15. These are estimates for one output per request, excluding retries, rejected artwork, tax and credit-purchase minimums. Four local WebP sizes do not mean four paid images.

| Approach | Published image rate | Illustrative image cost / 1,000 tracks | Tradeoff |
|---|---:|---:|---|
| Reuse an existing master | No generation request | $0 incremental API cost | Best for repairing derivatives |
| Local procedural artwork or an existing owned-art library | No generation request | $0 incremental API cost | Different aesthetic or repeated art; design work required |
| Together Juggernaut Lightning | $0.0017/MP | About **$0.45** at exactly 512×512 | Smallest provider change; validate quality/settings |
| Replicate FLUX Schnell | $0.003/output image | **$3.00** | Preserves model family; new provider integration |

Lightning's rate and serverless status are published on its [model page](https://www.together.ai/models/juggernaut-lightning-flux). Its illustrative calculation is `512 × 512 / 1,000,000 × $0.0017 × 1,000 = $0.4456448`. Confirm accepted dimensions, step settings and any billing floor in a live trial; this is arithmetic from the advertised rate, not an observed invoice. At a billable 1 MP per image it would be $1.70/1,000. Replicate's price is per output image, so do not assume resizing the request lowers its $3/1,000 price. [Replicate pricing](https://replicate.com/black-forest-labs/flux-schnell/api).

**Claude adds a small cost and an entire serial inference stage.** Haiku 4.5 is $1/million input tokens and $5/million output tokens. Assuming 400 input and 150 output tokens, a prompt costs `$0.0004 + $0.00075 = $0.00115`, or **$1.15/1,000 tracks**. These token counts are illustrative, not measured usage. At 300 output tokens with the same input, it is $1.90/1,000. [Anthropic pricing](https://platform.claude.com/docs/en/models/haiku-4-5/overview).

Thus the illustrative totals with Claude are about $1.60/1,000 for 512px Lightning, or $4.15/1,000 for Replicate Schnell. At this project's current three-track scale, engineering time and avoiding frustrating retries matter more than fractions of a cent per image.

fal also exposes Schnell with custom dimensions and a four-step default, making it another feasible adapter. Its fetched model page did not expose a price, so it is not ranked as cheaper here. [fal API schema](https://fal.ai/models/fal-ai/flux/schnell/api).

## How to make it faster without losing the intended art direction

The README reports that earlier rule-based prompts were repetitive and leaked title words into the image. Preserve that lesson. Do not simply concatenate the title and genre into a generic template.

Trial **24–48 reviewed visual concepts** matching the existing surreal city/sky/cosmic direction. Choose a concept and compatible palette/composition deterministically from the track hash, with BPM/genre influencing broad mood. Exclude literal title words from routine prompts. Version and save the result. This sacrifices some title-specific interpretation and needs visual evaluation for repetition; it is a proposed alternative, not proof that the previous template problem is solved. Use Claude for bespoke concepts and cache each accepted result.

Example concept: “A solitary obsidian arch suspended above a midnight sea, a huge amber moon near the horizon, cobalt clouds, one bold silhouette, surreal oil painting, simple square composition.”

The current image prompt should continue describing visual content only, following the repository's established avoidance of text-related wording.

Measured locally, resizing and encoding a synthetic 512px RGB noise image into all four WebPs took **50.9 ms median**, **51.9 ms maximum**, over 20 runs. This excludes image generation, decoding, disk writes and Python startup; it is not an end-to-end benchmark. It supports leaving Pillow alone. Measure network stages before making speed claims about either provider.

For a larger backfill, reuse clients and run a small bounded number of tracks concurrently, initially two, subject to provider limits. Never run two writers for the same track. Concurrency improves batch throughput; it does not remove the two dependent stages within a single track. A queue service or local GPU deployment is not justified by the current catalog size.

## Small implementation sequence

1. **Compatibility and correctness:** repair the request enum and genre key; trial a supported image model; validate metadata, keys, responses and dimensions. Keep all four filename/size contracts unchanged.
2. **Cheap retries and stable art:** saved prompt/manifest, skip existing valid outputs, local derivative repair, explicit regeneration, staged file writes, clear stage errors/timeouts.
3. **Optional one-request mode:** compare curated prompts against Claude concepts before choosing a new default. Preserve a bespoke mode.

Keep CLI logic in `src/generate.py`, per repository conventions. A reviewed prompt data file is sufficient; a provider framework, web UI, database or task service would add unnecessary work. The locked Together version is an alpha; update it deliberately if retaining Together, with transport contract checks, rather than performing a blanket dependency upgrade during this audit.

### Acceptance checks for the implementation

- Existing valid set: zero API calls and identical output bytes.
- Missing derivative with valid master: zero API calls and repaired expected dimensions.
- Same saved prompt/settings: no Claude call; manifest records effective inputs.
- Malformed metadata or missing required key: failure before any API call.
- Together request uses the supported enum; empty, truncated and invalid responses produce clear errors.
- Encoding failure leaves active outputs unchanged; interrupted promotion is detectable and repairable.
- Single-writer behavior prevents duplicate charges for the same track.
- All four output files retain 512/256/128/64 dimensions and existing names.

Then conduct a separately requested paid trial in a scratch output directory: 12 representative metadata fixtures, one output per candidate initially, inspect at 64px and 128px, record accidental writing, repetition, rejected images, billed cost and median/p95 elapsed time. Twelve images provide a screening sample, not a reliable production p95. Start with four inference steps for a Schnell adapter; do not transplant Schnell's step count into another model without validation. Select by **cost per accepted thumbnail**, including retries and human review time.

## Verification performed

| Check | Result |
|---|---|
| `uv run python src/generate.py --help` | Passed; no generation calls |
| `bash -n bin/thumbnail.sh` | Passed |
| Three local metadata files / 12 WebPs | Genre mismatch confirmed; existing image dimensions correct |
| Mocked Anthropic metadata capture | `genres` dropped, empty `styleTags` sent |
| Two direct runs, identical seed | Two prompts and two renders; distinct prompts reach image stage |
| Installed Together SDK with `httpx.MockTransport` | Unsupported request enum transmitted unchanged; mock base64 response decoded |
| Missing Together key after mocked prompt | Prompt stage already called before failure |
| Injected derivative save failure | New master/256px, old 128px/64px |
| Unexpected provider image dimensions | 768×512 master accepted unchanged |
| Local Pillow microbenchmark | 20 synthetic-image runs; timing and exclusions above |

Reproductions used temporary directories and `unittest.mock`; provider transport was intercepted locally. No permanent test suite was added for this documentation-only audit. The repository currently has no test suite. Live endpoint behavior, actual invoice amounts, provider latency and comparative artistic quality remain unverified.
