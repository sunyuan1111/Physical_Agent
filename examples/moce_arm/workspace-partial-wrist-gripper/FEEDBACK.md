---
schema: physical-agent/feedback/v1
owner: watch
revision: 10
---

# Execution Feedback

## Latest

```yaml
action_id: act_009
status: completed
robot: momo_1
capability: move_joint
message: Moved wrist_roll to -20.00 deg.
result:
  profile: partial
  joint_name: wrist_roll
  target_deg: -20.0
  goal_raw: 2100
artifacts: []
```

## History

```yaml
- action_id: act_001
  status: completed
  robot: momo_1
  capability: move_joint
  message: Moved wrist_roll to 10.00 deg.
  result:
    profile: partial
    joint_name: wrist_roll
    target_deg: 10.0
    goal_raw: 2215
  artifacts: []
- action_id: act_002
  status: completed
  robot: momo_1
  capability: open_gripper
  message: Gripper opened.
  result:
    profile: partial
    open_ratio: 1.0
  artifacts: []
- action_id: act_003
  status: completed
  robot: momo_1
  capability: close_gripper
  message: Gripper closed.
  result:
    profile: partial
    open_ratio: 0.0
  artifacts: []
- action_id: act_004
  status: completed
  robot: momo_1
  capability: move_joint
  message: Moved wrist_roll to 10.00 deg.
  result:
    profile: partial
    joint_name: wrist_roll
    target_deg: 10.0
    goal_raw: 2327
  artifacts: []
- action_id: act_005
  status: completed
  robot: momo_1
  capability: move_joint
  message: Moved wrist_roll to -20.00 deg.
  result:
    profile: partial
    joint_name: wrist_roll
    target_deg: -20.0
    goal_raw: 2098
  artifacts: []
- action_id: act_006
  status: completed
  robot: momo_1
  capability: move_joint
  message: Moved wrist_roll to 0.22 deg.
  result:
    profile: partial
    joint_name: wrist_roll
    target_deg: 0.224609375
    goal_raw: 2329
  artifacts: []
- action_id: act_007
  status: completed
  robot: momo_1
  capability: open_gripper
  message: Gripper opened.
  result:
    profile: partial
    open_ratio: 1.0
  artifacts: []
- action_id: act_008
  status: completed
  robot: momo_1
  capability: close_gripper
  message: Gripper closed.
  result:
    profile: partial
    open_ratio: 0.0
  artifacts: []
- action_id: act_009
  status: completed
  robot: momo_1
  capability: move_joint
  message: Moved wrist_roll to -20.00 deg.
  result:
    profile: partial
    joint_name: wrist_roll
    target_deg: -20.0
    goal_raw: 2100
  artifacts: []
```
