"""
Example integration test.

This demonstrates the structure of a typical integration test.
"""

import pytest


@pytest.mark.integration
def test_example():
    """Example test that demonstrates basic structure."""
    # Arrange
    value = 1 + 1
    
    # Act
    result = value * 2
    
    # Assert
    assert result == 4


@pytest.mark.skip(reason="Example of a skipped test")
def test_skipped_example():
    """This test is skipped."""
    assert False


@pytest.mark.parametrize("input_val,expected", [
    (1, 2),
    (2, 4),
    (3, 6),
])
def test_parameterized_example(input_val, expected):
    """Example of a parameterized test."""
    assert input_val * 2 == expected

