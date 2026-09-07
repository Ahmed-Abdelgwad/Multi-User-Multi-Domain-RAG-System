from unittest.mock import MagicMock, patch
from minio.error import S3Error
from src.storage import core


def _reset_client_cache():
    core.get_minio_client.cache_clear()


def test_ensure_bucket_creates_when_missing():
    _reset_client_cache()
    client = MagicMock()
    client.bucket_exists.return_value = False

    bucket = core.ensure_bucket(client)

    client.bucket_exists.assert_called_once_with("documents")
    client.make_bucket.assert_called_once_with("documents")
    assert bucket == "documents"


def test_ensure_bucket_skips_creation_when_present():
    _reset_client_cache()
    client = MagicMock()
    client.bucket_exists.return_value = True

    core.ensure_bucket(client)

    client.make_bucket.assert_not_called()


def test_upload_bytes_puts_object_and_returns_key():
    _reset_client_cache()
    with patch.object(core, "get_minio_client") as get_client:
        client = MagicMock()
        client.bucket_exists.return_value = True
        get_client.return_value = client

        key = core.upload_bytes("docs/a.pdf", b"hello", content_type="application/pdf")

        assert key == "docs/a.pdf"
        args, kwargs = client.put_object.call_args
        assert args[0] == "documents"
        assert args[1] == "docs/a.pdf"
        assert kwargs["length"] == 5
        assert kwargs["content_type"] == "application/pdf"


def test_download_bytes_reads_and_releases_response():
    _reset_client_cache()
    with patch.object(core, "get_minio_client") as get_client:
        client = MagicMock()
        client.bucket_exists.return_value = True
        response = MagicMock()
        response.read.return_value = b"content"
        client.get_object.return_value = response
        get_client.return_value = client

        data = core.download_bytes("docs/a.pdf")

        assert data == b"content"
        response.close.assert_called_once()
        response.release_conn.assert_called_once()


def test_object_exists_true_when_stat_succeeds():
    _reset_client_cache()
    with patch.object(core, "get_minio_client") as get_client:
        client = MagicMock()
        client.bucket_exists.return_value = True
        get_client.return_value = client

        assert core.object_exists("docs/a.pdf") is True


def test_object_exists_false_on_no_such_key():
    _reset_client_cache()
    with patch.object(core, "get_minio_client") as get_client:
        client = MagicMock()
        client.bucket_exists.return_value = True
        error = S3Error(
            code="NoSuchKey",
            message="not found",
            resource="/documents/docs/a.pdf",
            request_id="req-1",
            host_id="host-1",
            response=MagicMock(),
        )
        client.stat_object.side_effect = error
        get_client.return_value = client

        assert core.object_exists("docs/a.pdf") is False
