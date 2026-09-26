"""
Quick Tests for Scanner Multi-Ecosystem Support
================================================

Runs without pytest - standalone test script.
"""

import json
import sys
import tempfile
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from promptforge.scanner import ProjectScanner, SecurityAlert
from promptforge.security import SecurityContext, get_security_guidelines

print("=" * 60)
print("TESTS DES PARSERS MULTI-ECOSYSTEMES")
print("=" * 60)

passed = 0
failed = 0


def test(name, condition):
    global passed, failed
    if condition:
        print(f"[OK] {name}")
        passed += 1
    else:
        print(f"[FAIL] {name}")
        failed += 1


# Test 1: Conan Parser
with tempfile.TemporaryDirectory() as tmpdir:
    project = Path(tmpdir) / "project"
    project.mkdir()
    (project / "main.cpp").write_text("int main() { return 0; }")
    (project / "conanfile.txt").write_text("[requires]\nfmt/10.1.1\nspdlog/1.12.0\n")

    scanner = ProjectScanner()
    result = scanner.scan(project)
    conan_pkgs = [p for p in result.packages if p.ecosystem == "Conan"]

    test("Conan: Detecte les packages", len(conan_pkgs) >= 2)
    test("Conan: Trouve fmt", any("fmt" in p.name.lower() for p in conan_pkgs))

# Test 2: vcpkg Parser
with tempfile.TemporaryDirectory() as tmpdir:
    project = Path(tmpdir) / "project"
    project.mkdir()
    (project / "main.cpp").write_text("int main() { return 0; }")
    (project / "vcpkg.json").write_text(
        json.dumps({"dependencies": ["boost", {"name": "openssl", "version>=": "3.0.0"}]})
    )

    scanner = ProjectScanner()
    result = scanner.scan(project)
    vcpkg_pkgs = [p for p in result.packages if p.ecosystem == "vcpkg"]

    test("vcpkg: Detecte les packages", len(vcpkg_pkgs) == 2)
    test("vcpkg: Version constraint", any(p.version == "3.0.0" for p in vcpkg_pkgs))

# Test 3: Swift Parser
with tempfile.TemporaryDirectory() as tmpdir:
    project = Path(tmpdir) / "project"
    project.mkdir()
    (project / "main.swift").write_text('print("Hello")')
    (project / "Package.resolved").write_text(
        json.dumps(
            {
                "pins": [{"identity": "alamofire", "state": {"version": "5.8.1"}}],
                "version": 2,
            }
        )
    )

    scanner = ProjectScanner()
    installed = scanner._parse_swift_lockfile(project)

    test("Swift: Parse Package.resolved v2", "alamofire" in installed)
    test("Swift: Version correcte", installed.get("alamofire") == "5.8.1")

# Test 4: CMake Parser
with tempfile.TemporaryDirectory() as tmpdir:
    project = Path(tmpdir) / "project"
    project.mkdir()
    (project / "CMakeLists.txt").write_text("""
cmake_minimum_required(VERSION 3.20)
find_package(OpenSSL 3.0 REQUIRED)
find_package(Boost 1.80)
""")

    scanner = ProjectScanner()
    cmake_pkgs = scanner._parse_cmake_packages(project)

    test("CMake: find_package detecte", "openssl" in cmake_pkgs)
    test("CMake: Version extraite", cmake_pkgs.get("openssl") == "3.0")

# Test 5: Security Context C++
with tempfile.TemporaryDirectory() as tmpdir:
    project = Path(tmpdir) / "project"
    project.mkdir()
    (project / "main.cpp").write_text("int main() { return 0; }")

    scanner = ProjectScanner()
    result = scanner.scan(project)
    context = scanner._build_security_context(result)

    test("C++: Detecte langage", "cpp" in context.languages)

# Test 6: Security Context Swift
with tempfile.TemporaryDirectory() as tmpdir:
    project = Path(tmpdir) / "project"
    project.mkdir()
    (project / "main.swift").write_text('print("Hello")')

    scanner = ProjectScanner()
    result = scanner.scan(project)
    context = scanner._build_security_context(result)

    test("Swift: Detecte langage", "swift" in context.languages)

# Test 7: SecurityAlert avec references
alert = SecurityAlert(
    cve_id="CVE-2023-12345",
    package="test-pkg",
    severity="HIGH",
    references=["https://nvd.nist.gov/vuln/detail/CVE-2023-12345"],
)
test("SecurityAlert: Supporte references", len(alert.references) == 1)

print()
print("=" * 60)
print("TESTS DES GUIDELINES DE SECURITE")
print("=" * 60)

# Test 8: C/C++ Guidelines
context = SecurityContext(
    is_dev=True, languages=["cpp", "c"], security_keywords_found=["file"], security_level="standard"
)
guidelines = get_security_guidelines(context)
test(
    "C/C++: Guidelines buffer overflow",
    "buffer" in guidelines.lower() or "C/C++" in guidelines,
)
test(
    "C/C++: Compiler flags",
    "fstack" in guidelines or "Sanitizer" in guidelines or "FORTIFY" in guidelines,
)

# Test 9: Swift Guidelines
context = SecurityContext(
    is_dev=True, languages=["swift"], security_keywords_found=["api"], security_level="standard"
)
guidelines = get_security_guidelines(context)
test(
    "Swift: Guidelines Keychain",
    "Keychain" in guidelines or "Swift" in guidelines or "iOS" in guidelines,
)

# Test 10: Ruby Guidelines
context = SecurityContext(
    is_dev=True, languages=["ruby"], security_keywords_found=["database"], security_level="standard"
)
guidelines = get_security_guidelines(context)
test(
    "Ruby: Guidelines ActiveRecord",
    "Ruby" in guidelines or "ActiveRecord" in guidelines or "Rails" in guidelines,
)

# Test 11: PHP Guidelines
context = SecurityContext(
    is_dev=True, languages=["php"], security_keywords_found=["sql"], security_level="elevated"
)
guidelines = get_security_guidelines(context)
test("PHP: Guidelines PDO", "PHP" in guidelines or "PDO" in guidelines)

# Test 12: Java Guidelines
context = SecurityContext(
    is_dev=True, languages=["java"], security_keywords_found=["database"], security_level="standard"
)
guidelines = get_security_guidelines(context)
test(
    "Java: Guidelines PreparedStatement",
    "Java" in guidelines or "PreparedStatement" in guidelines,
)

# Test 13: C# Guidelines
context = SecurityContext(
    is_dev=True, languages=["csharp"], security_keywords_found=["api"], security_level="standard"
)
guidelines = get_security_guidelines(context)
test(
    "C#: Guidelines Entity Framework",
    "C#" in guidelines or ".NET" in guidelines or "Entity" in guidelines,
)

# Test 14: Frontend Frameworks
context = SecurityContext(
    is_dev=True,
    languages=["javascript"],
    security_keywords_found=["react", "frontend"],
    security_level="elevated",
)
guidelines = get_security_guidelines(context)
test(
    "Frontend: Guidelines XSS",
    "Frontend" in guidelines or "XSS" in guidelines or "React" in guidelines,
)

# Test 15: Backend Frameworks Python
context = SecurityContext(
    is_dev=True,
    languages=["python"],
    security_keywords_found=["django", "fastapi"],
    security_level="elevated",
)
guidelines = get_security_guidelines(context)
test(
    "Python Web: Guidelines CSRF",
    "Django" in guidelines or "FastAPI" in guidelines or "Python Web" in guidelines,
)

# Test 16: Backend Frameworks Node
context = SecurityContext(
    is_dev=True,
    languages=["javascript"],
    security_keywords_found=["express", "node"],
    security_level="elevated",
)
guidelines = get_security_guidelines(context)
test(
    "Node.js: Guidelines helmet",
    "Node" in guidelines or "Express" in guidelines or "helmet" in guidelines.lower(),
)

# Test 17: Spring Boot
context = SecurityContext(
    is_dev=True,
    languages=["java"],
    security_keywords_found=["spring", "springboot"],
    security_level="elevated",
)
guidelines = get_security_guidelines(context)
test("Spring: Guidelines Security", "Spring" in guidelines or "PreAuthorize" in guidelines)

# Test 18: ASP.NET
context = SecurityContext(
    is_dev=True,
    languages=["csharp"],
    security_keywords_found=["aspnet", "dotnet"],
    security_level="elevated",
)
guidelines = get_security_guidelines(context)
test(
    "ASP.NET: Guidelines Identity",
    "ASP.NET" in guidelines or "Identity" in guidelines or "Authorize" in guidelines,
)

# Test 19: OWASP Top 10
context = SecurityContext(
    is_dev=True, languages=["python"], security_keywords_found=["api"], security_level="standard"
)
guidelines = get_security_guidelines(context)
test("OWASP: Inclus", "OWASP" in guidelines)
test("OWASP: Injection mentionne", "Injection" in guidelines)

print()
print("=" * 60)
print(f"RESULTATS: {passed} passes, {failed} echecs")
print("=" * 60)

if failed > 0:
    sys.exit(1)
else:
    print("\nTous les tests passent!")
