# pyspec environment

The Python pyspec is the **reference implementation** — any deviation from
pyspec is a finding by definition. It also serves as the canonical fixture
generator.

## Setup

```bash
cd ../../consensus-specs
python3 -m venv .venv
. .venv/bin/activate
pip install -e .[lint,test]
# generate the fork-specific module set
python -m setup pyspecdev
```

Pyspec organizes by fork. The Electra module is at
`eth2spec.electra.mainnet`:

```python
from eth2spec.electra import mainnet as spec
state = spec.BeaconState()
spec.process_block(state, block)
```

## Use cases for the loop

- **Generate a fixture from a (pre, block) pair**: run `state_transition`
  in pyspec, dump pre/post as SSZ-snappy, write `meta.yaml`.
- **Cross-check a hypothesis**: read the predicate as it appears in pyspec
  Python, then audit each client's translation of that predicate.
- **Trace a `process_*` function**: pyspec is intentionally readable; use
  it as the diff baseline.

## Notes

- Pyspec mainnet config has `MAX_EFFECTIVE_BALANCE_ELECTRA = 2048 * 10**9`.
- Pyspec is **not** fast — it is correctness-first. Don't use it for fuzz
  campaigns; use it to generate seed inputs.
- Pyspec has its own bugs (rare, but they exist). When all six clients
  agree but pyspec disagrees, look hard at pyspec before declaring a
  divergence.
