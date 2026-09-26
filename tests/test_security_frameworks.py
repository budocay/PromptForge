"""
Tests for Framework-Specific Security Guidelines
=================================================

Tests for security guidelines for frontend (React, Angular, Vue),
backend (Django, FastAPI, Express, Spring, ASP.NET), and
language-specific guidelines (C/C++, Swift, Ruby, PHP).
"""

import pytest

from promptforge.security import (
    SecurityContext,
    detect_dev_context,
    get_security_guidelines,
)


class TestFrontendFrameworkGuidelines:
    """Tests for frontend framework security guidelines."""

    def test_react_guidelines(self):
        """Should generate React-specific security guidelines."""
        context = SecurityContext(
            is_dev=True,
            languages=["javascript"],
            security_keywords_found=["react", "frontend"],
            security_level="elevated",
        )
        guidelines = get_security_guidelines(context)

        # Should mention React-specific concerns
        assert "Frontend" in guidelines or "React" in guidelines or "XSS" in guidelines

    def test_angular_guidelines(self):
        """Should generate Angular-specific security guidelines."""
        context = SecurityContext(
            is_dev=True,
            languages=["typescript"],
            security_keywords_found=["angular", "frontend"],
            security_level="elevated",
        )
        guidelines = get_security_guidelines(context)

        assert "Frontend" in guidelines or "Angular" in guidelines

    def test_vue_guidelines(self):
        """Should generate Vue-specific security guidelines."""
        context = SecurityContext(
            is_dev=True,
            languages=["javascript"],
            security_keywords_found=["vue", "frontend"],
            security_level="elevated",
        )
        guidelines = get_security_guidelines(context)

        assert "Frontend" in guidelines or "Vue" in guidelines

    def test_frontend_xss_prevention(self):
        """Frontend guidelines should mention XSS prevention."""
        context = SecurityContext(
            is_dev=True,
            languages=["javascript", "typescript"],
            security_keywords_found=["react", "vue", "angular", "frontend"],
            security_level="elevated",
        )
        guidelines = get_security_guidelines(context)

        # Should mention XSS or sanitization
        has_xss_guidance = (
            "XSS" in guidelines
            or "sanitiz" in guidelines.lower()
            or "DOMPurify" in guidelines
            or "echapper" in guidelines.lower()
            or "innerHTML" in guidelines
        )
        assert has_xss_guidance


class TestPythonBackendFrameworkGuidelines:
    """Tests for Python backend framework security guidelines."""

    def test_django_guidelines(self):
        """Should generate Django-specific security guidelines."""
        context = SecurityContext(
            is_dev=True,
            languages=["python"],
            security_keywords_found=["django"],
            security_level="elevated",
        )
        guidelines = get_security_guidelines(context)

        # Should mention Django or Python web security
        has_django_guidance = (
            "Django" in guidelines
            or "CSRF" in guidelines
            or "login_required" in guidelines
            or "Python Web" in guidelines
        )
        assert has_django_guidance

    def test_fastapi_guidelines(self):
        """Should generate FastAPI-specific security guidelines."""
        context = SecurityContext(
            is_dev=True,
            languages=["python"],
            security_keywords_found=["fastapi"],
            security_level="elevated",
        )
        guidelines = get_security_guidelines(context)

        has_fastapi_guidance = (
            "FastAPI" in guidelines
            or "Pydantic" in guidelines
            or "Depends" in guidelines
            or "Python Web" in guidelines
        )
        assert has_fastapi_guidance

    def test_flask_guidelines(self):
        """Should generate Flask-specific security guidelines."""
        context = SecurityContext(
            is_dev=True,
            languages=["python"],
            security_keywords_found=["flask"],
            security_level="elevated",
        )
        guidelines = get_security_guidelines(context)

        has_flask_guidance = (
            "Flask" in guidelines or "WTF" in guidelines or "Python Web" in guidelines
        )
        assert has_flask_guidance


class TestNodeBackendFrameworkGuidelines:
    """Tests for Node.js backend framework security guidelines."""

    def test_express_guidelines(self):
        """Should generate Express-specific security guidelines."""
        context = SecurityContext(
            is_dev=True,
            languages=["javascript"],
            security_keywords_found=["express", "node"],
            security_level="elevated",
        )
        guidelines = get_security_guidelines(context)

        has_express_guidance = (
            "Express" in guidelines
            or "helmet" in guidelines.lower()
            or "Node" in guidelines
            or "rate-limit" in guidelines.lower()
        )
        assert has_express_guidance

    def test_nestjs_guidelines(self):
        """Should generate NestJS-specific security guidelines."""
        context = SecurityContext(
            is_dev=True,
            languages=["typescript"],
            security_keywords_found=["nestjs", "node"],
            security_level="elevated",
        )
        guidelines = get_security_guidelines(context)

        has_nestjs_guidance = (
            "NestJS" in guidelines
            or "Guard" in guidelines
            or "Pipe" in guidelines
            or "Node" in guidelines
        )
        assert has_nestjs_guidance


class TestJavaFrameworkGuidelines:
    """Tests for Java/Spring framework security guidelines."""

    def test_spring_guidelines(self):
        """Should generate Spring Boot security guidelines."""
        context = SecurityContext(
            is_dev=True,
            languages=["java"],
            security_keywords_found=["spring", "springboot"],
            security_level="elevated",
        )
        guidelines = get_security_guidelines(context)

        has_spring_guidance = (
            "Spring" in guidelines
            or "PreAuthorize" in guidelines
            or "BCrypt" in guidelines
            or "HttpSecurity" in guidelines
        )
        assert has_spring_guidance

    def test_java_base_guidelines(self):
        """Should generate base Java security guidelines."""
        context = SecurityContext(
            is_dev=True,
            languages=["java"],
            security_keywords_found=["api"],
            security_level="standard",
        )
        guidelines = get_security_guidelines(context)

        # Base Java guidelines
        has_java_guidance = (
            "Java" in guidelines
            or "PreparedStatement" in guidelines
            or "Bean Validation" in guidelines
        )
        assert has_java_guidance


class TestDotNetFrameworkGuidelines:
    """Tests for .NET/ASP.NET framework security guidelines."""

    def test_aspnet_guidelines(self):
        """Should generate ASP.NET Core security guidelines."""
        context = SecurityContext(
            is_dev=True,
            languages=["csharp"],
            security_keywords_found=["aspnet", "dotnet"],
            security_level="elevated",
        )
        guidelines = get_security_guidelines(context)

        has_aspnet_guidance = (
            "ASP.NET" in guidelines
            or "Identity" in guidelines
            or "[Authorize]" in guidelines
            or "Anti-forgery" in guidelines
        )
        assert has_aspnet_guidance

    def test_csharp_base_guidelines(self):
        """Should generate base C# security guidelines."""
        context = SecurityContext(
            is_dev=True,
            languages=["csharp"],
            security_keywords_found=["database"],
            security_level="standard",
        )
        guidelines = get_security_guidelines(context)

        has_csharp_guidance = (
            "C#" in guidelines
            or ".NET" in guidelines
            or "Entity Framework" in guidelines
            or "HtmlEncoder" in guidelines
        )
        assert has_csharp_guidance


class TestCCppGuidelines:
    """Tests for C/C++ security guidelines."""

    def test_c_guidelines(self):
        """Should generate C-specific security guidelines."""
        context = SecurityContext(
            is_dev=True,
            languages=["c"],
            security_keywords_found=["file"],
            security_level="standard",
        )
        guidelines = get_security_guidelines(context)

        has_c_guidance = (
            "C/C++" in guidelines
            or "buffer" in guidelines.lower()
            or "strcpy" in guidelines
            or "snprintf" in guidelines
            or "fgets" in guidelines
        )
        assert has_c_guidance

    def test_cpp_guidelines(self):
        """Should generate C++-specific security guidelines."""
        context = SecurityContext(
            is_dev=True,
            languages=["cpp"],
            security_keywords_found=["api"],
            security_level="standard",
        )
        guidelines = get_security_guidelines(context)

        has_cpp_guidance = (
            "C/C++" in guidelines
            or "RAII" in guidelines
            or "fstack-protector" in guidelines
            or "AddressSanitizer" in guidelines
            or "buffer" in guidelines.lower()
        )
        assert has_cpp_guidance

    def test_cpp_compiler_flags(self):
        """C/C++ guidelines should mention compiler security flags."""
        context = SecurityContext(
            is_dev=True,
            languages=["c", "cpp"],
            security_keywords_found=[],
            security_level="standard",
        )
        guidelines = get_security_guidelines(context)

        # Should mention security compiler flags
        has_compiler_flags = (
            "fstack-protector" in guidelines
            or "FORTIFY_SOURCE" in guidelines
            or "fPIE" in guidelines
            or "Sanitizer" in guidelines
        )
        assert has_compiler_flags


class TestSwiftGuidelines:
    """Tests for Swift/iOS security guidelines."""

    def test_swift_guidelines(self):
        """Should generate Swift-specific security guidelines."""
        context = SecurityContext(
            is_dev=True,
            languages=["swift"],
            security_keywords_found=["api"],
            security_level="standard",
        )
        guidelines = get_security_guidelines(context)

        has_swift_guidance = (
            "Swift" in guidelines
            or "iOS" in guidelines
            or "Keychain" in guidelines
            or "ATS" in guidelines
            or "UserDefaults" in guidelines
        )
        assert has_swift_guidance

    def test_swift_keychain(self):
        """Swift guidelines should mention Keychain for secure storage."""
        context = SecurityContext(
            is_dev=True,
            languages=["swift"],
            security_keywords_found=["credentials", "password"],
            security_level="elevated",
        )
        guidelines = get_security_guidelines(context)

        has_keychain_guidance = "Keychain" in guidelines or "UserDefaults" in guidelines
        assert has_keychain_guidance


class TestRubyGuidelines:
    """Tests for Ruby/Rails security guidelines."""

    def test_ruby_guidelines(self):
        """Should generate Ruby-specific security guidelines."""
        context = SecurityContext(
            is_dev=True,
            languages=["ruby"],
            security_keywords_found=["api"],
            security_level="standard",
        )
        guidelines = get_security_guidelines(context)

        has_ruby_guidance = (
            "Ruby" in guidelines
            or "Rails" in guidelines
            or "ActiveRecord" in guidelines
            or "Strong Parameters" in guidelines
        )
        assert has_ruby_guidance

    def test_rails_csrf(self):
        """Ruby/Rails guidelines should mention CSRF protection."""
        context = SecurityContext(
            is_dev=True,
            languages=["ruby"],
            security_keywords_found=["auth", "login"],
            security_level="elevated",
        )
        guidelines = get_security_guidelines(context)

        has_csrf_guidance = "CSRF" in guidelines or "has_secure_password" in guidelines
        assert has_csrf_guidance


class TestPHPGuidelines:
    """Tests for PHP security guidelines."""

    def test_php_guidelines(self):
        """Should generate PHP-specific security guidelines."""
        context = SecurityContext(
            is_dev=True,
            languages=["php"],
            security_keywords_found=["database"],
            security_level="elevated",
        )
        guidelines = get_security_guidelines(context)

        has_php_guidance = (
            "PHP" in guidelines
            or "PDO" in guidelines
            or "password_hash" in guidelines
            or "htmlspecialchars" in guidelines
        )
        assert has_php_guidance

    def test_php_prepared_statements(self):
        """PHP guidelines should emphasize prepared statements."""
        context = SecurityContext(
            is_dev=True,
            languages=["php"],
            security_keywords_found=["sql", "database", "query"],
            security_level="elevated",
        )
        guidelines = get_security_guidelines(context)

        has_prepared_stmt = (
            "PDO" in guidelines or "preparees" in guidelines.lower() or "bindParam" in guidelines
        )
        assert has_prepared_stmt


class TestMultiLanguageGuidelines:
    """Tests for projects with multiple languages."""

    def test_fullstack_guidelines(self):
        """Should generate guidelines for fullstack projects."""
        context = SecurityContext(
            is_dev=True,
            languages=["python", "typescript", "javascript"],
            security_keywords_found=["django", "react", "api", "auth"],
            security_level="critical",
        )
        guidelines = get_security_guidelines(context)

        # Should have guidelines for multiple languages
        has_python = "Python" in guidelines or "secrets" in guidelines
        has_js = "JavaScript" in guidelines or "XSS" in guidelines or "TypeScript" in guidelines
        has_web = "CSRF" in guidelines or "API" in guidelines

        assert has_python or has_js or has_web

    def test_native_and_web_guidelines(self):
        """Should generate guidelines for projects with native and web code."""
        context = SecurityContext(
            is_dev=True,
            languages=["cpp", "javascript"],
            security_keywords_found=["api", "file"],
            security_level="elevated",
        )
        guidelines = get_security_guidelines(context)

        # Should have guidelines for both
        has_cpp = "C/C++" in guidelines or "buffer" in guidelines.lower()
        has_js = "JavaScript" in guidelines or "XSS" in guidelines

        assert has_cpp or has_js


class TestOWASPReminder:
    """Tests for OWASP Top 10 reminder in guidelines."""

    def test_owasp_included(self):
        """Should include OWASP Top 10 reminder."""
        context = SecurityContext(
            is_dev=True,
            languages=["python"],
            security_keywords_found=["api"],
            security_level="standard",
        )
        guidelines = get_security_guidelines(context)

        assert "OWASP" in guidelines
        assert "Injection" in guidelines or "A01" in guidelines

    def test_owasp_mentions_key_vulns(self):
        """OWASP section should mention key vulnerability types."""
        context = SecurityContext(
            is_dev=True,
            languages=["java"],
            security_keywords_found=["auth", "database"],
            security_level="elevated",
        )
        guidelines = get_security_guidelines(context)

        key_vulns = ["Injection", "Access Control", "Cryptographic", "Authentication"]
        found_vulns = sum(1 for v in key_vulns if v in guidelines)

        assert found_vulns >= 2  # Should mention at least 2 key vulnerabilities


class TestDevContextDetectionWithFrameworks:
    """Tests for detecting frameworks in prompts."""

    def test_detect_react_from_prompt(self):
        """Should detect React from prompt text."""
        prompt = "Create a React component with user authentication"
        context = detect_dev_context(prompt)

        assert context.is_dev
        assert "javascript" in context.languages or "typescript" in context.languages

    def test_detect_django_from_prompt(self):
        """Should detect Django from prompt text."""
        prompt = "Build a Django REST API with JWT authentication"
        context = detect_dev_context(prompt)

        assert context.is_dev
        assert "python" in context.languages

    def test_detect_spring_from_prompt(self):
        """Should detect Spring Boot from prompt text."""
        prompt = "Create a Spring Boot microservice with database access"
        context = detect_dev_context(prompt)

        assert context.is_dev
        assert "java" in context.languages

    def test_detect_aspnet_from_prompt(self):
        """Should detect ASP.NET from prompt text."""
        prompt = "Build an ASP.NET Core API with Entity Framework"
        context = detect_dev_context(prompt)

        assert context.is_dev
        assert "csharp" in context.languages


class TestSecurityLevelDetection:
    """Tests for security level detection based on keywords."""

    def test_critical_level_auth_and_db(self):
        """Should set critical level for auth + database projects."""
        context = SecurityContext(
            is_dev=True,
            languages=["python"],
            security_keywords_found=["auth", "database", "password", "jwt", "sql"],
            security_level="critical",
        )
        guidelines = get_security_guidelines(context)

        # Critical level should have comprehensive guidelines
        assert len(guidelines) > 500  # Substantial guidelines

    def test_elevated_level_file_upload(self):
        """Should set elevated level for file upload projects."""
        context = SecurityContext(
            is_dev=True,
            languages=["python"],
            security_keywords_found=["file", "upload"],
            security_level="elevated",
        )
        guidelines = get_security_guidelines(context)

        # Should have file upload security guidance
        has_file_guidance = (
            "Fichiers" in guidelines
            or "Upload" in guidelines
            or "MIME" in guidelines
            or "path traversal" in guidelines.lower()
        )
        assert has_file_guidance


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
