---
schema: physical-agent/plan/v1
owner: agent
revision: 7
---

# Plan

## Current

```yaml
status: proposed_actions
intent: act
summary: "\u597D\u7684\uFF0C\u60A8\u8981\u6C42\u5C06\u8155\u90E8\u5173\u8282\uFF08\
  5\u53F7\u8235\u673A\uFF09\u76F8\u5BF9\u65CB\u8F6C-20\u5EA6\u3002\u5F53\u524D\u8155\
  \u90E8\u89D2\u5EA6\u4E3A0\u5EA6\uFF0C\u65CB\u8F6C-20\u5EA6\u540E\u76EE\u6807\u89D2\
  \u5EA6\u4E3A-20\u5EA6\u3002\u6211\u5C06\u5EFA\u8BAE\u4E00\u4E2A\u52A8\u4F5C\uFF0C\
  \u7531\u76D1\u63A7\u7CFB\u7EDF\u9A8C\u8BC1\u5E76\u6267\u884C\u3002"
steps: []
actions:
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
needs_watch: true
```
