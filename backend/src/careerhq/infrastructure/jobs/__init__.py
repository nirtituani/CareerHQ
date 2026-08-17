"""Reading a job posting from the web.

Split from `documents/` because the failure modes are entirely different: a
document is handed to us and either parses or does not, while a URL is fetched
from a network that will happily serve an attacker's page, refuse a legitimate
one, or point back at our own infrastructure.
"""

from careerhq.infrastructure.jobs.fetch import (
    JobFetchError,
    UnsafeUrlError,
    assert_fetchable,
    fetch_posting,
)
from careerhq.infrastructure.jobs.parse import (
    html_to_text,
    json_ld_job_posting,
    looks_unrendered,
)

__all__ = [
    "JobFetchError",
    "UnsafeUrlError",
    "assert_fetchable",
    "fetch_posting",
    "html_to_text",
    "json_ld_job_posting",
    "looks_unrendered",
]
