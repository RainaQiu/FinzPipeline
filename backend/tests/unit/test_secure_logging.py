import logging

from app.core.logging import OAuthQueryRedactionFilter


def test_oauth_callback_query_is_removed_from_access_log_record():
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        (
            "127.0.0.1",
            "GET",
            "/api/v1/integrations/qbo/callback?code=temporary-secret&state=opaque",
            "1.1",
            200,
        ),
        None,
    )

    assert OAuthQueryRedactionFilter().filter(record) is True
    rendered = record.getMessage()
    assert "temporary-secret" not in rendered
    assert "opaque" not in rendered
    assert rendered.endswith('/api/v1/integrations/qbo/callback HTTP/1.1" 200')
