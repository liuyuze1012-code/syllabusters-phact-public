"""Deploy the PHACT agent (agent/service.py) to Amazon Bedrock AgentCore Runtime. Safe to rerun (creates or updates).

    python scripts/deploy_agentcore.py        # build → upload → runtime READY → writes playground/agentcore_ids.json

No Docker: AgentCore's direct code deployment runs a zip from S3 (Python 3.12, arm64), so the package is
built from Linux arm64 wheels. Then run scripts/deploy_lambda.py: it points the worker Lambda at this runtime.
"""

import io
import json
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
NAME, ROLE = "phact_agent", "PhactAgentCoreRole"
BUILD = Path("/tmp/phact-agentcore-build")
REQS = ["anthropic[bedrock]", "boto3>=1.39", "pydantic", "bedrock-agentcore", "strands-agents", "aws-opentelemetry-distro>=0.18.0"]
SKIP = {"__pycache__", "tests", "eval", ".DS_Store"}


def build() -> bytes:
    shutil.rmtree(BUILD, ignore_errors=True)
    BUILD.mkdir(parents=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--target", str(BUILD), "--platform", "manylinux2014_aarch64",
                    "--implementation", "cp", "--python-version", "3.12", "--only-binary=:all:", "--upgrade", *REQS], check=True)
    shutil.copytree(ROOT / "agent", BUILD / "agent", ignore=lambda d, names: [n for n in names if n in SKIP])
    shutil.copytree(ROOT / "shared" / "phact_contracts", BUILD / "phact_contracts", ignore=lambda d, n: [x for x in n if x in SKIP])
    (BUILD / "knowledge-base").mkdir()
    shutil.copy2(ROOT / "knowledge-base" / "kb_ids.json", BUILD / "knowledge-base" / "kb_ids.json")
    shutil.copytree(ROOT / "knowledge-base" / "checklist", BUILD / "knowledge-base" / "checklist")
    shutil.copy2(ROOT / "agent" / "agentcore_app.py", BUILD / "agentcore_app.py")  # the entrypoint sits at the root
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in BUILD.rglob("*"):
            if f.is_file() and "__pycache__" not in f.parts:
                z.write(f, f.relative_to(BUILD))
    return buf.getvalue()


def role() -> str:
    iam = boto3.client("iam")
    trust = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
             "Action": "sts:AssumeRole", "Condition": {"StringEquals": {"aws:SourceAccount": ACCOUNT}}}]}
    try:
        arn = iam.create_role(RoleName=ROLE, AssumeRolePolicyDocument=json.dumps(trust), Description="PHACT agent on AgentCore")["Role"]["Arn"]
        time.sleep(10)
    except iam.exceptions.EntityAlreadyExistsException:
        arn = iam.get_role(RoleName=ROLE)["Role"]["Arn"]
    policy = {"Version": "2012-10-17", "Statement": [
        {"Sid": "Claude", "Effect": "Allow", "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock:Retrieve",
                                                        "bedrock:ApplyGuardrail"], "Resource": "*"},
        {"Sid": "PersonalData", "Effect": "Allow", "Action": ["comprehend:DetectPiiEntities"], "Resource": "*"},
        {"Sid": "Code", "Effect": "Allow", "Action": ["s3:GetObject"], "Resource": f"arn:aws:s3:::{ids['bucket']}/deploy/agentcore/*"},
        {"Sid": "BucketKey", "Effect": "Allow", "Action": ["kms:Decrypt"], "Resource": "*", "Condition": {"StringEquals": {"kms:ViaService": f"s3.{REGION}.amazonaws.com"}}},
        {"Sid": "Logs", "Effect": "Allow", "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams",
                                                      "logs:DescribeLogGroups"], "Resource": f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:/aws/bedrock-agentcore/*"},
        {"Sid": "Traces", "Effect": "Allow", "Action": ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:PutSpans", "xray:PutSpansForIndexing",
                                                        "xray:GetSamplingRules", "xray:GetSamplingTargets", "cloudwatch:PutMetricData"], "Resource": "*"},
        {"Sid": "SpanLogs", "Effect": "Allow", "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents", "logs:PutResourcePolicy",
                                                          "logs:DescribeResourcePolicies"],
         "Resource": [f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:aws/spans:*", f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:/aws/bedrock-agentcore/*",
                      f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:/aws/bedrock-agentcore/*:*", f"arn:aws:logs:{REGION}:{ACCOUNT}:*"]},
    ]}
    iam.put_role_policy(RoleName=ROLE, PolicyName="PhactAgent", PolicyDocument=json.dumps(policy))
    return arn


def observability(arn: str, rid: str) -> None:
    """The runtime's own logs and traces (the console's Log delivery + Tracing panes), set up by API. Safe to rerun."""
    logs = boto3.client("logs", region_name=REGION)
    def quiet(fn, **kw):
        try:
            return fn(**kw)
        except (logs.exceptions.ConflictException, logs.exceptions.ResourceAlreadyExistsException):
            return None
    group = f"/aws/vendedlogs/bedrock-agentcore/{rid}"
    quiet(logs.create_log_group, logGroupName=group)
    src_logs = quiet(logs.put_delivery_source, name=f"{rid}-logs", logType="APPLICATION_LOGS", resourceArn=arn)
    src_tr = quiet(logs.put_delivery_source, name=f"{rid}-traces", logType="TRACES", resourceArn=arn)
    dst_logs = logs.put_delivery_destination(name=f"{rid}-logs-dest", deliveryDestinationType="CWL",
                                             deliveryDestinationConfiguration={"destinationResourceArn": f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:{group}"})
    dst_tr = logs.put_delivery_destination(name=f"{rid}-traces-dest", deliveryDestinationType="XRAY")
    for src, dst in ((f"{rid}-logs", dst_logs), (f"{rid}-traces", dst_tr)):
        quiet(logs.create_delivery, deliverySourceName=src, deliveryDestinationArn=dst["deliveryDestination"]["arn"])
    print("observability: log + trace delivery on")


def main():
    print("building the arm64 package…")
    data = build()
    print(f"package {len(data) / 1e6:.1f} MB")
    key = f"deploy/agentcore/phact-agent-{int(time.time())}.zip"
    boto3.client("s3", region_name=REGION).put_object(Bucket=ids["bucket"], Key=key, Body=data)
    role_arn = role()
    ctl = boto3.client("bedrock-agentcore-control", region_name=REGION)
    cfg = dict(agentRuntimeArtifact={"codeConfiguration": {"code": {"s3": {"bucket": ids["bucket"], "prefix": key}},
                                                           "runtime": "PYTHON_3_12", "entryPoint": ["agentcore_app.py"]}},
               roleArn=role_arn, networkConfiguration={"networkMode": "PUBLIC"},
               environmentVariables={"KB_ID": kb["kb_id"], "KNOWLEDGE_BUCKET": kb["knowledge_bucket"]},
               description="PHACT: syllabus and assessment AI-integration + CEPH agent")
    found = next((r for r in ctl.list_agent_runtimes()["agentRuntimes"] if r["agentRuntimeName"] == NAME), None)
    for attempt in range(6):  # a just-created role can need a few seconds before AgentCore accepts it
        try:
            if found:
                r = ctl.update_agent_runtime(agentRuntimeId=found["agentRuntimeId"], **cfg)
            else:
                r = ctl.create_agent_runtime(agentRuntimeName=NAME, **cfg)
            break
        except ctl.exceptions.ValidationException as e:
            if "Role validation" not in str(e) or attempt == 5:
                raise
            time.sleep(10)
    rid, arn = r["agentRuntimeId"], r["agentRuntimeArn"]
    for _ in range(90):
        st = ctl.get_agent_runtime(agentRuntimeId=rid)
        if st["status"] in ("READY", "CREATE_FAILED", "UPDATE_FAILED"):
            break
        time.sleep(5)
    print("status:", st["status"], st.get("failureReason", ""))
    if st["status"] != "READY":
        sys.exit(1)
    try:
        observability(arn, rid)
    except Exception as e:  # noqa: BLE001 — e.g. Transaction Search still activating: rerun with --observability-only
        print(f"observability not set yet ({str(e)[:120]}); rerun: python scripts/deploy_agentcore.py --observability-only")
    (ROOT / "playground" / "agentcore_ids.json").write_text(json.dumps({"agent_runtime_arn": arn, "agent_runtime_id": rid, "version": str(st.get("agentRuntimeVersion", "")), "region": REGION}, indent=2) + "\n")
    print(json.dumps({"agent_runtime_arn": arn}, indent=2))


if __name__ == "__main__":
    if "--observability-only" in sys.argv:  # e.g. once Transaction Search has finished activating
        d = json.loads((ROOT / "playground" / "agentcore_ids.json").read_text())
        observability(d["agent_runtime_arn"], d["agent_runtime_id"])
    else:
        main()
