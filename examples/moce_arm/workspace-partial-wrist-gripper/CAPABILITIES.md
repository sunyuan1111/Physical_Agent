---
schema: physical-agent/capabilities/v1
owner: watch
revision: 9
---

# Capabilities

## Robots

```yaml
momo_1:
  kind: arm
  driver: momoagent_driver
  status: connected
  requires_approval: false
  capabilities:
  - name: observe
    description: Observe the current arm state.
    params_schema:
      type: object
      properties: {}
      additionalProperties: false
    constraints: {}
    requires_approval: false
  - name: home
    description: Return the arm to its runtime home pose.
    params_schema:
      type: object
      properties:
        speed_percent:
          type: number
          minimum: 1
          maximum: 100
      additionalProperties: false
    constraints: {}
    requires_approval: false
  - name: stop
    description: Stop the current arm motion and hold the current pose.
    params_schema:
      type: object
      properties: {}
      additionalProperties: false
    constraints: {}
    requires_approval: false
  - name: move_joint
    description: Move one available joint by absolute target or relative delta in
      degrees.
    params_schema:
      type: object
      required:
      - joint_name
      properties:
        joint_name:
          type: string
          enum:
          - wrist_roll
        target_deg:
          type: number
        delta_deg:
          type: number
        speed_percent:
          type: number
          minimum: 1
          maximum: 100
      additionalProperties: false
      anyOf:
      - required:
        - target_deg
      - required:
        - delta_deg
    constraints: {}
    requires_approval: false
  - name: move_joints
    description: Move multiple available joints to target degrees.
    params_schema:
      type: object
      required:
      - targets_deg
      properties:
        targets_deg:
          type: object
          properties:
            wrist_roll:
              type: number
          additionalProperties: false
        speed_percent:
          type: number
          minimum: 1
          maximum: 100
      additionalProperties: false
    constraints: {}
    requires_approval: false
  - name: set_gripper
    description: Set gripper opening ratio from 0.0 to 1.0.
    params_schema:
      type: object
      required:
      - open_ratio
      properties:
        open_ratio:
          type: number
          minimum: 0.0
          maximum: 1.0
        speed_percent:
          type: number
          minimum: 1
          maximum: 100
      additionalProperties: false
    constraints: {}
    requires_approval: false
  - name: open_gripper
    description: Fully open the gripper.
    params_schema:
      type: object
      properties:
        speed_percent:
          type: number
          minimum: 1
          maximum: 100
      additionalProperties: false
    constraints: {}
    requires_approval: false
  - name: close_gripper
    description: Fully close the gripper.
    params_schema:
      type: object
      properties:
        speed_percent:
          type: number
          minimum: 1
          maximum: 100
      additionalProperties: false
    constraints: {}
    requires_approval: false
```
