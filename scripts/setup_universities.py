"""University layer setup. Safe to rerun.

    python scripts/setup_universities.py          # Cognito attribute + app client; then demo universities and accounts

1. Cognito: adds `custom:university_id`. The app client may READ it (it rides in the ID token, so API Gateway and
   the server see it as a verified claim) but not WRITE it: a user can never move themselves to another university.
   Only the server's admin API sets it, after a valid invite code.
2. Demo data (fictional): two universities, each with a university admin and a professor, so isolation can be
   tested live. Passwords go ONLY to playground/.uploads/demo_accounts.txt (git-ignored), never printed.
"""

import json
import secrets
import string
import sys
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "playground")]
ids = json.loads((ROOT / "playground" / "userdb_ids.json").read_text())
cog = boto3.client("cognito-idp", region_name=ids["region"])
POOL, CLIENT = ids["user_pool_id"], ids["client_id"]
ATTR = "custom:university_id"


def cognito() -> None:
    pool = cog.describe_user_pool(UserPoolId=POOL)["UserPool"]
    if not any(a["Name"] == ATTR for a in pool["SchemaAttributes"]):
        cog.add_custom_attributes(UserPoolId=POOL, CustomAttributes=[
            {"Name": "university_id", "AttributeDataType": "String", "Mutable": True, "StringAttributeConstraints": {"MinLength": "0", "MaxLength": "64"}}])
        print("added", ATTR)
    c = cog.describe_user_pool_client(UserPoolId=POOL, ClientId=CLIENT)["UserPoolClient"]
    # update_user_pool_client resets anything not passed, so pass the current settings back
    keep = {k: c[k] for k in ("ExplicitAuthFlows", "RefreshTokenValidity", "AccessTokenValidity", "IdTokenValidity", "TokenValidityUnits",
                              "PreventUserExistenceErrors", "EnableTokenRevocation", "AuthSessionValidity", "SupportedIdentityProviders",
                              "AllowedOAuthFlows", "AllowedOAuthScopes", "AllowedOAuthFlowsUserPoolClient", "CallbackURLs", "LogoutURLs") if k in c}
    cog.update_user_pool_client(UserPoolId=POOL, ClientId=CLIENT, ClientName=c["ClientName"], **keep,
                                ReadAttributes=["email", "email_verified", "name", ATTR],
                                WriteAttributes=["email", "name"])  # NOT custom:university_id
    print("app client: university_id readable, not writable by users")


def password() -> str:
    a = string.ascii_letters + string.digits
    while True:
        p = "".join(secrets.choice(a) for _ in range(14))
        if any(c.islower() for c in p) and any(c.isdigit() for c in p):
            return p


OUT = ROOT / "playground" / ".uploads" / "demo_accounts.txt"


def known_passwords() -> dict:
    """Passwords already in the git-ignored file, so rerunning never breaks an account someone is using."""
    import re
    return dict(re.findall(r"email:\s+(\S+)\s*\n\s*password:\s+(\S+)", OUT.read_text())) if OUT.exists() else {}


def account(email, name, group, uni_id, known) -> tuple[str, str]:
    try:
        cog.admin_create_user(UserPoolId=POOL, Username=email, MessageAction="SUPPRESS",
                              UserAttributes=[{"Name": "email", "Value": email}, {"Name": "email_verified", "Value": "true"}, {"Name": "name", "Value": name}])
        pw = password()
        cog.admin_set_user_password(UserPoolId=POOL, Username=email, Password=pw, Permanent=True)
    except cog.exceptions.UsernameExistsException:
        pw = known.get(email)
        if not pw:  # exists but we lost its password: give it a new one
            pw = password()
            cog.admin_set_user_password(UserPoolId=POOL, Username=email, Password=pw, Permanent=True)
    attrs = [{"Name": "name", "Value": name}] + ([{"Name": ATTR, "Value": uni_id}] if uni_id else [])
    cog.admin_update_user_attributes(UserPoolId=POOL, Username=email, UserAttributes=attrs)
    cog.admin_add_user_to_group(UserPoolId=POOL, Username=email, GroupName=group)
    sub = next(a["Value"] for a in cog.admin_get_user(UserPoolId=POOL, Username=email)["UserAttributes"] if a["Name"] == "sub")
    return sub, pw


UNIS = [
    ("westbridge", "Westbridge University (fictional)", "restricted",
     [{"id": "WU-AI-1", "text": "Generative AI may be used for brainstorming and editing only, and every use must be disclosed."},
      {"id": "WU-AI-2", "text": "Graded exams are AI-free unless the instructor states otherwise in writing."}],
     ("Dana Reyes", [("demo-prof-westbridge@phact.demo", "Dr. Elena Morgan", "Epidemiology"),
                     ("demo-prof2-westbridge@phact.demo", "Dr. James Okafor", "Biostatistics")])),
    ("northfield", "Northfield University (fictional)", "open",
     [{"id": "NU-AI-1", "text": "Collaborative AI use is allowed when disclosed and accompanied by a reflection on its limits."}],
     ("Sam Whitaker", [("demo-prof-northfield@phact.demo", "Dr. Priya Shah", "Health Policy"),
                       ("demo-prof2-northfield@phact.demo", "Dr. Marcus Lee", "Community Health")])),
]


LOCATION = {"westbridge": ("Boston", "MA"), "northfield": ("Minneapolis", "MN")}
# more fictional member schools (no accounts) so ASPPH's Universities page shows every region
EXTRA = [("lakeshore", "Lakeshore University (fictional)", "Chicago", "IL", "restricted"),
         ("gulfcoast", "Gulf Coast University (fictional)", "Houston", "TX", "open"),
         ("piedmont", "Piedmont State University (fictional)", "Durham", "NC", "restricted"),
         ("cascadia", "Cascadia University (fictional)", "Seattle", "WA", "open"),
         ("sierra", "Sierra Pacific University (fictional)", "Sacramento", "CA", "ban"),
         ("hudson", "Hudson Valley University (fictional)", "Albany", "NY", "restricted")]


def demo() -> None:
    import universities
    import userdata
    known = known_passwords()
    for slug, name, city, state, stance in EXTRA:
        if not universities.get(slug):
            universities.create(name, uni_id=slug, city=city, state=state)
        universities.set_location(slug, city, state)
        universities.set_policy(slug, {"max_ai_stance": stance, "rules": [], "notes": "Demo (fictional)."}, "setup")
        print(f"ready: {slug} ({city}, {state})")
    url = json.loads((ROOT / "playground" / "deploy_ids.json").read_text())["url"]
    made = {}
    for slug, name, stance, rules, (admin_name, profs) in UNIS:
        uni = universities.get(slug) or universities.create(name, uni_id=slug, city=LOCATION[slug][0], state=LOCATION[slug][1])
        universities.set_location(slug, *LOCATION[slug])
        universities.set_policy(slug, {"max_ai_stance": stance, "rules": rules, "notes": "Demo policy (fictional)."}, "setup")
        short = name.split(" (")[0]
        people = [(f"demo-uniadmin-{slug}@phact.demo", f"{admin_name} ({short} admin)", "school-admin", "")] + \
                 [(e, n, "faculty", dept) for e, n, dept in profs]
        for email, display, group, dept in people:
            sub, pw = account(email, display, group, slug, known)
            universities.add_member(slug, sub, email, display, group)
            userdata.put_profile(sub, email=email, name=display, role=group, university_id=slug)
            made[email] = (display, pw, group, slug, dept)
            print(f"ready: {email} ({group} at {slug})")
    # the two accounts from seed_demo_accounts.py: keep them, with their passwords
    for email, display, group in (("demo-admin@phact.demo", "Demo ASPPH Admin", "aspph-admin"), ("demo-professor@phact.demo", "Demo Professor", "faculty")):
        if email in known:
            made[email] = (display, known[email], group, "", "")

    def block(email):
        display, pw, group, slug, dept = made[email]
        extra = f"  department: {dept}\n" if dept else ""
        return f"  {display}\n    email:    {email}\n    password: {pw}\n{extra.replace('  department', '    department')}"
    ADM = "demo-admin@phact.demo"
    text = f"""PHACT DEMO ACCOUNTS AND TEST GUIDE
Fictional accounts for testing only. This file is git-ignored: never commit it, never paste passwords into chat.
Generated by scripts/setup_universities.py (rerunning keeps these passwords).

==============================================================================
THE THREE LINKS
==============================================================================
1. Professor app ........... {url}
   Sign in and choose "Professor".
2. University admin portal . {url}/university
   Or open the main link and choose "University admin".
3. ASPPH admin console ..... {url}/admin
   For ASPPH staff.

==============================================================================
1. PROFESSOR APP  ({url})  choose "Professor"
==============================================================================
Westbridge University (AI policy: up to Guided; rules WU-AI-1, WU-AI-2)
{block("demo-prof-westbridge@phact.demo")}{block("demo-prof2-westbridge@phact.demo")}
Northfield University (AI policy: up to Integrated; rule NU-AI-1)
{block("demo-prof-northfield@phact.demo")}{block("demo-prof2-northfield@phact.demo")}
Independent (no university: PHACT's default rules, no AI cap)
{block("demo-professor@phact.demo") if "demo-professor@phact.demo" in made else "  (run scripts/seed_demo_accounts.py to create demo-professor@phact.demo)\n"}
==============================================================================
2. UNIVERSITY ADMIN PORTAL  ({url}/university)  choose "University admin"
==============================================================================
Sees only their own university's professors and courses (read-only), sets its AI policy, creates invite codes.
{block("demo-uniadmin-westbridge@phact.demo")}{block("demo-uniadmin-northfield@phact.demo")}
==============================================================================
3. ASPPH ADMIN CONSOLE  ({url}/admin)
==============================================================================
The whole organization: the knowledge base (grouped by content type, area, status), every member
university on one page (by region and state, with counts), adding universities and their first admin's
invite code, example-syllabus reviews and the audit log. ASPPH does NOT use the university portal.
{block(ADM) if ADM in made else "  (run scripts/seed_demo_accounts.py to create demo-admin@phact.demo)\n"}
==============================================================================
WHAT TO TEST (about 10 minutes)
==============================================================================
a. Policy above the professor: sign in as Dr. Elena Morgan (Westbridge), upload the sample "EPID 601
   syllabus" in step 1. In step 2, "Integrated" is blocked: Westbridge allows up to Guided.
b. University admin sees it: sign in as Dana Reyes (Westbridge admin) at /university. Courses shows
   Elena's course, read-only, with every recommendation and decision.
c. Isolation: sign in as Sam Whitaker (Northfield admin). Elena's course is NOT there.
d. Wrong door: sign in as a professor but choose "University admin": refused.
e. Invite: as Dana, Invite codes → Create code. Sign out, "Create an account" with that code:
   the new professor appears under Westbridge's Professors.
f. ASPPH: sign in at /admin. Universities: 8 fictional schools grouped by region; filter by state, sort,
   open one. Knowledge base: filter by type, area, assessment type; group by area or status.
"""
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(text)
    OUT.chmod(0o600)
    print(f"guide written to {OUT} ({len(made)} accounts)")


if __name__ == "__main__":
    cognito()
    if "--cognito-only" not in sys.argv:
        demo()
