---
name: code
title: Code Skill
description: Edit repository files, write tests, and run local scripts.
triggers:
  - modify files
  - write tests
  - fix this bug
  - run script
  - execute code
intents:
  - code_edit
  - code_run
priority: 10
---

# Code Skill

Use this skill when the user asks to change code, add tests, or run a repository script.
The runtime may edit files inside the repository root, run tests, or execute a script and
report the output back to chat.
