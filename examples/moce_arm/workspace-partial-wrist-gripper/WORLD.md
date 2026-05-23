---
schema: physical-agent/world/v1
owner: watch
revision: 621
---

# World State

## Summary

momo_1 is connected over serial in partial hardware mode. Active joint: wrist_roll. Gripper available: True.

## State

```yaml
robots:
  momo_1:
    status: idle
    mode: hardware
    hardware_profile: partial
    transport: serial
    active_joints:
    - wrist_roll
    joints_deg:
      wrist_roll: 0.0
    gripper:
      available: true
      open_ratio: 0.016666666666666666
      present_raw: 1969
      open_raw: 2087
      close_raw: 1967
      mapping: partial_raw_window
objects: {}
environment: {}
artifacts: []
raw:
  serial_port: /dev/serial/by-id/usb-1a86_USB_Single_Serial_5B61036646-if00
  partial_joint_name: wrist_roll
  partial_joint_id: 5
  partial_joint_present_raw: 2328
  partial_joint_startup_raw: 2328
  gripper:
    available: true
    open_ratio: 0.016666666666666666
    present_raw: 1969
    open_raw: 2087
    close_raw: 1967
    mapping: partial_raw_window
```
