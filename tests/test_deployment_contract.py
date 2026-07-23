import json
from pathlib import Path

from cppwiki.config import Settings


ROOT = Path(__file__).parents[1]


def test_target_defaults_use_cpu_bge_and_glm():
    settings = Settings(_env_file=None)
    assert settings.profile == "production-zai-cpu"
    assert settings.embed_model == "bge-m3"
    assert settings.embed_num_gpu == 0
    assert settings.opencode_provider == "zai"
    assert settings.opencode_model == "glm-5.1"


def test_zai_config_has_no_embedded_credentials():
    paths = [
        ROOT / "opencode.json",
        ROOT / "config" / "opencode" / "zai-general.json",
        ROOT / "config" / "opencode" / "zai-coding-plan.json",
    ]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        payload = json.loads(text)
        assert "apiKey" not in text
        assert payload["model"] == "zai/glm-5.1"
        assert payload["provider"]["zai"]["models"]["glm-5.1"]
        assert payload["permission"]["bash"] == "deny"
        assert payload["permission"]["edit"] == "deny"


def test_deployment_agent_artifacts_exist():
    required = [
        "scripts/deploy-target.sh",
        "scripts/preflight-target.sh",
        "scripts/run-production.sh",
        "scripts/validate-target.sh",
        "scripts/stop-services.sh",
        "docs/AGENT_DEPLOYMENT_GUIDE.md",
    ]
    for relative in required:
        assert (ROOT / relative).is_file(), relative

