"""Create PHACT's user data stores. Safe to rerun: reuses anything that already exists.

    python scripts/create_userdb.py        # writes playground/userdb_ids.json (ids only, no secrets)

  Cognito user pool  phact-users       accounts: email + password (hashed by AWS) + role group
                                        groups: faculty, aspph-staff, school-admin
  DynamoDB table     phact-app          one table, PK/SK (NoSQL single-table design):
                                          USER#<sub>  PROFILE           email, name, role, preferences
                                          USER#<sub>  COURSE#<code>     course details + progress summary + S3 key
                                          USER#<sub>  EVENT#<iso time>  history: login, upload, analyze, decision, export
  S3 bucket          phact-userdata-…   each course's full progress (users/<sub>/courses/<code>.json);
                                        private, encrypted. DynamoDB items max out at 400 KB, progress can be larger.
"""

import json
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[1]
REGION = "us-west-2"
POOL, CLIENT, TABLE = "phact-users", "phact-web", "phact-app"
GROUPS = {"faculty": "Professors", "aspph-admin": "ASPPH admin (spec name): knowledge base and example-syllabus review",
          "school-admin": "A school's admin: AI policy"}


def main():
    acct = boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]
    bucket = f"phact-userdata-{acct}-{REGION}"

    cog = boto3.client("cognito-idp", region_name=REGION)
    pool = next((p for p in cog.list_user_pools(MaxResults=60)["UserPools"] if p["Name"] == POOL), None)
    if pool:
        pool_id = pool["Id"]
    else:
        pool_id = cog.create_user_pool(
            PoolName=POOL, UsernameAttributes=["email"], AutoVerifiedAttributes=["email"],
            Policies={"PasswordPolicy": {"MinimumLength": 8, "RequireUppercase": False, "RequireLowercase": True,
                                         "RequireNumbers": True, "RequireSymbols": False}},
            AdminCreateUserConfig={"AllowAdminCreateUserOnly": False},
            Schema=[{"Name": "name", "AttributeDataType": "String", "Mutable": True}],
            DeletionProtection="INACTIVE")["UserPool"]["Id"]
    clients = cog.list_user_pool_clients(UserPoolId=pool_id, MaxResults=60)["UserPoolClients"]
    client = next((c for c in clients if c["ClientName"] == CLIENT), None)
    client_id = client["ClientId"] if client else cog.create_user_pool_client(
        UserPoolId=pool_id, ClientName=CLIENT, GenerateSecret=False,
        ExplicitAuthFlows=["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"],
        PreventUserExistenceErrors="ENABLED")["UserPoolClient"]["ClientId"]
    have = {g["GroupName"] for g in cog.list_groups(UserPoolId=pool_id)["Groups"]}
    for g, d in GROUPS.items():
        if g not in have:
            cog.create_group(UserPoolId=pool_id, GroupName=g, Description=d)

    ddb = boto3.client("dynamodb", region_name=REGION)
    if TABLE not in ddb.list_tables()["TableNames"]:
        ddb.create_table(TableName=TABLE, BillingMode="PAY_PER_REQUEST",
                         AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"},
                                               {"AttributeName": "SK", "AttributeType": "S"}],
                         KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
                         SSESpecification={"Enabled": True})
        ddb.get_waiter("table_exists").wait(TableName=TABLE)

    s3 = boto3.client("s3", region_name=REGION)
    existing = {b["Name"] for b in s3.list_buckets()["Buckets"]}
    if bucket not in existing:
        s3.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": REGION})
        s3.put_public_access_block(Bucket=bucket, PublicAccessBlockConfiguration={
            "BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True, "RestrictPublicBuckets": True})
        s3.put_bucket_encryption(Bucket=bucket, ServerSideEncryptionConfiguration={
            "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]})

    ids = {"region": REGION, "user_pool_id": pool_id, "client_id": client_id, "table": TABLE, "bucket": bucket}
    (ROOT / "playground" / "userdb_ids.json").write_text(json.dumps(ids, indent=2) + "\n")
    print(json.dumps(ids, indent=2))


if __name__ == "__main__":
    main()
