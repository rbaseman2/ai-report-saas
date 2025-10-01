import os
from openai import OpenAI

_client = None

def get_client():
    global _client
    if _client is None:
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY not set.")
        _client = OpenAI(api_key=key)
    return _client
