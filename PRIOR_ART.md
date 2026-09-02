# Prior art and naming

## Not PDX EvidenceGate

`pdx-evidence-gate` is a Nutrient DWS Challenge product. It extracts PDFs with
Nutrient and also consumes published ProDocuX / PDX packages.

ReviewDesk (`pdx-reviewdesk`) consumes the **same PyPI packages** through a
WebMCP workspace. Nutrient is out of scope. Typed evidence for the demo is a
host-supplied fixture so the live URL needs no third-party extraction keys.

## Upstream

| Package | Pin | Role |
|---|---|---|
| `prodocux` | 0.3.0rc4 | `verify_evidence_bundle` |
| `pdx-artifact-engine` | 0.3.0a4 | `pdx_artifact_core` checkpoint / approval |

Pins match `compatibility/pdx_prodocux_release_v1.json` in the public
ProDocuX repository. This repo must not import those products by filesystem
path.

## Related public work

- [prodocux 0.3.0rc4 on PyPI](https://pypi.org/project/prodocux/0.3.0rc4/)
- [pdx-artifact-engine 0.3.0a4 on PyPI](https://pypi.org/project/pdx-artifact-engine/0.3.0a4/)
- [WebMCP specification](https://webmachinelearning.github.io/webmcp/)
