# OUT OF SCOPE — flagged but not chain-split risk

Things encountered during the audit that are real but not within the
chain-split scope of `BEACONBREAKER.md`. Keep here so the main `WORKLOG.md`
stays focused.

## Spec ambiguities

_(Multiple defensible readings of pyspec / fork-spec text. Worth a
"spec-ambiguity" item even if all clients currently agree on one reading —
a future spec revision may surface a divergence.)_

_None yet._

## MEV / proposer-side timing

_(Optimizations that affect when an attestation gets included or how a
payload is assembled. Out of strict consensus but relevant for builder
markets and liveness.)_

_None yet._

## Network-layer DOS

_(Messages that, if accepted, cause denial-of-service but cannot cause a
chain split. Real risk; tracked separately from chain-split surface.)_

_None yet._

## Light-client protocol

_(Different attack model. Worth a parallel audit but not part of this
worklog.)_

_None yet._

## Builder API (mev-boost)

_(Out of consensus per se but worth a parallel audit.)_

_None yet._

## Beacon API / RPC

_(`/eth/v1/beacon/...`. Not consensus-critical.)_

_None yet._
