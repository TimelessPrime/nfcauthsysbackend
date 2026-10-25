import hashlib
import hmac
import ipaddress
import secrets
import time
from typing import Any

from src.config import get_auth_token, is_auth_required


def generate_nonce(length: int = 16) -> str:
    return secrets.token_hex(length)


def compute_hmac(key: str, message: str) -> str:
    return hmac.new(
        key.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_hmac(key: str, message: str, expected_signature: str) -> bool:
    actual_signature = compute_hmac(key, message)
    return hmac.compare_digest(actual_signature.lower(), expected_signature.lower())


def verify_token(provided_token: str | None) -> bool:
    if not is_auth_required():
        return True
    if not provided_token:
        return False
    expected_token = get_auth_token()
    return hmac.compare_digest(provided_token.strip(), expected_token.strip())


def generate_server_handshake_response(
    device_id: str,
    client_nonce: str,
    secret_key: str | None = None,
) -> dict[str, Any]:
    key = secret_key or get_auth_token()
    server_nonce = generate_nonce(8)
    server_timestamp = int(time.time())

    proof_payload = f"{device_id}:{client_nonce}:{server_nonce}:{server_timestamp}"
    server_signature = compute_hmac(key, proof_payload)
    session_token = secrets.token_urlsafe(24)

    return {
        "action": "handshake_ack",
        "status": "AUTHENTICATED",
        "session_token": session_token,
        "server_nonce": server_nonce,
        "server_timestamp": server_timestamp,
        "server_signature": server_signature,
        "message": "Ket noi backend hop le va xac thuc thanh cong",
    }


def create_step2_challenge(
    device_id: str,
    client_nonce: str,
    secret_key: str | None = None,
) -> tuple[str, dict[str, Any]]:
    key = secret_key or get_auth_token()
    server_nonce = generate_nonce(16)
    server_timestamp = int(time.time())
    server_proof = compute_hmac(key, f"STEP2:{device_id}:{client_nonce}:{server_nonce}:{server_timestamp}")

    return server_nonce, {
        "action": "handshake_step2",
        "status": "CHALLENGE",
        "device_id": device_id,
        "server_nonce": server_nonce,
        "server_proof": server_proof,
        "timestamp": server_timestamp,
    }


def verify_step3_response(
    device_id: str,
    client_nonce: str,
    server_nonce: str,
    client_proof: str,
    secret_key: str | None = None,
) -> tuple[bool, str | None]:
    key = secret_key or get_auth_token()
    expected_proof = compute_hmac(key, f"STEP3:{device_id}:{server_nonce}:{client_nonce}")

    if not hmac.compare_digest(client_proof.lower(), expected_proof.lower()):
        return False, None

    return True, secrets.token_urlsafe(32)


def ensure_ssl_certificates(cert_path, key_path) -> bool:
    from pathlib import Path
    cert_file = Path(cert_path)
    key_file = Path(key_path)

    if cert_file.exists() and key_file.exists():
        return True

    try:
        cert_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.parent.mkdir(parents=True, exist_ok=True)

        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        import datetime

        key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )

        with open(key_file, "wb") as f:
            f.write(
                key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            )

        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "VN"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "SG"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "NFC School Auth"),
            x509.NameAttribute(NameOID.COMMON_NAME, "nfc-server.local"),
        ])

        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(
                x509.SubjectAlternativeName([
                    x509.DNSName("localhost"),
                    x509.DNSName("nfc-server.local"),
                    x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                ]),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )

        with open(cert_file, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

        return True
    except Exception:
        return False
