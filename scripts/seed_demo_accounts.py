"""Create the demo accounts (safe to rerun: existing accounts get a fresh password).

    python scripts/seed_demo_accounts.py

  demo-admin@phact.demo       ASPPH admin  (groups aspph-admin + aspph-staff, the older name, for compatibility)
  demo-professor@phact.demo   professor    (group faculty)

Passwords are random and written ONLY to playground/.uploads/demo_accounts.txt (git-ignored), never printed.
"""

import json
import secrets
import string
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[1]
ids = json.loads((ROOT / "playground" / "userdb_ids.json").read_text())
ACCOUNTS = [("demo-admin@phact.demo", "Demo ASPPH Admin", ["aspph-admin", "aspph-staff"]),
            ("demo-professor@phact.demo", "Demo Professor", ["faculty"])]


def password() -> str:
    a = string.ascii_letters + string.digits
    while True:
        p = "".join(secrets.choice(a) for _ in range(14))
        if any(c.islower() for c in p) and any(c.isdigit() for c in p):
            return p


def main():
    cog = boto3.client("cognito-idp", region_name=ids["region"])
    pool = ids["user_pool_id"]
    lines = ["PHACT demo accounts (git-ignored file; do not commit or paste into chat)", ""]
    for email, name, groups in ACCOUNTS:
        pw = password()
        try:
            cog.admin_create_user(UserPoolId=pool, Username=email, MessageAction="SUPPRESS",
                                  UserAttributes=[{"Name": "email", "Value": email}, {"Name": "email_verified", "Value": "true"},
                                                  {"Name": "name", "Value": name}])
        except cog.exceptions.UsernameExistsException:
            pass
        cog.admin_set_user_password(UserPoolId=pool, Username=email, Password=pw, Permanent=True)
        for g in groups:
            cog.admin_add_user_to_group(UserPoolId=pool, Username=email, GroupName=g)
        lines += [f"{name}", f"  email:    {email}", f"  password: {pw}", f"  role:     {groups[0]}", ""]
        print(f"ready: {email} ({groups[0]})")
    out = ROOT / "playground" / ".uploads" / "demo_accounts.txt"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines))
    out.chmod(0o600)
    print(f"passwords saved to {out}")


if __name__ == "__main__":
    main()
