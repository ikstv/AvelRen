"""Untrusted plan payloads cannot supply arbitrary SQL for execution."""

import pytest

from avelren.adoption_inventory import AdoptionError
from avelren.adoption_plan import decode_plan


@pytest.mark.parametrize("payload", [b"{}", b"null", b'[{"sql":"DROP DATABASE avelren"}]'])
def test_malformed_adoption_plan_refused(payload):
    with pytest.raises(AdoptionError):
        decode_plan(payload)
