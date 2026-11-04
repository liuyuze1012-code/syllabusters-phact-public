"""Create the PHACT knowledge base in the sandbox. Safe to rerun: existing pieces are reused.

    python scripts/create_kb.py            # prints the IDs at the end and writes knowledge-base/kb_ids.json

Creates, in the current AWS region (our sandbox: us-west-2):
  1. S3 bucket  phact-knowledge-<account>-<region>   KMS-encrypted, all public access blocked, HTTPS only
  2. S3 Vectors bucket + index (1024 dims, cosine); AMAZON_BEDROCK_TEXT/METADATA + display keys non-filterable
  3. IAM role   PhactKnowledgeBaseRole                read kb/ in the bucket, use the index, call Titan embeddings
  4. Bedrock Knowledge Base  phact-kb               Titan Text Embeddings v2, S3 Vectors storage
  5. Data source             phact-kb-source        syncs ONLY the kb/ prefix; fixed-size chunks, 300 tokens, 20% overlap

A quick-start for the hackathon; infra/lib/knowledge-stack.ts is the CDK version of the same settings.
"""

import json
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
session = boto3.Session()
REGION = session.region_name
ACCOUNT = session.client("sts").get_caller_identity()["Account"]

BUCKET = f"phact-knowledge-{ACCOUNT}-{REGION}"
VECTOR_BUCKET = f"phact-vectors-{ACCOUNT}"
INDEX = "phact-kb-index"
ROLE = "PhactKnowledgeBaseRole"
KB_NAME = "phact-kb"
DS_NAME = "phact-kb-source"
EMBED_MODEL = "amazon.titan-embed-text-v2:0"
EMBED_ARN = f"arn:aws:bedrock:{REGION}::foundation-model/{EMBED_MODEL}"
NON_FILTERABLE = ["AMAZON_BEDROCK_TEXT", "AMAZON_BEDROCK_METADATA", "title", "section", "original"]

s3 = session.client("s3")
s3v = session.client("s3vectors")
iam = session.client("iam")
agent = session.client("bedrock-agent")


def step(msg):
    print(f"• {msg}")


def make_bucket():
    try:
        s3.head_bucket(Bucket=BUCKET)
        step(f"bucket exists: {BUCKET}")
    except ClientError:
        s3.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": REGION})
        step(f"created bucket: {BUCKET}")
    s3.put_public_access_block(Bucket=BUCKET, PublicAccessBlockConfiguration={
        "BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True, "RestrictPublicBuckets": True})
    s3.put_bucket_encryption(Bucket=BUCKET, ServerSideEncryptionConfiguration={"Rules": [{
        "ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "aws:kms"}, "BucketKeyEnabled": True}]})
    s3.put_bucket_versioning(Bucket=BUCKET, VersioningConfiguration={"Status": "Enabled"})
    s3.put_bucket_policy(Bucket=BUCKET, Policy=json.dumps({"Version": "2012-10-17", "Statement": [{
        "Sid": "HttpsOnly", "Effect": "Deny", "Principal": "*", "Action": "s3:*",
        "Resource": [f"arn:aws:s3:::{BUCKET}", f"arn:aws:s3:::{BUCKET}/*"],
        "Condition": {"Bool": {"aws:SecureTransport": "false"}}}]}))
    step("bucket locked down: KMS encryption, public access blocked, HTTPS only, versioning on")


def make_vector_index() -> str:
    try:
        s3v.create_vector_bucket(vectorBucketName=VECTOR_BUCKET)
        step(f"created vector bucket: {VECTOR_BUCKET}")
    except ClientError as e:
        if e.response["Error"]["Code"] not in ("ConflictException", "BucketAlreadyExists"):
            raise
        step(f"vector bucket exists: {VECTOR_BUCKET}")
    try:
        s3v.create_index(vectorBucketName=VECTOR_BUCKET, indexName=INDEX, dataType="float32", dimension=1024,
                         distanceMetric="cosine",
                         metadataConfiguration={"nonFilterableMetadataKeys": NON_FILTERABLE})
        step(f"created vector index: {INDEX} (1024 dims, cosine)")
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConflictException":
            raise
        step(f"vector index exists: {INDEX}")
    return s3v.get_index(vectorBucketName=VECTOR_BUCKET, indexName=INDEX)["index"]["indexArn"]


def make_role(index_arn: str) -> str:
    trust = {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Principal": {"Service": "bedrock.amazonaws.com"}, "Action": "sts:AssumeRole",
        "Condition": {"StringEquals": {"aws:SourceAccount": ACCOUNT}}}]}
    try:
        arn = iam.create_role(RoleName=ROLE, AssumeRolePolicyDocument=json.dumps(trust),
                              Description="PHACT Bedrock Knowledge Base: read kb/, use the vector index, embed")["Role"]["Arn"]
        step(f"created role: {ROLE}")
        fresh = True
    except ClientError as e:
        if e.response["Error"]["Code"] != "EntityAlreadyExists":
            raise
        arn = iam.get_role(RoleName=ROLE)["Role"]["Arn"]
        step(f"role exists: {ROLE}")
        fresh = False
    policy = {"Version": "2012-10-17", "Statement": [
        {"Sid": "Embed", "Effect": "Allow", "Action": "bedrock:InvokeModel", "Resource": EMBED_ARN},
        {"Sid": "ListKb", "Effect": "Allow", "Action": "s3:ListBucket", "Resource": f"arn:aws:s3:::{BUCKET}",
         "Condition": {"StringLike": {"s3:prefix": ["kb/*", "kb"]}}},
        {"Sid": "ReadKb", "Effect": "Allow", "Action": "s3:GetObject", "Resource": f"arn:aws:s3:::{BUCKET}/kb/*"},
        {"Sid": "Vectors", "Effect": "Allow", "Resource": index_arn, "Action": [
            "s3vectors:PutVectors", "s3vectors:GetVectors", "s3vectors:DeleteVectors",
            "s3vectors:QueryVectors", "s3vectors:GetIndex", "s3vectors:ListVectors"]},
        {"Sid": "KmsViaS3", "Effect": "Allow", "Action": ["kms:Decrypt", "kms:GenerateDataKey"], "Resource": "*",
         "Condition": {"StringEquals": {"kms:ViaService": f"s3.{REGION}.amazonaws.com"}}},
    ]}
    iam.put_role_policy(RoleName=ROLE, PolicyName="PhactKnowledgeBaseAccess", PolicyDocument=json.dumps(policy))
    if fresh:
        step("waiting 15 s for the new role to become usable")
        time.sleep(15)
    return arn


def make_kb(role_arn: str, index_arn: str) -> str:
    for kb in agent.list_knowledge_bases(maxResults=100)["knowledgeBaseSummaries"]:
        if kb["name"] == KB_NAME:
            step(f"knowledge base exists: {kb['knowledgeBaseId']}")
            return kb["knowledgeBaseId"]
    for attempt in range(4):  # a brand-new role can take a little longer to propagate
        try:
            kb = agent.create_knowledge_base(
                name=KB_NAME, roleArn=role_arn,
                description="PHACT: ASPPH guidance and workforce sources for cited syllabus recommendations",
                knowledgeBaseConfiguration={"type": "VECTOR", "vectorKnowledgeBaseConfiguration": {
                    "embeddingModelArn": EMBED_ARN,
                    "embeddingModelConfiguration": {"bedrockEmbeddingModelConfiguration": {
                        "dimensions": 1024, "embeddingDataType": "FLOAT32"}}}},
                storageConfiguration={"type": "S3_VECTORS", "s3VectorsConfiguration": {"indexArn": index_arn}},
            )["knowledgeBase"]
            break
        except ClientError as e:
            if attempt == 3 or "role" not in str(e).lower():
                raise
            step("role not ready yet, retrying in 15 s")
            time.sleep(15)
    kb_id = kb["knowledgeBaseId"]
    while agent.get_knowledge_base(knowledgeBaseId=kb_id)["knowledgeBase"]["status"] == "CREATING":
        time.sleep(5)
    step(f"created knowledge base: {kb_id}")
    return kb_id


def make_data_source(kb_id: str) -> str:
    for ds in agent.list_data_sources(knowledgeBaseId=kb_id, maxResults=100)["dataSourceSummaries"]:
        if ds["name"] == DS_NAME:
            step(f"data source exists: {ds['dataSourceId']}")
            return ds["dataSourceId"]
    ds = agent.create_data_source(
        knowledgeBaseId=kb_id, name=DS_NAME,
        dataSourceConfiguration={"type": "S3", "s3Configuration": {
            "bucketArn": f"arn:aws:s3:::{BUCKET}", "inclusionPrefixes": ["kb/"]}},
        vectorIngestionConfiguration={"chunkingConfiguration": {
            "chunkingStrategy": "FIXED_SIZE",
            "fixedSizeChunkingConfiguration": {"maxTokens": 300, "overlapPercentage": 20}}},
    )["dataSource"]
    step(f"created data source: {ds['dataSourceId']} (syncs kb/ only, 300-token chunks)")
    return ds["dataSourceId"]


def main():
    print(f"account {ACCOUNT}, region {REGION}")
    make_bucket()
    index_arn = make_vector_index()
    role_arn = make_role(index_arn)
    kb_id = make_kb(role_arn, index_arn)
    ds_id = make_data_source(kb_id)
    ids = {"region": REGION, "knowledge_bucket": BUCKET, "vector_bucket": VECTOR_BUCKET, "index_arn": index_arn,
           "role_arn": role_arn, "kb_id": kb_id, "data_source_id": ds_id, "embedding_model": EMBED_MODEL}
    (ROOT / "knowledge-base/kb_ids.json").write_text(json.dumps(ids, indent=2) + "\n")
    print("\n" + json.dumps(ids, indent=2))
    print(f"\nNext:\n  KNOWLEDGE_BUCKET={BUCKET} KB_ID={kb_id} DATA_SOURCE_ID={ds_id} python scripts/upload_kb.py")


if __name__ == "__main__":
    main()
