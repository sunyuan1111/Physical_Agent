---
schema: physical-agent/feedback/v1
owner: watch
revision: 32
---

# Execution Feedback

## Latest

```yaml
action_id: act_031
status: completed
robot: momo_1
capability: move_joint
message: Moved shoulder_pan to -10.00 deg.
result:
  profile: partial
  joint_name: shoulder_pan
  target_deg: -10.0
  goal_raw: 2790
artifacts: []
```

## History

```yaml
- action_id: act_001
  status: completed
  robot: momo_1
  capability: observe
  message: Observation completed.
  result:
    observation:
      summary: 'momo_1 is connected over serial in partial hardware mode. Active joint:
        wrist_roll. Gripper available: True.'
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
            open_ratio: 0.029548229548229547
            present_raw: 2087
            adjusted_raw: 121
            range_min: 0
            range_max: 4095
      objects: {}
      environment: {}
      artifacts: []
      raw:
        serial_port: /dev/ttyACM1
        partial_joint_name: wrist_roll
        partial_joint_id: 5
        partial_joint_present_raw: 2093
        partial_joint_startup_raw: 2093
        gripper:
          available: true
          open_ratio: 0.029548229548229547
          present_raw: 2087
          adjusted_raw: 121
          range_min: 0
          range_max: 4095
  artifacts: []
- action_id: act_002
  status: completed
  robot: momo_1
  capability: observe
  message: Observation completed.
  result:
    observation:
      summary: 'momo_1 is connected over serial in partial hardware mode. Active joint:
        wrist_roll. Gripper available: True.'
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
            open_ratio: 0.029548229548229547
            present_raw: 2087
            adjusted_raw: 121
            range_min: 0
            range_max: 4095
      objects: {}
      environment: {}
      artifacts: []
      raw:
        serial_port: /dev/ttyACM1
        partial_joint_name: wrist_roll
        partial_joint_id: 5
        partial_joint_present_raw: 2093
        partial_joint_startup_raw: 2093
        gripper:
          available: true
          open_ratio: 0.029548229548229547
          present_raw: 2087
          adjusted_raw: 121
          range_min: 0
          range_max: 4095
  artifacts: []
- action_id: act_003
  status: completed
  robot: momo_1
  capability: open_gripper
  message: Gripper opened.
  result:
    profile: partial
    open_ratio: 1.0
  artifacts: []
- action_id: act_004
  status: completed
  robot: momo_1
  capability: open_gripper
  message: Gripper opened.
  result:
    profile: partial
    open_ratio: 1.0
  artifacts: []
- action_id: act_005
  status: completed
  robot: momo_1
  capability: open_gripper
  message: Gripper opened.
  result:
    profile: partial
    open_ratio: 1.0
  artifacts: []
- action_id: act_006
  status: completed
  robot: momo_1
  capability: close_gripper
  message: Gripper closed.
  result:
    profile: partial
    open_ratio: 0.0
  artifacts: []
- action_id: act_007
  status: completed
  robot: momo_1
  capability: observe
  message: Observation completed.
  result:
    observation:
      summary: 'momo_1 is connected over serial in partial hardware mode. Active joint:
        wrist_roll. Gripper available: True.'
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
            open_ratio: 0.0002442002442002442
            present_raw: 1967
            adjusted_raw: 1
            range_min: 0
            range_max: 4095
      objects: {}
      environment: {}
      artifacts: []
      raw:
        serial_port: /dev/ttyACM1
        partial_joint_name: wrist_roll
        partial_joint_id: 5
        partial_joint_present_raw: 2093
        partial_joint_startup_raw: 2093
        gripper:
          available: true
          open_ratio: 0.0002442002442002442
          present_raw: 1967
          adjusted_raw: 1
          range_min: 0
          range_max: 4095
  artifacts: []
- action_id: act_008
  status: completed
  robot: momo_1
  capability: observe
  message: Observation completed.
  result:
    observation:
      summary: 'momo_1 is connected over serial in partial hardware mode. Active joint:
        wrist_roll. Gripper available: True.'
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
            open_ratio: 0.0
            present_raw: 1967
            open_raw: 2087
            close_raw: 1967
            mapping: partial_raw_window
      objects: {}
      environment: {}
      artifacts: []
      raw:
        serial_port: /dev/ttyACM1
        partial_joint_name: wrist_roll
        partial_joint_id: 5
        partial_joint_present_raw: 2093
        partial_joint_startup_raw: 2093
        gripper:
          available: true
          open_ratio: 0.0
          present_raw: 1967
          open_raw: 2087
          close_raw: 1967
          mapping: partial_raw_window
  artifacts: []
- action_id: act_009
  status: completed
  robot: momo_1
  capability: open_gripper
  message: Gripper opened.
  result:
    profile: partial
    open_ratio: 1.0
  artifacts: []
- action_id: act_010
  status: completed
  robot: momo_1
  capability: close_gripper
  message: Gripper closed.
  result:
    profile: partial
    open_ratio: 0.0
  artifacts: []
- action_id: act_011
  status: completed
  robot: momo_1
  capability: observe
  message: Observation completed.
  result:
    observation:
      summary: 'momo_1 is connected over serial in partial hardware mode. Active joint:
        wrist_roll. Gripper available: True.'
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
        serial_port: /dev/ttyACM1
        partial_joint_name: wrist_roll
        partial_joint_id: 5
        partial_joint_present_raw: 2093
        partial_joint_startup_raw: 2093
        gripper:
          available: true
          open_ratio: 0.016666666666666666
          present_raw: 1969
          open_raw: 2087
          close_raw: 1967
          mapping: partial_raw_window
  artifacts: []
- action_id: act_012
  status: completed
  robot: momo_1
  capability: move_joint
  message: Moved wrist_roll to 10.00 deg.
  result:
    profile: partial
    joint_name: wrist_roll
    target_deg: 10.0
    goal_raw: 2207
  artifacts: []
- action_id: act_013
  status: completed
  robot: momo_1
  capability: open_gripper
  message: Gripper opened.
  result:
    profile: partial
    open_ratio: 1.0
  artifacts: []
- action_id: act_014
  status: completed
  robot: momo_1
  capability: move_joint
  message: Moved wrist_roll to 10.00 deg.
  result:
    profile: partial
    joint_name: wrist_roll
    target_deg: 10.0
    goal_raw: 2320
  artifacts: []
- action_id: act_015
  status: completed
  robot: momo_1
  capability: move_joint
  message: Moved wrist_roll to 10.00 deg.
  result:
    profile: partial
    joint_name: wrist_roll
    target_deg: 10.0
    goal_raw: 2320
  artifacts: []
- action_id: act_016
  status: completed
  robot: momo_1
  capability: move_joint
  message: Moved wrist_roll to -10.00 deg.
  result:
    profile: partial
    joint_name: wrist_roll
    target_deg: -10.0
    goal_raw: 2092
  artifacts: []
- action_id: act_017
  status: completed
  robot: momo_1
  capability: move_joint
  message: Moved wrist_roll to 15.00 deg.
  result:
    profile: partial
    joint_name: wrist_roll
    target_deg: 15.0
    goal_raw: 2266
  artifacts: []
- action_id: act_018
  status: completed
  robot: momo_1
  capability: move_joint
  message: Moved wrist_roll to -15.00 deg.
  result:
    profile: partial
    joint_name: wrist_roll
    target_deg: -15.0
    goal_raw: 1924
  artifacts: []
- action_id: act_019
  status: completed
  robot: momo_1
  capability: move_joint
  message: Moved wrist_roll to 10.00 deg.
  result:
    profile: partial
    joint_name: wrist_roll
    target_deg: 10.0
    goal_raw: 2209
  artifacts: []
- action_id: act_020
  status: completed
  robot: momo_1
  capability: open_gripper
  message: Gripper opened.
  result:
    profile: partial
    open_ratio: 1.0
  artifacts: []
- action_id: act_021
  status: completed
  robot: momo_1
  capability: close_gripper
  message: Gripper closed.
  result:
    profile: partial
    open_ratio: 0.0
  artifacts: []
- action_id: act_022
  status: completed
  robot: momo_1
  capability: open_gripper
  message: Gripper opened.
  result:
    profile: partial
    open_ratio: 1.0
  artifacts: []
- action_id: act_023
  status: completed
  robot: momo_1
  capability: move_joint
  message: Moved wrist_roll to 10.00 deg.
  result:
    profile: partial
    joint_name: wrist_roll
    target_deg: 10.0
    goal_raw: 2209
  artifacts: []
- action_id: act_024
  status: completed
  robot: momo_1
  capability: move_joint
  message: Moved wrist_roll to -10.00 deg.
  result:
    profile: partial
    joint_name: wrist_roll
    target_deg: -10.0
    goal_raw: 1981
  artifacts: []
- action_id: act_025
  status: completed
  robot: momo_1
  capability: move_joint
  message: Moved shoulder_pan to 10.00 deg.
  result:
    profile: partial
    joint_name: shoulder_pan
    target_deg: 10.0
    goal_raw: 3132
  artifacts: []
- action_id: act_026
  status: completed
  robot: momo_1
  capability: move_joint
  message: Moved shoulder_pan to -10.00 deg.
  result:
    profile: partial
    joint_name: shoulder_pan
    target_deg: -10.0
    goal_raw: 2904
  artifacts: []
- action_id: act_027
  status: completed
  robot: momo_1
  capability: move_joint
  message: Moved shoulder_pan to -10.00 deg.
  result:
    profile: partial
    joint_name: shoulder_pan
    target_deg: -10.0
    goal_raw: 2904
  artifacts: []
- action_id: act_028
  status: completed
  robot: momo_1
  capability: move_joint
  message: Moved shoulder_pan to 20.00 deg.
  result:
    profile: partial
    joint_name: shoulder_pan
    target_deg: 20.0
    goal_raw: 3246
  artifacts: []
- action_id: act_029
  status: completed
  robot: momo_1
  capability: move_joint
  message: Moved shoulder_pan to -20.00 deg.
  result:
    profile: partial
    joint_name: shoulder_pan
    target_deg: -20.0
    goal_raw: 2790
  artifacts: []
- action_id: act_030
  status: completed
  robot: momo_1
  capability: move_joint
  message: Moved shoulder_pan to 10.00 deg.
  result:
    profile: partial
    joint_name: shoulder_pan
    target_deg: 10.0
    goal_raw: 2904
  artifacts: []
- action_id: act_031
  status: completed
  robot: momo_1
  capability: move_joint
  message: Moved shoulder_pan to -10.00 deg.
  result:
    profile: partial
    joint_name: shoulder_pan
    target_deg: -10.0
    goal_raw: 2790
  artifacts: []
```
