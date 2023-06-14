"""
TDS S3 storage.
"""
import os

import boto3

from tds.settings import settings


def s3_client():
    """
    Function sets up an S3 client based on env settings.
    """
    if settings.STORAGE_HOST:
        s3_ = boto3.client(
            "s3",
            endpoint_url=settings.STORAGE_HOST,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            aws_session_token=None,
            config=boto3.session.Config(signature_version="s3v4"),
            verify=False,
        )
    else:
        s3_ = boto3.client("s3")

    return s3_


def get_file_path(entity_id: str | int, file_name: str, path: str) -> str:
    """
    Function builds a file path for s3.
    """
    return os.path.join(path, str(entity_id), file_name)


def get_presigned_url(entity_id: str | int, file_name: str, method: str, path: str):
    """
    Function generates a presigned URL for the HMI client.
    """
    s3_ = s3_client()
    s3_key = get_file_path(entity_id=entity_id, file_name=file_name, path=path)
    return s3_.generate_presigned_url(
        ClientMethod=method, Params={"Bucket": settings.S3_BUCKET, "Key": s3_key}
    )
