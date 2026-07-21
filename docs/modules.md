# Modules

Activity modules extend what the agent can do. Install by dropping a module
folder into `data/modules/<name>/`, or via `pip install` for packaged modules.

## Trust tiers

The registry prints a tier label when loading each module:

- **Official:** maintained by the base author and shipped or distributed
  alongside the base. Listed in `trusted_modules.json` under `"official"`.
- **Approved:** community module reviewed against the module contract and
  approved by the maintainer. Listed in `trusted_modules.json` under
  `"approved"`.
- **Community:** installed but unreviewed. Install at your own judgment,
  like any other third-party code.

| Module | Tier | Author | Needs keys? | Posts publicly? | Description |
|---|---|---|---|---|---|
| [Text RPG](https://github.com/ella0333/Eli_Felse_Text_RPG) | Official | ella0333 | No | No | Text-based RPG module (Zork and other Z-machine games) |

## Getting your module listed

Open a [Module Approval Request](https://github.com/ella0333/Eli_Felse_Base/issues/new?template=module_approval.yml)
issue on this repository. The request asks you to:

1. Link your repo
2. Describe what the module does
3. Self-review against the module contract (see [safety claims](safety-claims.md))
4. Declare whether it needs API keys or posts publicly

Approved modules are added to `trusted_modules.json` and listed here.
Community modules can be listed without approval (just note the tier).
