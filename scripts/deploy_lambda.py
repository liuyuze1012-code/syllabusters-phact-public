"""Phase 1 deployment: FastAPI + Mangum on Lambda behind an API Gateway HTTP API with a Cognito JWT authorizer,
plus a worker Lambda for async jobs. Safe to rerun (creates or updates). Phase 2 replaces this with CDK.

    python scripts/deploy_lambda.py            # build + deploy; prints the URL

Builds a Linux (x86_64, Python 3.12) package without Docker: pip downloads Linux wheels; our code is copied in.
Nothing secret goes in the package: AWS access comes from the function role; ids are not secrets.
"""

import io
import json
import secrets
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[1]
REGION = "us-west-2"
ids = json.loads((ROOT / "playground" / "userdb_ids.json").read_text())
kb = json.loads((ROOT / "knowledge-base" / "kb_ids.json").read_text())
ACCOUNT = boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]
_ac = ROOT / "playground" / "agentcore_ids.json"  # written by deploy_agentcore.py; absent → the agent runs inside the Lambda
AGENTCORE = json.loads(_ac.read_text()) if _ac.exists() else None
ROLE, API_FN, WORKER_FN, API_NAME = "PhactLambdaRole", "phact-api", "phact-worker", "phact-http-api"
BUILD = Path("/tmp/phact-lambda-build")
REQS = ["anthropic[bedrock]", "boto3>=1.39", "fastapi", "pydantic", "python-docx", "python-multipart", "mangum", "httpx"]
INCLUDE = ["agent", "backend/app", "playground", "shared/phact_contracts", "knowledge-base/checklist", "knowledge-base/policies",
           "knowledge-base/kb_ids.json", "data/test-assessments", "data/test-syllabi/Synthetic"]
SKIP = {"__pycache__", ".uploads", "out", "tests", ".DS_Store"}


def build() -> bytes:
    shutil.rmtree(BUILD, ignore_errors=True)
    BUILD.mkdir(parents=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--target", str(BUILD), "--platform", "manylinux2014_x86_64",
                    "--implementation", "cp", "--python-version", "3.12", "--only-binary=:all:", "--upgrade", *REQS], check=True)
    for rel in INCLUDE:
        src = ROOT / rel
        dst = BUILD / ("phact_contracts" if rel == "shared/phact_contracts" else rel)
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        else:
            shutil.copytree(src, dst, ignore=lambda d, names: [n for n in names if n in SKIP])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in BUILD.rglob("*"):
            if f.is_file() and "__pycache__" not in f.parts:
                z.write(f, f.relative_to(BUILD))
    return buf.getvalue()


def role() -> str:
    iam = boto3.client("iam")
    trust = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]}
    try:
        arn = iam.create_role(RoleName=ROLE, AssumeRolePolicyDocument=json.dumps(trust), Description="PHACT API + worker Lambdas")["Role"]["Arn"]
        time.sleep(10)  # new roles take a moment before Lambda can assume them
    except iam.exceptions.EntityAlreadyExistsException:
        arn = iam.get_role(RoleName=ROLE)["Role"]["Arn"]
    iam.attach_role_policy(RoleName=ROLE, PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole")
    kbb, ub = kb["knowledge_bucket"], ids["bucket"]
    policy = {"Version": "2012-10-17", "Statement": [
        {"Sid": "Claude", "Effect": "Allow", "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock:Retrieve", "bedrock:ApplyGuardrail"], "Resource": "*"},
        {"Sid": "KbSync", "Effect": "Allow", "Action": ["bedrock:StartIngestionJob", "bedrock:GetIngestionJob", "bedrock:ListIngestionJobs"],
         "Resource": f"arn:aws:bedrock:{REGION}:{ACCOUNT}:knowledge-base/{kb['kb_id']}"},
        {"Sid": "PersonalData", "Effect": "Allow", "Action": ["comprehend:DetectPiiEntities"], "Resource": "*"},
        {"Sid": "PdfTables", "Effect": "Allow", "Action": ["textract:StartDocumentAnalysis", "textract:GetDocumentAnalysis", "textract:AnalyzeDocument"], "Resource": "*"},
        {"Sid": "Buckets", "Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"], "Resource": [f"arn:aws:s3:::{kbb}/*", f"arn:aws:s3:::{ub}/*"]},
        {"Sid": "BucketList", "Effect": "Allow", "Action": ["s3:ListBucket"], "Resource": [f"arn:aws:s3:::{kbb}", f"arn:aws:s3:::{ub}"]},
        {"Sid": "BucketKey", "Effect": "Allow", "Action": ["kms:Decrypt", "kms:GenerateDataKey"], "Resource": "*", "Condition": {"StringEquals": {"kms:ViaService": f"s3.{REGION}.amazonaws.com"}}},
        {"Sid": "Table", "Effect": "Allow", "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:Scan", "dynamodb:BatchWriteItem"],
         "Resource": f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/{ids['table']}"},
        {"Sid": "Accounts", "Effect": "Allow", "Action": ["cognito-idp:AdminConfirmSignUp", "cognito-idp:AdminUpdateUserAttributes", "cognito-idp:AdminAddUserToGroup"],
         "Resource": f"arn:aws:cognito-idp:{REGION}:{ACCOUNT}:userpool/{ids['user_pool_id']}"},
        {"Sid": "StartWorker", "Effect": "Allow", "Action": ["lambda:InvokeFunction"], "Resource": f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{WORKER_FN}"},
        {"Sid": "AgentMonitor", "Effect": "Allow", "Action": ["cloudwatch:GetMetricData"], "Resource": "*"},  # read-only: the Agent monitor
        *([{"Sid": "Agent", "Effect": "Allow", "Action": ["bedrock-agentcore:InvokeAgentRuntime"],
            "Resource": [AGENTCORE["agent_runtime_arn"], AGENTCORE["agent_runtime_arn"] + "/*"]}] if AGENTCORE else []),
    ]}
    iam.put_role_policy(RoleName=ROLE, PolicyName="PhactApp", PolicyDocument=json.dumps(policy))
    return arn


def function(lam, name, handler, timeout, memory, role_arn, s3_key, env):
    cfg = dict(Runtime="python3.12", Handler=handler, Timeout=timeout, MemorySize=memory, Role=role_arn, Environment={"Variables": env})
    try:
        lam.get_function(FunctionName=name)
        lam.update_function_code(FunctionName=name, S3Bucket=ids["bucket"], S3Key=s3_key)
        lam.get_waiter("function_updated_v2").wait(FunctionName=name)
        lam.update_function_configuration(FunctionName=name, **cfg)
    except lam.exceptions.ResourceNotFoundException:
        for _ in range(6):  # a just-created role can need a few more seconds
            try:
                lam.create_function(FunctionName=name, Code={"S3Bucket": ids["bucket"], "S3Key": s3_key}, **cfg)
                break
            except lam.exceptions.InvalidParameterValueException:
                time.sleep(8)
    lam.get_waiter("function_updated_v2").wait(FunctionName=name)
    return lam.get_function(FunctionName=name)["Configuration"]["FunctionArn"]


def api(api_fn_arn: str) -> str:
    gw = boto3.client("apigatewayv2", region_name=REGION)
    found = next((a for a in gw.get_apis()["Items"] if a["Name"] == API_NAME), None)
    api_id = found["ApiId"] if found else gw.create_api(Name=API_NAME, ProtocolType="HTTP")["ApiId"]
    integ = next((i for i in gw.get_integrations(ApiId=api_id)["Items"] if i.get("IntegrationUri") == api_fn_arn), None)
    integ_id = integ["IntegrationId"] if integ else gw.create_integration(
        ApiId=api_id, IntegrationType="AWS_PROXY", IntegrationUri=api_fn_arn, PayloadFormatVersion="2.0", TimeoutInMillis=30000)["IntegrationId"]
    auth = next((a for a in gw.get_authorizers(ApiId=api_id)["Items"] if a["Name"] == "cognito-jwt"), None)
    auth_id = auth["AuthorizerId"] if auth else gw.create_authorizer(
        ApiId=api_id, Name="cognito-jwt", AuthorizerType="JWT", IdentitySource=["$request.header.Authorization"],
        JwtConfiguration={"Issuer": f"https://cognito-idp.{REGION}.amazonaws.com/{ids['user_pool_id']}", "Audience": [ids["client_id"]]})["AuthorizerId"]
    routes = {r["RouteKey"]: r for r in gw.get_routes(ApiId=api_id)["Items"]}
    wanted = {"ANY /api/{proxy+}": True,                # every API call needs a verified Cognito token…
              "ANY /api/auth/{proxy+}": False,          # …except login / sign-up / status
              "GET /api/health": False, "GET /": False, "GET /admin": False, "GET /university": False, "GET /client.js": False, "$default": False}
    for key, secured in wanted.items():
        kw = dict(ApiId=api_id, RouteKey=key, Target=f"integrations/{integ_id}",
                  **({"AuthorizationType": "JWT", "AuthorizerId": auth_id} if secured else {"AuthorizationType": "NONE"}))
        if key in routes:
            gw.update_route(RouteId=routes[key]["RouteId"], **{k: v for k, v in kw.items() if k != "RouteKey"})
        else:
            gw.create_route(**kw)
    stages = {s["StageName"] for s in gw.get_stages(ApiId=api_id)["Items"]}
    throttle = {"ThrottlingBurstLimit": 50, "ThrottlingRateLimit": 20}  # rate limiting per the security requirements
    if "$default" in stages:
        gw.update_stage(ApiId=api_id, StageName="$default", DefaultRouteSettings=throttle)
    else:
        gw.create_stage(ApiId=api_id, StageName="$default", AutoDeploy=True, DefaultRouteSettings=throttle)
    lam = boto3.client("lambda", region_name=REGION)
    try:
        lam.add_permission(FunctionName=API_FN, StatementId="apigw-invoke", Action="lambda:InvokeFunction",
                           Principal="apigateway.amazonaws.com", SourceArn=f"arn:aws:execute-api:{REGION}:{ACCOUNT}:{api_id}/*")
    except lam.exceptions.ResourceConflictException:
        pass
    return f"https://{api_id}.execute-api.{REGION}.amazonaws.com"


def main():
    print("building the package…")
    data = build()
    print(f"package {len(data) / 1e6:.1f} MB")
    key = f"deploy/lambda/phact-{int(time.time())}.zip"
    boto3.client("s3", region_name=REGION).put_object(Bucket=ids["bucket"], Key=key, Body=data)
    role_arn = role()
    lam = boto3.client("lambda", region_name=REGION)
    env = {"PHACT_AUTH": "1", "PHACT_AUTH_MODE": "jwt", "PHACT_JOBS": "lambda", "WORKER_FUNCTION": WORKER_FN,
           "PHACT_TEXTRACT": "1", "PHACT_SECRET": secrets.token_hex(32),
           **({"PHACT_AGENT": "agentcore", "AGENT_RUNTIME_ARN": AGENTCORE["agent_runtime_arn"],
               "AGENT_VERSION": AGENTCORE.get("version", "")} if AGENTCORE else {})}
    worker_arn = function(lam, WORKER_FN, "playground/lambda_handler.worker_handler", 900, 1536, role_arn, key, env)
    lam.put_function_event_invoke_config(FunctionName=WORKER_FN, MaximumRetryAttempts=0)  # a job runs once; the UI reports failures
    api_arn = function(lam, API_FN, "playground/lambda_handler.api_handler", 30, 1024, role_arn, key, env)
    url = api(api_arn)
    print(json.dumps({"url": url, "api_function": api_arn, "worker_function": worker_arn}, indent=2))
    (ROOT / "playground" / "deploy_ids.json").write_text(json.dumps({"url": url, "region": REGION}, indent=2) + "\n")


if __name__ == "__main__":
    main()
