import os
import secrets
from pathlib import Path


def load_env(path=".local/runtime.env"):
    path = Path(path)
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                name, separator, value = line.partition("=")
                if separator and (name.startswith("OSA_") or name.startswith("RAZORPAY_") or name == "BRAVE_API_KEY"):
                    os.environ.setdefault(name.strip(), value.strip())


def initialize(path=".local/runtime.env"):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive create: never replace existing credentials during setup.
    with path.open("x", encoding="utf-8") as output:
        output.write("# Private local runtime configuration. Never commit this file.\n")
        for key in ("OSA_API_TOKEN", "OSA_DOWNLOAD_SECRET", "RAZORPAY_WEBHOOK_SECRET"):
            output.write(f"{key}={secrets.token_urlsafe(48)}\n")
        output.write("OSA_PAYMENT_MODE=test\nOSA_LIVE_PAYMENTS=false\nOSA_MAIL_ENABLED=false\nOSA_PUBLIC_URL=http://127.0.0.1:8787\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return str(path.resolve())
