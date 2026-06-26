import os
from pathlib import Path
from langchain_mcp_adapters.client import MultiServerMCPClient

_REPO_ROOT = Path(__file__).parent.parent
_MCP_SERVER_PYTHON = _REPO_ROOT / "mcp_server" / ".venv" / "bin" / "python"
_MCP_SERVER_SCRIPT = _REPO_ROOT / "mcp_server" / "mcp_server.py"

_ENV_KEYS = [
    "DATABRICKS_HOST",
    "DATABRICKS_HTTP_PATH",
    "DATABRICKS_TOKEN",
    "ANTHROPIC_API_KEY",
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
]


def make_mcp_client() -> MultiServerMCPClient:
    """
    Returns a MultiServerMCPClient that spawns mcp_server.py via its own venv Python.
    Env vars are passed explicitly to the subprocess so they are available even if
    the parent process environment isn't fully inherited by the adapter.
    Call load_dotenv() before this function so os.environ is populated.
    """
    env = {k: v for k in _ENV_KEYS if (v := os.environ.get(k))}
    return MultiServerMCPClient({
        "databricks-demo": {
            "command": str(_MCP_SERVER_PYTHON),
            "args": [str(_MCP_SERVER_SCRIPT)],
            "transport": "stdio",
            "env": env,
        }
    })
