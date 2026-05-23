---
schema: physical-agent/actions/v1
owner: agent
revision: 19
---

# Action Board

## Pending

```yaml
[]
```

## Completed

```yaml
- id: act_008
  robot: momo_1
  capability: close_gripper
  params: {}
  reason: The task asks to close the gripper.
  depends_on: []
- id: act_009
  robot: momo_1
  capability: move_joint
  params:
    joint_name: wrist_roll
    delta_deg: -20
    speed_percent: 50
  reason: "\u7528\u6237\u8981\u6C42\u8F6C5\u53F7\u8235\u673A-20\u5EA6\uFF0C\u5F53\u524D\
    \u8155\u90E8\u5173\u8282\u89D2\u5EA6\u4E3A0\u5EA6\uFF0C\u4F7F\u7528\u76F8\u5BF9\
    \u8FD0\u52A8\uFF08delta_deg=-20\uFF09\u5B9E\u73B0\u3002"
  depends_on: []
```

## Cancelled

```yaml
[]
```
