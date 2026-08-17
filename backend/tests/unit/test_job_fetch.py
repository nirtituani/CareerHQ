"""Fetching and reading a job posting from a URL.

Two things are being protected here, and only one of them is the feature.

**The feature**: a posting becomes structured fields. Where the page publishes
schema.org `JobPosting` data — most applicant tracking systems do — that costs
no model call at all, which is why the parser is tried before the model.

**The security property**: this is the first place in CareerHQ that fetches a
URL the *user* supplied, from *inside* the network. Without a guard that is a
server-side request forgery hole pointed at the cloud metadata endpoint, the
database, and every internal service by name. The guard is the larger part of
this file for that reason.
"""

from __future__ import annotations

import pytest

from careerhq.infrastructure.jobs.fetch import UnsafeUrlError, assert_fetchable
from careerhq.infrastructure.jobs.parse import html_to_text, json_ld_job_posting


class TestTheSsrfGuard:
    """`assert_fetchable` raises unless the URL is safe to request."""

    @pytest.mark.parametrize(
        "url",
        [
            "http://169.254.169.254/latest/meta-data/",  # AWS/GCP metadata
            "http://metadata.google.internal/",
            "http://127.0.0.1:5432/",
            "http://localhost:8000/api/health",
            "http://[::1]:8000/",
            "http://10.0.0.5/",
            "http://192.168.1.1/",
            "http://172.16.0.1/",
            "http://0.0.0.0/",
        ],
    )
    def test_it_refuses_to_reach_inside_the_network(self, url: str) -> None:
        """The whole point. Each of these is reachable from the container.

        `backend`, `pgvector` and the metadata endpoint are all one request away
        from a process that will fetch whatever it is given, and the response
        would come back to the user as an "extracted job posting".
        """
        with pytest.raises(UnsafeUrlError):
            assert_fetchable(url)

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "gopher://example.com/",
            "ftp://example.com/",
            "data:text/html,<h1>hi</h1>",
            "javascript:alert(1)",
        ],
    )
    def test_it_accepts_no_scheme_but_http_and_https(self, url: str) -> None:
        with pytest.raises(UnsafeUrlError):
            assert_fetchable(url)

    def test_it_refuses_a_hostname_that_resolves_inward(self) -> None:
        """Blocking literal IPs is not enough.

        A hostname is what actually arrives — `backend` resolves to a private
        address inside compose, and a hostile posting URL can point at one just
        as easily. The check has to run against the *resolved* address.
        """
        with pytest.raises(UnsafeUrlError):
            assert_fetchable("http://backend:8000/api/health")

    @pytest.mark.parametrize(
        "url",
        [
            "https://boards.greenhouse.io/example/jobs/1234",
            "https://jobs.lever.co/example/abc-123",
            "https://www.linkedin.com/jobs/view/1234567890/",
        ],
    )
    def test_it_allows_an_ordinary_public_posting(self, url: str) -> None:
        assert_fetchable(url)


class TestReadingThePage:
    def test_it_reads_schema_org_job_posting_without_a_model_call(self) -> None:
        """The free path. Most applicant tracking systems publish this.

        Exact rather than inferred, and it costs nothing — which is why it is
        tried before the model rather than as a fallback after it.
        """
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"JobPosting",
         "title":"Senior Backend Engineer",
         "hiringOrganization":{"@type":"Organization","name":"Acme Corporation",
                               "sameAs":"https://acme.com"},
         "jobLocation":{"@type":"Place","address":{"@type":"PostalAddress",
                        "addressLocality":"Tel Aviv","addressCountry":"IL"}},
         "baseSalary":{"@type":"MonetaryAmount","currency":"USD",
                       "value":{"@type":"QuantitativeValue","minValue":90000,
                                "maxValue":110000,"unitText":"YEAR"}},
         "description":"<p>We are looking for a <b>Senior Backend Engineer</b>.</p>"}
        </script></head><body>ignored</body></html>
        """

        posting = json_ld_job_posting(html)

        assert posting is not None
        assert posting.job_title == "Senior Backend Engineer"
        assert posting.company == "Acme Corporation"
        assert posting.company_domain == "acme.com"
        # Locality and country, not locality alone: "Tel Aviv, IL" is what a
        # person would write in the field, and the country disambiguates the
        # many cities that share a name.
        assert posting.location == "Tel Aviv, IL"
        # The description arrives as HTML even inside JSON-LD, and must not
        # reach the user as tags.
        assert "Senior Backend Engineer" in (posting.job_description or "")
        assert "<b>" not in (posting.job_description or "")

    def test_it_finds_the_posting_inside_a_graph(self) -> None:
        """Real pages wrap it in `@graph` or an array as often as not."""
        html = """
        <script type="application/ld+json">
        {"@context":"https://schema.org","@graph":[
          {"@type":"Organization","name":"Acme"},
          {"@type":"JobPosting","title":"Staff Engineer",
           "hiringOrganization":{"name":"Acme Corporation"},
           "description":"Build things."}]}
        </script>
        """

        posting = json_ld_job_posting(html)

        assert posting is not None
        assert posting.job_title == "Staff Engineer"

    def test_it_returns_nothing_when_the_page_has_no_posting_data(self) -> None:
        """Not a failure — the caller falls through to the model."""
        assert json_ld_job_posting("<html><body><h1>Careers</h1></body></html>") is None
        assert json_ld_job_posting('<script type="application/ld+json">{ broken</script>') is None

    def test_it_strips_a_page_to_readable_text(self) -> None:
        """What the model reads when there is no structured data.

        Script and style content must not survive: it is the bulk of a modern
        job page, it is not the posting, and it would dominate the prompt.
        """
        html = """
        <html><head><style>.a{color:red}</style>
        <script>var tracking = "do not send this";</script></head>
        <body><h1>Senior Backend Engineer</h1>
        <p>We are looking&nbsp;for someone to <b>own</b> the platform.</p>
        <!-- a comment --></body></html>
        """

        text = html_to_text(html)

        assert "Senior Backend Engineer" in text
        assert "own the platform" in text
        assert "do not send this" not in text
        assert "color:red" not in text
        assert "<" not in text


class TestWhatTheModelIsAskedFor:
    """The model reads *about* the posting; it never retypes it.

    Asking for the description back costs thousands of output tokens, and output
    is the slow half of a completion: a real Greenhouse posting took **52
    seconds** end to end that way, which is not a form interaction. The
    description is already in the text we stripped, so the model is asked only
    for the short fields it can actually add — company, title, location, salary.

    This is a property of the schema, so it is asserted against the schema
    rather than against a timing, which would be flaky.
    """

    def test_the_model_is_not_asked_to_reproduce_the_description(self) -> None:
        from careerhq.application.extract_job import JobMetadata

        assert "job_description" not in JobMetadata.model_fields, (
            "asking the model to echo the description back is what made this "
            "take 52 seconds; the text is already in hand"
        )

    def test_the_metadata_fields_are_all_short(self) -> None:
        """Every field is a phrase, so the completion stays small and quick."""
        from careerhq.application.extract_job import JobMetadata

        assert set(JobMetadata.model_fields) == {
            "company",
            "job_title",
            "location",
            "salary_text",
            "company_domain",
            # A list of lines, not prose: the one long field, and asking for it
            # as lines means copied rather than composed.
            "requirements",
        }


class TestStructuredDataIsMetadataOnly:
    """JSON-LD supplies the short fields. It does **not** supply the body.

    Found on a real posting: the page's `JobPosting` block carried a 1,591
    character description that was the company blurb, while the page itself held
    9,447 characters including the actual requirements. Returning early on the
    structured-data path therefore produced *less* than reading the page, and
    skipped the requirements narrowing entirely — the description came back
    starting "Company Overview:".

    So structured data is trusted for title, company, location and salary, where
    the employer wrote the field and there is nothing to infer, and the body is
    always read from the page.
    """

    def test_the_url_path_always_asks_for_requirements(self) -> None:
        import inspect

        from careerhq.application import extract_job

        source = inspect.getsource(extract_job.extract_job_from_url)
        assert "return JobExtraction(posting=structured" not in source, (
            "returning early on structured data skips the requirements narrowing "
            "and can return less than the page itself"
        )

    async def test_structured_metadata_wins_over_the_models_reading(self) -> None:
        """Where the employer stated a field, that beats a model inferring it."""
        from decimal import Decimal

        from pydantic import BaseModel

        from careerhq.application.extract_job import extract_job_from_url
        from careerhq.application.ports import Completion, Usage

        page = """
        <html><head><script type="application/ld+json">
        {"@type":"JobPosting","title":"Senior Backend Engineer",
         "hiringOrganization":{"name":"Acme Corporation"},
         "description":"<p>Company Overview: we are a company.</p>"}
        </script></head><body>
        <h1>Careers</h1>
        <p>Requirements: 5+ years of Python. Experience with PostgreSQL.</p>
        <p>%s</p></body></html>
        """ % ("filler " * 60)

        class _Stub:
            async def complete[T: BaseModel](
                self, *, task: str, schema: type[T], prompt: str
            ) -> Completion[T]:
                return Completion(
                    value=schema.model_validate(
                        {
                            "job_title": "Something The Model Guessed",
                            "requirements": ["5+ years of Python", "Experience with PostgreSQL"],
                        }
                    ),
                    usage=Usage(model="stub", input_tokens=1, output_tokens=1, cost=Decimal("0")),
                )

        async def _fetch(_: str) -> str:
            return page

        from careerhq.application import extract_job as module

        original = module.fetch_posting
        module.fetch_posting = _fetch  # type: ignore[assignment]
        try:
            result = await extract_job_from_url("https://example.com/j", completion=_Stub())
        finally:
            module.fetch_posting = original  # type: ignore[assignment]

        # The employer's own title, not the model's guess.
        assert result.posting.job_title == "Senior Backend Engineer"
        assert result.posting.company == "Acme Corporation"
        # And the requirements, not the company blurb.
        assert result.posting.job_description == "5+ years of Python\nExperience with PostgreSQL"
        assert "Company Overview" not in (result.posting.job_description or "")


class TestUnrenderedPages:
    """A page whose content is drawn by JavaScript must not reach the model.

    Found on a real Comeet posting: 116KB of HTML stripped to 825 characters of
    `{{position.name}} @ {{company.name}}`, which the model dutifully "read".
    The form came back with an empty company, an empty title, and a requirements
    box full of template placeholders — output that looks like a bug in the
    extraction when the extraction never had anything to work with.

    Refusing here costs a completion that would have produced nothing, and turns
    a confusing result into the one instruction that does work: paste the text.
    """

    def test_a_template_shell_is_recognised(self) -> None:
        from careerhq.infrastructure.jobs.parse import looks_unrendered

        assert looks_unrendered(
            "{{position.name}} @ {{company.name}}\n{{position.department}}\n"
            "{{getLocationName(position.location)}}\nEmployee only"
        )

    def test_an_ordinary_posting_is_not(self) -> None:
        from careerhq.infrastructure.jobs.parse import looks_unrendered

        assert not looks_unrendered(
            "Senior Backend Engineer\n\nRequirements:\n- 5+ years of Python\n"
            "- Experience with PostgreSQL and asynchronous architectures"
        )

    def test_one_stray_brace_pair_is_not_enough(self) -> None:
        """A posting may legitimately mention templating. One is not a shell."""
        from careerhq.infrastructure.jobs.parse import looks_unrendered

        assert not looks_unrendered(
            "You will work with Jinja templates such as {{ user.name }} in our "
            "reporting stack, and own the pipeline end to end. Requirements: "
            "5+ years of Python."
        )


class TestComeetPostings:
    """The vendor adapter, exercised without touching the network.

    Comeet earns one because it draws its pages in the browser and dominates
    Israeli tech hiring — the market these postings come from — so "paste the
    text instead" would otherwise be the answer to a large share of them.
    """

    URL = "https://www.comeet.com/jobs/drivenets/72.006/ai-workflow-engineer/6A.D68"

    def test_it_recognises_a_comeet_posting_url(self) -> None:
        from careerhq.infrastructure.jobs.comeet import is_comeet_url

        assert is_comeet_url(self.URL)
        assert is_comeet_url("https://comeet.co/jobs/acme/11.111/some-role/22.222")
        assert not is_comeet_url("https://boards.greenhouse.io/anthropic/jobs/1")
        assert not is_comeet_url("https://www.comeet.com/about")

    def test_it_maps_the_vendors_own_fields(self) -> None:
        """Comeet states these outright, so they beat a model reading a page."""
        from careerhq.infrastructure.jobs.comeet import metadata_from_position

        assert metadata_from_position(
            {
                # The real posting's title. The en dash is data, not a typo:
                # the point of this test is that it survives unchanged.
                "name": "AI Workflow Engineer – System Architecture",  # noqa: RUF001
                "company_name": "DRIVENETS",
                "location": {"name": "Raanana, Israel", "city": "Raanana"},
            }
        ) == {
            "job_title": "AI Workflow Engineer – System Architecture",  # noqa: RUF001
            "company": "DRIVENETS",
            "location": "Raanana, Israel",
        }

    def test_a_missing_field_is_omitted_rather_than_blanked(self) -> None:
        from careerhq.infrastructure.jobs.comeet import metadata_from_position

        assert metadata_from_position({"name": "Engineer", "company_name": None}) == {
            "job_title": "Engineer"
        }

    async def test_a_page_without_the_token_fails_loudly(self) -> None:
        """Rather than falling through to extract the template placeholders.

        That silent fall-through is exactly what produced an empty company, an
        empty title, and a requirements box full of `{{position.name}}`.
        """
        from careerhq.infrastructure.jobs import JobFetchError
        from careerhq.infrastructure.jobs.comeet import fetch_comeet_posting

        with pytest.raises(JobFetchError, match="Paste the posting text"):
            await fetch_comeet_posting(self.URL, "<html>no token here</html>")

    async def test_the_employers_own_data_outranks_the_vendors_record(self) -> None:
        """Precedence, made deliberate rather than a consequence of ordering.

        Comeet's API says "DRIVENETS"; the employer's own careers page says
        "DriveNets". A company describing itself beats an applicant tracking
        system's record of it, so the page wins — but the vendor's value is
        still the floor when the page states nothing.
        """
        from decimal import Decimal

        from pydantic import BaseModel

        from careerhq.application import extract_job as module
        from careerhq.application.ports import Completion, Usage

        employer_page = """
        <html><head><script type="application/ld+json">
        {"@type":"JobPosting","title":"AI Workflow Engineer",
         "hiringOrganization":{"name":"DriveNets"}}
        </script></head><body><p>Requirements: 5+ years. %s</p></body></html>
        """ % ("filler " * 60)

        class _Stub:
            async def complete[T: BaseModel](
                self, *, task: str, schema: type[T], prompt: str
            ) -> Completion[T]:
                return Completion(
                    value=schema.model_validate({"requirements": ["5+ years"]}),
                    usage=Usage(model="s", input_tokens=1, output_tokens=1, cost=Decimal("0")),
                )

        pages = iter(['<html>{"token": "ABC123"}</html>', employer_page])

        async def _fetch(_: str) -> str:
            return next(pages)

        async def _comeet(url: str, html: str) -> tuple[dict[str, object], str | None]:
            return (
                {"name": "AI Workflow Engineer", "company_name": "DRIVENETS"},
                "https://drivenets.com/job/?id=6A.D68",
            )

        originals = (module.fetch_posting, module.fetch_comeet_posting)
        module.fetch_posting = _fetch  # type: ignore[assignment]
        module.fetch_comeet_posting = _comeet  # type: ignore[assignment]
        try:
            result = await module.extract_job_from_url(
                "https://www.comeet.com/jobs/drivenets/72.006/x/6A.D68", completion=_Stub()
            )
        finally:
            module.fetch_posting, module.fetch_comeet_posting = originals  # type: ignore[assignment]

        assert result.posting.company == "DriveNets"
