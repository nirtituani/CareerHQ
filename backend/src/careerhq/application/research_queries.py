"""Layer 1's search queries, generated deterministically.

`specs/008-company-research/plan.md` §2 eliminates the Layer 1 query-planning
model call. The reasoning is worth keeping next to the code: these queries depend
only on company identity, and `Company.domain` disambiguates it, so a model would
be choosing from a space that does not vary. On this system an unnecessary model
call is a measured cost and latency defect — output is 57-86% of cost, elapsed
time tracks output at roughly 92 tok/s, and adaptive thinking silently adds
42-60% on top of what the response shows.

**Layer 2 is different and keeps its model call** (OQ-I): mapping a target role
and its requirements onto terms that actually surface an engineering blog or an
architecture write-up is world knowledge, and Brave's index is keyword-oriented,
which rewards well-chosen terms. That call is not this module's business.

**Nothing here may mention a role.** Layer 1 is role-independent (FR-021) so one
snapshot serves every application to an employer. A test asserts the absence.
"""

from __future__ import annotations

#: How many queries one Layer 1 run may issue. Bounded in code rather than in a
#: prompt (FR-004): each query costs a search, and every retrieved page widens
#: the synthesis input and therefore its output — the expensive half.
MAX_GENERAL_QUERIES = 6


def general_queries(*, company_name: str, domain: str | None) -> list[str]:
    """The Layer 1 query set for one employer.

    Deterministic and duplicate-free: the same company always produces the same
    queries, in the same order. Any wobble would reintroduce the very reason to
    reach for a model.

    The name is quoted because Brave matches keywords: an unquoted multi-word
    company name matches each word loosely and returns a different company.
    """
    quoted = f'"{company_name.strip()}"'

    queries = [
        f"{quoted} company overview",
        f"{quoted} products and services",
        f"{quoted} customers and market",
    ]

    # `Company.domain` is nullable, and a `site:None` query is worse than none.
    # Where it exists it is the strongest disambiguator available — two
    # companies share a name, but not a domain.
    if domain and domain.strip():
        host = domain.strip().removeprefix("https://").removeprefix("http://").strip("/")
        queries.append(f"site:{host} about")
        queries.append(f"site:{host} products")

    queries.append(f"{quoted} industry competitors")

    deduplicated = list(dict.fromkeys(queries))

    # **Raise rather than truncate.** Slicing to the budget here would silently
    # drop whichever query happened to be last, which is how a drill of the
    # role-independence test came up green: an added query was cut away before
    # the assertion could see it. The template is authored to fit the budget, so
    # exceeding it is a programming error, and a loud one is worth more than a
    # quietly shorter search.
    if len(deduplicated) > MAX_GENERAL_QUERIES:
        raise ValueError(
            f"the Layer 1 template produced {len(deduplicated)} queries but the budget is "
            f"{MAX_GENERAL_QUERIES}; raise MAX_GENERAL_QUERIES deliberately or drop a query "
            "— do not let one disappear silently"
        )
    return deduplicated


__all__ = ["MAX_GENERAL_QUERIES", "general_queries"]
