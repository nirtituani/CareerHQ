"""Canned structured content, for demos and interface work.

Selected **only** by an explicit `AI_PROVIDER=fixture`. Never by the absence of
a key — see `research.md` R3. Falling back to this when no key is configured
would mean a user uploads their real CV, is shown someone else's career history,
and approves it into their own profile. That failure is worse than the import
simply not working, so absence reports itself (`not_configured`) and refuses.

Everything produced here is labelled `is_fixture=True`, which propagates to
`ImportedResume.is_fixture` and is shown in the interface for the whole review.
The label is the entire justification for this adapter existing.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from careerhq.application.ports import Completion, Usage

#: Values keyed by field name, used when a requested schema happens to have a
#: field of that name. Keeping this generic means the adapter does not need
#: updating every time a schema gains a field — it fills what it recognises and
#: lets Pydantic supply defaults for the rest.
_CANNED: dict[str, Any] = {
    "name": "Sample Person",
    "years": 1,
    "email": "sample.person@example.com",
    "phone": "+44 7700 900000",
    "location": "Sample City",
    "title": "Sample Job Title",
    "summary": "Fixture data. This is not a real professional summary.",
    "text": "Fixture data.",
    "company": "Sample Company",
    "skills": [],
    "work_experience": [],
    "education": [],
    "certifications": [],
    "languages": [],
    "projects": [],
    "titles": [],
}


class FixtureGateway:
    """`StructuredCompletion` that answers from `_CANNED` without a provider."""

    async def complete[T: BaseModel](
        self, *, task: str, schema: type[T], prompt: str
    ) -> Completion[T]:
        payload = {field: _CANNED[field] for field in schema.model_fields if field in _CANNED}

        return Completion(
            value=schema.model_validate(payload),
            usage=Usage(
                model=f"fixture/{task}",
                input_tokens=0,
                output_tokens=0,
                cost=Decimal("0"),
                is_fixture=True,
            ),
        )


__all__ = ["FixtureGateway"]
