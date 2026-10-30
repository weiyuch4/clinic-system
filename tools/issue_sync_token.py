"""Give one clinic's sync agent its own token. Prints the token once; only its hash is stored.
Put the printed value in that clinic's agent as SYNC_TOKEN. Running it again replaces the old token
(the old one stops working immediately). Clinic 1 may keep using the SYNC_TOKEN set on the server.
    DATABASE_URL=postgresql://... python tools/issue_sync_token.py <clinic_id>"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auth  # noqa: E402
import db  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        print(__doc__)
        return 2
    db.init_pool(minconn=1, maxconn=1)
    auth.init()
    try:
        token = auth.issue_sync_token(int(sys.argv[1]))
    except ValueError as e:
        print(e)
        return 1
    print(token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
