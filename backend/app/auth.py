"""Who is calling. Reads the Cognito claims that API Gateway's authorizer already verified.

RULE: user_id and school_id come ONLY from these claims, never from the request body.
With DEV_AUTH=1 (local only) a fixed demo professor is used instead.
"""

from dataclasses import dataclass

from fastapi import HTTPException, Request

from app.config import settings


@dataclass
class User:
    user_id: str
    school_id: str | None
    groups: list[str]

    @property
    def is_school_admin(self) -> bool:
        return "school-admin" in self.groups

    @property
    def is_reviewer(self) -> bool:
        return "aspph-reviewer" in self.groups


def current_user(request: Request) -> User:
    if settings.dev_auth:
        return User(user_id="dev-prof-1", school_id="potomac", groups=["faculty"])
    # TODO: read request.scope["aws.event"]["requestContext"]["authorizer"]["claims"]
    #       → sub, custom:school_id, cognito:groups
    raise HTTPException(401, "Not signed in")


def require_group(user: User, group: str) -> None:
    """Call at the top of every role-restricted route. Hiding a button is not security."""
    if group not in user.groups:
        raise HTTPException(403, "You don't have access to this page.")
