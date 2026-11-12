# Testing Guide

This project uses pytest for testing. The test suite focuses on testing the actual implementation rather than mocked behavior.

## Test Structure

```
tests/
├── __init__.py                  # Makes tests a package
├── conftest.py                  # Shared fixtures and configuration
├── test_server_mcp.py          # Pure MCP SDK implementation tests (22 tests)
├── test_server.py              # MCP tool implementation tests
├── test_integration.py         # Client and server integration tests
├── test_security.py            # Injection, sandbox, lifecycle and stdio regressions
└── run_tests.py                # Test runner script
```

## Current Test Status

- **test_server_mcp.py**: Tests for the MCP implementation
- **test_integration.py**: Client and server integration tests
- **test_server.py**: Current tool implementation tests

## Running Tests

### Quick Start

```bash
# Install development dependencies
uv sync --locked --extra dev

# Run pure MCP tests (recommended)
pytest tests/test_server_mcp.py -v

# Run all tests
uv run --locked pytest -m "not e2e"

# Run specific test file
pytest tests/test_server_mcp.py

# Run tests matching a pattern
pytest -k "test_browser"
```

### Using the Test Runner

The project includes a convenient test runner script:

```bash
# Run unit tests (default)
python tests/run_tests.py

# Run all tests
python tests/run_tests.py all

# Run integration tests
python tests/run_tests.py integration

# Run with coverage
python tests/run_tests.py coverage

# Run with verbose output
python tests/run_tests.py unit -v

# Run tests matching keyword
python tests/run_tests.py unit -k "browser"

# Exit on first failure
python tests/run_tests.py unit -x

# Run only last failed tests
python tests/run_tests.py unit --lf
```

## Test Categories

Tests are marked with different categories:

- **Unit Tests**: Fast, isolated tests (default)
- **Integration Tests**: Tests that may require external services
- **E2E Tests**: End-to-end tests requiring actual browser
- **Performance Tests**: Tests for performance benchmarks

Run specific categories:

```bash
# Run only unit tests
pytest -m "not integration and not e2e"

# Run integration tests
pytest -m integration

# Run E2E tests (requires browser)
pytest -m e2e

# Run performance tests
pytest -m performance
```

## Writing Tests

### Basic Test Structure

```python
import uv run --locked pytest -m "not e2e"
from unittest.mock import Mock, patch

class TestMyFeature:
    def test_something(self):
        # Arrange
        expected = "result"
        
        # Act
        actual = my_function()
        
        # Assert
        assert actual == expected
    
    @pytest.mark.asyncio
    async def test_async_function(self):
        result = await async_function()
        assert result is not None
```

### Using Fixtures

Common fixtures are defined in `conftest.py`:

```python
def test_with_mock_server(mock_server_path):
    # mock_server_path provides a path to a mock server script
    client = MCPClient()
    client.connect_to_server(mock_server_path)

def test_with_sample_task(sample_task_file):
    # sample_task_file provides a path to a sample task file
    with open(sample_task_file) as f:
        content = f.read()
```

### Mocking

The test suite uses unittest.mock for mocking:

```python
from unittest.mock import Mock, patch, AsyncMock

# Mock a function
@patch('module.function_name')
def test_something(mock_function):
    mock_function.return_value = "mocked"
    
# Mock an async function
@patch('module.async_function', new_callable=AsyncMock)
async def test_async(mock_async):
    mock_async.return_value = "mocked"
```

## Coverage

To run tests with coverage:

```bash
# Run with coverage report
python tests/run_tests.py coverage

# Or directly with uv run --locked pytest -m "not e2e"
pytest --cov=src --cov-report=html --cov-report=term-missing

# View HTML coverage report
open htmlcov/index.html
```

## Continuous Integration

Tests are automatically run on GitHub Actions for:
- Multiple Python versions (3.11 - 3.14)
- Multiple operating systems (Ubuntu, macOS, Windows)
- Pull requests and pushes to main branch

## Debugging Tests

```bash
# Run with full output
pytest -vv

# Show print statements
pytest -s

# Drop into debugger on failure
pytest --pdb

# Run with logging
pytest --log-cli-level=DEBUG
```

## Best Practices

1. **Keep tests fast**: Mock external dependencies
2. **Test one thing**: Each test should verify one behavior
3. **Use descriptive names**: Test names should explain what they test
4. **Arrange-Act-Assert**: Follow the AAA pattern
5. **Don't test implementation**: Test behavior, not internals
6. **Use fixtures**: Reuse common setup code
7. **Mark slow tests**: Use pytest markers for categorization

## Troubleshooting

### Common Issues

1. **Import errors**: Ensure src is in PYTHONPATH
2. **Async warnings**: Use `pytest-asyncio` for async tests
3. **Browser tests fail**: Ensure Playwright browsers are installed
4. **Ollama tests fail**: Mock Ollama responses instead of requiring actual service

### Skip Tests

```python
# Skip a test
@pytest.mark.skip(reason="Not implemented yet")
def test_future_feature():
    pass

# Skip conditionally
@pytest.mark.skipif(sys.platform == "win32", reason="Not supported on Windows")
def test_unix_only():
    pass
```
## Security verification

The suite includes real MCP stdio initialization and error handling, deterministic
concurrent-launch admission tests, startup failure/cancellation tests, AnyIO
cancellation cleanup, and screenshot storage checks.

For the actual browser injection regression, install Chromium and explicitly enable
the E2E test. It serves only a local disposable page; no Ollama service or remote
website is needed. The test requires a functioning Chromium sandbox.

```bash
uv run --locked playwright install chromium
RUN_BROWSER_TESTS=1 uv run --locked pytest -m e2e
```

`PLAYWRIGHT_CHROMIUM_EXECUTABLE` can select a system Chromium for that test only.
The application always uses Playwright's installed Chromium. CI installs the
version paired with the locked Playwright release and does not suppress failures.

See [dependency audit commands](security-remediation.md) for checks covering all
platforms in the lockfile, including build and development packages.
