"""S3 helpers: presigned upload/download links and reading uploaded files.

The buckets use KMS, so the client MUST use signature v4 or links fail.
"""

import boto3
from botocore.config import Config

s3 = boto3.client("s3", config=Config(signature_version="s3v4"))


def upload_key(school_id: str, user_id: str, course: str, version: int, filename: str) -> str:
    return f"{school_id}/{user_id}/{course}/v{version}/{filename}"


# TODO: presign_put(bucket, key, content_type, expires=300)
# TODO: presign_get(bucket, key, expires=300)
# TODO: read_bytes(bucket, key)
