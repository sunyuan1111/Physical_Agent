from __future__ import annotations

from collections import Counter
from pathlib import Path

from scripts import f0_bad_task_experiment as f0


def test_f0_task_set_has_required_categories():
    counts = Counter(case.category for case in f0.TASK_CASES)

    assert counts["越界坐标"] >= 3
    assert counts["幻觉能力"] >= 3
    assert counts["中文任务"] >= 3
    assert counts["多步任务"] >= 3
    assert counts["模糊指令"] >= 3


def test_f0_report_renders_stats_and_priority_lines():
    results = [
        {
            "id": "bounds_far_positive",
            "category": "越界坐标",
            "outcome": "gate_rejected",
            "proposal_json": [
                {"id": "act_001", "capability": "move_to", "params": {"x": 999}}
            ],
            "gate": [
                {
                    "action_id": "act_001",
                    "ok": False,
                    "message": "Param x=999 is outside allowed bounds [-1.0, 1.0]",
                }
            ],
            "feedback_messages": [
                "Param x=999 is outside allowed bounds [-1.0, 1.0]"
            ],
        },
        {
            "id": "zh_place_red_block",
            "category": "中文任务",
            "outcome": "completed",
            "proposal_json": [{"id": "act_001", "capability": "pick", "params": {}}],
            "gate": [{"action_id": "act_001", "ok": True, "message": "accepted"}],
            "feedback_messages": ["Picked red_block successfully."],
        },
    ]

    report = f0.render_report(
        results=results,
        generated_at="2026-07-06T00:00:00+00:00",
        results_path=Path("workspace/f0/results.json"),
    )

    assert "Gate 拦截统计" in report
    assert "| 越界坐标 | 1 | 0 | 1 | 0 | 0 | 0 |" in report
    assert "bounds_far_positive" in report
    assert "F1/F3/F4" in report
