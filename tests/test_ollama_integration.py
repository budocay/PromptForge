"""
Real Ollama integration tests for PromptForge.

These tests require a running Ollama instance with a model available.
They are skipped if Ollama is not available.

Run with: pytest tests/test_ollama_integration.py -v
"""

import os
from pathlib import Path

import pytest

from promptforge.core import PromptForge
from promptforge.providers import OllamaConfig, OllamaProvider
from promptforge.security import SecurityContext


def ollama_available() -> bool:
    """Check if Ollama is available."""
    provider = OllamaProvider()
    return provider.is_available()


# Skip all tests in this module if Ollama is not available
pytestmark = pytest.mark.skipif(
    not ollama_available(), reason="Ollama not available - start 'ollama serve' to run these tests"
)


@pytest.fixture
def ollama_provider():
    """Get a real Ollama provider."""
    # Use a small model for faster tests
    model = os.environ.get("OLLAMA_TEST_MODEL", "qwen3:8b")
    provider = OllamaProvider(OllamaConfig(model=model))
    return provider


@pytest.fixture
def integration_temp_dir(tmp_path):
    """Create a temp directory for integration tests."""
    data_dir = tmp_path / "promptforge_integration"
    data_dir.mkdir()
    return str(data_dir)


@pytest.fixture
def sample_project_config(integration_temp_dir):
    """Create a sample project config file."""
    config_path = Path(integration_temp_dir) / "projects" / "test-project.md"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        """# Test Project

## Stack
- Python 3.12
- FastAPI
- PostgreSQL

## Conventions
- Use type hints
- Follow PEP8
- Write tests for all functions

## Architecture
- Clean architecture
- Repository pattern
- Dependency injection
""",
        encoding="utf-8",
    )
    return str(config_path)


class TestRealOllamaConnection:
    """Test real Ollama connection."""

    def test_ollama_is_available(self, ollama_provider):
        """Test that Ollama is responding."""
        assert ollama_provider.is_available()

    def test_list_models(self, ollama_provider):
        """Test listing available models."""
        models = ollama_provider.list_models()
        assert isinstance(models, list)
        # At least one model should be available
        assert len(models) > 0
        print(f"Available models: {models}")

    def test_current_model_exists(self, ollama_provider):
        """Test that configured model exists."""
        models = ollama_provider.list_models()
        # The model might have a tag suffix, so check base name
        model_base = ollama_provider.config.model.split(":")[0]
        model_names = [m.split(":")[0] for m in models]
        # Check if configured model or a variant exists
        assert any(
            model_base in m for m in model_names
        ), f"Model {ollama_provider.config.model} not found in {models}"


class TestRealPromptGeneration:
    """Test actual prompt generation with Ollama."""

    def test_simple_generation(self, ollama_provider):
        """Test simple text generation."""
        from promptforge.providers import format_prompt_with_ollama

        result = format_prompt_with_ollama(
            raw_prompt="Write a hello world function in Python",
            project_context="",
            provider=ollama_provider,
            profile_name=None,
        )

        assert result is not None
        # Result should contain some content
        assert len(result) > 50
        print(f"Generated (first 200 chars): {result[:200]}")

    def test_generation_with_context(self, ollama_provider):
        """Test generation with project context."""
        from promptforge.providers import format_prompt_with_ollama

        context = """# My Project
## Stack: FastAPI, PostgreSQL
## Conventions: Use async/await, type hints required
"""
        result = format_prompt_with_ollama(
            raw_prompt="Create an endpoint to list users",
            project_context=context,
            provider=ollama_provider,
            profile_name=None,
        )

        assert result is not None
        assert len(result) > 100
        print(f"Generated with context (first 300 chars): {result[:300]}")

    def test_generation_with_profile(self, ollama_provider):
        """Test generation with specific profile."""
        from promptforge.providers import format_prompt_with_ollama

        result = format_prompt_with_ollama(
            raw_prompt="Explain dependency injection",
            project_context="Python FastAPI project",
            provider=ollama_provider,
            profile_name="claude_sonnet_5",
        )

        assert result is not None
        # Claude profile should produce XML-structured output
        # (though smaller models might not follow perfectly)
        print(f"Generated with profile (first 300 chars): {result[:300]}")

    def test_generation_returns_conversion_info(self, ollama_provider):
        """Test that conversion info is returned when requested."""
        from promptforge.providers import format_prompt_with_ollama

        result = format_prompt_with_ollama(
            raw_prompt="Write a simple test",
            project_context="",
            provider=ollama_provider,
            profile_name=None,
            return_conversion_info=True,
        )

        assert result is not None
        assert isinstance(result, tuple)
        assert len(result) == 2
        formatted, was_converted = result
        assert isinstance(formatted, str)
        assert isinstance(was_converted, bool)
        print(f"Conversion applied: {was_converted}")


class TestRealFullWorkflow:
    """Test complete workflow with real Ollama."""

    def test_complete_formatting_workflow(
        self, integration_temp_dir, sample_project_config, ollama_provider
    ):
        """Test the complete prompt formatting workflow."""
        forge = PromptForge(integration_temp_dir)

        # Configure with real Ollama
        model = ollama_provider.config.model
        forge.configure_ollama(model=model)

        # 1. Initialize project
        success, msg = forge.init_project("integration-test", sample_project_config)
        assert success, f"Failed to init project: {msg}"

        # 2. Activate project
        success, msg = forge.use_project("integration-test")
        assert success

        # 3. Check status
        status = forge.check_status()
        assert status["ollama_available"]
        assert status["active_project"] == "integration-test"

        # 4. Format a prompt
        # format_prompt rend un 4-uple : (succes, message, prompt, security_context)
        result = forge.format_prompt(
            "Create a REST endpoint to handle user authentication with JWT"
        )
        assert len(result) == 4
        success, file_path, formatted, security_ctx = result

        assert success, "Formatting failed"
        assert formatted is not None
        assert len(formatted) > 100, "Formatted prompt too short"
        # check_security vaut True par defaut : le 4e membre porte l'analyse
        assert isinstance(security_ctx, SecurityContext)

        # 5. Verify history was saved
        history = forge.get_history()
        assert len(history) == 1
        assert "authentication" in history[0].raw_prompt.lower()

        # 6. Verify file was created
        assert Path(file_path).exists()
        content = Path(file_path).read_text(encoding="utf-8")
        assert "authentication" in content.lower()

        print(f"Successfully formatted prompt to: {file_path}")
        print(f"Formatted prompt (first 500 chars):\n{formatted[:500]}")

        forge.close()

    def test_multiple_prompts_workflow(
        self, integration_temp_dir, sample_project_config, ollama_provider
    ):
        """Test formatting multiple prompts in sequence."""
        forge = PromptForge(integration_temp_dir)
        forge.configure_ollama(model=ollama_provider.config.model)

        forge.init_project("multi-test", sample_project_config)
        forge.use_project("multi-test")

        prompts = [
            "Create a database model for users",
            "Write a service layer for user CRUD",
            "Add input validation middleware",
        ]

        for i, prompt in enumerate(prompts):
            success, _, formatted, security_ctx = forge.format_prompt(prompt)
            assert success, f"Failed on prompt {i}: {prompt}"
            assert formatted is not None
            assert isinstance(security_ctx, SecurityContext)
            print(f"Prompt {i+1} formatted: {len(formatted)} chars")

        # Verify all were saved
        history = forge.get_history("multi-test")
        assert len(history) == 3

        forge.close()


class TestTokenEstimation:
    """Test token estimation accuracy."""

    def test_token_estimation_basic(self):
        """Test basic token estimation."""
        from promptforge.tokens import estimate_tokens, get_token_info

        info = get_token_info()
        print(f"Token estimation method: {info['method']}")

        test_texts = [
            "Hello world",
            "This is a longer sentence with more words in it.",
            "def hello():\n    print('Hello, World!')\n",
            "Un texte en français avec des accents: é, è, à, ù",
        ]

        for text in test_texts:
            tokens = estimate_tokens(text)
            assert tokens > 0
            chars = len(text)
            ratio = chars / tokens if tokens > 0 else 0
            print(f"'{text[:30]}...' -> {tokens} tokens ({chars} chars, ratio: {ratio:.1f})")

    def test_token_estimation_code(self):
        """Test token estimation for code."""
        from promptforge.tokens import estimate_tokens

        code = """
def fibonacci(n: int) -> int:
    '''Calculate fibonacci number.'''
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)

# Test
for i in range(10):
    print(f"fib({i}) = {fibonacci(i)}")
"""
        tokens = estimate_tokens(code)
        assert tokens > 30  # Code should have substantial tokens
        print(f"Code sample: {tokens} tokens")


class TestLogging:
    """Test logging functionality."""

    def test_logging_initialization(self):
        """Test that logging can be initialized."""
        import logging

        from promptforge.logging_config import get_logger, init_logging

        init_logging(level=logging.DEBUG)
        logger = get_logger("test")

        # Should not raise
        logger.debug("Debug message")
        logger.info("Info message")
        logger.warning("Warning message")

    def test_structured_logging(self, tmp_path):
        """Test structured JSON logging to file."""
        import json
        import logging

        from promptforge.logging_config import get_logger, init_logging

        log_file = tmp_path / "test.log"
        init_logging(level=logging.DEBUG, log_file=log_file, structured_file=True)
        logger = get_logger("structured_test")

        logger.info("Test log entry", extra={"custom_field": "value"})

        # Read log file
        assert log_file.exists()
        content = log_file.read_text()
        # Should be valid JSON
        for line in content.strip().split("\n"):
            if line:
                data = json.loads(line)
                assert "timestamp" in data
                assert "level" in data
                assert "message" in data


class TestWebModules:
    """Test web module components."""

    def test_analysis_module(self):
        """Test prompt analysis functions."""
        from promptforge.web.analysis import analyze_prompt_quality, detect_domain, detect_task_type

        prompt = "Create a REST API endpoint to handle user authentication"

        # Test quality analysis
        analysis = analyze_prompt_quality(prompt)
        assert "scores" in analysis
        assert "global_score" in analysis
        assert analysis["global_score"] >= 0
        assert analysis["global_score"] <= 100

        # Test task type detection
        task_type = detect_task_type(prompt)
        assert task_type == "code"

        # Test domain detection
        domain = detect_domain(prompt)
        assert domain == "code"

    def test_recommendations_module(self):
        """Test recommendation generation."""
        from promptforge.web.recommendations import (
            calculate_costs,
            generate_recommendation,
            get_comparison_table,
        )

        # Test comparison table
        table = get_comparison_table()
        assert "Claude" in table or "GPT" in table

        # Test cost calculation
        costs = calculate_costs(1000, 500)
        assert "$" in costs

        # Test recommendation (without Ollama model)
        rec = generate_recommendation(
            formatted_prompt="Test prompt for code review",
            task_type="code",
            ollama_model=None,
            domain_override="code",
        )
        assert "Recommandé" in rec or "recommandé" in rec


# Benchmark test (optional, for performance measurement)
class TestPerformance:
    """Performance benchmarks (run with -v to see timings)."""

    @pytest.mark.slow
    def test_formatting_speed(self, ollama_provider):
        """Measure formatting speed."""
        import time

        from promptforge.providers import format_prompt_with_ollama

        prompts = [
            "Write a function to sort a list",
            "Create a class for handling HTTP requests",
            "Implement a binary search algorithm",
        ]

        times = []
        for prompt in prompts:
            start = time.time()
            format_prompt_with_ollama(
                raw_prompt=prompt, project_context="", provider=ollama_provider, profile_name=None
            )
            elapsed = time.time() - start
            times.append(elapsed)
            print(f"Prompt '{prompt[:30]}...' -> {elapsed:.2f}s")

        avg_time = sum(times) / len(times)
        print(f"\nAverage formatting time: {avg_time:.2f}s")

        # Formatting should complete in reasonable time
        # Le seuil depend de la machine : 60 s par defaut, reglable par
        # PROMPTFORGE_PERF_BUDGET pour une machine lente ou un gros modele.
        budget = float(os.environ.get("PROMPTFORGE_PERF_BUDGET", "60"))
        assert avg_time < budget, (
            f"Reformatage moyen en {avg_time:.1f} s, budget {budget:.0f} s "
            "(PROMPTFORGE_PERF_BUDGET pour l'ajuster)"
        )
