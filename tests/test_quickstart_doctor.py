import yaml

from physical_agent.doctor import doctor_ok, run_doctor
from physical_agent.quickstart import setup_project
from physical_agent.state import open_state_store


def test_doctor_reports_missing_config(tmp_path):
    checks = run_doctor(tmp_path / "physical-agent.yaml")
    assert not doctor_ok(checks)
    assert any(check.name == "config" and not check.ok for check in checks)


def test_setup_project_smoke_test(tmp_path):
    config_path = tmp_path / "physical-agent.yaml"
    result = setup_project(config_path, smoke_test=True)
    assert result["doctor_ok"] is True
    assert result["smoke_test"]["ok"] is True
    assert result["smoke_test"]["red_block_location"] == "tray"
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert data["workspace"]["backend"] == "sqlite"
    store = open_state_store(config_path=config_path)
    assert store.db_path.exists()
    assert store.file("safety").exists()

