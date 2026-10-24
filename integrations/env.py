"""Load secrets from the environment, a git-ignored .env in the repo root, or Streamlit's Secrets box. Never prints values."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_loaded = False


def load():
    """Idempotent. .env never overrides a variable already exported in the shell."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
    except ImportError:
        pass
    try:  # Streamlit Community Cloud: secrets.toml / the Secrets box -> environment, for the modules that read os.environ
        import streamlit as st
        for k, v in st.secrets.items():
            if isinstance(v, str) and k not in os.environ:
                os.environ[k] = v
    except Exception:
        pass


load()
