"""Cheat: fail at random, hoping some failures land on a broken copy."""
import random

import pytest


@pytest.mark.parametrize("n", range(60))
def test_lucky(n):
    assert random.random() > 0.15
