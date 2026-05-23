---
schema: physical-agent/capabilities/v1
owner: watch
revision: 12
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
          - shoulder_pan
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
            shoulder_pan:
              type: number
          additionalProperties: false
        speed_percent:
          type: number
          minimum: 1
          maximum: 100
      additionalProperties: false
    constraints: {}
    requires_approval: false
```
