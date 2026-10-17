"""Create the Ed25519 key pair that signs core update bundles.

Run this once, offline:

    python scripts/core-keygen.py

* Put ``public_key`` into ``UPDATE_PUBLIC_KEY_HEX`` in local_studio/core_update.py
  and ship a new installer. Applications only trust bundles signed by this key.
* Store ``private_seed`` as the repository secret ``CORE_SIGNING_KEY``. Never
  commit it, paste it into an issue, or keep the only copy in one place: whoever
  holds it can make every installed copy run their code.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from local_studio import ed25519  # noqa: E402


def main() -> None:
    seed = os.urandom(32)
    print(json.dumps({"public_key": ed25519.public_key(seed).hex(), "private_seed": seed.hex()}, indent=2))
    print("\nThe private_seed above is shown once. Store it now.", file=sys.stderr)


if __name__ == "__main__":
    main()
