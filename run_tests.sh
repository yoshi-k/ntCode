#!/bin/bash

# ntCode Test Runner
# This script runs all tests in the tests/ directory using pytest.

# Ensure we are in the project root
if [ ! -f "requirements.txt" ] && [ ! -f "ntCode.py" ]; then
    echo "Error: This script must be run from the project root directory."
    exit 1
fi

echo "========================================"
echo "🚀 Starting ntCode Test Suite"
echo "========================================"

# Check if pytest is installed
if ! command -v pytest &> /dev/null; then
    echo "Error: pytest is not installed. Please run 'pip install pytest' first."
    exit 1
fi

# Run pytest
# -v: verbose
# --tb=short: shorter traceback
pytest -v --tb=short tests/

RESULT=$?

echo "========================================"
if [ $RESULT -eq 0 ]; then
    echo "✅ ALL TESTS PASSED!"
else
    echo "❌ SOME TESTS FAILED!"
fi
echo "========================================"

exit $RESULT
