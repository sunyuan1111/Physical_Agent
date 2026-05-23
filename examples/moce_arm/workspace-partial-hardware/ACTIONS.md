---
schema: physical-agent/actions/v1
owner: agent
revision: 63
---

# Action Board

## Pending

```yaml
[]
```

## Completed

```yaml
- id: act_029
  robot: momo_1
  capability: move_joint
  params:
    joint_name: shoulder_pan
    target_deg: -20.0
  reason: The task asks for a joint-level movement.
  depends_on: []
- id: act_030
  robot: momo_1
  capability: move_joint
  params:
    joint_name: shoulder_pan
    target_deg: 10.0
  reason: "\u7528\u6237\u8981\u6C42\u5C06\u5E95\u5EA7\uFF08shoulder_pan\uFF09\u8F6C\
    \u5230 10 \u5EA6\u3002"
  depends_on: []
- id: act_031
  robot: momo_1
  capability: move_joint
  params:
    joint_name: shoulder_pan
    target_deg: -10.0
  reason: "\u7528\u6236\u8981\u6C42\u5C07\u5E95\u5EA7\uFF08shoulder_pan\uFF09\u8F49\
    \u5230 -10 \u5EA6\uFF0C\u7576\u524D\u61C9\u70BA 10 \u5EA6\u3002"
  depends_on: []
```

## Cancelled

```yaml
[]
```
