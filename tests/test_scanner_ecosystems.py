"""
Tests for Scanner Multi-Ecosystem Support
==========================================

Tests for C/C++ (Conan, vcpkg, CMake), Swift, and enhanced lockfile parsing.
"""

import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import pytest

from promptforge import scanner as scanner_module
from promptforge.scanner import (
    DetectedPackage,
    ProjectScanner,
    ScanResult,
    SecurityAlert,
)
from promptforge.security import (
    CVE_CHECK_INCOMPLETE_PREFIX,
    OSV_UNSUPPORTED_ECOSYSTEMS,
    normalize_osv_ecosystem,
)


class TestConanParser:
    """Tests for Conan (C/C++) lockfile parsing."""

    def test_parse_conanfile_txt(self, temp_dir):
        """Should parse conanfile.txt requirements."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.cpp").write_text("int main() { return 0; }")
        (project_dir / "conanfile.txt").write_text("""[requires]
fmt/10.1.1
spdlog/1.12.0
nlohmann_json/3.11.2
boost/1.83.0

[generators]
cmake
""")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        conan_packages = [p for p in result.packages if p.ecosystem == "Conan"]
        assert len(conan_packages) >= 3

        pkg_names = [p.name.lower() for p in conan_packages]
        assert "fmt" in pkg_names
        assert "spdlog" in pkg_names
        assert "nlohmann_json" in pkg_names

    def test_parse_conanfile_py(self, temp_dir):
        """Should parse conanfile.py requires."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.cpp").write_text("int main() { return 0; }")
        (project_dir / "conanfile.py").write_text("""from conan import ConanFile

class MyProjectConan(ConanFile):
    requires = [
        "fmt/10.1.1",
        "spdlog/1.12.0",
    ]
""")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        conan_packages = [p for p in result.packages if p.ecosystem == "Conan"]
        pkg_names = [p.name.lower() for p in conan_packages]
        assert "fmt" in pkg_names or "spdlog" in pkg_names

    def test_parse_conan_lock_v2(self, temp_dir):
        """Should parse Conan 2.x lockfile format."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.cpp").write_text("int main() { return 0; }")
        (project_dir / "conanfile.txt").write_text("[requires]\nfmt/10.0.0\n")
        (project_dir / "conan.lock").write_text(
            json.dumps(
                {"version": "0.5", "requires": ["fmt/10.1.1@", "spdlog/1.12.0@user/channel"]}
            )
        )

        scanner = ProjectScanner()
        # Call the lockfile parser directly
        installed = scanner._parse_conan_lockfile(project_dir)

        assert "fmt" in installed
        assert installed["fmt"] == "10.1.1"


class TestVcpkgParser:
    """Tests for vcpkg (C/C++) package parsing."""

    def test_parse_vcpkg_json_simple(self, temp_dir):
        """Should parse vcpkg.json with simple dependencies."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.cpp").write_text("int main() { return 0; }")
        (project_dir / "vcpkg.json").write_text(
            json.dumps(
                {
                    "name": "my-project",
                    "version": "1.0.0",
                    "dependencies": ["boost", "openssl", "curl"],
                }
            )
        )

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        vcpkg_packages = [p for p in result.packages if p.ecosystem == "vcpkg"]
        assert len(vcpkg_packages) == 3

        pkg_names = [p.name.lower() for p in vcpkg_packages]
        assert "boost" in pkg_names
        assert "openssl" in pkg_names
        assert "curl" in pkg_names

    def test_parse_vcpkg_json_with_versions(self, temp_dir):
        """Should parse vcpkg.json with version constraints."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.cpp").write_text("int main() { return 0; }")
        (project_dir / "vcpkg.json").write_text(
            json.dumps(
                {
                    "name": "my-project",
                    "dependencies": [
                        {"name": "openssl", "version>=": "3.0.0"},
                        {"name": "curl", "version": "8.4.0"},
                    ],
                    "overrides": [{"name": "zlib", "version": "1.3.0"}],
                }
            )
        )

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        vcpkg_packages = [p for p in result.packages if p.ecosystem == "vcpkg"]
        pkg_dict = {p.name.lower(): p for p in vcpkg_packages}

        assert "openssl" in pkg_dict
        assert pkg_dict["openssl"].version == "3.0.0"
        assert "curl" in pkg_dict
        assert pkg_dict["curl"].version == "8.4.0"


class TestSwiftParser:
    """Tests for Swift Package Manager parsing."""

    def test_parse_package_swift(self, temp_dir):
        """Should parse Package.swift dependencies."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.swift").write_text('print("Hello")')
        (project_dir / "Package.swift").write_text("""
// swift-tools-version:5.7
import PackageDescription

let package = Package(
    name: "MyApp",
    dependencies: [
        .package(url: "https://github.com/Alamofire/Alamofire.git", from: "5.8.0"),
        .package(url: "https://github.com/realm/SwiftLint.git", exact: "0.54.0"),
    ]
)
""")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        swift_packages = [p for p in result.packages if p.ecosystem == "SwiftPM"]
        assert len(swift_packages) >= 2

        pkg_names = [p.name.lower() for p in swift_packages]
        assert any("alamofire" in n for n in pkg_names)

    def test_parse_package_resolved_v2(self, temp_dir):
        """Should parse Package.resolved version 2 format."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.swift").write_text('print("Hello")')
        (project_dir / "Package.swift").write_text("""
import PackageDescription
let package = Package(name: "Test", dependencies: [
    .package(url: "https://github.com/Alamofire/Alamofire.git", from: "5.0.0")
])
""")
        (project_dir / "Package.resolved").write_text(
            json.dumps(
                {
                    "pins": [
                        {"identity": "alamofire", "state": {"version": "5.8.1"}},
                        {"identity": "swiftlint", "state": {"version": "0.54.0"}},
                    ],
                    "version": 2,
                }
            )
        )

        scanner = ProjectScanner()
        installed = scanner._parse_swift_lockfile(project_dir)

        assert "alamofire" in installed
        assert installed["alamofire"] == "5.8.1"

    def test_parse_package_resolved_v1(self, temp_dir):
        """Should parse Package.resolved version 1 format (older Swift)."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.swift").write_text('print("Hello")')
        (project_dir / "Package.resolved").write_text(
            json.dumps(
                {"object": {"pins": [{"package": "Alamofire", "state": {"version": "5.6.0"}}]}}
            )
        )

        scanner = ProjectScanner()
        installed = scanner._parse_swift_lockfile(project_dir)

        assert "alamofire" in installed
        assert installed["alamofire"] == "5.6.0"


class TestCMakeParser:
    """Tests for CMake dependency detection."""

    def test_parse_find_package(self, temp_dir):
        """Should detect find_package dependencies."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.cpp").write_text("int main() { return 0; }")
        (project_dir / "CMakeLists.txt").write_text("""
cmake_minimum_required(VERSION 3.20)
project(MyProject)

find_package(OpenSSL 3.0 REQUIRED)
find_package(Boost 1.80 REQUIRED)
find_package(ZLIB)
""")

        scanner = ProjectScanner()
        packages = scanner._parse_cmake_packages(project_dir)

        assert "openssl" in packages
        assert packages["openssl"] == "3.0"
        assert "boost" in packages
        assert packages["boost"] == "1.80"

    def test_parse_fetchcontent(self, temp_dir):
        """Should detect FetchContent dependencies."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.cpp").write_text("int main() { return 0; }")
        (project_dir / "CMakeLists.txt").write_text("""
cmake_minimum_required(VERSION 3.20)
project(MyProject)

include(FetchContent)
FetchContent_Declare(
    googletest
    GIT_REPOSITORY https://github.com/google/googletest.git
    GIT_TAG v1.14.0
)
FetchContent_MakeAvailable(googletest)
""")

        scanner = ProjectScanner()
        packages = scanner._parse_cmake_packages(project_dir)

        assert "googletest" in packages
        assert packages["googletest"] == "1.14.0"


class TestVersionSourceDetection:
    """Tests for installed vs declared version source detection."""

    def test_version_source_installed(self, temp_dir):
        """Should mark packages with lockfile versions as 'installed'."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.swift").write_text('print("Hello")')
        (project_dir / "Package.swift").write_text("""
import PackageDescription
let package = Package(name: "Test", dependencies: [
    .package(url: "https://github.com/Alamofire/Alamofire.git", from: "5.0.0")
])
""")
        # Lockfile has different (more recent) version
        (project_dir / "Package.resolved").write_text(
            json.dumps(
                {"pins": [{"identity": "alamofire", "state": {"version": "5.9.1"}}], "version": 2}
            )
        )

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        swift_packages = [p for p in result.packages if p.ecosystem == "SwiftPM"]
        alamofire = next((p for p in swift_packages if "alamofire" in p.name.lower()), None)

        # Assertion inconditionnelle : le `if alamofire:` d'origine laissait le
        # test passer en silence quand le paquet n'etait pas detecte du tout.
        assert alamofire is not None, f"Alamofire absent de {swift_packages}"

        # Le nom ne doit pas garder le suffixe `.git` de l'URL du depot, sinon la
        # jointure avec Package.resolved (indexe sur `alamofire`) echoue.
        assert alamofire.name == "Alamofire"

        # La version resolue du lockfile prime sur la version declaree.
        assert alamofire.installed_version == "5.9.1"
        assert alamofire.declared_version == "5.0.0"
        assert alamofire.version == "5.9.1"
        assert alamofire.version_source == "installed"

    def test_swift_url_without_git_suffix(self, temp_dir):
        """Une URL sans `.git` doit se joindre au lockfile de la meme facon."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.swift").write_text('print("Hello")')
        (project_dir / "Package.swift").write_text("""
import PackageDescription
let package = Package(name: "Test", dependencies: [
    .package(url: "https://github.com/apple/swift-nio", from: "2.0.0")
])
""")
        (project_dir / "Package.resolved").write_text(
            json.dumps(
                {"pins": [{"identity": "swift-nio", "state": {"version": "2.65.0"}}], "version": 2}
            )
        )

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        nio = next(
            (
                p
                for p in result.packages
                if p.ecosystem == "SwiftPM" and p.name.lower() == "swift-nio"
            ),
            None,
        )
        assert nio is not None
        assert nio.version == "2.65.0"
        assert nio.version_source == "installed"

    def test_swift_without_lockfile_stays_declared(self, temp_dir):
        """Sans Package.resolved, la version reste declaree, pas installee."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.swift").write_text('print("Hello")')
        (project_dir / "Package.swift").write_text("""
import PackageDescription
let package = Package(name: "Test", dependencies: [
    .package(url: "https://github.com/Alamofire/Alamofire.git", from: "5.0.0")
])
""")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        alamofire = next(
            (
                p
                for p in result.packages
                if p.ecosystem == "SwiftPM" and p.name.lower() == "alamofire"
            ),
            None,
        )
        assert alamofire is not None
        assert alamofire.version == "5.0.0"
        assert alamofire.installed_version == ""
        assert alamofire.version_source == "declared"

    def test_version_source_declared(self, temp_dir):
        """Should mark packages without lockfile as 'declared'."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.cpp").write_text("int main() { return 0; }")
        (project_dir / "conanfile.txt").write_text("[requires]\nfmt/10.1.1\n")
        # No conan.lock file

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        conan_packages = [p for p in result.packages if p.ecosystem == "Conan"]
        if conan_packages:
            assert conan_packages[0].version_source == "declared"


class TestMultiEcosystemProject:
    """Tests for projects with multiple package ecosystems."""

    def test_cpp_project_with_multiple_managers(self, temp_dir):
        """Should detect packages from Conan, vcpkg, and CMake in same project."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.cpp").write_text("int main() { return 0; }")

        # Conan deps
        (project_dir / "conanfile.txt").write_text("[requires]\nfmt/10.1.1\nspdlog/1.12.0\n")

        # vcpkg deps
        (project_dir / "vcpkg.json").write_text(json.dumps({"dependencies": ["boost", "openssl"]}))

        # CMake deps
        (project_dir / "CMakeLists.txt").write_text("""
find_package(ZLIB REQUIRED)
""")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        ecosystems = set(p.ecosystem for p in result.packages)
        assert "Conan" in ecosystems
        assert "vcpkg" in ecosystems
        assert "CMake" in ecosystems

        # Should have packages from all three
        assert len(result.packages) >= 5


class TestSecurityAlertsWithReferences:
    """Tests for enhanced security alert formatting."""

    def test_security_alert_has_references(self):
        """SecurityAlert should support references field."""
        alert = SecurityAlert(
            cve_id="CVE-2023-12345",
            package="test-pkg",
            severity="HIGH",
            summary="Test vulnerability",
            fixed_version="1.2.0",
            references=["https://nvd.nist.gov/vuln/detail/CVE-2023-12345"],
        )

        assert alert.references is not None
        assert len(alert.references) == 1
        assert "nvd.nist.gov" in alert.references[0]

    def test_security_alert_empty_references(self):
        """SecurityAlert should handle empty references."""
        alert = SecurityAlert(
            cve_id="CVE-2023-99999",
            package="other-pkg",
            severity="MEDIUM",
        )

        assert alert.references == []


class TestLanguageDetectionForSecurity:
    """Tests for language detection affecting security guidelines."""

    def test_detect_cpp_language(self, temp_dir):
        """Should detect C++ and trigger C++ security guidelines."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.cpp").write_text("#include <iostream>\nint main() {}")
        (project_dir / "utils.hpp").write_text("#pragma once")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        lang_names = [lang.name for lang in result.languages]
        assert "C++" in lang_names

    def test_detect_c_language(self, temp_dir):
        """Should detect C language."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.c").write_text("#include <stdio.h>\nint main() {}")
        (project_dir / "utils.h").write_text("#ifndef UTILS_H")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        lang_names = [lang.name for lang in result.languages]
        assert "C" in lang_names

    def test_detect_swift_language(self, temp_dir):
        """Should detect Swift language."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.swift").write_text('import Foundation\nprint("Hello")')
        (project_dir / "Utils.swift").write_text("class Utils {}")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        lang_names = [lang.name for lang in result.languages]
        assert "Swift" in lang_names


class TestSecurityContextBuilding:
    """Tests for _build_security_context with new languages."""

    def test_security_context_cpp(self, temp_dir):
        """Should include cpp in security context for C++ projects."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.cpp").write_text("int main() { return 0; }")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)
        context = scanner._build_security_context(result)

        assert "cpp" in context.languages

    def test_security_context_swift(self, temp_dir):
        """Should include swift in security context for Swift projects."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.swift").write_text('print("Hello")')

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)
        context = scanner._build_security_context(result)

        assert "swift" in context.languages


class TestGeneratedConfigSecurity:
    """Tests for security section in generated config."""

    def test_config_includes_cpp_security(self, temp_dir):
        """Generated config should include C/C++ security guidelines."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.cpp").write_text("int main() { return 0; }")
        (project_dir / "conanfile.txt").write_text("[requires]\nfmt/10.1.1\n")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)
        config = scanner.generate_config(result, "cpp-project")

        # Should contain C/C++ security guidelines
        assert "C/C++" in config or "buffer" in config.lower() or "snprintf" in config.lower()

    def test_config_includes_swift_security(self, temp_dir):
        """Generated config should include Swift security guidelines."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.swift").write_text('print("Hello")')
        (project_dir / "Package.swift").write_text("""
import PackageDescription
let package = Package(name: "Test", dependencies: [])
""")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)
        config = scanner.generate_config(result, "swift-project")

        # Should contain Swift security guidelines
        assert "Swift" in config or "Keychain" in config or "iOS" in config


class TestCVEReportingEnhanced:
    """Tests for enhanced CVE reporting with links and remediation."""

    def test_cve_link_generation_nvd(self, temp_dir):
        """Should generate NVD links for CVE IDs."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.py").write_text('print("hello")')

        # Create a mock scan result with security alerts
        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        # Manually add a security alert for testing
        result.security_alerts = [
            SecurityAlert(
                cve_id="CVE-2023-12345",
                package="vulnerable-pkg",
                severity="CRITICAL",
                summary="Test vulnerability",
                fixed_version="2.0.0",
                references=["https://nvd.nist.gov/vuln/detail/CVE-2023-12345"],
            )
        ]

        config = scanner.generate_config(result, "test-project")

        # Should contain clickable CVE link
        assert "CVE-2023-12345" in config
        assert "nvd.nist.gov" in config or "https://" in config

    def test_remediation_commands_python(self, temp_dir):
        """Should generate pip remediation commands for Python CVEs."""
        project_dir = Path(temp_dir) / "project"
        project_dir.mkdir()
        (project_dir / "main.py").write_text('print("hello")')
        (project_dir / "requirements.txt").write_text("flask==2.0.0\n")

        scanner = ProjectScanner()
        result = scanner.scan(project_dir)

        # Add a mock CVE for a Python package
        result.security_alerts = [
            SecurityAlert(
                cve_id="CVE-2023-99999", package="flask", severity="HIGH", fixed_version="2.3.0"
            )
        ]

        config = scanner.generate_config(result, "test-project")

        # Should contain remediation section
        if "Remediation" in config or "pip install" in config:
            assert True  # Found remediation section
        else:
            # At least should mention the fix version
            assert "2.3.0" in config or "Mettre" in config


# =============================================================================
# PARITE ENTRE LES ECOSYSTEMES EMIS PAR LE SCANNER ET CEUX QU'ACCEPTE OSV
# =============================================================================


def _ecosystems_emitted_by_scanner() -> set:
    """Libelles passes a `DetectedPackage(ecosystem=...)` dans le scanner.

    Lecture du source plutot qu'enumeration a la main : une chaine ajoutee
    demain sans traduction OSV fait echouer le test de parite ci-dessous, au
    lieu de produire un HTTP 400 silencieux en production.
    """
    # Le scanner est un paquet : on lit tous ses modules, pas le seul
    # `__init__.py`, sinon un libelle emis par un sous-module echapperait.
    package_dir = Path(scanner_module.__file__).parent
    source = "\n".join(p.read_text(encoding="utf-8") for p in sorted(package_dir.glob("*.py")))
    return set(re.findall(r'ecosystem=["\']([^"\']+)["\']', source))


class TestScannerOsvEcosystemParity:
    """Aucun libelle emis par le scanner ne doit faire tomber une requete OSV."""

    def test_every_emitted_ecosystem_is_translated_or_declared_unsupported(self):
        emitted = _ecosystems_emitted_by_scanner()
        assert emitted, "la lecture du source n'a trouve aucun ecosysteme"

        unclassified = {
            eco
            for eco in emitted
            if normalize_osv_ecosystem(eco) is None and eco not in OSV_UNSUPPORTED_ECOSYSTEMS
        }
        assert unclassified == set(), (
            "ces libelles partiraient tels quels vers OSV et le feraient repondre "
            f"HTTP 400 : {sorted(unclassified)}"
        )

    def test_the_three_measured_rejects_are_handled(self):
        """SwiftPM, Conan et CMake : les trois cas mesures le 2026-09-04."""
        assert normalize_osv_ecosystem("SwiftPM") == "SwiftURL"
        assert normalize_osv_ecosystem("Conan") == "ConanCenter"
        assert normalize_osv_ecosystem("CMake") is None

    def test_scanner_still_labels_swift_and_conan_with_the_tooling_names(self):
        """La traduction est a la frontiere reseau, pas dans l'affichage."""
        emitted = _ecosystems_emitted_by_scanner()
        assert "SwiftPM" in emitted
        assert "Conan" in emitted


class TestCveCheckFailureReachesTheUser:
    """Une verification incomplete doit apparaitre, pas se taire."""

    def _result_with_packages(self):
        return ScanResult(
            packages=[
                DetectedPackage(
                    ecosystem="PyPI",
                    name="gradio",
                    version="4.0.0",
                    source_file="requirements.txt",
                ),
            ]
        )

    def test_unreachable_api_is_written_into_scan_errors(self):
        scanner = ProjectScanner()
        result = self._result_with_packages()

        def _boom(request, timeout=None):
            raise urllib.error.URLError("connexion refusee")

        with patch.object(urllib.request, "urlopen", _boom):
            alerts = scanner.check_security(result)

        assert alerts == []
        assert any(error.startswith(CVE_CHECK_INCOMPLETE_PREFIX) for error in result.errors)

    def test_healthy_check_adds_no_error(self):
        """Un projet sain ne doit pas ressembler a une panne."""
        scanner = ProjectScanner()
        result = self._result_with_packages()

        class _Response:
            def read(self):
                return b'{"results": [{}]}'

            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                return False

        with patch.object(urllib.request, "urlopen", lambda req, timeout=None: _Response()):
            alerts = scanner.check_security(result)

        assert alerts == []
        assert result.errors == []

    def test_generated_config_says_the_check_was_incomplete(self):
        """Sans cette section, l'absence d'alerte se lit comme « projet sain »."""
        scanner = ProjectScanner()
        result = self._result_with_packages()

        def _boom(request, timeout=None):
            raise urllib.error.URLError("connexion refusee")

        with patch.object(urllib.request, "urlopen", _boom):
            result.security_alerts = scanner.check_security(result)

        config = scanner.generate_config(result, "projet-test")

        assert "INCOMPLETE" in config
        assert "ne signifie PAS que le projet est sain" in config

    def test_generated_config_stays_silent_when_the_check_succeeded(self):
        scanner = ProjectScanner()
        result = self._result_with_packages()
        config = scanner.generate_config(result, "projet-test")

        assert "INCOMPLETE" not in config


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
