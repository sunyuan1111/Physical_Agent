---
schema: physical-agent/safety/v1
owner: human
revision: 1
---

# Safety Policy

## Rules

```yaml
require_human_approval_for_real_hardware: true
allow_autonomous_execution: true
max_action_timeout_s: 30
forbid_duplicate_action_ids: true
```
