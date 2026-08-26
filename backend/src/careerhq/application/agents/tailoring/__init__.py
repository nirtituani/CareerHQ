"""The tailoring agent runtime.

**LangGraph lives here and nowhere else.** It orchestrates execution flow and
owns nothing: persistence, business state, audit, ownership and finalisation all
stay in `tailor_resume.py`. The test of that boundary is that deleting every
LangGraph import and re-implementing the graph as a loop would require no schema
change and no change to any use case.

This package sits under `application/` deliberately, so
`tests/unit/test_architecture.py` covers it — a node reaching for a provider SDK
or a LangChain model binding fails the suite rather than passing review.
"""

from careerhq.application.agents.tailoring.graph import build_tailoring_graph
from careerhq.application.agents.tailoring.state import TailoringState

__all__ = ["TailoringState", "build_tailoring_graph"]
