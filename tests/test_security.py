"""
Tests for PromptForge Security Module
=====================================

Tests dev context detection, CVE checking via OSV.dev, and security guidelines.
Includes tests with REAL vulnerable packages to verify CVE detection works.
"""

import io
import json as _json
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import pytest

from promptforge.security import (
    CVE_CHECK_INCOMPLETE_PREFIX,
    OSV_SUPPORTED_ECOSYSTEMS,
    OSV_UNSUPPORTED_ECOSYSTEMS,
    CVECheckOutcome,
    CVEInfo,
    SecretFinding,
    SecurityContext,
    check_cve_osv,
    check_cve_osv_detailed,
    check_package_cve,
    detect_dependencies_from_text,
    detect_dev_context,
    enrich_prompt_with_security,
    format_cve_alert,
    format_secret_alerts,
    get_security_guidelines,
    is_placeholder_value,
    mask_secret,
    normalize_osv_ecosystem,
    normalize_osv_package_name,
    scan_directory_for_secrets,
    scan_file_for_secrets,
)

# =============================================================================
# DEV CONTEXT DETECTION TESTS
# =============================================================================


class TestDevContextDetection:
    """Tests for detect_dev_context function."""

    def test_detect_python_language(self):
        """Should detect Python from keywords."""
        text = "Create a Flask API with SQLAlchemy"
        context = detect_dev_context(text)
        assert context.is_dev
        assert "python" in context.languages

    def test_detect_rust_language(self):
        """Should detect Rust from keywords."""
        text = "Build a REST API using Axum and Tokio in Rust"
        context = detect_dev_context(text)
        assert context.is_dev
        assert "rust" in context.languages

    def test_detect_javascript_language(self):
        """Should detect JavaScript/Node from keywords."""
        text = "Create an Express.js server with React frontend"
        context = detect_dev_context(text)
        assert context.is_dev
        assert "javascript" in context.languages

    def test_detect_multiple_languages(self):
        """Should detect multiple languages."""
        text = "Build a Python backend with TypeScript frontend using React"
        context = detect_dev_context(text)
        assert context.is_dev
        assert "python" in context.languages
        assert "typescript" in context.languages

    def test_detect_security_keywords(self):
        """Should detect security-sensitive keywords."""
        text = "Create a login endpoint with JWT authentication and password hashing"
        context = detect_dev_context(text)
        assert context.is_dev
        assert (
            "auth" in context.security_keywords_found
            or "authentication" in context.security_keywords_found
        )
        assert "jwt" in context.security_keywords_found
        assert "password" in context.security_keywords_found

    def test_elevated_security_level(self):
        """Should set elevated security level with multiple security keywords."""
        text = "Build an API with authentication, database queries, and file uploads"
        context = detect_dev_context(text)
        assert context.security_level in ["elevated", "critical"]

    def test_non_dev_text(self):
        """Should not detect dev context for non-technical text."""
        text = "Write a blog post about cooking pasta"
        context = detect_dev_context(text)
        assert not context.is_dev
        assert len(context.languages) == 0


class TestDependencyDetection:
    """Tests for detect_dependencies_from_text function."""

    def test_detect_python_requirements(self):
        """Should detect Python packages from requirements.txt format."""
        text = """
        flask==2.0.1
        sqlalchemy>=1.4.0
        requests==2.25.0
        """
        deps = detect_dependencies_from_text(text)
        assert len(deps) >= 3
        ecosystems = [d[0] for d in deps]
        packages = [d[1] for d in deps]
        assert "PyPI" in ecosystems
        assert "flask" in packages
        assert "sqlalchemy" in packages

    def test_detect_npm_packages(self):
        """Should detect npm packages from package.json format."""
        text = """
        {
          "dependencies": {
            "express": "^4.17.1",
            "lodash": "4.17.20",
            "axios": "~0.21.1"
          }
        }
        """
        deps = detect_dependencies_from_text(text)
        packages = [d[1] for d in deps]
        assert "express" in packages
        assert "lodash" in packages

    def test_detect_cargo_packages(self):
        """Should detect Rust packages from Cargo.toml format."""
        text = """
        [dependencies]
        tokio = "1.0.0"
        serde = "1.0.130"
        """
        deps = detect_dependencies_from_text(text)
        assert ("crates.io", "tokio", "1.0.0") in deps
        assert ("crates.io", "serde", "1.0.130") in deps


# =============================================================================
# CVE CHECKING TESTS (REAL API CALLS)
# =============================================================================


class TestCVEChecking:
    """Tests for CVE checking via OSV.dev API.

    These tests make REAL API calls to OSV.dev to verify the integration works.
    They use known vulnerable package versions.
    """

    @pytest.mark.integration
    def test_check_vulnerable_python_package(self):
        """Test with a known vulnerable Python package: urllib3 < 1.26.5 (CVE-2021-33503)."""
        cves = check_package_cve("urllib3", "1.26.4", "PyPI")
        # This version has known vulnerabilities
        # Note: may return empty if no vulns found or API changes
        print(f"Found {len(cves)} CVEs for urllib3 1.26.4")
        for cve in cves:
            print(f"  - {cve.id}: {cve.severity} - {cve.summary[:80]}")

    @pytest.mark.integration
    def test_check_vulnerable_npm_package(self):
        """Test with a known vulnerable npm package: lodash < 4.17.21."""
        cves = check_package_cve("lodash", "4.17.20", "npm")
        print(f"Found {len(cves)} CVEs for lodash 4.17.20")
        for cve in cves:
            print(f"  - {cve.id}: {cve.severity} - {cve.summary[:80]}")

    @pytest.mark.integration
    def test_check_vulnerable_requests_package(self):
        """Test with requests package that had CVE-2023-32681."""
        cves = check_package_cve("requests", "2.28.0", "PyPI")
        print(f"Found {len(cves)} CVEs for requests 2.28.0")
        for cve in cves:
            print(f"  - {cve.id}: {cve.severity} - {cve.summary[:80]}")

    @pytest.mark.integration
    def test_check_safe_package(self):
        """Test with a package version that should be safe."""
        # Using a very recent version that should have no known CVEs
        cves = check_package_cve("pytest", "8.0.0", "PyPI")
        print(f"Found {len(cves)} CVEs for pytest 8.0.0")
        # Should ideally be 0 or very few

    @pytest.mark.integration
    def test_batch_check_multiple_packages(self):
        """Test batch checking multiple packages at once."""
        dependencies = [
            ("PyPI", "django", "3.2.0"),  # Had security issues
            ("PyPI", "pillow", "8.0.0"),  # Had security issues
            ("npm", "minimist", "1.2.5"),  # Had prototype pollution
        ]
        cves = check_cve_osv(dependencies)
        print(f"Found {len(cves)} total CVEs for batch check")
        for cve in cves:
            print(f"  - {cve.id}: {cve.package} - {cve.severity}")

    @pytest.mark.integration
    def test_check_nonexistent_package(self):
        """Test with a package that doesn't exist - should return empty, not error."""
        cves = check_package_cve("this-package-does-not-exist-xyz", "1.0.0", "PyPI")
        assert cves == []  # Should return empty list, not crash


# =============================================================================
# SECURITY GUIDELINES TESTS
# =============================================================================


class TestSecurityGuidelines:
    """Tests for security guidelines generation."""

    def test_python_guidelines(self):
        """Should generate Python-specific security guidelines."""
        context = SecurityContext(
            is_dev=True,
            languages=["python"],
            security_keywords_found=["database", "sql"],
            security_level="elevated",
        )
        guidelines = get_security_guidelines(context)
        assert "Python Security" in guidelines
        assert "secrets" in guidelines or "bcrypt" in guidelines

    def test_auth_guidelines(self):
        """Should generate auth-specific guidelines when auth keywords found."""
        context = SecurityContext(
            is_dev=True,
            languages=["python"],
            security_keywords_found=["auth", "jwt", "password"],
            security_level="elevated",
        )
        guidelines = get_security_guidelines(context)
        assert "Authentification" in guidelines
        assert "JWT" in guidelines or "jwt" in guidelines.lower()

    def test_database_guidelines(self):
        """Should generate database security guidelines."""
        context = SecurityContext(
            is_dev=True,
            languages=["python"],
            security_keywords_found=["sql", "database", "query"],
            security_level="elevated",
        )
        guidelines = get_security_guidelines(context)
        assert "Base de donnees" in guidelines or "parametrees" in guidelines

    def test_cve_warnings_in_guidelines(self):
        """Should include CVE warnings when CVEs are present."""
        cve = CVEInfo(
            id="CVE-2021-12345",
            summary="Test vulnerability",
            severity="HIGH",
            package="test-package",
            affected_versions="1.0.0 - 1.5.0",
            fixed_version="1.5.1",
        )
        context = SecurityContext(
            is_dev=True,
            languages=["python"],
            security_keywords_found=["database"],
            cves=[cve],
            security_level="elevated",
        )
        guidelines = get_security_guidelines(context)
        assert "CVE-2021-12345" in guidelines
        assert "HIGH" in guidelines
        assert "test-package" in guidelines

    def test_owasp_reminder(self):
        """Should always include OWASP Top 10 reminder for dev context."""
        context = SecurityContext(
            is_dev=True,
            languages=["python"],
            security_keywords_found=["api"],
            security_level="standard",
        )
        guidelines = get_security_guidelines(context)
        assert "OWASP" in guidelines
        assert "Injection" in guidelines

    def test_no_guidelines_for_non_dev(self):
        """Should return empty string for non-dev context."""
        context = SecurityContext(is_dev=False)
        guidelines = get_security_guidelines(context)
        assert guidelines == ""


# =============================================================================
# INTEGRATION HELPER TESTS
# =============================================================================


class TestEnrichPromptWithSecurity:
    """Tests for enrich_prompt_with_security function."""

    def test_enrich_dev_prompt(self):
        """Should enrich a dev prompt with security context."""
        raw_prompt = "Create a REST API with JWT authentication in Python"
        enriched, context = enrich_prompt_with_security(raw_prompt, "", check_cves=False)

        assert context.is_dev
        assert "python" in context.languages
        assert len(enriched) > 0
        assert "SECURITE" in enriched or "Security" in enriched

    def test_enrich_with_project_context(self):
        """Should combine project context with security guidelines."""
        raw_prompt = "Add a login endpoint"
        project_context = "# My Python API\nUsing Flask and SQLAlchemy"

        enriched, context = enrich_prompt_with_security(
            raw_prompt, project_context, check_cves=False
        )

        assert "My Python API" in enriched
        assert "SECURITE" in enriched or "Security" in enriched

    def test_no_enrichment_for_non_dev(self):
        """Should not add security context for non-dev prompts."""
        raw_prompt = "Write a poem about nature"
        enriched, context = enrich_prompt_with_security(raw_prompt, "", check_cves=False)

        assert not context.is_dev
        assert enriched == ""

    @pytest.mark.integration
    def test_enrich_with_cve_check(self):
        """Should include CVE check results when enabled."""
        raw_prompt = "Update my Python API"
        project_context = """
        # Dependencies
        flask==2.0.1
        requests==2.25.0
        """

        enriched, context = enrich_prompt_with_security(
            raw_prompt, project_context, check_cves=True
        )

        print(f"Found {len(context.cves)} CVEs")
        print(f"Enriched context length: {len(enriched)}")


class TestCVEAlertFormatting:
    """Tests for CVE alert formatting."""

    def test_format_critical_cves(self):
        """Should format critical CVEs with proper emphasis."""
        cves = [
            CVEInfo("CVE-2021-0001", "Critical vuln", "CRITICAL", "pkg1", "1.0", "1.1"),
            CVEInfo("CVE-2021-0002", "High vuln", "HIGH", "pkg2", "2.0", "2.1"),
        ]
        alert = format_cve_alert(cves)

        assert "[CRITICAL]" in alert
        assert "[HIGH]" in alert
        assert "CVE-2021-0001" in alert
        assert "pkg1" in alert

    def test_format_empty_cves(self):
        """Should return empty string for no CVEs."""
        alert = format_cve_alert([])
        assert alert == ""

    def test_format_many_medium_cves(self):
        """Should truncate many medium CVEs."""
        cves = [
            CVEInfo(f"CVE-2021-{i:04d}", f"Medium vuln {i}", "MEDIUM", f"pkg{i}", "1.0", None)
            for i in range(10)
        ]
        alert = format_cve_alert(cves)

        assert "[MEDIUM]" in alert
        assert "autres" in alert  # Should mention "... et X autres"


# =============================================================================
# REAL WORLD SCENARIO TESTS
# =============================================================================


class TestRealWorldScenarios:
    """Tests simulating real-world usage scenarios."""

    def test_rust_api_prompt(self):
        """Test a Rust API development prompt."""
        prompt = "Create a REST API route in Rust using Axum with JWT token authentication"
        context = detect_dev_context(prompt)

        assert context.is_dev
        assert "rust" in context.languages
        assert "jwt" in context.security_keywords_found
        assert context.security_level in ["elevated", "critical"]

    def test_fullstack_prompt(self):
        """Test a fullstack development prompt."""
        prompt = """
        Build a web application with:
        - Python FastAPI backend with PostgreSQL database
        - React TypeScript frontend
        - JWT authentication
        - File upload functionality
        """
        context = detect_dev_context(prompt)

        assert context.is_dev
        assert "python" in context.languages
        assert "typescript" in context.languages
        assert context.security_level == "critical"  # Many security keywords

    def test_data_science_prompt(self):
        """Test a data science prompt - should detect Python but fewer security concerns."""
        prompt = "Train a machine learning model using PyTorch and Pandas"
        context = detect_dev_context(prompt)

        assert context.is_dev
        assert "python" in context.languages
        assert context.security_level == "standard"  # No security keywords

    @pytest.mark.integration
    def test_vulnerable_project_scan(self):
        """Simulate scanning a project with vulnerable dependencies."""
        project_config = """
        # Old Project Config

        ## Dependencies
        django==3.1.0
        pillow==8.0.0
        requests==2.25.0
        pyyaml==5.3.1
        """

        prompt = "Help me secure this Django project"
        enriched, context = enrich_prompt_with_security(prompt, project_config, check_cves=True)

        print("\n=== Vulnerable Project Scan Results ===")
        print(f"Languages detected: {context.languages}")
        print(f"Security keywords: {context.security_keywords_found}")
        print(f"Security level: {context.security_level}")
        print(f"CVEs found: {len(context.cves)}")

        for cve in context.cves:
            print(f"  - {cve.id} ({cve.severity}): {cve.package}")

        print("\nEnriched context preview (first 500 chars):")
        print(enriched[:500])


# =============================================================================
# SECRET DETECTION TESTS
# =============================================================================


# Identifiants synthetiques, invalides, generes pour ces tests uniquement.
#
# Ils sont assembles par concatenation a dessein : le fichier source ne contient
# aucun litteral qui declencherait un scanner de secrets sur ce depot (gitleaks,
# prevu par F-008), tout en donnant au scanner teste une valeur de longueur et
# de forme exactes.
#
# Le decoupage retenu est de huit caracteres par fragment, et non une simple
# coupure du prefixe. Motif mesure : la regle `generic-api-key` de gitleaks ne
# regarde pas le prefixe mais le voisinage d'un nom de variable porteur de
# `key`, `secret` ou `token` et d'une valeur d'au moins dix caracteres a forte
# entropie. Or ces cinq noms de variables portent tous l'un de ces mots. Un
# fragment de dix-sept caracteres (l'ancien decoupage de FAKE_AWS_SECRET_KEY) ou
# de trente (l'ancien decoupage de la cle d'exemple AWS) suffit donc a
# declencher la regle, prefixe coupe ou non. Sous dix caracteres, aucun fragment
# ne peut la satisfaire, quelle que soit son entropie.
FAKE_AWS_ACCESS_KEY_ID = "AKIA" + "3F7KQ2N" + "9WBXDLZ4T"  # 4 + 16 = 20
FAKE_AWS_SECRET_KEY = "kR9dTn2Q" + "vL7mXe4W" + "zB1sYcJ0" + "pHgAfU6i" + "N3oD8rTq"  # 5 x 8 = 40
FAKE_GITHUB_TOKEN = (
    "ghp_" + "Kq7Zx2Vb" + "9NmTr4Lp" + "1Wc6Ys3H" + "d8Jf0Gu5" + "Ae2B"
)  # 4 + 36 = 40

# Identifiants d'exemple publies par la documentation AWS. Ils ne doivent JAMAIS
# etre remontes comme des secrets : ils sont copies dans d'innombrables README,
# `.env.example` et tutoriels. Meme decoupage a huit caracteres, meme motif.
AWS_DOC_EXAMPLE_ACCESS_KEY_ID = "AKIAIOSF" + "ODNN7" + "EXAMPLE"
AWS_DOC_EXAMPLE_SECRET_KEY = "wJalrXUt" + "nFEMI/K7" + "MDENG/bP" + "xRfiCY" + "EXAMPLE" + "KEY"


class TestSecretMasking:
    """Tests for secret masking function."""

    def test_mask_short_secret(self):
        """Should fully mask short secrets."""
        masked = mask_secret("abc123")
        assert "abc" not in masked
        assert masked == "******"

    def test_mask_long_secret(self):
        """Should show first and last chars of long secrets."""
        masked = mask_secret("sk-12345" + "67890abc" + "defghij")
        assert masked.startswith("sk-1")
        assert masked.endswith("ghij")
        assert "****" in masked

    def test_mask_empty(self):
        """Should handle empty string."""
        masked = mask_secret("")
        assert masked == "****"


class TestSecretFileScanning:
    """Tests for file-level secret scanning."""

    def test_scan_env_file_with_secrets(self):
        """Should detect secrets in .env file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("DATABASE_URL=postgresql://user:password123@localhost/db\n")
            f.write("API_KEY=sk-1234567890abcdefghijklmnopqrstuvwxyz\n")
            f.flush()
            path = Path(f.name)

        try:
            findings = scan_file_for_secrets(path)
            assert len(findings) >= 2
            secret_types = [f.secret_type for f in findings]
            assert any("Database" in t for t in secret_types)
        finally:
            path.unlink()

    def test_scan_file_with_aws_keys(self):
        """Should detect AWS credentials that are not documentation examples."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write(f"AWS_ACCESS_KEY_ID={FAKE_AWS_ACCESS_KEY_ID}\n")
            f.write(f"AWS_SECRET_ACCESS_KEY={FAKE_AWS_SECRET_KEY}\n")
            f.flush()
            path = Path(f.name)

        try:
            findings = scan_file_for_secrets(path)
            assert len(findings) >= 1
            assert any("AWS" in f.secret_type for f in findings)
            assert all(f.severity in ["HIGH", "CRITICAL"] for f in findings)
        finally:
            path.unlink()

    def test_skip_aws_documentation_example_keys(self):
        """Should NOT flag the credentials published by the AWS documentation.

        Pins the F-004 arbitration: a scanner that reports AWS's own published
        example credentials produces false positives on a large share of real
        projects, which CLAUDE.md forbids.
        """
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write(f"AWS_ACCESS_KEY_ID={AWS_DOC_EXAMPLE_ACCESS_KEY_ID}\n")
            f.write(f"AWS_SECRET_ACCESS_KEY={AWS_DOC_EXAMPLE_SECRET_KEY}\n")
            f.flush()
            path = Path(f.name)

        try:
            findings = scan_file_for_secrets(path)
            assert findings == []
        finally:
            path.unlink()

    def test_aws_access_key_id_longer_than_20_chars_not_flagged(self):
        """Should not report an AKIA-prefixed blob that is not 20 chars long."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("AWS_ACCESS_KEY_ID=" + "AKIA" + "3F7KQ2N" + "9WBXDLZ" + "4TQRST" + "\n")
            f.flush()
            path = Path(f.name)

        try:
            findings = scan_file_for_secrets(path)
            assert not any("AWS Access Key ID" == f.secret_type for f in findings)
        finally:
            path.unlink()

    def test_scan_file_with_github_token(self):
        """Should detect a GitHub PAT of the documented length.

        A classic PAT is `ghp_` followed by exactly 36 characters (40 total).
        See the length note on the GitHub Token pattern in security.py.
        """
        assert len(FAKE_GITHUB_TOKEN) == 40

        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write(f"GITHUB_TOKEN={FAKE_GITHUB_TOKEN}\n")
            f.flush()
            path = Path(f.name)

        try:
            findings = scan_file_for_secrets(path)
            assert len(findings) >= 1
            assert any("GitHub" in f.secret_type for f in findings)
        finally:
            path.unlink()

    @pytest.mark.parametrize("body_length", [32, 40])
    def test_github_token_of_wrong_length_not_flagged(self, body_length):
        """Should not report a `ghp_` blob whose body is not 36 chars long.

        Guards both directions of the length rule: too short (32) and too long
        (40). The upper bound only holds because the pattern is right-bounded.
        """
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("GITHUB_TOKEN=" + "ghp_" + ("a" * body_length) + "\n")
            f.flush()
            path = Path(f.name)

        try:
            findings = scan_file_for_secrets(path)
            assert not any("GitHub" in f.secret_type for f in findings)
        finally:
            path.unlink()

    def test_skip_placeholder_values(self):
        """Should skip placeholder values."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("API_KEY=your_api_key_here\n")
            f.write("SECRET=<replace_with_secret>\n")
            f.write("PASSWORD=changeme\n")
            f.flush()
            path = Path(f.name)

        try:
            findings = scan_file_for_secrets(path)
            # Should not flag placeholder values
            assert len(findings) == 0
        finally:
            path.unlink()

    def test_skip_comments(self):
        """Should skip commented lines."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("# API_KEY=sk-12345" + "67890abc" + "defghijk" + "lmnopqrs" + "tuvwxyz\n")
            f.write("// ANOTHER_KEY=secret1" + "23456789" + "012345\n")
            f.flush()
            path = Path(f.name)

        try:
            findings = scan_file_for_secrets(path)
            assert len(findings) == 0
        finally:
            path.unlink()


class TestPlaceholderFilter:
    """Tests for is_placeholder_value, the anti-false-positive filter (F-004)."""

    @pytest.mark.parametrize(
        "value",
        [
            "your_api_key_here",
            "XXXXXXXXXXXXXXXX",
            "changeme",
            "replace_with_secret",
            "placeholder_value",
            "TODO_set_this",
            "${VAULT_DB_PASSWORD}",
            "{{ db_password }}",
            "<SET-ME-IN-VAULT>",
            "",
        ],
    )
    def test_rejects_placeholders(self, value):
        assert is_placeholder_value(value) is True

    @pytest.mark.parametrize(
        "value",
        [
            FAKE_AWS_ACCESS_KEY_ID,
            FAKE_AWS_SECRET_KEY,
            FAKE_GITHUB_TOKEN,
            "Tr0ub4dor<3!",  # un chevron isole ne fait pas un gabarit
            "a<b>c_D3f9hK2mQ",  # chevrons au milieu, valeur non encadree
        ],
    )
    def test_accepts_real_looking_values(self, value):
        assert is_placeholder_value(value) is False

    def test_documented_example_credentials_are_placeholders(self):
        """AWS's published example credentials are placeholders, by decision."""
        assert is_placeholder_value(AWS_DOC_EXAMPLE_ACCESS_KEY_ID) is True
        assert is_placeholder_value(AWS_DOC_EXAMPLE_SECRET_KEY) is True

    def test_password_containing_angle_bracket_is_detected(self):
        """A password merely containing `<` must still be reported.

        Before F-004 the filter rejected any value containing `<` or `>`, which
        silently dropped a whole class of real passwords.
        """
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("DB_PASSWORD=Tr0ub4dor<3!xK9\n")
            f.flush()
            path = Path(f.name)

        try:
            findings = scan_file_for_secrets(path)
            assert len(findings) >= 1
        finally:
            path.unlink()


class TestSecretDirectoryScanning:
    """Tests for directory-level secret scanning."""

    def test_scan_directory_with_secrets(self):
        """Should scan multiple files in directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)

            # Create .env file
            (project / ".env").write_text("API_KEY=sk-1234567890abcdef\n")

            # Create config.py
            (project / "config.py").write_text(
                'SECRET = "' + "my_secre" + "t_value" + "_1234567" + '89"\n'
            )

            findings = scan_directory_for_secrets(project)
            assert len(findings) >= 1

    def test_scan_skips_node_modules(self):
        """Should skip node_modules directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)

            # Create node_modules with secrets (should be skipped)
            nm = project / "node_modules" / "some_pkg"
            nm.mkdir(parents=True)
            (nm / "config.js").write_text('const KEY = "' + "sk-12345" + "67890abc" + 'def";\n')

            # Create real file with secret
            (project / ".env").write_text("API_KEY=sk-realkey1234567890\n")

            findings = scan_directory_for_secrets(project)

            # Should only find the .env secret, not node_modules
            file_paths = [f.file_path for f in findings]
            assert not any("node_modules" in p for p in file_paths)

    def test_scan_empty_directory(self):
        """Should handle empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)
            findings = scan_directory_for_secrets(project)
            assert findings == []


class TestSecretAlertFormatting:
    """Tests for secret alert formatting."""

    def test_format_critical_findings(self):
        """Should format critical findings with emphasis."""
        findings = [
            SecretFinding(
                secret_type="AWS Secret Key",
                file_path="/project/.env",
                line_number=5,
                key_name="AWS_SECRET_KEY",
                masked_value="wJal****EKEY",
                severity="CRITICAL",
                recommendation="Use AWS IAM roles",
            )
        ]
        alert = format_secret_alerts(findings)

        assert "CRITIQUE" in alert
        assert "AWS_SECRET_KEY" in alert
        assert "wJal****EKEY" in alert

    def test_format_high_findings(self):
        """Should format high severity findings."""
        findings = [
            SecretFinding(
                secret_type="Generic API Key",
                file_path="/project/config.py",
                line_number=10,
                key_name="API_KEY",
                masked_value="sk-1****wxyz",
                severity="HIGH",
                recommendation="Use environment variables",
            )
        ]
        alert = format_secret_alerts(findings)

        assert "ELEVE" in alert
        assert "API_KEY" in alert

    def test_format_empty_findings(self):
        """Should return empty string for no findings."""
        alert = format_secret_alerts([])
        assert alert == ""

    def test_format_includes_recommendations(self):
        """Should include general recommendations."""
        findings = [
            SecretFinding(
                secret_type="Test",
                file_path="/test",
                line_number=1,
                key_name="TEST",
                masked_value="****",
                severity="HIGH",
                recommendation="Test rec",
            )
        ]
        alert = format_secret_alerts(findings)

        assert "gitignore" in alert.lower() or ".env" in alert
        assert "Secrets Manager" in alert or "secrets" in alert.lower()


class TestSecretPatterns:
    """Tests for specific secret pattern detection."""

    def test_detect_openai_key(self):
        """Should detect OpenAI API keys."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("OPENAI_API_KEY=sk-proj-1234567890abcdefghijklmnopqrstuvwxyz\n")
            f.flush()
            path = Path(f.name)

        try:
            findings = scan_file_for_secrets(path)
            assert any("OpenAI" in f.secret_type for f in findings)
        finally:
            path.unlink()

    def test_detect_anthropic_key(self):
        """Should detect Anthropic API keys."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("ANTHROPIC_API_KEY=sk-ant-api03-abcdefghijklmnopqrstuvwxyz12345678\n")
            f.flush()
            path = Path(f.name)

        try:
            findings = scan_file_for_secrets(path)
            assert any("Anthropic" in f.secret_type for f in findings)
        finally:
            path.unlink()

    def test_detect_stripe_live_key(self):
        """Should detect Stripe live keys as critical."""
        # Use fake key that looks real but won't trigger GitHub scanner
        # Pattern: sk_live_ + 24 alphanumeric (avoid xxx which is filtered as placeholder)
        fake_stripe_key = "sk_live_" + "0a1b2c3d" + "4e5f6g7h" + "8i9j0k1l"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(f'STRIPE_SECRET_KEY = "{fake_stripe_key}"\n')
            f.flush()
            path = Path(f.name)

        try:
            findings = scan_file_for_secrets(path)
            stripe_findings = [f for f in findings if "Stripe" in f.secret_type]
            assert len(stripe_findings) >= 1
            assert any(f.severity == "CRITICAL" for f in stripe_findings)
        finally:
            path.unlink()

    def test_detect_jwt_token(self):
        """Should detect JWT tokens."""
        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(f'TOKEN = "{jwt}"\n')
            f.flush()
            path = Path(f.name)

        try:
            findings = scan_file_for_secrets(path)
            assert any("JWT" in f.secret_type for f in findings)
        finally:
            path.unlink()

    def test_detect_private_key(self):
        """Should detect private keys."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as f:
            f.write("-----BEGIN RSA PRIVATE KEY-----\n")
            f.write("MIIEpAIBAAKCAQEA0Z3VS5JJcds3xfn/ygWyF6M...\n")
            f.write("-----END RSA PRIVATE KEY-----\n")
            f.flush()
            path = Path(f.name)

        try:
            findings = scan_file_for_secrets(path)
            assert any("Private Key" in f.secret_type for f in findings)
            assert any(f.severity == "CRITICAL" for f in findings)
        finally:
            path.unlink()


# =============================================================================
# OSV.DEV : ECOSYSTEMES, RESILIENCE DES LOTS, ECHEC DISTINCT DE L'ABSENCE
# =============================================================================

# Chaines d'ecosysteme mesurees le 2026-09-04 par requete reelle sur
# `POST https://api.osv.dev/v1/querybatch`, paquet fictif `foo` version `1.0.0`.
# Ce sont des faits, pas une intention : ils verrouillent la table du module.
OSV_ECOSYSTEMS_MEASURED_200 = {
    "PyPI",
    "npm",
    "Go",
    "crates.io",
    "Maven",
    "NuGet",
    "Packagist",
    "RubyGems",
    "ConanCenter",
    "vcpkg",
    "SwiftURL",
}
OSV_ECOSYSTEMS_MEASURED_400 = {"SwiftPM", "CMake", "Conan"}


class _FakeResponse:
    """Reponse HTTP minimale, suffisante pour `urlopen` en context manager."""

    def __init__(self, payload):
        self._body = _json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _http_400(url):
    """Reproduit le rejet reel d'OSV sur un lot contenant une entree invalide."""
    body = io.BytesIO(
        b'{"code":3,"message":"error in query at index 1: rpc error: '
        b'code = InvalidArgument desc = invalid ecosystem"}'
    )
    return urllib.error.HTTPError(url, 400, "Bad Request", {}, body)


def _fake_osv(poison_names=(), vulnerable_names=(), calls=None, raise_exc=None):
    """Fabrique un `urlopen` de substitution pour l'API OSV.

    `poison_names` reproduit le comportement mesure de l'API : le lot ENTIER est
    rejete des qu'une seule de ses entrees est invalide.
    """

    def _urlopen(request, timeout=None):
        payload = _json.loads(request.data.decode("utf-8"))
        queries = payload["queries"]
        if calls is not None:
            calls.append(queries)
        if raise_exc is not None:
            raise raise_exc
        if any(q["package"]["name"] in poison_names for q in queries):
            raise _http_400(request.full_url)
        results = []
        for query in queries:
            name = query["package"]["name"]
            if name in vulnerable_names:
                results.append({"vulns": [{"id": f"GHSA-fake-{name}"}]})
            else:
                results.append({})
        return _FakeResponse({"results": results})

    return _urlopen


def _fake_details(vuln_id):
    """Detail OSV minimal, parsable par `parse_osv_vulnerability`."""
    package = vuln_id.replace("GHSA-fake-", "")
    return {
        "id": vuln_id,
        "aliases": [],
        "summary": f"vuln de test sur {package}",
        "severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/C:H/I:H/A:H"}],
        "affected": [{"package": {"name": package}, "versions": ["1.0.0"]}],
        "references": [],
    }


class TestOsvEcosystemStrings:
    """Verrouille les chaines d'ecosysteme sur la mesure du 2026-09-04."""

    def test_supported_set_matches_what_osv_accepted(self):
        """La table du module ne contient que des chaines mesurees en HTTP 200."""
        assert set(OSV_SUPPORTED_ECOSYSTEMS) == OSV_ECOSYSTEMS_MEASURED_200

    @pytest.mark.parametrize("rejected", sorted(OSV_ECOSYSTEMS_MEASURED_400))
    def test_rejected_strings_are_never_sent_as_is(self, rejected):
        """Aucune des trois chaines rejetees ne doit rester telle quelle."""
        assert rejected not in OSV_SUPPORTED_ECOSYSTEMS

    def test_swiftpm_is_translated_to_swifturl(self):
        assert normalize_osv_ecosystem("SwiftPM") == "SwiftURL"

    def test_conan_is_translated_to_conancenter(self):
        assert normalize_osv_ecosystem("Conan") == "ConanCenter"

    def test_cmake_has_no_osv_ecosystem(self):
        """CMake est un systeme de construction, pas un index de paquets."""
        assert normalize_osv_ecosystem("CMake") is None
        assert "CMake" in OSV_UNSUPPORTED_ECOSYSTEMS

    def test_unknown_ecosystem_is_refused_not_guessed(self):
        assert normalize_osv_ecosystem("Bazel") is None

    @pytest.mark.parametrize("supported", sorted(OSV_ECOSYSTEMS_MEASURED_200))
    def test_supported_ecosystems_pass_through_unchanged(self, supported):
        assert normalize_osv_ecosystem(supported) == supported


class TestOsvPackageNameNormalization:
    """SwiftURL indexe par URL de depot : le nom doit prendre cette forme."""

    @pytest.mark.parametrize(
        "raw",
        [
            "https://github.com/apple/swift-nio.git",
            "https://github.com/apple/swift-nio",
            "github.com/apple/swift-nio.git",
            "github.com/apple/swift-nio/",
        ],
    )
    def test_swifturl_names_are_reduced_to_the_indexed_form(self, raw):
        assert normalize_osv_package_name("SwiftURL", raw) == "github.com/apple/swift-nio"

    @pytest.mark.parametrize("ecosystem", ["PyPI", "npm", "Go", "ConanCenter"])
    def test_other_ecosystems_are_left_untouched(self, ecosystem):
        """Ne rien normaliser ailleurs : `requests.git` n'existe pas sur PyPI."""
        assert normalize_osv_package_name(ecosystem, "some.git") == "some.git"


class TestOsvBatchResilience:
    """Un paquet rejete ne doit plus annuler la verification des autres."""

    def test_mixed_batch_keeps_the_valid_packages(self):
        """Lot mixte valide/invalide : les valides sont verifies quand meme.

        Reproduit la mesure du 2026-09-04 : `[PyPI/gradio]` seul rend HTTP 200
        avec des vulnerabilites, `[PyPI/gradio, SwiftPM/...]` rend HTTP 400 et
        perd tout. La bissection isole l'entree fautive.
        """
        calls = []
        dependencies = [
            ("PyPI", "gradio", "4.0.0"),
            ("npm", "poison-pkg", "1.0.0"),
            ("npm", "express", "4.17.1"),
        ]
        with (
            patch.object(
                urllib.request,
                "urlopen",
                _fake_osv(
                    poison_names={"poison-pkg"}, vulnerable_names={"gradio", "express"}, calls=calls
                ),
            ),
            patch("promptforge.security.fetch_vuln_details", _fake_details),
        ):
            outcome = check_cve_osv_detailed(dependencies)

        assert {cve.package for cve in outcome.cves} == {"gradio", "express"}
        assert outcome.failed == [("npm", "poison-pkg", "1.0.0")]
        assert ("PyPI", "gradio", "4.0.0") in outcome.checked
        assert outcome.complete is False
        assert len(calls) > 1, "sans bissection, le lot entier aurait ete perdu"

    def test_a_single_bad_package_does_not_hide_the_others_cves(self):
        """Contre-mesure directe de l'empoisonnement : la vulnerabilite sort."""
        dependencies = [
            ("PyPI", "gradio", "4.0.0"),
            ("SwiftPM", "swift-nio", "2.0.0"),
        ]
        with (
            patch.object(
                urllib.request,
                "urlopen",
                _fake_osv(poison_names={"swift-nio"}, vulnerable_names={"gradio"}),
            ),
            patch("promptforge.security.fetch_vuln_details", _fake_details),
        ):
            outcome = check_cve_osv_detailed(dependencies)

        assert len(outcome.cves) == 1
        assert outcome.cves[0].package == "gradio"

    def test_unsupported_ecosystem_is_never_put_on_the_wire(self):
        """CMake ne part pas : il ne peut donc plus faire tomber le lot."""
        calls = []
        dependencies = [
            ("PyPI", "gradio", "4.0.0"),
            ("CMake", "OpenSSL", "1.1.1"),
        ]
        with patch.object(
            urllib.request, "urlopen", _fake_osv(vulnerable_names=set(), calls=calls)
        ):
            outcome = check_cve_osv_detailed(dependencies)

        sent = [q["package"]["ecosystem"] for call in calls for q in call]
        assert sent == ["PyPI"]
        assert outcome.skipped == [("CMake", "OpenSSL", "1.1.1")]

    def test_non_concrete_versions_are_skipped_not_sent(self):
        """Une version non concrete ferait remonter TOUT le catalogue du paquet.

        Mesure du 2026-09-04 sur `PyPI/gradio` : `4.0.0` -> 80 vulnerabilites,
        version vide / `detected` / `>=3.10` -> 86 a 100, soit toutes versions
        confondues. Les envoyer produirait une avalanche de faux positifs.
        """
        calls = []
        dependencies = [
            ("PyPI", "gradio", "4.0.0"),
            ("PyPI", "colorama", ""),
            ("CMake", "OpenSSL", "detected"),
            ("PyPI", "django", ">=3.10"),
        ]
        with patch.object(
            urllib.request, "urlopen", _fake_osv(vulnerable_names=set(), calls=calls)
        ):
            outcome = check_cve_osv_detailed(dependencies)

        sent = [q["package"]["name"] for call in calls for q in call]
        assert sent == ["gradio"]
        assert len(outcome.skipped) == 3


class TestOsvFailureIsDistinctFromAbsence:
    """`cves == []` doit cesser d'etre ambigu."""

    def test_healthy_scan_is_complete_and_silent(self):
        dependencies = [("PyPI", "gradio", "4.0.0"), ("npm", "express", "4.17.1")]
        with patch.object(urllib.request, "urlopen", _fake_osv(vulnerable_names=set())):
            outcome = check_cve_osv_detailed(dependencies)

        assert outcome.cves == []
        assert outcome.complete is True
        assert outcome.summary() == ""
        assert len(outcome.checked) == 2

    def test_unreachable_api_is_reported_not_swallowed(self):
        dependencies = [("PyPI", "gradio", "4.0.0")]
        with patch.object(
            urllib.request,
            "urlopen",
            _fake_osv(raise_exc=urllib.error.URLError("connexion refusee")),
        ):
            outcome = check_cve_osv_detailed(dependencies)

        assert outcome.cves == []
        assert outcome.complete is False
        assert outcome.failed == dependencies
        assert outcome.summary().startswith(CVE_CHECK_INCOMPLETE_PREFIX)

    def test_the_two_empty_results_do_not_look_alike(self):
        """Le point du gate : sain et en panne rendaient le meme `[]`."""
        with patch.object(urllib.request, "urlopen", _fake_osv(vulnerable_names=set())):
            healthy = check_cve_osv_detailed([("PyPI", "gradio", "4.0.0")])
        with patch.object(
            urllib.request, "urlopen", _fake_osv(raise_exc=urllib.error.URLError("boom"))
        ):
            broken = check_cve_osv_detailed([("PyPI", "gradio", "4.0.0")])

        assert healthy.cves == broken.cves == []
        assert healthy.complete != broken.complete
        assert healthy.summary() == "" and broken.summary() != ""

    def test_http_500_is_not_bisected_but_reported(self):
        """Une panne serveur ne vise aucune entree : inutile de bissecter."""
        calls = []

        def _urlopen(request, timeout=None):
            calls.append(request)
            raise urllib.error.HTTPError(
                request.full_url, 500, "Server Error", {}, io.BytesIO(b"boom")
            )

        with patch.object(urllib.request, "urlopen", _urlopen):
            outcome = check_cve_osv_detailed(
                [("PyPI", "gradio", "4.0.0"), ("npm", "express", "4.17.1")]
            )

        assert len(calls) == 1
        assert len(outcome.failed) == 2
        assert outcome.complete is False

    def test_truncated_response_is_a_failure_not_a_clean_bill(self):
        """Moins de resultats que de requetes : on ne devine pas l'appariement."""

        def _urlopen(request, timeout=None):
            return _FakeResponse({"results": [{}]})

        with patch.object(urllib.request, "urlopen", _urlopen):
            outcome = check_cve_osv_detailed(
                [("PyPI", "gradio", "4.0.0"), ("npm", "express", "4.17.1")]
            )

        assert outcome.complete is False
        assert outcome.cves == []

    def test_lost_vulnerability_details_are_reported(self):
        """Une vulnerabilite trouvee puis non detaillee ne doit pas disparaitre."""
        with (
            patch.object(urllib.request, "urlopen", _fake_osv(vulnerable_names={"gradio"})),
            patch("promptforge.security.fetch_vuln_details", lambda vuln_id: None),
        ):
            outcome = check_cve_osv_detailed([("PyPI", "gradio", "4.0.0")])

        assert outcome.cves == []
        assert outcome.complete is False
        assert any("details indisponibles" in error for error in outcome.errors)

    def test_the_same_cve_indexed_twice_by_osv_is_reported_once(self):
        """OSV indexe une meme CVE sous plusieurs identifiants (GHSA, PYSEC).

        Le dedoublonnage sur l'identifiant OSV ne les rapproche pas : c'est
        l'alias CVE commun, produit par `parse_osv_vulnerability`, qui doit
        aussi etre filtre. Mesure du 2026-09-04 sur `PyPI/pytest 8.3.4` :
        CVE-2025-71176 rendue deux fois avant ce filtre.
        """

        def _urlopen(request, timeout=None):
            return _FakeResponse(
                {"results": [{"vulns": [{"id": "GHSA-aaaa"}, {"id": "PYSEC-bbbb"}]}]}
            )

        def _details(vuln_id):
            return {
                "id": vuln_id,
                "aliases": ["CVE-2025-71176"],
                "summary": "meme faille, deux index",
                "severity": [],
                "affected": [{"package": {"name": "pytest"}, "versions": ["8.3.4"]}],
                "references": [],
            }

        with (
            patch.object(urllib.request, "urlopen", _urlopen),
            patch("promptforge.security.fetch_vuln_details", _details),
        ):
            outcome = check_cve_osv_detailed([("PyPI", "pytest", "8.3.4")])

        assert [cve.id for cve in outcome.cves] == ["CVE-2025-71176"]

    def test_a_vulnerability_without_cve_alias_is_still_reported(self):
        """Sans alias CVE, l'identifiant rendu EST l'identifiant OSV.

        Un dedoublonnage a un seul ensemble ferait alors collision avec
        lui-meme et supprimerait toutes les vulnerabilites non aliasees, qui
        sont la majorite des avis GHSA recents.
        """
        with (
            patch.object(urllib.request, "urlopen", _fake_osv(vulnerable_names={"gradio"})),
            patch("promptforge.security.fetch_vuln_details", _fake_details),
        ):
            outcome = check_cve_osv_detailed([("PyPI", "gradio", "4.0.0")])

        assert [cve.id for cve in outcome.cves] == ["GHSA-fake-gradio"]

    def test_empty_input_is_complete(self):
        outcome = check_cve_osv_detailed([])
        assert outcome.complete is True
        assert outcome.summary() == ""

    def test_skipped_alone_still_warns_the_user(self):
        """Ignore n'est pas sain : le message sort meme si rien n'a echoue."""
        with patch.object(urllib.request, "urlopen", _fake_osv(vulnerable_names=set())):
            outcome = check_cve_osv_detailed(
                [("PyPI", "gradio", "4.0.0"), ("CMake", "OpenSSL", "1.1.1")]
            )

        assert outcome.complete is True
        assert "non verifiables" in outcome.summary()

    def test_compat_wrapper_still_returns_a_plain_list(self):
        """`check_cve_osv` garde sa signature pour ses appelants existants."""
        with (
            patch.object(urllib.request, "urlopen", _fake_osv(vulnerable_names={"gradio"})),
            patch("promptforge.security.fetch_vuln_details", _fake_details),
        ):
            cves = check_cve_osv([("PyPI", "gradio", "4.0.0")])

        assert isinstance(cves, list)
        assert len(cves) == 1
        assert isinstance(cves[0], CVEInfo)


class TestCveCheckOutcomeSummary:
    """Le message rendu a l'utilisateur doit etre exact."""

    def test_empty_outcome_says_nothing(self):
        assert CVECheckOutcome().summary() == ""

    def test_failure_message_names_the_ecosystems(self):
        outcome = CVECheckOutcome(
            failed=[("PyPI", "gradio", "4.0.0")], errors=["OSV.dev injoignable : boom"]
        )
        message = outcome.summary()
        assert message.startswith(CVE_CHECK_INCOMPLETE_PREFIX)
        assert "PyPI" in message
        assert "OSV.dev injoignable" in message


if __name__ == "__main__":
    # Run with: python -m pytest tests/test_security.py -v
    # Run integration tests: python -m pytest tests/test_security.py -v -m integration
    pytest.main([__file__, "-v"])
