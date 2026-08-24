import os

import pytest

require_root = pytest.mark.skipif(
        os.getuid() != 0, reason="Running this test requires to be root")
