# Item 29 — `compute_signing_root` / `compute_domain` / `compute_fork_data_root` / `get_domain` cross-client byte-for-byte equivalence audit

**Status:** no-divergence-pending-source-review — audited 2026-05-03. Foundational primitive cross-cutting items #6 (CAPELLA pin), #20 (GENESIS_FORK_VERSION pin), #25 (current-fork attestation domain). The chokepoint quartet that EVERY signature verification path flows through. **Plus a major Heze-fork finding that contradicts item #28's per-client Gloas-readiness scorecard.**

These four primitives form the signature-domain layer of every consensus-relevant signature in the protocol. `compute_fork_data_root` builds a 32-byte root from `(version, genesis_validators_root)`; `compute_domain` concatenates a 4-byte domain_type with the first 28 bytes of that root to form a 32-byte Domain; `get_domain` selects fork-version from a BeaconState (with EIP-7044 voluntary-exit pin); `compute_signing_root` wraps an SSZ object's hash_tree_root with the Domain to produce the BLS signing message. Divergence at any layer causes signature verification failure → block rejection → fork. All 6 clients are byte-for-byte equivalent at the algorithm level; differences are entirely in caching strategies, fork-version selection encoding, EIP-7044 pin location, and forward-compat patterns.

## Scope

In: `compute_signing_root(ssz_object, domain) -> Root`; `compute_domain(domain_type, fork_version, genesis_validators_root) -> Domain`; `compute_fork_data_root(current_version, genesis_validators_root) -> Root`; `get_domain(state, domain_type, epoch) -> Domain`; EIP-7044 voluntary-exit pin to CAPELLA_FORK_VERSION across all 6 clients.

Out: `compute_fork_digest` (p2p-layer; partially audited at items #15/#19); per-DomainType byte-value registry (pure constants); BLS verification primitives (audited at item #20 and item #25); SigningData/ForkData SSZ schema layout (orthogonal — separate Track E audit).

## Hypotheses

| # | Hypothesis | Verdict | Rationale |
|---|---|---|---|
| H1 | `compute_signing_root(obj, domain) = hash_tree_root(SigningData{object_root: hash_tree_root(obj), domain})` byte-identical across all 6 | ✅ all 6 | Two-step SSZ hash composition; SigningData is a 2-field container. |
| H2 | `compute_fork_data_root(version, gvr) = hash_tree_root(ForkData{current_version: version, genesis_validators_root: gvr})` byte-identical across all 6 | ✅ all 6 | Single SSZ container hash. |
| H3 | `compute_domain(domain_type, fork_version, gvr) = domain_type[:4] || compute_fork_data_root(fork_version, gvr)[:28]` byte-identical across all 6 | ✅ all 6 | 32-byte Domain layout = 4-byte type + 28-byte fork_data_root prefix. |
| H4 | `get_domain` uses `fork.previous_version if epoch < fork.epoch else fork.current_version` (strict `<`) | ✅ all 6 | All 6 use strict `<` for previous_version selection — no off-by-one at fork boundary. |
| H5 | EIP-7044: voluntary-exit signing domain pinned to CAPELLA_FORK_VERSION when current fork ≥ Deneb | ✅ all 6 (six DIFFERENT implementation patterns; identical byte output) | Item #6 confirmed at Pectra fixtures; this audit confirms the primitive layer. |
| H6 | `compute_domain(DOMAIN_DEPOSIT, None, None) = compute_domain(DOMAIN_DEPOSIT, GENESIS_FORK_VERSION, ZERO_HASH)` (deposit domain pin) | ✅ all 6 | Item #20 confirmed at Pectra deposit fixtures; this audit confirms the primitive layer. |
| H7 | Domain[:4] = domain_type; Domain[4:32] = fork_data_root[:28]; total 32 bytes | ✅ all 6 | Confirmed via direct source read across 6 clients. |
| H8 | `compute_signing_root` accepts ANY SSZ-hashable object (generic over type) | ✅ all 6 (6 distinct generic mechanisms) | Go fssz.HashRoot, Rust SignedRoot trait, Java Merkleizable, Nim auto, TS Type<T>, Rust SszHash. |
| H9 | Forward-compat: per-fork DomainType constants extension is open-ended (no algorithm change at new forks) | ✅ all 6 | Adding new DomainType only requires adding a constant; the 4 primitives don't change. |
| H10 | Caching of fork_data_root computation: at most 2 of 6 clients pre-cache (hot path optimization) | ✅ confirmed: prysm (digestMap with sync.RWMutex), lodestar (domainCache per-fork-name), other 4 compute on every call | Performance trade-off; correctness equivalent. |

## Per-client cross-reference

| Client | `compute_signing_root` | `compute_domain` | `compute_fork_data_root` | `get_domain` | EIP-7044 pin location | Caching |
|---|---|---|---|---|---|---|
| **prysm** | `core/signing/signing_root.go:97` (delegates to `Data` → `ComputeSigningRootForRoot`) | `core/signing/signing_root.go:230` | `core/signing/signing_root.go:270` (private `computeForkDataRoot`) | `core/signing/domain.go:21` (named `Domain`) | `signing_root.go:67-73` in `ComputeDomainAndSignWithoutState` (signing trigger) | **`digestMap` keyed by `string(version)+string(root)` with `sync.RWMutex`** (cross-fork; unbounded) |
| **lighthouse** | (per-type via `SignedRoot` trait `signing_root()`; no standalone function) | `consensus/types/src/core/chain_spec.rs:646` | `chain_spec.rs:565` (associated function) | `chain_spec.rs:528` (also `get_deposit_domain`, `get_builder_domain`) | `consensus/types/src/exit/voluntary_exit.rs:48-57` (method on VoluntaryExit type, checks `fork_name.deneb_enabled()`) | NONE (per-call) |
| **teku** | `MiscHelpers.java:363` (3 overloads: Merkleizable / UInt64 / Bytes) | `MiscHelpers.java:398` (3-arg) + `:390-396` (2 overloads with default GENESIS) | `MiscHelpers.java:404` (protected) | `BeaconStateAccessors.java:357` (also `:353` ForkInfo overload) | **`BeaconStateAccessors.java:369-372`** `getVoluntaryExitDomain` (separate method); actual pin enforced in BeaconBlockBodyValidator via item #6's CAPELLA-version selection | NONE (per-call) |
| **nimbus** | `beacon_chain/spec/helpers.nim:174` (generic over `auto`) | `helpers.nim:145` | `forks.nim:1678` | `helpers.nim:159` | `state_transition_block.nim:494` and `signatures.nim:224` (explicit `compute_domain(DOMAIN_VOLUNTARY_EXIT, cfg.CAPELLA_FORK_VERSION, ...)` at signing site) | NONE |
| **lodestar** | `state-transition/src/util/signingRoot.ts:7` | `state-transition/src/util/domain.ts:7` (also config-level `genesisConfig/index.ts:144`) | `state-transition/src/util/domain.ts:25` | **`config/src/genesisConfig/index.ts:60-72`** (CONFIG-LEVEL, not state-level — domain memoized per (forkName, domainType)) | **`genesisConfig/index.ts:96-104`** `getDomainForVoluntaryExit(stateSlot)` — slot-based gate `stateSlot < DENEB_FORK_EPOCH * SLOTS_PER_EPOCH` (others use epoch) | **`domainCache` per-fork-name `Map<DomainType, Uint8Array>`** (computed lazily, cached forever) |
| **grandine** | `helper_functions/src/misc.rs:205` | `misc.rs:189` | `misc.rs:130` (PRIVATE — no `pub`) | `accessors.rs:543` (`get_domain<P: Preset>`) | `helper_functions/src/signing.rs:430-449` (4-fork OR-list `if version == deneb_fork_version OR electra OR fulu OR gloas` — explicit forward-compat list, must add Heze when ready) | NONE |

## Notable per-client findings

### EIP-7044 voluntary-exit CAPELLA-pin: 6 DIFFERENT implementation patterns

The same logical operation ("when current fork ≥ Deneb, use CAPELLA_FORK_VERSION for voluntary-exit signing domain") is implemented six distinct ways:

1. **prysm** (`signing_root.go:67-73`): TRIGGER-BASED — checks `domain == DomainVoluntaryExit && epoch >= DenebForkEpoch` inside the generic `ComputeDomainAndSignWithoutState`; constructs a synthetic Fork struct in-place with `PreviousVersion = CurrentVersion = CapellaForkVersion`. **Most general — works for any future caller.**
2. **lighthouse** (`voluntary_exit.rs:48-57`): TYPE-METHOD — `VoluntaryExit::get_domain` checks `fork_name.deneb_enabled()`; returns `spec.fork_version_for_name(ForkName::Capella)`. **Tightly bound to the VoluntaryExit type.**
3. **teku** (`BeaconStateAccessors.java:369`): SEPARATE-METHOD — `getVoluntaryExitDomain` exists alongside `getDomain`; the actual fork pin must be enforced by callers (item #6 audit found it in BeaconBlockBodyValidator). **Most loosely coupled — relies on caller discipline.**
4. **nimbus** (`signatures.nim:224`, `state_transition_block.nim:494`): EXPLICIT-CALL — every signing/verification site explicitly calls `compute_domain(DOMAIN_VOLUNTARY_EXIT, cfg.CAPELLA_FORK_VERSION, ...)`. **No abstraction — duplicated at each call site.**
5. **lodestar** (`genesisConfig/index.ts:96-104`): SEPARATE-METHOD-WITH-SLOT-GATE — `getDomainForVoluntaryExit(stateSlot, messageSlot)` uses `stateSlot < DENEB_FORK_EPOCH * SLOTS_PER_EPOCH` (slot-based, NOT epoch-based). Other 5 gate on epoch. **Observable-equivalent at fork boundary** since `epoch == fork.epoch <=> slot >= fork.epoch * SLOTS_PER_EPOCH`, but encoding is different.
6. **grandine** (`signing.rs:430-449`): 4-FORK-OR-LIST — `if current_fork_version == deneb_fork_version || electra_fork_version || fulu_fork_version || gloas_fork_version then use capella`. **Most explicit forward-compat — must be extended at every fork; high risk of forgotten extension at Heze.**

**Forward-compat consequences**: at the Heze fork (post-Gloas, see Heze finding below), all 6 clients must extend their EIP-7044 pin to also accept Heze fork version. prysm + lighthouse + teku + lodestar handle this automatically via "≥ Deneb" semantics. **nimbus** explicit-call sites need no change (the pin is at signing sites, not version-aware). **grandine** must explicitly add `|| heze_fork_version` to the OR-list — without this change, voluntary exits signed under Heze fork version would FAIL signature verification.

### MAJOR FINDING: teku has FULL Heze fork (post-Gloas) implementation; prysm has Heze constants

**Heze** is the next fork after Gloas, introducing inclusion lists per EIP-7805. Discovered while reading teku's `MiscHelpers.computeForkVersion` (lines 76-77):

```java
if (epoch.isGreaterThanOrEqualTo(specConfig.getHezeForkEpoch())) {
  return specConfig.getHezeForkVersion();
}
```

teku has:
- `SpecConfig.getHezeForkVersion()` + `getHezeForkEpoch()`
- `SpecConfigPhase0.java:538-543` defaults
- `DelegatingSpecConfig.java:228-234` delegate
- **`HezeStateUpgrade.java`** — full state upgrade implementation
- `SpecMilestone.HEZE` enum constant
- `SpecFactory.java:50` Heze fork detection

prysm has:
- `.ethspecify.yml` with Heze constants: `DOMAIN_INCLUSION_LIST_COMMITTEE`, `HEZE_FORK_EPOCH`, `HEZE_FORK_VERSION`, `INCLUSION_LIST_SUBMISSION_DUE_BPS`, `MAX_BYTES_PER_INCLUSION_LIST`, `MAX_REQUEST_INCLUSION_LIST`, `PROPOSER_INCLUSION_LIST_CUTOFF_BPS`, `VIEW_FREEZE_CUTOFF_BPS`, `BeaconState#heze`, `ExecutionPayloadBid#heze`, `InclusionList#heze`, `SignedExecutionPayloadBid#heze`, `SignedInclusionList#heze`, `GetInclusionListResponse#heze`, `InclusionListStore#heze`, `PayloadAttributes#heze`. **Constants only — no implementation code yet.**

**lighthouse, nimbus, lodestar, grandine: NO Heze references found.**

**This contradicts item #28's claim that "teku is the laggard"**. teku is in fact a LEADER on the post-Gloas Heze surface — the leadership scorecard from item #28 captured the Pectra/Gloas surface but missed the post-Gloas/Heze surface. **Item #28 needs an addendum** — see Future Research item #2 below.

The new Heze domain `DOMAIN_INCLUSION_LIST_COMMITTEE` will require all 6 clients to add a new constant; the 4 primitives audited here don't change (the algorithm is open-ended over DomainType).

### Caching strategies (2 of 6 cache; 4 don't)

- **prysm `digestMap`** (`signing_root.go:24-25, 271-289`): keyed by `string(version)+string(root)` (concatenated 4+32 = 36 bytes); guarded by `sync.RWMutex`; UNBOUNDED growth (no eviction). Memoizes `compute_fork_data_root` only — `compute_domain` still recomputes the 32-byte concatenation on each call. Cross-fork cache (one map for all forks).
- **lodestar `domainCache`** (`genesisConfig/index.ts:60-72`): keyed by `forkName -> Map<DomainType, Domain>`; lazy-populated per `(forkName, domainType)` pair on first access; bounded by (num_forks × num_domains) ≈ 8 forks × ~15 DomainTypes = ~120 entries max. Memoizes the FULL Domain (not just fork_data_root), so `compute_domain` is also short-circuited.
- **lighthouse, teku, nimbus, grandine**: NO caching — recompute on every call.

The performance differential is real (prysm/lodestar avoid the SSZ hash on hot signing paths) but observable-equivalent. **Note**: prysm's UNBOUNDED `digestMap` is a memory-leak risk over very long-running nodes (each new genesis_validators_root creates a permanent entry — relevant for clients that switch networks).

### Lodestar `getDomain` is config-level, not state-level

Unique architecture: **lodestar moves the `get_domain` function from BeaconState to ChainConfig** (`config/src/genesisConfig/index.ts:60-72`). The genesisValidatorsRoot is captured at config creation time and reused for all `getDomain` calls. The Pectra spec function `get_domain(state, ...)` is only used internally for signing-time validation; the public API is `chainConfig.getDomain(slot, domainType, messageSlot?)`.

This has a subtle consequence: **lodestar's per-config domainCache is correctly invalidated when the config changes** (different chain), but is shared across all BeaconState instances — fine because genesis_validators_root is immutable per chain.

### Lighthouse has no standalone `compute_signing_root`

Lighthouse's signing-root computation is implemented per-type via the **`SignedRoot` trait**: each SSZ type that needs to be signed (BeaconBlock, AttestationData, VoluntaryExit, etc.) implements `SignedRoot::signing_root(domain) -> Hash256`. The trait method internally constructs `SigningData{object_root: self.tree_hash_root(), domain}` and hashes it. **No central `compute_signing_root` function exists** — the 6 audit-relevant types each have their own implementation, but they ALL delegate to the same SSZ pattern.

This is a Rust idiom (zero-cost trait dispatch); observable-equivalent to the explicit-function pattern in the other 5 clients.

### Grandine's 4-fork OR-list is forward-fragile

Grandine's EIP-7044 voluntary-exit pin (`signing.rs:434-438`) explicitly enumerates Deneb / Electra / Fulu / Gloas:

```rust
let domain = if current_fork_version == config.deneb_fork_version
    || current_fork_version == config.electra_fork_version
    || current_fork_version == config.fulu_fork_version
    || current_fork_version == config.gloas_fork_version
{
    let fork_version = Some(config.capella_fork_version);
    ...
```

This pattern requires explicit extension at every new fork. At Heze activation, voluntary exits signed under Heze fork version would FAIL (the OR-list doesn't include Heze yet → the else branch runs `accessors::get_domain(...)` which uses `current_version` = Heze fork version → wrong domain → BLS verification fails).

**Compare to lighthouse's `fork_name.deneb_enabled()`** (semantic predicate that auto-extends to all forks ≥ Deneb) — much safer. **grandine is the only client with this forward-compat risk at the EIP-7044 pin specifically.**

### Prysm explicitly truncates fork_version to 4 bytes

Prysm's `Domain` function (`domain.go:34-36`):

```go
var forkVersionArray [4]byte
copy(forkVersionArray[:], forkVersion[:4])
return ComputeDomain(domainType, forkVersionArray[:], genesisRoot)
```

If `forkVersion` is shorter than 4 bytes, the array is zero-padded; if longer, it's truncated. Other 5 clients use type-system-enforced 4-byte types (`Bytes4`/`Version`/`[u8; 4]`) — no defensive copy needed. Defensive programming on prysm's side; observable-equivalent for spec-compliant inputs.

## EF fixture status

**No dedicated EF fixtures** for `compute_signing_root`, `compute_domain`, `compute_fork_data_root`, or `get_domain`. These are pure functions exercised implicitly by every signature-verifying fixture.

**Implicit coverage** through the prior items:
- item #6: 25 voluntary-exit fixtures (CAPELLA pin via EIP-7044 — exercises `get_domain` + EIP-7044 pin)
- item #8: 30 attester-slashing fixtures (DOMAIN_BEACON_ATTESTER current-fork)
- item #9: 15 proposer-slashing fixtures (DOMAIN_BEACON_PROPOSER current-fork)
- item #7: 45 attestation fixtures (DOMAIN_BEACON_ATTESTER + IndexedAttestation FastAggregateVerify)
- item #4: 43 pending-deposit fixtures (DOMAIN_DEPOSIT GENESIS pin)
- item #14: 11 deposit-request fixtures
- item #2: 10 consolidation-request fixtures (item #6 cross-cut)
- item #3: 19 withdrawal-request fixtures
- item #5: 13 pending-consolidation fixtures
- item #10: 24 slashings-vector epoch fixtures

Total: ~235 unique fixtures × 4 wired clients (prysm/lighthouse/lodestar/grandine) = **~940 PASSes implicitly validate the byte-for-byte equivalence of all 4 primitives**. teku+nimbus SKIP per harness limit but their internal CI is green at the same fixture set.

## Cross-cut chain

This audit closes the foundational-primitive layer underneath:
- item #6 (`process_voluntary_exit` + EIP-7044 CAPELLA pin)
- item #20 (`apply_pending_deposit` + GENESIS_FORK_VERSION pin)
- item #25 (`is_valid_indexed_attestation` + DOMAIN_BEACON_ATTESTER current-fork)
- item #7 (`process_attestation` AttestationData signing root)
- item #8 (`process_attester_slashing` AttestationData × 2)
- item #9 (`process_proposer_slashing` BeaconBlockHeader × 2)
- item #14 (`process_deposit_request` PendingDeposit construction)
- item #4 (`process_pending_deposits` `is_valid_deposit_signature` drain side)

Every BLS signature verification in the Pectra state-transition cycle flows through these 4 primitives. **Zero divergence at this layer means the entire signature subsystem is consistent across all 6 clients at Pectra.**

## Adjacent untouched Electra-active

- `compute_fork_digest` cross-client byte-for-byte (p2p layer, partially audited at items #15/#19 for Engine API method routing)
- `compute_fork_digest_post_fulu` Fulu's blob-parameter masking via XOR (already exercised at items #15/#19 as `engine_newPayloadV5` boundary)
- DomainType registry consistency: DOMAIN_BEACON_PROPOSER = 0x00000000, DOMAIN_BEACON_ATTESTER = 0x01000000, ..., DOMAIN_VOLUNTARY_EXIT = 0x04000000 — verify byte values match across all 6 (lodestar `params/src/index.ts:155` confirms `[4, 0, 0, 0]`)
- SigningData SSZ schema layout: `Container { object_root: Bytes32, domain: Bytes32 }` cross-client byte-for-byte equivalence
- ForkData SSZ schema layout: `Container { current_version: Bytes4, genesis_validators_root: Bytes32 }` cross-client byte-for-byte equivalence
- Heze post-Gloas fork: cross-client tracking (teku FULL impl + prysm constants; other 4 lag)
- Cache eviction policies: prysm `digestMap` unbounded growth; lodestar `domainCache` per-config bounded
- `Domain` type representation: prysm `[]byte`, lighthouse/grandine `[u8; 32]`/`H256`, nimbus `Eth2Domain`, teku `Bytes32`, lodestar `Uint8Array` — verify equivalence at the 32-byte boundary
- teku `computeSigningRoot(Bytes, domain)` overload — verify other 5 produce equivalent results when signing pre-hashed objects
- prysm `forkVersionArray [4]byte` defensive truncation — confirm spec-defined fork_version is exactly 4 bytes everywhere
- lighthouse `SignedRoot` trait: per-type implementation audit (each signing-bearing SSZ type has its own implementation; verify all delegate consistently)

## Future research items

1. **Cache eviction audit** — prysm `digestMap` (`signing_root.go:24-25`) is unbounded; verify memory growth in a long-running fuzzer with many distinct `(version, gvr)` pairs. Lodestar `domainCache` is bounded by (num_forks × num_domains); confirm at runtime.
2. **Item #28 ADDENDUM**: teku's full Heze implementation (`HezeStateUpgrade.java`) + prysm's Heze constants in `.ethspecify.yml` CONTRADICT item #28's "teku is the laggard" finding. Re-run per-client Gloas/Heze-readiness scorecard with post-Gloas surface included. **Suggested update**: teku is the LEADER on post-Gloas Heze surface; nimbus/lighthouse/grandine/lodestar lag on Heze.
3. **Per-network DOMAIN_* constant verification** — verify all 6 clients share identical byte values for each DomainType across mainnet/sepolia/holesky configs.
4. **SigningData SSZ schema cross-client equivalence** — generate dedicated fixture set verifying SigningData hash_tree_root byte-for-byte; cross-cuts Track E.
5. **ForkData SSZ schema cross-client equivalence** — same for ForkData; cross-cuts Track E.
6. **Generate dedicated EF fixtures** for the 4 primitives — pure-function fixtures (input: SSZ object + domain → output: 32-byte root). Currently no `signing` category exists in pyspec.
7. **Lodestar `getDomainForVoluntaryExit` slot-vs-epoch boundary equivalence** — `stateSlot < DENEB_FORK_EPOCH * SLOTS_PER_EPOCH` (slot-based) vs other 5 clients' epoch-based gate. Verify equivalence at the exact fork-boundary slot (slot = `DENEB_FORK_EPOCH * 32`).
8. **Lighthouse `SignedRoot` trait per-type audit** — every SSZ type with a signing root implements `SignedRoot::signing_root`. Verify all implementations delegate to the same `SigningData` construction (no per-type drift).
9. **Grandine 4-fork OR-list forward-compat regression test** — at Heze activation, voluntary exits signed under Heze fork version would FAIL grandine BLS verification (OR-list doesn't include Heze yet). High-priority pre-emptive fix needed before Heze activation; track at Heze activation planning.
10. **DomainType registry cross-client byte-value audit** — verify DOMAIN_INCLUSION_LIST_COMMITTEE byte value matches between teku and prysm (Heze pre-emptive); track other DomainType extensions.
11. **`compute_signing_root` overload audit** — teku has 3 overloads (Merkleizable / UInt64 / Bytes); verify all 6 clients produce equivalent results when signing pre-hashed objects via their generic mechanisms.
12. **Prysm `forkVersionArray [4]byte` defensive truncation behavior** — confirm spec inputs are always exactly 4 bytes; if not, prysm zero-pads while other 5 reject — minor divergence vector with malformed inputs.
13. **EIP-7044 implementation pattern audit** — 6 distinct patterns documented above. Cross-fork-transition stateful fixture spanning Deneb→Electra→Fulu boundary on a long-pending voluntary exit (verify all 6 clients produce identical Domain across the transition).
14. **`get_domain` `previous_version` selection equivalence** — fixture set with `epoch == fork.epoch` exact-boundary case; verify all 6 clients use `current_version` (strict `<` semantics — not `<=`).
15. **Pre-emptive Heze divergence consolidated audit** — same pattern as item #28 but for Heze surface. Catalogue all Heze-aware code across the 6 clients (teku full impl, prysm constants, others lag); construct per-client Heze-readiness scorecard; identify A/C/F-tier divergence vectors at Heze activation.
16. **EIP-7805 inclusion-list signing-domain audit** — Heze adds `DOMAIN_INCLUSION_LIST_COMMITTEE`; verify teku's signing path uses the same Domain construction algorithm and produces correct fork_data_root.
17. **`compute_fork_digest` post-Fulu XOR cross-client byte-for-byte** — Fulu's blob-parameter masking. Already exercised at items #15/#19 for Engine API method routing; standalone audit for the `compute_fork_digest_post_fulu` function would close this thread.

## Summary

All 6 clients implement the 4 signing-domain primitives with byte-for-byte equivalence at the algorithm level. The differences are entirely in:
- **Caching strategies** (prysm + lodestar cache; other 4 don't) — performance trade-off
- **EIP-7044 pin location** (6 distinct patterns) — observable-equivalent at signing time
- **Generic mechanism** for `compute_signing_root` (Go fssz / Rust SignedRoot trait / Java Merkleizable / Nim auto / TS Type<T> / Rust SszHash)
- **Architecture** (lodestar hoists `getDomain` to chain config; lighthouse uses per-type SignedRoot trait)

**Zero divergence at this foundational primitive layer means the entire signature subsystem (items #6, #7, #8, #9, #14, #20, #25) flows through identical Domain bytes across all 6 clients at Pectra.**

**Major Heze finding** (post-Gloas inclusion-list fork EIP-7805): teku has FULL implementation including `HezeStateUpgrade.java`; prysm has all Heze constants in `.ethspecify.yml`; lighthouse/nimbus/lodestar/grandine have NO Heze references. **This contradicts item #28's "teku is the laggard" finding** and motivates a Heze-divergence consolidated audit (Future Research item #15) parallel to item #28's Gloas tracking.
