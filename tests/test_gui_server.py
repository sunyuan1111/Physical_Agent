import json
import threading
import urllib.request

from physical_agent.gui import make_server


def _request(url: str, *, method: str = "GET", payload: dict | None = None) -> dict:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _read_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.read().decode("utf-8")


def test_gui_homepage_has_language_toggle(tmp_path):
    server = make_server(tmp_path / "physical-agent.yaml", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        html = _read_text(f"{base_url}/")
        assert "Physical Agent" in html
        assert 'data-lang="en"' in html
        assert 'data-lang="zh"' in html
        assert "中文" in html
        assert "Chat" in html
    finally:
        server.shutdown()
        server.server_close()


def test_gui_http_demo_endpoint(tmp_path):
    server = make_server(tmp_path / "physical-agent.yaml", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        setup = _request(f"{base_url}/api/setup", method="POST", payload={})
        assert setup["ok"] is True

        demo = _request(f"{base_url}/api/demo", method="POST", payload={})
        assert demo["ok"] is True
        assert demo["executed"] == 2
        assert demo["state"]["world"]["state"]["objects"]["red_block"]["location"] == "tray"

        state = _request(f"{base_url}/api/state")
        assert state["ready"] is True
        assert state["actions"]["completed"][-1]["capability"] == "place"
    finally:
        server.shutdown()
        server.server_close()


def test_gui_http_chat_endpoint(tmp_path):
    server = make_server(tmp_path / "physical-agent.yaml", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        _request(f"{base_url}/api/setup", method="POST", payload={})
        chat = _request(
            f"{base_url}/api/chat",
            method="POST",
            payload={
                "message": "pick the red block and place it on the tray",
                "planner": "rule_based",
                "auto_step": True,
            },
        )
        assert chat["ok"] is True
        assert chat["executed"] == 2
        assert chat["state"]["chat"]["messages"][-1]["role"] == "assistant"
        assert chat["state"]["world"]["state"]["objects"]["red_block"]["location"] == "tray"
    finally:
        server.shutdown()
        server.server_close()


def test_gui_http_integrate_endpoint(tmp_path):
    sdk = tmp_path / "vendor_sdk"
    sdk.mkdir()
    (sdk / "README.md").write_text(
        "# Demo Voice Device\n\nHTTP SDK with voice, speak, tts, light and RGB support.",
        encoding="utf-8",
    )
    server = make_server(tmp_path / "physical-agent.yaml", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        result = _request(
            f"{base_url}/api/integrate",
            method="POST",
            payload={"source": str(sdk), "name": "voice_light_driver"},
        )
        output_path = result["result"]["output_path"]
        assert result["ok"] is True
        assert "physical-agent-integration" in output_path
        assert result["result"]["source"]["transport"] == "http"
        assert result["result"]["source"]["robot_kind"] == "audio_device"
        assert result["state"]["ready"] is True
    finally:
        server.shutdown()
        server.server_close()
