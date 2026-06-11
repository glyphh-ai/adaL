"""
Ada's vault — encrypted credential storage.

Stores secrets encrypted at rest using a machine-derived key.
The key is derived from a combination of:
  - Machine ID (hardware-bound)
  - Ada's install path (location-bound)
  - A salt stored alongside the encrypted data

Not unbreakable — but prevents casual extraction from pip packages
or disk inspection. The secrets are useless without the machine context.

Storage: ~/.ada/vault (binary file)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import struct
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

VAULT_DIR = Path.home() / ".ada"
VAULT_FILE = VAULT_DIR / "vault"


def _get_machine_fingerprint() -> bytes:
    """Derive a machine-specific fingerprint.

    Combines multiple signals so the key is bound to this machine.
    Not cryptographically perfect, but good enough to prevent
    casual credential extraction.
    """
    signals = []

    # Machine node (MAC-based UUID)
    try:
        import uuid
        signals.append(str(uuid.getnode()).encode())
    except Exception:
        pass

    # Platform
    signals.append(platform.node().encode())
    signals.append(platform.machine().encode())

    # Ada's install location
    signals.append(str(Path(__file__).resolve()).encode())

    # Fallback: username
    signals.append(os.environ.get("USER", "ada").encode())

    combined = b"|".join(signals)
    return hashlib.sha256(combined).digest()


def _derive_key(salt: bytes) -> bytes:
    """Derive encryption key from machine fingerprint + salt."""
    fingerprint = _get_machine_fingerprint()
    # PBKDF2-like: iterate hash to slow down brute force
    key = hashlib.sha256(salt + fingerprint).digest()
    for _ in range(10000):
        key = hashlib.sha256(key + salt + fingerprint).digest()
    return key


def _xor_bytes(data: bytes, key: bytes) -> bytes:
    """XOR cipher — simple but sufficient with a derived key."""
    key_len = len(key)
    return bytes(data[i] ^ key[i % key_len] for i in range(len(data)))


class Vault:
    """Encrypted credential storage for Ada."""

    def __init__(self):
        self._data: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        """Load and decrypt vault from disk."""
        if not VAULT_FILE.exists():
            return

        try:
            raw = VAULT_FILE.read_bytes()
            if len(raw) < 36:  # salt(32) + length(4) minimum
                return

            salt = raw[:32]
            key = _derive_key(salt)
            encrypted = raw[32:]
            decrypted = _xor_bytes(encrypted, key)

            # First 4 bytes are length of JSON payload
            payload_len = struct.unpack(">I", decrypted[:4])[0]
            payload = decrypted[4:4 + payload_len]

            self._data = json.loads(payload.decode("utf-8"))
        except Exception as e:
            # Legacy or foreign-key vault — unreadable, not fatal. Recorded
            # so `ada setup key` can tell the user to recreate it.
            self.load_error = str(e)
            logger.debug(f"Vault unreadable (legacy format or wrong machine key): {e}")
            self._data = {}

    def _save(self) -> None:
        """Encrypt and save vault to disk."""
        VAULT_DIR.mkdir(exist_ok=True)

        payload = json.dumps(self._data).encode("utf-8")

        # Random salt per save
        salt = os.urandom(32)
        key = _derive_key(salt)

        # Length-prefix the payload so we know where it ends
        prefixed = struct.pack(">I", len(payload)) + payload
        encrypted = _xor_bytes(prefixed, key)

        VAULT_FILE.write_bytes(salt + encrypted)
        os.chmod(VAULT_FILE, 0o600)

    def get(self, key: str) -> Optional[str]:
        """Get a secret."""
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        """Set a secret and persist."""
        self._data[key] = value
        self._save()

    def delete(self, key: str) -> None:
        """Remove a secret and persist."""
        self._data.pop(key, None)
        self._save()

    def has(self, key: str) -> bool:
        return key in self._data

    def keys(self) -> list[str]:
        return list(self._data.keys())


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_vault: Optional[Vault] = None


def get_vault() -> Vault:
    global _vault
    if _vault is None:
        _vault = Vault()
    return _vault
