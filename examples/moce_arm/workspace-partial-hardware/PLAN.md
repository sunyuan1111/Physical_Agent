---
schema: physical-agent/plan/v1
owner: agent
revision: 16
---

# Plan

## Current

```yaml
status: proposed_actions
intent: act
summary: "\u597D\u7684\uFF0C\u5E95\u5EA7\uFF08shoulder_pan\uFF09\u7576\u524D\u4F4D\
  \u7F6E\u70BA 10 \u5EA6\uFF08\u6839\u64DA\u4E0A\u4E00\u6B65\u52D5\u4F5C\u7D50\u679C\
  \uFF09\u3002\u60A8\u8981\u6C42\u8F49\u5230 -10 \u5EA6\uFF0C\u6211\u5C07\u63D0\u8B70\
  \u9019\u9805\u79FB\u52D5\u3002Watch \u6703\u9A57\u8B49\u5F8C\u57F7\u884C\u3002"
steps: []
actions:
- id: act_031
  robot: momo_1
  capability: move_joint
  params:
    joint_name: shoulder_pan
    target_deg: -10.0
  reason: "\u7528\u6236\u8981\u6C42\u5C07\u5E95\u5EA7\uFF08shoulder_pan\uFF09\u8F49\
    \u5230 -10 \u5EA6\uFF0C\u7576\u524D\u61C9\u70BA 10 \u5EA6\u3002"
  depends_on: []
needs_watch: true
```
