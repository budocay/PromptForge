"""Lecture des manifestes et lockfiles, par ecosysteme."""

import re
from pathlib import Path


class LockfileParsersMixin:
    """Parseurs de lockfiles partages par `ProjectScanner`."""

    def _get_installed_packages(self) -> dict[str, str]:
        """
        Get actually installed Python package versions using importlib.metadata.
        Returns dict mapping package_name (lowercase) -> version.
        """
        installed = {}
        try:
            from importlib.metadata import distributions

            for dist in distributions():
                name = dist.metadata.get("Name", "").lower()
                version = dist.metadata.get("Version", "")
                if name and version:
                    installed[name] = version
                    # Also add with underscores replaced by hyphens and vice versa
                    installed[name.replace("-", "_")] = version
                    installed[name.replace("_", "-")] = version
        except Exception:
            pass
        return installed

    def _parse_npm_lockfile(self, path: Path) -> dict[str, str]:
        """
        Parse package-lock.json for installed npm package versions.
        Returns dict mapping package_name -> version.
        """
        installed = {}
        lockfile = path / "package-lock.json"
        if not lockfile.exists():
            return installed

        content = self._safe_read_file(lockfile)
        if not content:
            return installed

        try:
            import json

            data = json.loads(content)

            # package-lock.json v2/v3 format (packages field)
            if "packages" in data:
                for pkg_path, pkg_info in data["packages"].items():
                    if pkg_path.startswith("node_modules/"):
                        name = pkg_path.replace("node_modules/", "").split("/")[0]
                        # Handle scoped packages (@org/pkg)
                        if name.startswith("@") and "/" in pkg_path.replace("node_modules/", ""):
                            parts = pkg_path.replace("node_modules/", "").split("/")
                            name = f"{parts[0]}/{parts[1]}"
                        version = pkg_info.get("version", "")
                        if name and version:
                            installed[name.lower()] = version

            # package-lock.json v1 format (dependencies field)
            elif "dependencies" in data:
                for name, info in data["dependencies"].items():
                    version = info.get("version", "")
                    if version:
                        installed[name.lower()] = version
        except Exception:
            pass

        return installed

    def _parse_cargo_lockfile(self, path: Path) -> dict[str, str]:
        """
        Parse Cargo.lock for installed Rust crate versions.
        Returns dict mapping crate_name -> version.
        """
        installed = {}
        lockfile = path / "Cargo.lock"
        if not lockfile.exists():
            return installed

        content = self._safe_read_file(lockfile)
        if not content:
            return installed

        # Parse TOML-like format: [[package]] name = "x" version = "y"
        current_name = None
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("name = "):
                current_name = line.split('"')[1] if '"' in line else None
            elif line.startswith("version = ") and current_name:
                version = line.split('"')[1] if '"' in line else None
                if version:
                    installed[current_name.lower()] = version
                current_name = None

        return installed

    def _parse_go_sum(self, path: Path) -> dict[str, str]:
        """
        Parse go.sum for Go module versions.
        Returns dict mapping module_path -> version.
        """
        installed = {}
        sumfile = path / "go.sum"
        if not sumfile.exists():
            return installed

        content = self._safe_read_file(sumfile)
        if not content:
            return installed

        for line in content.split("\n"):
            parts = line.strip().split()
            if len(parts) >= 2:
                module = parts[0]
                version = parts[1].lstrip("v").split("/")[0]  # Remove v prefix and /go.mod suffix
                if module and version and not version.endswith("/go.mod"):
                    # Use last part of module path as name
                    name = module.split("/")[-1] if "/" in module else module
                    installed[name.lower()] = version
                    installed[module.lower()] = version  # Also store full path

        return installed

    def _parse_composer_lockfile(self, path: Path) -> dict[str, str]:
        """
        Parse composer.lock for PHP package versions.
        Returns dict mapping package_name -> version.
        """
        installed = {}
        lockfile = path / "composer.lock"
        if not lockfile.exists():
            return installed

        content = self._safe_read_file(lockfile)
        if not content:
            return installed

        try:
            import json

            data = json.loads(content)

            for pkg in data.get("packages", []):
                name = pkg.get("name", "")
                version = pkg.get("version", "").lstrip("v")
                if name and version:
                    installed[name.lower()] = version
                    # Also store just the package name without vendor
                    if "/" in name:
                        installed[name.split("/")[1].lower()] = version

            for pkg in data.get("packages-dev", []):
                name = pkg.get("name", "")
                version = pkg.get("version", "").lstrip("v")
                if name and version:
                    installed[name.lower()] = version
        except Exception:
            pass

        return installed

    def _parse_gemfile_lockfile(self, path: Path) -> dict[str, str]:
        """
        Parse Gemfile.lock for Ruby gem versions.
        Returns dict mapping gem_name -> version.
        """
        installed = {}
        lockfile = path / "Gemfile.lock"
        if not lockfile.exists():
            return installed

        content = self._safe_read_file(lockfile)
        if not content:
            return installed

        # Parse GEM section
        in_specs = False
        for line in content.split("\n"):
            if "specs:" in line:
                in_specs = True
                continue
            if in_specs:
                if line and not line.startswith(" "):
                    in_specs = False
                    continue
                # Match "    gem_name (version)"
                match = re.match(r"^\s{4}([a-zA-Z0-9_-]+)\s+\(([0-9.]+)", line)
                if match:
                    name = match.group(1)
                    version = match.group(2)
                    installed[name.lower()] = version

        return installed

    def _parse_nuget_lockfile(self, path: Path) -> dict[str, str]:
        """
        Parse packages.lock.json or *.csproj for .NET package versions.
        Returns dict mapping package_name -> version.
        """
        installed = {}

        # Try packages.lock.json first (NuGet lock file)
        lockfile = path / "packages.lock.json"
        if lockfile.exists():
            content = self._safe_read_file(lockfile)
            if content:
                try:
                    import json

                    data = json.loads(content)
                    for framework, deps in data.get("dependencies", {}).items():
                        for name, info in deps.items():
                            version = info.get("resolved", "")
                            if version:
                                installed[name.lower()] = version
                except Exception:
                    pass

        # Also try parsing .csproj files for PackageReference
        for csproj in path.glob("*.csproj"):
            content = self._safe_read_file(csproj)
            if content:
                for match in re.finditer(
                    r'<PackageReference\s+Include="([^"]+)"\s+Version="([^"]+)"', content
                ):
                    name = match.group(1)
                    version = match.group(2)
                    if name and version:
                        installed[name.lower()] = version

        return installed

    def _parse_gradle_lockfile(self, path: Path) -> dict[str, str]:
        """
        Parse gradle.lockfile or build.gradle for Java/Kotlin dependency versions.
        Returns dict mapping artifact_name -> version.
        """
        installed = {}

        # Try gradle.lockfile
        lockfile = path / "gradle.lockfile"
        if lockfile.exists():
            content = self._safe_read_file(lockfile)
            if content:
                for line in content.split("\n"):
                    # Format: group:artifact:version=hash
                    if ":" in line and "=" in line:
                        parts = line.split("=")[0].split(":")
                        if len(parts) >= 3:
                            artifact = parts[1]
                            version = parts[2]
                            installed[artifact.lower()] = version

        # Also try build.gradle
        for gradle_file in ["build.gradle", "build.gradle.kts"]:
            gradle_path = path / gradle_file
            if gradle_path.exists():
                content = self._safe_read_file(gradle_path)
                if content:
                    # Match implementation 'group:artifact:version'
                    for match in re.finditer(
                        r"(?:implementation|api|compile)\s*['\"]([^:]+):([^:]+):([^'\"]+)['\"]",
                        content,
                    ):
                        artifact = match.group(2)
                        version = match.group(3)
                        installed[artifact.lower()] = version

        return installed

    def _parse_maven_lockfile(self, path: Path) -> dict[str, str]:
        """
        Parse pom.xml for Maven dependency versions.
        Returns dict mapping artifact_name -> version.
        """
        installed = {}
        pom_file = path / "pom.xml"
        if not pom_file.exists():
            return installed

        content = self._safe_read_file(pom_file)
        if not content:
            return installed

        # Simple regex parsing for <dependency> blocks
        # Match <artifactId>xxx</artifactId> followed by <version>yyy</version>
        for match in re.finditer(
            r"<artifactId>([^<]+)</artifactId>\s*<version>([^<]+)</version>", content, re.DOTALL
        ):
            artifact = match.group(1).strip()
            version = match.group(2).strip()
            # Skip version variables like ${project.version}
            if version and not version.startswith("$"):
                installed[artifact.lower()] = version

        return installed

    def _parse_conan_lockfile(self, path: Path) -> dict[str, str]:
        """
        Parse conan.lock for C/C++ Conan package versions.
        Returns dict mapping package_name -> version.
        """
        installed = {}

        # Try conan.lock (Conan 2.x format - JSON)
        lockfile = path / "conan.lock"
        if lockfile.exists():
            content = self._safe_read_file(lockfile)
            if content:
                try:
                    import json

                    data = json.loads(content)
                    # Conan 2.x format: {"requires": ["pkg/version@...", ...]}
                    for req in data.get("requires", []):
                        # Format: "package/version@user/channel" or "package/version"
                        if "/" in req:
                            parts = req.split("/")
                            name = parts[0]
                            version = parts[1].split("@")[0] if "@" in parts[1] else parts[1]
                            installed[name.lower()] = version
                except Exception:
                    pass

        # Try conanfile.lock (Conan 1.x format)
        lockfile_v1 = path / "conanfile.lock"
        if lockfile_v1.exists():
            content = self._safe_read_file(lockfile_v1)
            if content:
                try:
                    import json

                    data = json.loads(content)
                    # Conan 1.x: graph_lock.nodes
                    nodes = data.get("graph_lock", {}).get("nodes", {})
                    for node_id, node_info in nodes.items():
                        ref = node_info.get("ref", "")
                        if "/" in ref:
                            parts = ref.split("/")
                            name = parts[0]
                            version = parts[1].split("@")[0] if "@" in parts[1] else parts[1]
                            installed[name.lower()] = version
                except Exception:
                    pass

        return installed

    def _parse_vcpkg_lockfile(self, path: Path) -> dict[str, str]:
        """
        Parse vcpkg.json and vcpkg-configuration.json for C/C++ vcpkg package versions.
        Returns dict mapping package_name -> version.
        """
        installed = {}

        # vcpkg.json manifest
        manifest = path / "vcpkg.json"
        if manifest.exists():
            content = self._safe_read_file(manifest)
            if content:
                try:
                    import json

                    data = json.loads(content)

                    # Dependencies can be strings or objects
                    for dep in data.get("dependencies", []):
                        if isinstance(dep, str):
                            # Simple dependency: "boost"
                            installed[dep.lower()] = "latest"
                        elif isinstance(dep, dict):
                            # Object: {"name": "boost", "version>=": "1.80.0"}
                            name = dep.get("name", "")
                            version = dep.get("version>=", dep.get("version", "latest"))
                            if name:
                                installed[name.lower()] = str(version)

                    # Check overrides for pinned versions
                    for override in data.get("overrides", []):
                        name = override.get("name", "")
                        version = override.get("version", "")
                        if name and version:
                            installed[name.lower()] = version
                except Exception:
                    pass

        # Also check vcpkg_installed directory for actual versions
        vcpkg_installed = path / "vcpkg_installed"
        if vcpkg_installed.exists():
            # Look for status file
            for status_file in vcpkg_installed.glob("*/status"):
                content = self._safe_read_file(status_file)
                if content:
                    current_pkg = None
                    for line in content.split("\n"):
                        if line.startswith("Package: "):
                            current_pkg = line.split(": ", 1)[1].strip()
                        elif line.startswith("Version: ") and current_pkg:
                            version = line.split(": ", 1)[1].strip()
                            installed[current_pkg.lower()] = version
                            current_pkg = None

        return installed

    def _parse_swift_lockfile(self, path: Path) -> dict[str, str]:
        """
        Parse Package.resolved for Swift package versions.
        Returns dict mapping package_name -> version.
        """
        installed = {}

        # Package.resolved (Swift Package Manager)
        resolved = path / "Package.resolved"
        if not resolved.exists():
            # Also check in .build directory
            resolved = path / ".build" / "Package.resolved"

        if not resolved.exists():
            return installed

        content = self._safe_read_file(resolved)
        if not content:
            return installed

        try:
            import json

            data = json.loads(content)

            # Version 2 format (Swift 5.6+)
            if "pins" in data:
                for pin in data.get("pins", []):
                    identity = pin.get("identity", "")
                    state = pin.get("state", {})
                    version = state.get("version", state.get("revision", "")[:8])
                    if identity and version:
                        installed[identity.lower()] = version

            # Version 1 format (older Swift)
            elif "object" in data:
                pins = data.get("object", {}).get("pins", [])
                for pin in pins:
                    name = pin.get("package", "")
                    state = pin.get("state", {})
                    version = state.get("version", state.get("revision", "")[:8])
                    if name and version:
                        installed[name.lower()] = version
        except Exception:
            pass

        return installed

    def _parse_cmake_packages(self, path: Path) -> dict[str, str]:
        """
        Parse CMakeLists.txt for find_package and FetchContent dependencies.
        Returns dict mapping package_name -> version (or 'detected').
        """
        installed = {}

        cmake_file = path / "CMakeLists.txt"
        if not cmake_file.exists():
            return installed

        content = self._safe_read_file(cmake_file)
        if not content:
            return installed

        # find_package(PackageName VERSION x.y.z)
        for match in re.finditer(
            r"find_package\s*\(\s*(\w+)(?:\s+(\d+(?:\.\d+)*))?", content, re.IGNORECASE
        ):
            name = match.group(1)
            version = match.group(2) or "detected"
            installed[name.lower()] = version

        # FetchContent_Declare with GIT_TAG
        for match in re.finditer(
            r'FetchContent_Declare\s*\(\s*(\w+).*?GIT_TAG\s+["\']?v?(\d+\.\d+(?:\.\d+)?)["\']?',
            content,
            re.IGNORECASE | re.DOTALL,
        ):
            name = match.group(1)
            version = match.group(2)
            installed[name.lower()] = version

        return installed
