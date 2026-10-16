"""HMAC proof scoped to the Cards import endpoint; never a browser session."""

import hashlib
import hmac

from .contracts import IMPORT_PATH


def signature(key: str, body: bytes, timestamp: str) -> str:
    digest = hashlib.sha256(body).hexdigest()
    message = f"cards-import-v1\nPOST\n{IMPORT_PATH}\n{timestamp}\n{digest}".encode()
    return hmac.new(key.encode(), message, hashlib.sha256).hexdigest()
