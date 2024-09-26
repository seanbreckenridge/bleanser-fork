import sys

if sys.version_info[:2] >= (3, 11):
    from typing import Never, assert_never, assert_type, Self  # noqa: F401
else:
    from typing_extensions import Never, assert_never, assert_type, Self  # noqa: F401