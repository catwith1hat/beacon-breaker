# Glamsterdam — upcoming Ethereum hard fork

**Status (2026-05-09):** active devnet phase. No mainnet date. Fork after Fusaka.
**Naming:** *Glamsterdam* = *Gloas* (consensus layer) + *Amsterdam* (execution layer).
The CL is named after the star Gloas; the EL takes the next Devcon city, following
the Devcon-naming convention used for EL upgrades.
**Mascot:** TBD — last call for suggestions on Ethereum Magicians (🐜 Ant, 🦫 Beaver,
🐝 Bee, 🦩 Flamingo, 🐹 Hamster, 🐩 Poodle).

---

## Theme

Two headliners:

1. **Block Access Lists (EIP-7928)** — every block carries a commitment over
   the set of accounts/storage slots/balance-changes/nonce-changes/code-changes
   touched, plus per-touch indices into the tx that touched them. Enables
   parallel pre-execution and stateless light clients.
2. **Enshrined Proposer-Builder Separation (ePBS)** — the protocol takes
   over the role currently held by relays in the MEV-Boost stack. A
   beacon block's "execution payload" is split from the consensus block;
   builders bid in-protocol; the proposer commits to the bid before
   knowing the payload.

These ride together with **EIP-8037** (state-gas reservoir, item #157)
which reprices state-creating operations on a separate gas dimension.
Several other EIPs are SFI (Scheduled For Inclusion) as of 2026-05-07 ACDE #236:

- **EIP-7708** — transfer logs under EIP-7702 delegation (item #154).
- **EIP-7778** — block-level access-list constants.
- **EIP-7843** — SLOTNUM opcode.
- **EIP-7954** — TBD.
- **EIP-7976** — calldata floor 64 gas/byte (item #159 drafting).
- **EIP-7981** — access-list floor.
- **EIP-8024** — DUPN/SWAPN/EXCHANGE.
- **EIP-8037** — state-gas reservoir (item #157).

Recently proposed for Glamsterdam (ACDE #236, May 7):
- **EIP-8246** — remove SELFDESTRUCT burn (chfast).
- **EIP-8254** — cap deposit requests per block (barnabasbusa); 8192 → 512.
- **EIP-8237** — independent CL/EL sync (potuz).
- **EIP-8070** — sparse blobpool refresh (kamilsa).
- **EIP-7708** ABI for transfer logs (already CFI).

STEEL flagged **EIP-8037 testing concerns** on 2026-04-23 (ACDE #235): test
determinism breaks because state gas is now derived from block gas limit,
~30 % of tests had to be modified. They asked for a temperature check on
whether 8037 can ship on the current schedule. Open question at this writing.

The fork **after** Glamsterdam is **Hegotá** (mascot 🦖🦕). Non-headliner
proposal window is open: EIP-7709 (BLOCKHASH from storage), EIP-8163
(reserve EXTENSION 0xae), EIP-7979 (CALL/RETURN opcodes), EIP-8253
(remove pre-Spurious-Dragon accounts), and various AA proposals are all
under discussion.

---

## Devnets currently online

| Devnet | Scope | Spec / status |
|---|---|---|
| **bal-devnet-6** | EL-only Block Access List (EIP-7928 + EIP-8037) | Active. Bug tracker: `ethereum/execution-specs#2804`. Spec clarifications: `ethereum/EIPs#11611`. |
| **bal-devnet-7** | EL-only, planned ≈ 2026-05-15 | "Should be the last EL-only devnet" (qu0b, ACDE #236). Will pull bal-devnet-3 perf opts + bal-devnet-6 fixes + constant updates from `ethereum/EIPs#11616`. |
| **glamsterdam-devnet-3** | combined CL+EL (chainId `7057084805`) | Active. domain `glamsterdam-devnet-3.ethpandaops.io`. EL still on bal-devnet-6 images while CL ships glamsterdam-* changes. |
| **blob-devnet-0** | blob/PeerDAS testing (partial-cells / partial-columns) | Active. Uses experimental fork branches, not upstream master. |
| **epbs-devnet-1** | enshrined PBS | Active. epbs-devnet-2 planned, possibly blocked on `ethereum/consensus-specs#5094`. |

Marius proposed at ACDT #78 (April 20) to skip bal-devnet-4 and go straight
to glamsterdam-devnet-0 for ELs, on the grounds that non-ePBS CLs can still
test BAL — the only EL-side ePBS change is "allow reorging the head block."
That logic is what produced today's pattern of glamsterdam-devnet-3 still
running EL images from bal-devnet-6.

---

## Per-client branches per devnet

The ethpandaops Docker tags map 1:1 to upstream branch names (verified
against `ethpandaops/eth-client-docker-image-builder/branches.yaml`).
Default upstream repos from that repo's `generate_config.py:DEFAULT_REPOS`.

### glamsterdam-devnet-3 (combined CL+EL — the main "Glamsterdam testnet")

Pulled from `ethpandaops/glamsterdam-devnets/ansible/inventories/devnet-3/group_vars/all/images.yaml`.

**Execution layer** (all on `bal-devnet-6` branch):

| Client | Repo | Branch |
|---|---|---|
| geth | `ethereum/go-ethereum` | `bal-devnet-6` |
| besu | `hyperledger/besu` | `bal-devnet-6` |
| nethermind | `NethermindEth/nethermind` | `bal-devnet-6` |
| erigon | `erigontech/erigon` | `bal-devnet-6` |
| reth | `paradigmxyz/reth` | `bal-devnet-6` |
| ethrex | `lambdaclass/ethrex` | `bal-devnet-6` (also has `bal-devnet-7` pushed) |
| nimbus-eth1 | `status-im/nimbus-eth1` | `bal-devnet-6` |

**Consensus layer:**

| Client | Repo | Branch |
|---|---|---|
| lighthouse | `sigp/lighthouse` | `glamsterdam-devnet-3` |
| nimbus | `status-im/nimbus-eth2` | `glamsterdam-devnet-3` |
| prysm | `OffchainLabs/prysm` | image tag `glamsterdam-devnet-3` (no matching upstream branch — confirm via `eth-client-docker-image-builder/prysm/`) |
| lodestar | `ChainSafe/lodestar` | `glamsterdam-devnet-2` (no -3 yet) |
| teku | `ConsenSys/teku` | `glamsterdam-devnet-2` (no -3 yet) |
| grandine | `grandinetech/grandine` | `glamsterdam-devnet-2` |

### bal-devnet-6 (EL-only)

| Layer | Client | Repo | Branch |
|---|---|---|---|
| EL | geth/besu/nethermind/erigon/reth/ethrex/nimbus-eth1 | (each upstream) | `bal-devnet-6` |
| CL | lighthouse | `sigp/lighthouse` | image tag `bal-devnet-6` (upstream branch only goes to `-5`) |
| CL | lodestar | `ChainSafe/lodestar` | image tag `bal-devnet-6` (upstream branch only goes to `-5`) |
| CL | prysm | `OffchainLabs/prysm` | image tag `bal-devnet-6` (upstream goes up to `bal-devnet-1` plus debug branches) |
| CL | nimbus | `statusim/nimbus-eth2:multiarch-latest` | upstream `unstable` |
| CL | teku | `consensys/teku:latest` | upstream tip |
| CL | grandine | `ethpandaops/grandine:develop` | upstream `develop` |

For BAL devnets the CL is doing very little custom work — most upstream
branches stop at `-5` and the pipeline pulls from a CI-built tag for `-6`.

### blob-devnet-0 (PeerDAS / partial-cells)

| Layer | Client | Repo | Branch / tag |
|---|---|---|---|
| EL | geth | `MariusVanDerWijden/go-ethereum` | `has-blobs` (NOT `ethereum/go-ethereum`) |
| EL | besu | `hyperledger/besu` | `main` |
| EL | erigon | `erigontech/erigon` | `main` |
| EL | nethermind | `NethermindEth/nethermind` | `master` |
| EL | reth | `paradigmxyz/reth` | `main` |
| EL | nimbus-eth1 | `status-im/nimbus-eth1` | `master` |
| EL | (no ethrex on this devnet) | — | — |
| CL | lighthouse | `dknopik/lighthouse` | `partial-columns` |
| CL | prysm | `MarcoPolo/prysm` | `partial-columns` (image tag `prysm-partial-cells-current`) |
| CL | nimbus | `statusim/nimbus-eth2:multiarch-latest` | upstream `unstable` |
| CL | lodestar | `chainsafe/lodestar:latest` | upstream tip |
| CL | teku | `ConsenSys/teku` | `master` |
| CL | grandine | `grandinetech/grandine` | `develop` |

### epbs-devnet-1

| Layer | Client | Repo | Branch |
|---|---|---|---|
| EL | geth | `ethereum/go-ethereum` | `epbs-devnet-1` |
| EL | nethermind | `NethermindEth/nethermind` | `epbs-devnet-1` |
| EL | reth | `paradigmxyz/reth` | `epbs-devnet-1` |
| EL | besu | upstream `hyperledger/besu:latest` | not customized |
| EL | erigon | upstream `erigontech/erigon:main-latest` | not customized |
| EL | ethrex | upstream `ghcr.io/lambdaclass/ethrex:latest` | not customized |
| EL | nimbus-eth1 | `status-im/nimbus-eth1` | `master` |
| CL | lighthouse | `sigp/lighthouse` | `epbs-devnet-1` |
| CL | nimbus | `status-im/nimbus-eth2` | `epbs-devnet-1` |
| CL | prysm | `OffchainLabs/prysm` | `epbs-devnet-1` |
| CL | lodestar | `ChainSafe/lodestar` | `epbs-devnet-1` |
| CL | teku | `ConsenSys/teku` | `master` |
| CL | grandine | `grandinetech/grandine` | `epbs-devnet-1` |

---

## Spinning up an audit checkout

This audit project pins each client as a git submodule under `vendor/`.
Each devnet's audit checkout is a different choice of `(repo, ref)` per
client. Recipes:

- **Glamsterdam-devnet-3 (CL+EL)**: pick an EL fork at branch `bal-devnet-6`
  plus a CL fork at branch `glamsterdam-devnet-3` (lighthouse/nimbus) or
  `glamsterdam-devnet-2` (lodestar/teku/grandine), then point both at
  `https://config.glamsterdam-devnet-3.ethpandaops.io/{el,cl}/...` for
  genesis/config/bootnodes. Same pattern as fusaka/pectra devnets.
- **bal-devnet-6 (EL-only)**: any EL on branch `bal-devnet-6`; CL is whatever
  upstream nightly + bal-devnet-6 image tag.
- **blob-devnet-0**: needs the explicit experimental forks listed above
  (MariusVanDerWijden:has-blobs, MarcoPolo:partial-columns,
  dknopik:partial-columns). Not just upstream branches.
- **epbs-devnet-1**: matching `epbs-devnet-1` branch on each.

### Caveats

1. For some clients the docker tag exists but there is **no matching
   upstream branch** (e.g. `prysm:bal-devnet-6` has no
   `OffchainLabs/prysm:bal-devnet-6` branch). The
   `eth-client-docker-image-builder/<client>/Dockerfile.*` plus
   `runner_overrides.yaml` in that repo will tell you what was actually
   checked out for the build. Confirm before pulling source code.
2. **Ethrex `bal-devnet-7`** already exists on `lambdaclass/ethrex` even
   though devnet config files for `bal-devnet-7` haven't been published
   yet — expect `ethpandaops/bal-devnets/network-configs/devnet-7/` to
   land within ≈ a week of 2026-05-09 per qu0b's ACDE #236 comment.
3. **This repo's current pin**: `vendor/ethrex` is on `v12.0.0-rc.2`
   (= `d71b53d68`), which sits *between* `bal-devnet-6` tip and the
   upcoming `bal-devnet-7` tip. For exact bal-devnet-6 client behaviour,
   the matching ref is `lambdaclass/ethrex` branch `bal-devnet-6` (not
   `v12.0.0-rc.2`).
4. **No mainnet activation yet.** None of these branches are post-merge
   on a public chain. Audit findings classify as `custom-chain` /
   `synthetic-state` until a Glamsterdam timestamp is set.

---

## Audit priorities

The Fusaka audit cluster (#1–#162) covers Pectra + Osaka + Fulu. For
Glamsterdam these are the new surfaces:

### EL — Glamsterdam

1. **EIP-7928 Block Access Lists** — flagship target, item #160 already
   drafting. Cross-client diff on:
   - canonicalisation rules (account ordering, slot ordering, dedup).
   - `block_access_index` width and bounds (16-bit was bumped to 64-bit
     per PR `ethereum/EIPs#11535`).
   - reverted-frame touches: which entries survive a revert per spec.
   - hash composition order.
   - header validation when a noncanonical BAL is supplied.
2. **EIP-8037 state-gas reservoir** — item #157 already final
   (5/6 implement, geth ships only scaffolding); item #158, #161 still
   drafting. Re-audit with the new schedule:
   - Top-level revert state-gas accounting (#158).
   - Runtime regular-gas cap (#161): EIP-8037 changes the meaning of
     EIP-7825's `tx.gas_limit` cap.
   - Already-final cross-tx exists pollution (#163, ethrex-only,
     remediated upstream).
3. **EIP-7976 calldata floor** + **EIP-7981 access-list floor** — item
   #159 drafting. New floor formula (64 gas/byte, no zero/non-zero
   distinction). Cross-cuts #93 (EIP-7623 floor) and #137 (EIP-2930
   intrinsic).
4. **EIP-7843 SLOTNUM opcode** — new dispatch entry. Standard
   opcode-audit recipe: dispatch-table diff, gas constant, stack
   effects, fork-gating.
5. **EIP-7708 transfer logs under EIP-7702** — item #154 final;
   re-audit if Glamsterdam changes log composition.
6. **EIP-8024 DUPN / SWAPN / EXCHANGE** — three new EVM opcodes.
   Standard opcode-audit recipe.
7. **EIP-8254 deposit cap per block** (proposed) — block-level
   validation, cross-cut with #105 (EIP-7685 requests-hash) and #106
   (EIP-6110 deposit log).
8. **Engine API v2 schema fix** (`ethereum/execution-apis#781`) — a
   small typing change for V2 result. Touches engine-API non-exploit
   sections of header-gating items (#108, #121, #122).

### CL — Glamsterdam (for the BeaconBreaker companion project)

1. **ePBS** — top-priority CL audit. Builder bidding, payload split,
   slot timing changes, missed-payload handling, equivocation slashing.
2. **EIP-7716** (ACDC #177 discussion item) — TBD.
3. **EIP-8205** (ACDC #177) — TBD.
4. **min-reorg depth without resync** (`ethereum/EIPs#11601`,
   nerolation, ACDE #236) — engine-API contract clarifying what depth
   of reorg ELs must support without triggering re-sync. May be
   shipped without a hardfork; affects Engine API audits.

---

## References

- ACD calls (open): none scheduled in this issue list.
- ACD calls (closed, most recent first):
  - **#2033** ACDE #236, 2026-05-07 — bal-devnet-6 status, EIP-8254
    proposal, EIP-8246 SELFDESTRUCT burn removal, EIP-7709 BLOCKHASH
    from storage. https://github.com/ethereum/pm/issues/2033
  - **#2031** FOCIL Breakout #33, 2026-04-21.
    https://github.com/ethereum/pm/issues/2031
  - **#2019** ACDT #78, 2026-04-20 — blob-devnet-0, bal devnets,
    epbs-devnet-1. https://github.com/ethereum/pm/issues/2019
  - **#2016** Glamsterdam Repricings #6, 2026-04-15.
    https://github.com/ethereum/pm/issues/2016
  - **#2015** ACDE #235, 2026-04-23 — STEEL EIP-8037 concerns; EIP-8237.
    https://github.com/ethereum/pm/issues/2015
  - **#2008** ACDT #77, 2026-04-13 — bal-devnet-4 spec discussion.
    https://github.com/ethereum/pm/issues/2008
  - **#2004** ACDE #234, 2026-04-09 — Glamsterdam SFI definition,
    devnet updates.  https://github.com/ethereum/pm/issues/2004
  - **#1990** ACDC #177, 2026-04-16 — epbs-devnet-2 plan, EIP-7716,
    EIP-8205. https://github.com/ethereum/pm/issues/1990
- ethpandaops devnet repos:
  - https://github.com/ethpandaops/glamsterdam-devnets
  - https://github.com/ethpandaops/bal-devnets
  - https://github.com/ethpandaops/blob-devnets
  - https://github.com/ethpandaops/epbs-devnets
- Image-build registry (canonical mapping image-tag → upstream branch):
  https://github.com/ethpandaops/eth-client-docker-image-builder
- Svalbard interop (recap relevant to Glamsterdam):
  https://blog.ethereum.org/2026/05/02/soldogn-interop-recap
- Forkcast Glamsterdam tracker: https://forkcast.org/upgrade/glamsterdam
- ethereum.org Glamsterdam roadmap (when published).
- Local EIP texts: `vendor/EIPs/EIPS/eip-{7708,7778,7843,7928,7954,7976,7981,8024,8037,8070,8237,8246,8254}.md`
  (some may be in PRs only, not yet merged to `vendor/EIPs/`).
- Audit items already drafting against this fork: #157 (final), #158,
  #159, #160, #161, #162, #163 (final).
