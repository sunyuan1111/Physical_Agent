---
schema: physical-agent/world/v1
owner: watch
revision: 1354
---

# World State

## Summary

momo_1 is connected over serial in partial hardware mode. Active joint: shoulder_pan. Gripper available: False.

## State

```yaml
robots:
  momo_1:
    status: idle
    mode: hardware
    hardware_profile: partial
    transport: serial
    active_joints:
    - shoulder_pan
    joints_deg:
      shoulder_pan: 0.0
    gripper:
      available: false
objects: {}
environment: {}
artifacts: []
raw:
  serial_port: /dev/ttyACM1
  partial_joint_name: shoulder_pan
  partial_joint_id: 1
  partial_joint_present_raw: 2904
  partial_joint_startup_raw: 2904
  gripper:
    available: false
```
