"""Explicit live test; uses configured credentials but never prints them."""
import os
import subprocess
import sys
import pytest
from app.config import Settings


@pytest.mark.skipif(os.getenv("DEVPILOT_LIVE_LLM_TEST") != "1", reason="Opt in to a real quota-consuming LLM test")
def test_real_openrouter_structured_response():
    if not Settings().openrouter_api_key.get_secret_value():
        pytest.skip("OPENROUTER_API_KEY not configured")
    result = subprocess.run([sys.executable, "-m", "scripts.check_services", "--worker", "openrouter"],
                            capture_output=True, text=True, timeout=105)
    assert result.returncode == 0, "Live OpenRouter check failed; credentials and raw provider output suppressed"
