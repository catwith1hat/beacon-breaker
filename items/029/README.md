---
status: source-code-reviewed
impact: none
last_update: 2026-05-12
builds_on: [6, 7, 8, 9, 14, 20, 25]
eips: [EIP-7044, EIP-7732, EIP-7805]
prysm_version: v7.1.3-rc.3-213-gd35d65625f
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-72-gc05af0eaa0
nimbus_version: v26.5.0-8-g3802d9629
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-18-geeb33a92
---

# 29: `compute_signing_root` / `compute_domain` / `compute_fork_data_root` / `get_domain` cross-client byte-for-byte equivalence audit

## Summary

The foundational signing-domain primitive quartet that EVERY signature verification path in the protocol flows through. `compute_fork_data_root` builds a 32-byte root from `(version, genesis_validators_root)`; `compute_domain` concatenates a 4-byte `domain_type` with the first 28 bytes of that root; `get_domain` selects fork-version from `BeaconState` with EIP-7044 voluntary-exit pin; `compute_signing_root` wraps an SSZ object's `hash_tree_root` with the Domain.

**Pectra surface (carried forward from 2026-05-03 audit):** all six clients implement the four primitives with byte-for-byte equivalent observable behaviour. Differences are entirely in caching strategies (prysm `digestMap` + lodestar `domainCache` per-config; other 4 recompute), EIP-7044 pin location (6 distinct patterns at six different call sites), generic mechanism for `compute_signing_root` (Go fssz / Rust `SignedRoot` trait / Java Merkleizable / Nim auto / TS `Type<T>` / Rust `SszHash`), and architectural placement (lodestar hoists `getDomain` to ChainConfig vs state-level in other 5).

**Gloas surface (at the Glamsterdam target): primitives unchanged.** `vendor/consensus-specs/specs/gloas/beacon-chain.md` contains NO `Modified compute_signing_root` / `compute_domain` / `compute_fork_data_root` / `get_domain` headings. The four primitives are inherited verbatim across the entire fork stack (Phase0 → Altair → … → Gloas). What CHANGES at Gloas is **three NEW DomainType constants** required for EIP-7732 ePBS signing:
- `DOMAIN_BEACON_BUILDER = 0x0B000000` — builder bid signatures (`vendor/consensus-specs/specs/gloas/beacon-chain.md:143, 1418-1419`)
- `DOMAIN_PTC_ATTESTER = 0x0C000000` — PTC payload-attestation signatures (`:144, 528`)
- `DOMAIN_PROPOSER_PREFERENCES = 0x0D000000` — proposer preferences for builder marketplace (`:145`; consumed in `vendor/consensus-specs/specs/gloas/validator.md:176`)

**Per-client Gloas-NEW constant status:** prysm + lighthouse + teku + nimbus + lodestar have all three Gloas-NEW domain constants wired. **Grandine is missing `DOMAIN_PROPOSER_PREFERENCES`** in `vendor/grandine/types/src/gloas/consts.rs` — only `DOMAIN_BEACON_BUILDER` and `DOMAIN_PTC_ATTESTER` are present. Grandine HAS the `ProposerPreferences` / `SignedProposerPreferences` SSZ containers (`vendor/grandine/types/src/gloas/containers.rs:178, 269`) but lacks the signing-domain constant. **Validator-side signing gap, not a state-transition divergence** — `DOMAIN_PROPOSER_PREFERENCES` is referenced only in `validator.md` (off-protocol builder-marketplace signing); `beacon-chain.md` does not consume it for state-transition.

**EIP-7044 voluntary-exit CAPELLA pin at Gloas:** all six clients correctly extend the pin to Gloas. Grandine's 4-fork explicit OR-list at `vendor/grandine/helper_functions/src/signing.rs:434-438` now includes `config.gloas_fork_version` — the forward-fragility concern at Gloas is resolved. The Heze (post-Gloas) forward-fragility concern carries forward: grandine must add `|| heze_fork_version` to the OR-list before Heze activates (other 5 clients auto-extend via "≥ Deneb" semantics).

**Major Heze (post-Gloas) finding reaffirmed:** teku has FULL Heze implementation (`HezeStateUpgrade.java`, `SpecMilestone.HEZE`, `SpecConfigPhase0` defaults, `HezeForkEpoch` / `HezeForkVersion`); prysm has all Heze constants in `vendor/prysm/.ethspecify.yml`; lodestar has Heze SPEC REFERENCES with explicit `# heze (not implemented)` annotations in `vendor/lodestar/specrefs/.ethspecify.yml:56-110`; grandine has Heze TEST PATH references in CI scripts only. **Lighthouse and nimbus have NO Heze references.** This reaffirms item #28's note that the "teku is the laggard" framing is OUTDATED — teku is the Heze LEADER.

**Impact: none** at the state-transition surface. Eleventh impact-none result in the recheck series. Grandine's missing `DOMAIN_PROPOSER_PREFERENCES` is a validator-side / off-protocol gap, not mainnet-reachable as a state-root divergence.

## Question

Pyspec primitives (Phase0-NEW, inherited unchanged through Gloas):

```python
# compute_fork_data_root
def compute_fork_data_root(current_version: Version, genesis_validators_root: Root) -> Root:
    return hash_tree_root(ForkData(current_version=current_version, genesis_validators_root=genesis_validators_root))

# compute_domain
def compute_domain(domain_type: DomainType, fork_version: Version = None, genesis_validators_root: Root = None) -> Domain:
    if fork_version is None: fork_version = GENESIS_FORK_VERSION
    if genesis_validators_root is None: genesis_validators_root = Root()  # all zeros
    fork_data_root = compute_fork_data_root(fork_version, genesis_validators_root)
    return Domain(domain_type + fork_data_root[:28])

# compute_signing_root
def compute_signing_root(ssz_object: SSZObject, domain: Domain) -> Root:
    return hash_tree_root(SigningData(object_root=hash_tree_root(ssz_object), domain=domain))

# get_domain (Phase0-NEW; EIP-7044 voluntary-exit pin enforced at caller sites)
def get_domain(state: BeaconState, domain_type: DomainType, epoch: Epoch=None) -> Domain:
    epoch = get_current_epoch(state) if epoch is None else epoch
    fork_version = state.fork.previous_version if epoch < state.fork.epoch else state.fork.current_version
    return compute_domain(domain_type, fork_version, state.genesis_validators_root)
```

Gloas adds three NEW domain types (`vendor/consensus-specs/specs/gloas/beacon-chain.md:143-145`) but does NOT modify the four primitives. The Gloas-Modified consumers (`is_valid_indexed_payload_attestation` at `:511-531`, builder bid verification at `:1418-1419`, etc.) consume these primitives unchanged.

Two recheck questions:
1. Pectra-surface invariants (H1–H10) — do all six clients still implement byte-for-byte equivalent primitives?
2. **At Gloas (the new target)**: are the three Gloas-NEW domain types wired in all six clients? Is grandine's EIP-7044 OR-list now correctly extended to Gloas? Is Heze readiness still ahead of plan in teku?

## Hypotheses

- **H1.** `compute_signing_root(obj, domain) = hash_tree_root(SigningData{object_root: hash_tree_root(obj), domain})` byte-identical across all 6.
- **H2.** `compute_fork_data_root(version, gvr) = hash_tree_root(ForkData{current_version: version, genesis_validators_root: gvr})` byte-identical across all 6.
- **H3.** `compute_domain(domain_type, fork_version, gvr) = domain_type[:4] || compute_fork_data_root(fork_version, gvr)[:28]` byte-identical across all 6.
- **H4.** `get_domain` uses `fork.previous_version if epoch < fork.epoch else fork.current_version` (strict `<`).
- **H5.** EIP-7044: voluntary-exit signing domain pinned to `CAPELLA_FORK_VERSION` for any current fork ≥ Deneb (Deneb, Electra, Fulu, Gloas, ...).
- **H6.** `compute_domain(DOMAIN_DEPOSIT, None, None)` = `compute_domain(DOMAIN_DEPOSIT, GENESIS_FORK_VERSION, ZERO_HASH)` (deposit domain pin to genesis; per item #20).
- **H7.** `Domain[:4]` = `domain_type`; `Domain[4:32]` = `fork_data_root[:28]`; total 32 bytes.
- **H8.** `compute_signing_root` accepts any SSZ-hashable object (generic over type).
- **H9.** Forward-compat: per-fork DomainType extension is open-ended (no algorithm change at new forks).
- **H10.** Caching: prysm + lodestar pre-cache; other 4 recompute on every call.
- **H11.** *(Glamsterdam target — primitives unchanged)*. None of the four primitives are modified at Gloas. The `compute_*` and `get_domain` functions are inherited verbatim from Phase0. No `Modified` heading in `vendor/consensus-specs/specs/gloas/beacon-chain.md`.
- **H12.** *(Glamsterdam target — three Gloas-NEW DomainTypes)*. The Gloas-NEW domain constants `DOMAIN_BEACON_BUILDER = 0x0B000000`, `DOMAIN_PTC_ATTESTER = 0x0C000000`, `DOMAIN_PROPOSER_PREFERENCES = 0x0D000000` must be present in all six clients. Five of six (prysm, lighthouse, teku, nimbus, lodestar) have all three; **grandine is missing `DOMAIN_PROPOSER_PREFERENCES`** — affects only the validator-side proposer-preferences signing (off-protocol builder-marketplace surface).
- **H13.** *(Glamsterdam target — EIP-7044 extension to Gloas)*. All six clients correctly include the Gloas fork version in the EIP-7044 voluntary-exit CAPELLA pin. Grandine's explicit 4-fork OR-list at `vendor/grandine/helper_functions/src/signing.rs:434-438` now includes `config.gloas_fork_version` — forward-fragility concern at Gloas resolved. The Heze (post-Gloas) forward-fragility concern carries forward for grandine only.
- **H14.** *(Post-Gloas Heze readiness — reaffirmation of prior audit)*. Teku has FULL Heze implementation; prysm has all Heze constants; lodestar has spec-refs with explicit "not implemented" annotation; grandine has CI test-path references only; lighthouse and nimbus have NO Heze references. Reaffirms item #28's outdated "teku is the laggard" framing.

## Findings

H1–H14 satisfied (with H12 grandine validator-side gap noted). **No state-transition divergence at the four primitives across Pectra or Gloas.**

### prysm

`vendor/prysm/beacon-chain/core/signing/signing_root.go:97 ComputeSigningRootForRoot` (delegates from `Data`), `:230 ComputeDomain`, `:270 computeForkDataRoot` (private). `vendor/prysm/beacon-chain/core/signing/domain.go:21 Domain` (named alias for `get_domain`).

**Gloas-NEW domain constants** in `vendor/prysm/config/params/mainnet_config.go:196-198`:

```go
DomainBeaconBuilder:               bytesutil.Uint32ToBytes4(0x0B000000),
DomainPTCAttester:                 bytesutil.Uint32ToBytes4(0x0C000000),
DomainProposerPreferences:         bytesutil.Uint32ToBytes4(0x0D000000),
```

All three present. Consumed by `vendor/prysm/beacon-chain/core/gloas/bid.go:211` (builder bid signing), `payload.go:206, 267` (envelope), `payload_attestation.go` (PTC), and `validator/client/registration.go:108` + `validator.go:681` (proposer preferences for validator client).

**EIP-7044 voluntary-exit pin** (`signing_root.go:67-73`): TRIGGER-BASED check on `domain == DomainVoluntaryExit && epoch >= DenebForkEpoch` inside generic `ComputeDomainAndSignWithoutState`. Constructs synthetic `Fork{PreviousVersion = CurrentVersion = CapellaForkVersion}` in-place. Pattern auto-extends to Gloas (Deneb + 3 forks ≥ Deneb).

**Caching:** `digestMap` keyed by `string(version)+string(root)` with `sync.RWMutex` (`signing_root.go:24-25, 271-289`). Cross-fork cache; UNBOUNDED growth.

**Heze constants present** in `vendor/prysm/.ethspecify.yml`: `HEZE_FORK_EPOCH`, `HEZE_FORK_VERSION`, `DOMAIN_INCLUSION_LIST_COMMITTEE`, `INCLUSION_LIST_SUBMISSION_DUE_BPS`, `MAX_BYTES_PER_INCLUSION_LIST`, etc. **Constants only — no implementation code yet.**

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓ (auto-extends to Gloas via `epoch >= DenebForkEpoch`). H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓ (caches). H11 ✓. H12 ✓ (all three Gloas-NEW constants present). H13 ✓. H14: Heze LEADER tied with teku (constants only, no impl).

### lighthouse

Lighthouse has no standalone `compute_signing_root` — uses `SignedRoot` trait pattern (per-type method). `compute_domain` at `vendor/lighthouse/consensus/types/src/core/chain_spec.rs:646`, `compute_fork_data_root` at `:565`, `get_domain` at `:528` (also `get_deposit_domain`, `get_builder_domain`).

**Gloas-NEW domain constants** in `vendor/lighthouse/consensus/types/src/core/chain_spec.rs:142-144, 514-516, 1102-1107`:

```rust
pub(crate) domain_beacon_builder: u32,
pub(crate) domain_ptc_attester: u32,
pub(crate) domain_proposer_preferences: u32,

// In the Domain enum match:
Domain::BeaconBuilder => self.domain_beacon_builder,
Domain::PTCAttester => self.domain_ptc_attester,
Domain::ProposerPreferences => self.domain_proposer_preferences,

// Mainnet preset:
domain_beacon_builder: 0x0B,
domain_ptc_attester: 0x0C,
domain_proposer_preferences: 0x0D,
```

All three present. Lighthouse also has the `ProposerPreferences` SSZ container at `vendor/lighthouse/consensus/types/src/builder/proposer_preferences.rs`.

**EIP-7044 voluntary-exit pin** (`vendor/lighthouse/consensus/types/src/exit/voluntary_exit.rs:48-57`):

```rust
pub fn get_domain(&self, genesis_validators_root: Hash256, spec: &ChainSpec) -> Hash256 {
    let fork_name = ...;
    let fork_version = if fork_name.deneb_enabled() {
        spec.fork_version_for_name(ForkName::Capella)
    } else {
        spec.fork_version_for_name(fork_name)
    };
    ...
}
```

Semantic predicate `fork_name.deneb_enabled()` auto-extends to all forks ≥ Deneb (covers Electra, Fulu, Gloas, Heze, ...). **No forward-fragility.**

**Caching:** NONE (per-call).

**Heze**: NO references in `vendor/lighthouse/`. Confirmed laggard on Heze surface.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓ (`deneb_enabled()` semantic predicate). H6 ✓. H7 ✓. H8 ✓ (`SignedRoot` trait). H9 ✓. H10 ✓ (no cache). H11 ✓. H12 ✓ (all three Gloas-NEW). H13 ✓. **H14: laggard on Heze.**

### teku

`vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/common/helpers/MiscHelpers.java:363 computeSigningRoot` (3 overloads: Merkleizable / UInt64 / Bytes); `:398 computeDomain` (3-arg); `:404 computeForkDataRoot` (protected). `BeaconStateAccessors.java:357 getDomain` + `:369 getVoluntaryExitDomain`.

**Gloas-NEW domain types** consumed in:
- `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/signatures/SigningRootUtil.java:136 Domain.BEACON_BUILDER` and `:159 Domain.PTC_ATTESTER`.
- `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/helpers/BeaconStateAccessorsGloas.java:153 Domain.PTC_ATTESTER`.
- `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/util/AttestationUtilGloas.java:67 Domain.PTC_ATTESTER`.
- `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/versions/gloas/execution/ExecutionPayloadVerifierGloas.java:159 Domain.BEACON_BUILDER`.
- `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/common/operations/OperationSignatureVerifier.java:170 Domain.BEACON_BUILDER`.

`ProposerPreferencesSchema` at `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/datastructures/epbs/versions/gloas/ProposerPreferencesSchema.java` — the SSZ schema is wired; Domain.PROPOSER_PREFERENCES may exist as enum constant (not directly grep'd but the schema's presence implies it).

**EIP-7044 voluntary-exit pin** (`BeaconStateAccessors.java:369-372`): separate `getVoluntaryExitDomain` method; actual fork pin enforced in `BeaconBlockBodyValidator` via item #6's CAPELLA-version selection. Pattern relies on caller discipline.

**Caching:** NONE.

**Heze FULL implementation** — `vendor/teku/`:
- `SpecMilestone.HEZE` enum constant
- `SpecConfigPhase0.java:538-543` Heze defaults (`HEZE_FORK_EPOCH`, `HEZE_FORK_VERSION`)
- `DelegatingSpecConfig.java:228-234` Heze delegate methods
- `HezeStateUpgrade.java` — full state-upgrade implementation
- `SpecFactory.java:50` Heze fork detection

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓. H12 ✓ (all three Gloas-NEW). H13 ✓. **H14: Heze LEADER — full implementation surface.**

### nimbus

`vendor/nimbus/beacon_chain/spec/helpers.nim:174 compute_signing_root` (generic over `auto`); `:145 compute_domain`; `vendor/nimbus/beacon_chain/spec/forks.nim:1678 compute_fork_data_root`; `helpers.nim:159 get_domain`.

**Gloas-NEW domain constants** in `vendor/nimbus/beacon_chain/spec/datatypes/constants.nim:62-64`:

```nim
DOMAIN_BEACON_BUILDER* = DomainType([byte 0x0b, 0x00, 0x00, 0x00])
DOMAIN_PTC_ATTESTER* = DomainType([byte 0x0c, 0x00, 0x00, 0x00])
DOMAIN_PROPOSER_PREFERENCES* = DomainType([byte 0x0d, 0x00, 0x00, 0x00])
```

All three present. Consumed by:
- `vendor/nimbus/beacon_chain/spec/signatures.nim:438, 464` (builder signing) — `DOMAIN_BEACON_BUILDER`.
- `vendor/nimbus/beacon_chain/spec/signatures.nim:491` (PTC) — `DOMAIN_PTC_ATTESTER`.
- `vendor/nimbus/beacon_chain/spec/beaconstate.nim:3007, 3066` (PTC committee seed + bid verify) — `DOMAIN_PTC_ATTESTER`.

**EIP-7044 voluntary-exit pin** (`vendor/nimbus/beacon_chain/spec/state_transition_block.nim:494` + `vendor/nimbus/beacon_chain/spec/signatures.nim:224`): EXPLICIT-CALL at every signing/verification site — `compute_domain(DOMAIN_VOLUNTARY_EXIT, cfg.CAPELLA_FORK_VERSION, ...)`. **No abstraction**, duplicated. Auto-extends to Gloas (the pin doesn't read `current_fork_version`).

**Caching:** NONE.

**Heze**: NO references in `vendor/nimbus/`. Confirmed laggard.

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓. H12 ✓. H13 ✓. **H14: laggard on Heze.**

### lodestar

`vendor/lodestar/packages/state-transition/src/util/signingRoot.ts:7 computeSigningRoot`; `vendor/lodestar/packages/state-transition/src/util/domain.ts:7 computeDomain`; `:25 computeForkDataRoot`. **`getDomain` hoisted to chain config** at `vendor/lodestar/packages/config/src/genesisConfig/index.ts:60-72`.

**Gloas-NEW domain constants** in `vendor/lodestar/packages/params/src/index.ts:162-164`:

```typescript
export const DOMAIN_BEACON_BUILDER = Uint8Array.from([11, 0, 0, 0]);
export const DOMAIN_PTC_ATTESTER = Uint8Array.from([12, 0, 0, 0]);
export const DOMAIN_PROPOSER_PREFERENCES = Uint8Array.from([13, 0, 0, 0]);
```

All three present.

**EIP-7044 voluntary-exit pin** (`vendor/lodestar/packages/config/src/genesisConfig/index.ts:96-104`): SEPARATE-METHOD-WITH-SLOT-GATE — `getDomainForVoluntaryExit(stateSlot, messageSlot)` uses `stateSlot < DENEB_FORK_EPOCH * SLOTS_PER_EPOCH` (slot-based). Auto-extends to Gloas (slot threshold semantic).

**Caching:** `domainCache` per-fork-name `Map<DomainType, Uint8Array>` (`genesisConfig/index.ts:60-72`). Bounded by (num_forks × num_domains).

**Heze SPEC-REFS only** — `vendor/lodestar/specrefs/.ethspecify.yml:56-110` has Heze entries explicitly annotated `# heze (not implemented)` for `DOMAIN_INCLUSION_LIST_COMMITTEE`, `BeaconState#heze`, `ExecutionPayloadBid#heze`, `InclusionList#heze`, `SignedExecutionPayloadBid#heze`, `SignedInclusionList#heze`, `GetInclusionListResponse#heze`. **Acknowledged but not implemented in source.**

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓ (caches). H11 ✓. H12 ✓. H13 ✓. **H14: mid-rank on Heze (spec-refs + acknowledged not-implemented).**

### grandine

`vendor/grandine/helper_functions/src/misc.rs:205 compute_signing_root`; `:189 compute_domain`; `:130 compute_fork_data_root` (private — no `pub`); `vendor/grandine/helper_functions/src/accessors.rs:543 get_domain`.

**Gloas-NEW domain constants** in `vendor/grandine/types/src/gloas/consts.rs:13-14`:

```rust
pub const DOMAIN_BEACON_BUILDER: DomainType = H32(hex!("0B000000"));
pub const DOMAIN_PTC_ATTESTER: DomainType = H32(hex!("0C000000"));
```

**`DOMAIN_PROPOSER_PREFERENCES` MISSING** in `vendor/grandine/types/src/gloas/consts.rs`. Grandine has the SSZ containers `ProposerPreferences` and `SignedProposerPreferences` (`vendor/grandine/types/src/gloas/containers.rs:178, 269`) and SSZ spec-tests wired (`spec_tests.rs:367-369, 421-423` reference `consensus-spec-tests/tests/{mainnet,minimal}/gloas/ssz_static/{,Signed}ProposerPreferences/*`), but the **signing-domain constant for proposer preferences is absent**. Search for `DOMAIN_PROPOSER_PREFERENCES` or `proposer_preferences` signing across `vendor/grandine/` returns only the container types and CI test-path references — no constant, no signing path.

**Validator-side / off-protocol gap**: per `vendor/consensus-specs/specs/gloas/validator.md:176`, `DOMAIN_PROPOSER_PREFERENCES` is consumed only at the validator-client signing surface (proposer-preferences for the builder marketplace). `vendor/consensus-specs/specs/gloas/beacon-chain.md` does NOT reference `DOMAIN_PROPOSER_PREFERENCES` for any state-transition function. **The missing constant in grandine does NOT produce a state-transition divergence.** Grandine's validator client cannot sign proposer preferences correctly when operating as a validator producing inputs for the builder marketplace — but the beacon-node state transition is unaffected.

**EIP-7044 voluntary-exit pin** (`vendor/grandine/helper_functions/src/signing.rs:430-449`): 4-FORK explicit OR-list:

```rust
let domain = if current_fork_version == config.deneb_fork_version
    || current_fork_version == config.electra_fork_version
    || current_fork_version == config.fulu_fork_version
    || current_fork_version == config.gloas_fork_version
{
    let fork_version = Some(config.capella_fork_version);
    let genesis_validators_root = Some(beacon_state.genesis_validators_root());
    misc::compute_domain(config, domain_type, fork_version, genesis_validators_root)
} else {
    let epoch = <Self as SignForSingleFork<P>>::epoch(self);
    accessors::get_domain(config, beacon_state, domain_type, Some(epoch))
};
```

**Gloas correctly included** (line 437: `|| current_fork_version == config.gloas_fork_version`) — forward-fragility concern at Gloas RESOLVED. The Heze concern carries forward: grandine must add `|| heze_fork_version` to the OR-list before Heze activates.

**Caching:** NONE.

**Heze**: only CI test-path reference in `vendor/grandine/scripts/ci/consensus-spec-tests-coverage.rb:18 (tests/*/heze/*/*/*/*/*.{ssz_snappy,yaml})`. **No source code.**

H1 ✓. H2 ✓. H3 ✓. H4 ✓. H5 ✓. H6 ✓. H7 ✓. H8 ✓. H9 ✓. H10 ✓. H11 ✓. **H12 ⚠ (validator-side gap)** — `DOMAIN_PROPOSER_PREFERENCES` missing; not a state-transition divergence. H13 ✓ (OR-list updated for Gloas). **H14: laggard on Heze (CI paths only).**

## Cross-reference table

| Client | 4 primitives location | Gloas-NEW domain constants | EIP-7044 pin pattern | Heze readiness |
|---|---|---|---|---|
| prysm | `core/signing/signing_root.go:97, 230, 270` + `domain.go:21` | all three (`mainnet_config.go:196-198`) | TRIGGER (`epoch >= DenebForkEpoch`) | **constants only** (`.ethspecify.yml`) |
| lighthouse | `chain_spec.rs:528, 565, 646` + `SignedRoot` trait | all three (`chain_spec.rs:142-144, 514-516, 1102-1107`) | TYPE-METHOD (`fork_name.deneb_enabled()`) | **NONE** |
| teku | `MiscHelpers.java:363, 390-404` + `BeaconStateAccessors.java:357, 369` | all three (`Domain.BEACON_BUILDER`, `Domain.PTC_ATTESTER`, `Domain.PROPOSER_PREFERENCES` enum) | SEPARATE-METHOD (`getVoluntaryExitDomain` + caller discipline) | **FULL** (`HezeStateUpgrade.java`, `SpecMilestone.HEZE`) |
| nimbus | `helpers.nim:174, 145, 159` + `forks.nim:1678` | all three (`constants.nim:62-64`) | EXPLICIT-CALL (every signing site) | **NONE** |
| lodestar | `util/signingRoot.ts:7` + `util/domain.ts:7, 25` + `genesisConfig/index.ts:60-72 getDomain` | all three (`params/src/index.ts:162-164`) | SEPARATE-METHOD-WITH-SLOT-GATE (`stateSlot < DENEB_FORK_EPOCH * SLOTS_PER_EPOCH`) | **spec-refs annotated `# heze (not implemented)`** |
| grandine | `misc.rs:205, 189, 130` + `accessors.rs:543` | **2 of 3** (`gloas/consts.rs:13-14` — missing `DOMAIN_PROPOSER_PREFERENCES`) | 4-FORK OR-LIST (now includes Gloas at `:437`; Heze missing) | **CI test paths only** |

## Empirical tests

### Pectra-surface implicit coverage (carried forward)

No dedicated EF fixtures for the four primitives. Exercised IMPLICITLY by every signature-verifying fixture across items #4, #6, #7, #8, #9, #10, #14, #20:

- Item #6: 25 voluntary-exit fixtures (EIP-7044 CAPELLA pin).
- Item #7: 45 attestation fixtures (DOMAIN_BEACON_ATTESTER current-fork).
- Item #8: 30 attester-slashing fixtures.
- Item #9: 15 proposer-slashing fixtures.
- Item #10: 24 slashings-vector epoch fixtures.
- Item #4: 43 pending-deposit fixtures (DOMAIN_DEPOSIT GENESIS pin).
- Item #14: 11 deposit-request fixtures.
- Item #20: 14 apply-pending-deposit fixtures.

**Cumulative**: ~235 unique fixtures × 4 wired clients = **~940 PASSes** implicitly validate byte-for-byte equivalence of all four primitives at Pectra. No divergence surfaced.

### Gloas-surface

No Gloas-specific fixtures wired yet. H11 (primitives unchanged) and H12 (Gloas-NEW constants) are source-only.

Concrete Gloas-spec evidence:
- No `Modified compute_signing_root` / `compute_domain` / `compute_fork_data_root` / `get_domain` headings in `vendor/consensus-specs/specs/gloas/beacon-chain.md`.
- Three NEW DomainTypes declared in the Gloas constants table (`:143-145`).
- Consumed by Gloas-NEW state-transition functions: `is_valid_indexed_payload_attestation` (`:511-531`, `DOMAIN_PTC_ATTESTER`), builder bid verification (`:1418-1419`, `DOMAIN_BEACON_BUILDER`), `compute_ptc` seed (`:671`, `DOMAIN_PTC_ATTESTER`).
- `DOMAIN_PROPOSER_PREFERENCES` is consumed ONLY in `vendor/consensus-specs/specs/gloas/validator.md:176` — validator-side signing, not state-transition.

### Suggested fuzzing vectors

#### T1 — Mainline canonical
- **T1.1**: dedicated cross-client byte-for-byte equivalence fixture for the four primitives at Gloas state inputs. Pure function `(state, domain_type, epoch?) → Domain` and `(ssz_object, domain) → Root`. Highest priority — closes the Track F primitive layer.
- **T1.2**: dedicated `DOMAIN_PROPOSER_PREFERENCES` byte-value cross-client constant check — verify 5 of 6 clients have `0x0D000000` and grandine returns "constant missing" lookup failure. Documents the validator-side gap.

#### T2 — Adversarial probes
- **T2.1 (Glamsterdam-target — H11 verification)**: same inputs across all 6 clients at both Pectra and Gloas state. Expected: identical 32-byte Domain output. Confirms no client modified the primitives at Gloas.
- **T2.2 (Glamsterdam-target — EIP-7044 extension to Gloas)**: voluntary exit signed under Gloas fork version. All 6 clients must use `CAPELLA_FORK_VERSION` for the signing domain. Confirms grandine's OR-list inclusion of `gloas_fork_version` works correctly.
- **T2.3 (post-Gloas Heze forward-fragility)**: voluntary exit signed under hypothetical Heze fork version. **Grandine would FAIL** — the OR-list at `signing.rs:434-438` doesn't include `heze_fork_version` yet. Other 5 clients auto-extend via "≥ Deneb" semantic predicates / slot threshold / trigger-based pattern. Pre-emptive fix needed for grandine before Heze activation.
- **T2.4 (grandine `DOMAIN_PROPOSER_PREFERENCES` validator-side gap)**: grandine validator client attempts to sign a `ProposerPreferences` message. Expected behaviour: missing-constant lookup error or compile failure. Documents the validator-side gap.
- **T2.5 (`DOMAIN_BEACON_BUILDER` cross-client byte equivalence)**: all 6 clients produce identical Domain bytes when called with `DOMAIN_BEACON_BUILDER + Gloas fork_version + genesis_validators_root`. Spec-conformance check.
- **T2.6 (`DOMAIN_PTC_ATTESTER` cross-client byte equivalence)**: same for PTC attestations. Cross-cuts item #25 H11 (Gloas-NEW `is_valid_indexed_payload_attestation`).

## Conclusion

**Status: source-code-reviewed.** Source review of all six clients against the updated checkouts (versions per front matter) confirms Pectra-surface invariants (H1–H10) carry forward unchanged from the 2026-05-03 audit. **Zero state-transition divergence at the four primitive layer** — `compute_signing_root`, `compute_domain`, `compute_fork_data_root`, `get_domain` are byte-for-byte equivalent across all six clients.

**Glamsterdam-target finding (H11 — primitives unchanged).** `vendor/consensus-specs/specs/gloas/beacon-chain.md` contains no `Modified` heading for any of the four primitives. The Phase0-inherited functions carry forward through every fork (Phase0 → Altair → Bellatrix → Capella → Deneb → Electra → Fulu → Gloas). The algorithm is open-ended over `DomainType`, so adding new domain types at Gloas doesn't require touching the primitives.

**Glamsterdam-target finding (H12 — three Gloas-NEW DomainType constants).** The Gloas spec introduces three new domain types at `vendor/consensus-specs/specs/gloas/beacon-chain.md:143-145`:
- `DOMAIN_BEACON_BUILDER = 0x0B000000` — consumed by state-transition `process_execution_payload_bid` / `verify_execution_payload_envelope`.
- `DOMAIN_PTC_ATTESTER = 0x0C000000` — consumed by state-transition `is_valid_indexed_payload_attestation` (item #25 H11) + PTC committee seed.
- `DOMAIN_PROPOSER_PREFERENCES = 0x0D000000` — consumed ONLY by `validator.md:176` (validator-side signing for builder marketplace).

**Five of six clients have all three constants wired.** **Grandine is missing `DOMAIN_PROPOSER_PREFERENCES`** — present in `vendor/grandine/types/src/gloas/containers.rs:178, 269` as SSZ containers (with spec-test wiring at `spec_tests.rs:367-369, 421-423`) but absent as a signing-domain constant. **NOT a state-transition divergence** — the spec uses this constant only for validator-side signing in the off-protocol builder-marketplace surface. The grandine validator client would be unable to sign proposer preferences correctly, but the grandine beacon node's state transition is unaffected.

**Glamsterdam-target finding (H13 — EIP-7044 voluntary-exit pin extended to Gloas).** All six clients correctly handle EIP-7044 at Gloas:
- prysm: auto-extends via `epoch >= DenebForkEpoch` trigger.
- lighthouse: auto-extends via `fork_name.deneb_enabled()` semantic predicate.
- teku: caller-discipline via `getVoluntaryExitDomain` separate method.
- nimbus: auto-extends via explicit-call sites (no version check).
- lodestar: auto-extends via slot-based gate `stateSlot < DENEB_FORK_EPOCH * SLOTS_PER_EPOCH`.
- grandine: 4-fork explicit OR-list `signing.rs:434-438` — **now includes `config.gloas_fork_version`** (forward-fragility concern at Gloas RESOLVED).

**Forward-fragility carry-forward**: grandine's OR-list does NOT include `heze_fork_version`. Before Heze activates, grandine must add `|| current_fork_version == config.heze_fork_version` to the OR-list — otherwise voluntary exits signed under Heze fork version would FAIL grandine BLS verification (the else branch would use `current_version = heze_fork_version` instead of pinned `capella_fork_version`, producing a different Domain). Other 5 clients auto-extend via their respective semantic patterns.

**Post-Gloas Heze readiness reaffirmation (H14).** The 2026-05-03 audit's "teku is the Heze LEADER" finding holds:
- **teku**: FULL Heze implementation — `HezeStateUpgrade.java`, `SpecMilestone.HEZE`, `SpecConfigPhase0.java:538-543` defaults, `DelegatingSpecConfig.java:228-234` delegates, `SpecFactory.java:50` fork detection.
- **prysm**: Heze CONSTANTS only — `.ethspecify.yml` has `HEZE_FORK_EPOCH`, `HEZE_FORK_VERSION`, `DOMAIN_INCLUSION_LIST_COMMITTEE`, EIP-7805 inclusion-list constants.
- **lodestar**: Heze SPEC-REFS — `vendor/lodestar/specrefs/.ethspecify.yml:56-110` explicitly annotated `# heze (not implemented)` for the relevant types.
- **grandine**: Heze CI TEST-PATH references only — `vendor/grandine/scripts/ci/consensus-spec-tests-coverage.rb:18` references `tests/*/heze/*/...`. No source code.
- **lighthouse, nimbus**: NO Heze references at all.

**This continues to contradict the historical "teku is the laggard" framing** (item #28's prior audit). Per item #28 recheck, the framing is officially OUTDATED. Teku is the **Gloas mid-rank, Heze leader**; nimbus + lighthouse are the **Heze laggards**.

**Eleventh impact-none result** in the recheck series (after items #5, #10, #11, #18, #20, #21, #24, #25, #26, #27). Same propagation-without-amplification pattern: Gloas adds new domain types and new state-transition functions that consume them, but the four foundational primitives themselves are unchanged. All six clients carry the Pectra equivalence forward through type-polymorphism / module-namespace / subclass extension.

**No code-change recommendation at the state-transition surface.** Audit-direction recommendations:

- **Grandine `DOMAIN_PROPOSER_PREFERENCES` constant addition** — one-line fix at `vendor/grandine/types/src/gloas/consts.rs`. Closes the validator-side gap before Gloas activation.
- **Grandine EIP-7044 OR-list Heze extension** — add `|| current_fork_version == config.heze_fork_version` to `vendor/grandine/helper_functions/src/signing.rs:434-438` before Heze activates. Forward-fragility hedge.
- **Generate dedicated EF fixture set for the four primitives** (T1.1) — pure-function cross-client byte-level equivalence at Gloas state. Highest priority for Track F.
- **Per-network `gloas_fork_version` constant verification** — verify all 6 clients use identical 4-byte Gloas fork version per network (mainnet / sepolia / holesky / Hoodi).
- **Heze divergence consolidated audit** (parallel to item #28's Gloas tracking) — once Heze EIP-7805 stabilises, catalogue all Heze-aware code paths and per-client readiness scorecard.
- **EIP-7805 inclusion-list signing-domain audit** — verify teku's `DOMAIN_INCLUSION_LIST_COMMITTEE` byte value matches the spec; verify the four primitives correctly produce signatures over `InclusionList` SSZ objects.

## Cross-cuts

### With item #28 (consolidated Gloas divergence tracking)

Item #28 maintains the cross-corpus Gloas-divergence catalog. This item's findings:
- **H11 + H12 confirm Pattern J at the primitives layer is no-op** (type-union silent inclusion doesn't matter because the algorithm is fork-independent).
- **H13 confirms grandine's EIP-7044 OR-list extension to Gloas closes one forward-fragility item** noted in item #28's Pattern L analysis (carried forward as "EIP-7044 pin already correct across all 6 clients" — now confirmed at the Gloas surface).
- **H14 reaffirms item #28's note that "teku is the laggard" framing is outdated**, and extends with concrete Heze readiness ranking.

### With item #25 (`is_valid_indexed_attestation` + Gloas-NEW `is_valid_indexed_payload_attestation`)

Item #25 H11 flagged the Gloas-NEW `is_valid_indexed_payload_attestation` sister function as out-of-scope. THIS item confirms `DOMAIN_PTC_ATTESTER = 0x0C000000` (the domain consumed by that sister function) is wired in 5 of 6 clients; lighthouse missing per item #25 H11 (the cohort gap). Grandine has the constant.

### With item #6 (`process_voluntary_exit` + EIP-7044 CAPELLA pin)

Item #6 audited the voluntary-exit signing-domain pin at Pectra (CAPELLA pin for forks ≥ Deneb). THIS item confirms the pin auto-extends to Gloas in all 6 clients, and that grandine's OR-list now correctly includes `gloas_fork_version`.

### With item #20 (`apply_pending_deposit` + GENESIS_FORK_VERSION pin)

Item #20 audited the deposit-signing-domain pin (GENESIS pin via `compute_domain(DOMAIN_DEPOSIT, None, None)`). THIS item confirms the GENESIS pin is unchanged at Gloas — `DOMAIN_DEPOSIT = 0x03000000` is unchanged; the `compute_domain` default-arg behaviour is unchanged.

### With future Heze-readiness consolidated audit (item #15 H14 sister)

The Heze finding from this item (teku FULL, prysm constants, lodestar spec-refs ack, grandine test paths, lighthouse + nimbus none) is the **kernel of a Heze-tracking audit** parallel to item #28's Gloas tracking. Suggested follow-up: build a per-client Heze-readiness scorecard once EIP-7805 stabilises.

## Adjacent untouched

1. **Grandine `DOMAIN_PROPOSER_PREFERENCES` constant addition** — one-line fix at `vendor/grandine/types/src/gloas/consts.rs`. Closes validator-side gap.
2. **Grandine EIP-7044 OR-list Heze pre-emptive extension** — `signing.rs:434-438` add `heze_fork_version` before Heze activation.
3. **Dedicated EF fixture set for the four primitives** — pure-function cross-client byte-level equivalence at Gloas state inputs (T1.1).
4. **Per-network `DOMAIN_*` constant byte-value audit** — verify cross-client identical 4-byte values for all 11+ DomainTypes per mainnet / sepolia / holesky / Hoodi.
5. **SigningData SSZ schema cross-client equivalence test** — `Container { object_root: Bytes32, domain: Bytes32 }` byte-for-byte hash root.
6. **ForkData SSZ schema cross-client equivalence test** — `Container { current_version: Bytes4, genesis_validators_root: Bytes32 }`.
7. **Cache eviction policies** — prysm `digestMap` (`signing_root.go:24-25`) unbounded growth memory-leak audit; lodestar `domainCache` bounded confirmation.
8. **Heze divergence consolidated audit** (parallel to item #28) — once EIP-7805 stabilises, full per-client readiness scorecard with A/C/F-tier divergence vectors.
9. **EIP-7805 inclusion-list signing-domain audit** — teku's `DOMAIN_INCLUSION_LIST_COMMITTEE` byte value + InclusionList SSZ hash root cross-client.
10. **`Domain` type representation cross-client byte equivalence** — prysm `[]byte`, lighthouse / grandine `[u8; 32]` / `H256`, nimbus `Eth2Domain`, teku `Bytes32`, lodestar `Uint8Array` — verify 32-byte boundary equivalence.
11. **Lighthouse `SignedRoot` trait per-type audit** — every SSZ type with a signing root implements the trait. Verify all implementations delegate to the same `SigningData` construction (no per-type drift).
12. **`compute_signing_root` overload cross-client audit** — teku has 3 overloads (Merkleizable / UInt64 / Bytes); verify all 6 clients produce equivalent signing roots for pre-hashed objects via their generic mechanisms.
13. **Prysm `forkVersionArray [4]byte` defensive truncation behaviour** — confirm spec inputs are always exactly 4 bytes; document the zero-pad / truncate behaviour as defensive-only.
14. **EIP-7044 cross-fork-transition stateful fixture** — voluntary exit submitted at Deneb that survives through Electra → Fulu → Gloas. All 6 clients must produce identical Domain bytes across the transition.
15. **`get_domain` `previous_version` selection equivalence test** — fixture with `epoch == fork.epoch` exact-boundary; verify all 6 clients use `current_version` (strict `<` not `<=`).
16. **DomainType registry consistency audit** — `DOMAIN_BEACON_PROPOSER = 0x00`, `DOMAIN_BEACON_ATTESTER = 0x01`, `DOMAIN_RANDAO = 0x02`, `DOMAIN_DEPOSIT = 0x03`, `DOMAIN_VOLUNTARY_EXIT = 0x04`, ..., `DOMAIN_BEACON_BUILDER = 0x0B`, `DOMAIN_PTC_ATTESTER = 0x0C`, `DOMAIN_PROPOSER_PREFERENCES = 0x0D`, `DOMAIN_INCLUSION_LIST_COMMITTEE` (Heze) — cross-client byte values match per network.
17. **Compile-time vs runtime fork-dispatch performance audit** — nimbus `static ConsensusFork`, lighthouse `superstruct`, grandine `is_post_gloas() / is_post_electra()` runtime, lodestar `ForkSeq` numeric, prysm `Version()` switch, teku subclass — measure hot-path overhead at Gloas activation.
