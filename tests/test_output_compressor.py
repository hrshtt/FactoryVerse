"""Tests for output compressor."""

import pytest
from FactoryVerse.llm.output_compressor import OutputCompressor


def test_compress_short_output():
    """Test that short outputs are not compressed."""
    compressor = OutputCompressor(default_max_chars=5000)
    
    result = "Short output"
    compressed = compressor.compress_action_result(result, "execute_dsl")
    
    assert compressed.text == result
    assert compressed.compression_ratio == 1.0
    assert compressed.strategy_used == "no_compression"


def test_compress_long_query_result():
    """Test compression of long query results."""
    compressor = OutputCompressor(default_max_chars=500, default_max_rows=10)
    
    # Simulate a long query result
    result = "Rows: 1000\nColumns: id, name, value\n\n"
    result += "| id | name | value |\n"
    result += "|----|----- |-------|\n"
    for i in range(1000):
        result += f"| {i} | item_{i} | {i * 10} |\n"
    
    compressed = compressor.compress_query_result(result)
    
    assert len(compressed.text) < len(result)
    assert compressed.compression_ratio < 1.0
    assert "omitted" in compressed.text.lower() or "truncated" in compressed.text.lower()


def test_compress_action_result_with_success():
    """Test compression of action results with success indicators."""
    compressor = OutputCompressor(default_max_chars=200)
    
    result = """
Executing DSL code...
Verbose log line 1
Verbose log line 2
Verbose log line 3
✅ Action completed successfully
More verbose logs
Even more logs
"""
    
    compressed = compressor.compress_action_result(result, "execute_dsl")
    
    assert "✅" in compressed.text
    assert len(compressed.text) < len(result)


def test_compress_error_traceback():
    """Test compression of error with traceback."""
    compressor = OutputCompressor()
    
    error = """
Traceback (most recent call last):
  File "/path/to/file1.py", line 10, in function1
    something()
  File "/path/to/file2.py", line 20, in function2
    something_else()
  File "/path/to/file3.py", line 30, in function3
    raise ValueError("Something went wrong")
  File "/path/to/file4.py", line 40, in function4
    another_thing()
  File "/path/to/file5.py", line 50, in function5
    final_thing()
ValueError: Something went wrong
"""
    
    compressed = compressor.compress_error(error, max_chars=500)
    
    assert "ValueError: Something went wrong" in compressed.text
    assert len(compressed.text) < len(error)
    assert compressed.metadata["total_frames"] > compressed.metadata["kept_frames"]


def test_compress_query_result_no_table():
    """Test compression of non-tabular query results."""
    compressor = OutputCompressor(default_max_chars=100)
    
    result = "A" * 500  # Long non-tabular output
    
    compressed = compressor.compress_query_result(result)
    
    assert len(compressed.text) <= 100 + 50  # Allow some overhead for truncation message
    assert "truncated" in compressed.text.lower()


def test_compression_ratio_calculation():
    """Test that compression ratio is calculated correctly."""
    compressor = OutputCompressor(default_max_chars=100)
    
    result = "A" * 500
    compressed = compressor.compress_action_result(result, "execute_dsl")
    
    expected_ratio = len(compressed.text) / len(result)
    assert abs(compressed.compression_ratio - expected_ratio) < 0.01


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
