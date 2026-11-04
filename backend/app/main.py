"""FastAPI app. Locally: `uvicorn app.main:app --reload`. On Lambda: `handler` via Mangum.

API Gateway's Cognito authorizer verifies the token before requests reach this app.
"""

from fastapi import FastAPI
from mangum import Mangum

from app.routes import courses, edits, exports, health, jobs, me, review, school

app = FastAPI(title="PHACT API", version="0.1.0")

for r in (health, me, courses, jobs, edits, exports, school, review):
    app.include_router(r.router)

handler = Mangum(app)  # Lambda entrypoint for the API function
