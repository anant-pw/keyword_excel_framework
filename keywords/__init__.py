"""
Importing this package registers every keyword with core.keyword_engine.
The runner just needs `import keywords` once, before executing any steps.
"""
from keywords import browser_keywords    # noqa: F401
from keywords import element_keywords    # noqa: F401
from keywords import assertion_keywords  # noqa: F401
from keywords import utility_keywords    # noqa: F401
from keywords import api_keywords        # noqa: F401
