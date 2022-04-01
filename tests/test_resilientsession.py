import logging
from unittest.mock import Mock, patch

import pytest
from requests import Response

import jira.resilientsession
from jira.exceptions import JIRAError
from tests.conftest import JiraTestCase


class ListLoggingHandler(logging.Handler):
    """A logging handler that records all events in a list."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def reset(self):
        self.records = []


class ResilientSessionLoggingConfidentialityTests(JiraTestCase):
    """No sensitive data shall be written to the log."""

    def setUp(self):
        self.loggingHandler = ListLoggingHandler()
        jira.resilientsession.logging.getLogger().addHandler(self.loggingHandler)

    def test_logging_with_connection_error(self):
        """No sensitive data shall be written to the log in case of a connection error."""
        witness = "etwhpxbhfniqnbbjoqvw"  # random string; hopefully unique
        for max_retries in (0, 1):
            for verb in ("get", "post", "put", "delete", "head", "patch", "options"):
                with self.subTest(max_retries=max_retries, verb=verb):
                    with jira.resilientsession.ResilientSession() as session:
                        session.max_retries = max_retries
                        session.max_retry_delay = 0
                        try:
                            getattr(session, verb)(
                                "http://127.0.0.1:9",
                                headers={"sensitive_header": witness},
                                data={"sensitive_data": witness},
                            )
                        except jira.resilientsession.ConnectionError:
                            pass
                    # check that `witness` does not appear in log
                    for record in self.loggingHandler.records:
                        self.assertNotIn(witness, record.msg)
                        for arg in record.args:
                            self.assertNotIn(witness, str(arg))
                        self.assertNotIn(witness, str(record))
                    self.loggingHandler.reset()

    def tearDown(self):
        jira.resilientsession.logging.getLogger().removeHandler(self.loggingHandler)
        del self.loggingHandler


status_codes_retries_test_data = [
    (429, 4, 3),
    (401, 1, 0),
    (403, 1, 0),
    (404, 1, 0),
    (502, 1, 0),
    (503, 1, 0),
    (504, 1, 0),
]


@patch("requests.Session.get")
@patch("time.sleep")
@pytest.mark.parametrize(
    "status_code,expected_number_of_retries,expected_number_of_sleep_invocations",
    status_codes_retries_test_data,
)
def test_status_codes_retries(
    mocked_sleep_method: Mock,
    mocked_get_method: Mock,
    status_code: int,
    expected_number_of_retries: int,
    expected_number_of_sleep_invocations: int,
):
    mocked_response: Response = Response()
    mocked_response.status_code = status_code
    mocked_response.headers["X-RateLimit-FillRate"] = "1"
    mocked_response.headers["X-RateLimit-Interval-Seconds"] = "1"
    mocked_response.headers["retry-after"] = "1"
    mocked_response.headers["X-RateLimit-Limit"] = "1"
    mocked_get_method.return_value = mocked_response
    session: jira.resilientsession.ResilientSession = (
        jira.resilientsession.ResilientSession()
    )
    with pytest.raises(JIRAError):
        session.get("mocked_url")
    assert mocked_get_method.call_count == expected_number_of_retries
    assert mocked_sleep_method.call_count == expected_number_of_sleep_invocations
