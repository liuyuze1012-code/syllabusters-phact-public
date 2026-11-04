"""Create demo Cognito users and add them to groups (no public sign-up exists).

Demo cast: Dr. Elena Marchetti (faculty, potomac), a second professor (faculty, lakeshore),
a school admin (school-admin, potomac), an ASPPH reviewer (aspph-reviewer).
Usage: python seed_users.py --user-pool-id <id>
Uses admin_create_user + admin_add_user_to_group. Passwords come from the environment, never this file.
"""
# TODO
