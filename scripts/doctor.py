#!/usr/bin/env python3
"""
LocalTopSH Security Doctor - Audit security configuration

Usage:
    python scripts/doctor.py
    python scripts/doctor.py --fix
    python scripts/doctor.py --json
"""

import os
import sys
import json
import stat
import socket
import argparse
import shutil
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Iterator, Optional

import yaml

# Colors
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"
BOLD = "\033[1m"

COMPOSE_FILES = ("docker-compose.yml", "victoriametrics/docker-compose.yml")
# Caddy is the public entrypoint by design; everything else must stay on loopback.
PUBLIC_BY_DESIGN = {("caddy", 80), ("caddy", 443)}


def _compose_services(compose_path: Path) -> dict:
    payload = yaml.safe_load(compose_path.read_text(encoding="utf-8")) or {}
    services = payload.get("services", {})
    return services if isinstance(services, dict) else {}


def iter_published_ports(compose_path: Path) -> Iterator[tuple[str, str]]:
    """Yield (service, raw port spec) for every published port."""
    for service, config in _compose_services(compose_path).items():
        if not isinstance(config, dict):
            continue
        ports = config.get("ports", [])
        if not isinstance(ports, list):
            continue
        for port in ports:
            if isinstance(port, dict):
                published = port.get("published")
                target = port.get("target")
                if published is None or target is None:
                    continue
                host_ip = port.get("host_ip")
                raw_spec = f"{host_ip}:{published}:{target}" if host_ip else f"{published}:{target}"
            else:
                raw_spec = str(port)
            yield str(service), raw_spec


def service_networks(compose_path: Path) -> dict[str, list[str]]:
    """Return declared networks per service."""
    result: dict[str, list[str]] = {}
    for service, config in _compose_services(compose_path).items():
        networks = config.get("networks", []) if isinstance(config, dict) else []
        if isinstance(networks, dict):
            result[str(service)] = [str(network) for network in networks]
        elif isinstance(networks, list):
            result[str(service)] = [str(network) for network in networks]
        else:
            result[str(service)] = []
    return result


def _target_port(raw_spec: str) -> Optional[int]:
    target = raw_spec.rsplit(":", 1)[-1].split("/", 1)[0]
    try:
        return int(target)
    except ValueError:
        return None


@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str
    severity: str  # critical, high, medium, low
    fix_hint: Optional[str] = None


class SecurityDoctor:
    """Security audit for LocalTopSH"""
    
    def __init__(self, project_root: Path):
        self.root = project_root
        self.results: list[CheckResult] = []
    
    def check(self, name: str, passed: bool, message: str, 
              severity: str = "medium", fix_hint: str = None):
        """Add check result"""
        self.results.append(CheckResult(
            name=name,
            passed=passed,
            message=message,
            severity=severity,
            fix_hint=fix_hint
        ))
    
    def run_all_checks(self):
        """Run all security checks"""
        print(f"""
{BOLD}🛡️ LocalTopSH Security Doctor{RESET}

Checking 5 layers of protection:
  • ACCESS   - DM Policy configuration
  • INPUT    - Blocked patterns & injection defense
  • SANDBOX  - Docker isolation & resource limits
  • SECRETS  - Proxy architecture & key protection
  • OUTPUT   - Sanitization & encoding detection
""")
        print("=" * 60)
        
        self.check_secrets()
        self.check_docker_compose()
        self.check_blocked_patterns()
        self.check_injection_patterns()
        self.check_network_exposure()
        self.check_file_permissions()
        self.check_workspace_permissions()
        self.check_access_mode()
        self.check_resource_limits()
        self.check_corp_db_rfc026_schema()
        
        print("=" * 60)
        self.print_summary()
    
    def check_secrets(self):
        """Check secrets configuration"""
        print(f"\n{BLUE}[1/8] Checking secrets...{RESET}")
        
        secrets_dir = self.root / "secrets"
        
        # Check secrets directory exists
        if not secrets_dir.exists():
            self.check("secrets_dir", False, "secrets/ directory not found",
                      "critical", "mkdir secrets && touch secrets/.gitkeep")
            return
        
        self.check("secrets_dir", True, "secrets/ directory exists")
        
        # Check required secrets
        required = ["telegram_token.txt", "api_key.txt", "base_url.txt"]
        for secret in required:
            path = secrets_dir / secret
            if path.exists():
                # Check not empty
                content = path.read_text().strip()
                if content:
                    self.check(f"secret_{secret}", True, f"{secret} configured")
                else:
                    self.check(f"secret_{secret}", False, f"{secret} is empty",
                              "critical", f"echo 'your-value' > secrets/{secret}")
            else:
                self.check(f"secret_{secret}", False, f"{secret} missing",
                          "critical", f"echo 'your-value' > secrets/{secret}")
        
        # Check file permissions (644 for Docker Compose, 600 for Swarm)
        # Note: Docker Compose file-based secrets need 644 to be readable in containers
        for f in secrets_dir.glob("*.txt"):
            mode = f.stat().st_mode
            mode_oct = mode & 0o777
            # Accept 600 (secure) or 644 (Docker Compose compatible)
            is_secure = mode_oct in (0o600, 0o644)
            self.check(f"perm_{f.name}", is_secure,
                      f"{f.name} permissions: {oct(mode_oct)}",
                      "high" if not is_secure else "low",
                      f"chmod 644 secrets/{f.name}  # For Docker Compose")
        
        # Check .gitignore
        gitignore = self.root / ".gitignore"
        if gitignore.exists():
            content = gitignore.read_text()
            has_secrets = "secrets/" in content or "secrets/*" in content
            self.check("gitignore_secrets", has_secrets,
                      "secrets/ in .gitignore" if has_secrets else "secrets/ NOT in .gitignore!",
                      "critical" if not has_secrets else "low",
                      "echo 'secrets/' >> .gitignore")
    
    def check_docker_compose(self):
        """Check docker-compose.yml security"""
        print(f"\n{BLUE}[2/8] Checking docker-compose.yml...{RESET}")
        
        compose_paths = [self.root / relative_path for relative_path in COMPOSE_FILES]
        missing_paths = [path.relative_to(self.root) for path in compose_paths if not path.exists()]
        if missing_paths:
            self.check(
                "docker_compose",
                False,
                f"Compose files not found: {', '.join(map(str, missing_paths))}",
                "critical",
            )
        existing_paths = [path for path in compose_paths if path.exists()]
        if not existing_paths:
            return

        content = "\n".join(path.read_text(encoding="utf-8") for path in existing_paths)
        
        # Check no-new-privileges
        has_no_new_priv = "no-new-privileges" in content
        self.check("no_new_privileges", has_no_new_priv,
                  "no-new-privileges enabled" if has_no_new_priv else "no-new-privileges NOT set",
                  "high")
        
        # Check resource limits
        has_mem_limit = "mem_limit" in content or "memory:" in content
        self.check("memory_limits", has_mem_limit,
                  "Memory limits configured" if has_mem_limit else "No memory limits!",
                  "high")
        
        has_cpu_limit = "cpu" in content.lower()
        self.check("cpu_limits", has_cpu_limit,
                  "CPU limits configured" if has_cpu_limit else "No CPU limits!",
                  "medium")
        
        has_pids_limit = "pids_limit" in content or "pids:" in content
        self.check("pids_limit", has_pids_limit,
                  "PIDs limit configured" if has_pids_limit else "No PIDs limit (fork bomb risk)",
                  "high")
        
        # Check secrets usage
        uses_secrets = "secrets:" in content
        self.check("docker_secrets", uses_secrets,
                  "Using Docker secrets" if uses_secrets else "Not using Docker secrets!",
                  "high")
        
        # Check no env vars with actual secret values (not just references)
        import re
        # Look for actual secret values in env vars (e.g. API_KEY=sk-xxx)
        # Exclude Docker secrets references (just names like 'api_key', 'telegram_token')
        env_secrets = re.findall(r'(API_KEY|TOKEN|SECRET|PASSWORD)\s*[=:]\s*["\']?[A-Za-z0-9_-]{20,}', content, re.IGNORECASE)
        has_env_secrets = len(env_secrets) > 0
        self.check("no_env_secrets", not has_env_secrets,
                  "No hardcoded secrets in environment" if not has_env_secrets else f"Found hardcoded secrets: {env_secrets}",
                  "critical" if has_env_secrets else "low")
    
    def check_blocked_patterns(self):
        """Check blocked patterns configuration"""
        print(f"\n{BLUE}[3/8] Checking blocked patterns...{RESET}")
        
        patterns_file = self.root / "core" / "src" / "approvals" / "blocked-patterns.json"
        
        if not patterns_file.exists():
            self.check("blocked_patterns", False, "blocked-patterns.json not found", "critical")
            return
        
        try:
            data = json.loads(patterns_file.read_text())
            patterns = data.get("patterns", [])
            count = len(patterns)
            
            self.check("blocked_patterns_count", count >= 200,
                      f"{count} blocked patterns loaded",
                      "medium" if count < 200 else "low")
            
            # Check critical categories
            categories = set(p.get("category", "") for p in patterns)
            critical_cats = ["env_leak", "docker_secrets", "exfiltration", "reverse_shell"]
            
            for cat in critical_cats:
                has_cat = cat in categories
                self.check(f"category_{cat}", has_cat,
                          f"Category '{cat}' present" if has_cat else f"Missing category: {cat}",
                          "high" if not has_cat else "low")
                          
        except Exception as e:
            self.check("blocked_patterns", False, f"Error parsing: {e}", "critical")
    
    def check_injection_patterns(self):
        """Check prompt injection patterns"""
        print(f"\n{BLUE}[4/8] Checking prompt injection patterns...{RESET}")
        
        patterns_file = self.root / "bot" / "prompt-injection-patterns.json"
        
        if not patterns_file.exists():
            self.check("injection_patterns", False, "prompt-injection-patterns.json not found", "high")
            return
        
        try:
            data = json.loads(patterns_file.read_text())
            patterns = data.get("patterns", [])
            count = len(patterns)
            
            self.check("injection_patterns_count", count >= 15,
                      f"{count} injection patterns loaded",
                      "medium" if count < 15 else "low")
            
            # Check key patterns exist
            all_patterns = " ".join(p.get("pattern", "") for p in patterns)
            key_checks = [
                ("forget", "forget instructions"),
                ("ignore", "ignore previous"),
                ("system", "[system] tag"),
                ("jailbreak", "jailbreak"),
                ("DAN", "DAN mode"),
            ]
            
            for key, desc in key_checks:
                has_key = key.lower() in all_patterns.lower()
                self.check(f"injection_{key}", has_key,
                          f"Pattern for '{desc}'" if has_key else f"Missing: {desc}",
                          "medium" if not has_key else "low")
                          
        except Exception as e:
            self.check("injection_patterns", False, f"Error parsing: {e}", "high")
    
    def check_network_exposure(self):
        """Check network exposure"""
        print(f"\n{BLUE}[5/8] Checking network exposure...{RESET}")
        
        compose_paths = [self.root / relative_path for relative_path in COMPOSE_FILES]
        existing_paths = [path for path in compose_paths if path.exists()]
        if not existing_paths:
            return

        networks_by_service: dict[str, list[str]] = {}
        has_internal = False
        for compose_path in existing_paths:
            relative_path = compose_path.relative_to(self.root)
            for service, raw_spec in iter_published_ports(compose_path):
                target_port = _target_port(raw_spec)
                public_by_design = target_port is not None and (service, target_port) in PUBLIC_BY_DESIGN
                loopback_only = raw_spec.startswith("127.0.0.1:")
                safe = public_by_design or loopback_only
                self.check(
                    f"port_{service}_{target_port or raw_spec}",
                    safe,
                    f"{service} port {raw_spec} is restricted appropriately"
                    if safe
                    else f"{service} port {raw_spec} in {relative_path} is published beyond loopback!",
                    "high" if not safe else "low",
                    None if safe else f"Change to '127.0.0.1:{raw_spec}'",
                )

            networks_by_service.update(service_networks(compose_path))
            payload = yaml.safe_load(compose_path.read_text(encoding="utf-8")) or {}
            declared_networks = payload.get("networks", {})
            if isinstance(declared_networks, dict):
                has_internal = has_internal or any(
                    isinstance(config, dict) and "internal" in config
                    for config in declared_networks.values()
                )

        admin_networks = networks_by_service.get("admin", [])
        self.check(
            "admin_networks",
            set(admin_networks) == {"admin-net"},
            "admin is isolated on admin-net"
            if set(admin_networks) == {"admin-net"}
            else f"admin networks must be exactly admin-net, found: {admin_networks}",
            "critical" if set(admin_networks) != {"admin-net"} else "low",
            "Remove agent-net and any other networks from the admin service",
        )

        core_networks = set(networks_by_service.get("core", []))
        core_is_bridged = {"agent-net", "admin-net"}.issubset(core_networks)
        self.check(
            "core_networks",
            core_is_bridged,
            "core bridges agent-net and admin-net"
            if core_is_bridged
            else f"core must join agent-net and admin-net, found: {sorted(core_networks)}",
            "critical" if not core_is_bridged else "low",
        )

        unexpected_admin_members = sorted(
            service
            for service, networks in networks_by_service.items()
            if service not in {"admin", "core"} and "admin-net" in networks
        )
        self.check(
            "admin_net_isolation",
            not unexpected_admin_members,
            "Only admin and core join admin-net"
            if not unexpected_admin_members
            else f"Unexpected services on admin-net: {', '.join(unexpected_admin_members)}",
            "critical" if unexpected_admin_members else "low",
            "Remove admin-net from every service except admin and core",
        )

        self.check(
            "internal_network",
            has_internal,
            "Internal network setting declared"
            if has_internal
            else "No explicit internal network setting found",
            "medium" if not has_internal else "low",
        )
    
    def check_file_permissions(self):
        """Check file permissions"""
        print(f"\n{BLUE}[6/8] Checking file permissions...{RESET}")
        
        # Check sensitive files
        sensitive_files = [
            ("secrets/", "700"),
            (".env", "600"),
            ("docker-compose.yml", "644"),
        ]
        
        for path, expected in sensitive_files:
            full_path = self.root / path
            if full_path.exists():
                mode = full_path.stat().st_mode
                actual = oct(mode & 0o777)
                is_ok = actual == f"0o{expected}"
                self.check(f"perm_{path}", is_ok,
                          f"{path}: {actual}" + ("" if is_ok else f" (should be {expected})"),
                          "medium" if not is_ok else "low",
                          f"chmod {expected} {path}")

    def check_workspace_permissions(self):
        """Check host bind-mount workspace is writable by core."""
        print(f"\n{BLUE}[7/9] Checking workspace bind mount...{RESET}")

        workspace = self.root / "workspace"
        shared = workspace / "_shared"
        for path in (workspace, shared):
            if not path.exists():
                self.check(
                    f"workspace_{path.name}",
                    False,
                    f"{path.relative_to(self.root)} missing",
                    "high",
                    f"mkdir -p {path.relative_to(self.root)} && chmod 777 {path.relative_to(self.root)}",
                )
                continue

            writable = os.access(path, os.W_OK | os.X_OK)
            mode = oct(path.stat().st_mode & 0o777)
            self.check(
                f"workspace_{path.name}",
                writable,
                f"{path.relative_to(self.root)} writable ({mode})" if writable else f"{path.relative_to(self.root)} not writable ({mode})",
                "high" if not writable else "low",
                f"chmod 777 {path.relative_to(self.root)}",
            )
    
    def check_access_mode(self):
        """Check access control mode"""
        print(f"\n{BLUE}[8/9] Checking access control...{RESET}")
        
        # Check if access.py exists
        access_file = self.root / "bot" / "access.py"
        self.check("access_module", access_file.exists(),
                  "access.py module present" if access_file.exists() else "access.py missing!",
                  "high" if not access_file.exists() else "low")
        
        # Check ACCESS_MODE env (from docker-compose or .env)
        compose_file = self.root / "docker-compose.yml"
        if compose_file.exists():
            content = compose_file.read_text()
            
            # Check if ACCESS_MODE is set
            has_access_mode = "ACCESS_MODE" in content
            
            # Check if public mode (risky)
            is_public = "ACCESS_MODE=public" in content or "ACCESS_MODE: public" in content
            
            if is_public:
                self.check("access_mode", False,
                          "ACCESS_MODE=public (risky!)",
                          "high",
                          "Change to ACCESS_MODE=admin or ACCESS_MODE=allowlist")
            elif has_access_mode:
                self.check("access_mode", True, "ACCESS_MODE configured")
            else:
                self.check("access_mode", True, "ACCESS_MODE defaults to 'admin' (safe)")
        
        # Check ADMIN_USER_ID is set
        admin_id = os.getenv("ADMIN_USER_ID", "")
        if compose_file.exists():
            content = compose_file.read_text()
            has_admin = "ADMIN_USER_ID" in content
            self.check("admin_user_id", has_admin,
                      "ADMIN_USER_ID configured" if has_admin else "ADMIN_USER_ID not set!",
                      "high" if not has_admin else "low")
    
    def check_resource_limits(self):
        """Check resource limits in sandbox"""
        print(f"\n{BLUE}[9/9] Checking sandbox limits...{RESET}")
        
        sandbox_file = self.root / "core" / "tools" / "sandbox.py"
        if not sandbox_file.exists():
            self.check("sandbox", False, "sandbox.py not found", "high")
            return
        
        content = sandbox_file.read_text()
        
        # Check memory limit
        has_mem = "mem_limit" in content
        self.check("sandbox_memory", has_mem,
                  "Sandbox memory limit set" if has_mem else "No sandbox memory limit!",
                  "high")
        
        # Check CPU limit
        has_cpu = "cpu_quota" in content or "cpu_period" in content
        self.check("sandbox_cpu", has_cpu,
                  "Sandbox CPU limit set" if has_cpu else "No sandbox CPU limit!",
                  "high")
        
        # Check PIDs limit
        has_pids = "pids_limit" in content
        self.check("sandbox_pids", has_pids,
                  "Sandbox PIDs limit set" if has_pids else "No sandbox PIDs limit!",
                  "high")
        
        # Check timeout
        has_timeout = "COMMAND_TIMEOUT" in content or "timeout" in content.lower()
        self.check("sandbox_timeout", has_timeout,
                  "Command timeout configured" if has_timeout else "No command timeout!",
                  "medium")

    def check_corp_db_rfc026_schema(self):
        """Check live corp-db RFC-026 schema/data drift."""
        print(f"\n{BLUE}[10/10] Checking corp-db RFC-026 schema...{RESET}")

        expected_counts = self._expected_rfc026_counts()
        if expected_counts is None:
            self.check(
                "corp_db_rfc026_sources",
                False,
                "db/categories.json or db/spheres.json missing",
                "high",
                "Restore canonical corp-db source files in db/",
            )
            return

        if shutil.which("docker") is None:
            self.check(
                "corp_db_rfc026_schema",
                False,
                "docker CLI not available; skipped live corp-db RFC-026 verification",
                "medium",
                "Run doctor on the Docker host to verify live corp-db schema drift",
            )
            return

        compose_ps = self._run_docker_compose(["ps", "-q", "corp-db"])
        if compose_ps.returncode != 0:
            self.check(
                "corp_db_rfc026_schema",
                False,
                f"docker compose ps failed: {compose_ps.stderr.strip() or compose_ps.stdout.strip()}",
                "high",
                "Fix docker compose access, then rerun doctor",
            )
            return

        if not compose_ps.stdout.strip():
            self.check(
                "corp_db_rfc026_schema",
                False,
                "corp-db container is not running; skipped live RFC-026 verification",
                "medium",
                "Start corp-db and rerun doctor",
            )
            return

        query = """
        SELECT json_build_object(
            'sphere_curated_categories_table',
            to_regclass('corp.sphere_curated_categories') IS NOT NULL,
            'categories_parent_category_id_column',
            EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'corp'
                  AND table_name = 'categories'
                  AND column_name = 'parent_category_id'
            ),
            'categories_parent_fk',
            EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'categories_parent_category_id_fkey'
                  AND conrelid = 'corp.categories'::regclass
            ),
            'idx_categories_parent_category_id',
            to_regclass('corp.idx_categories_parent_category_id') IS NOT NULL,
            'idx_sphere_curated_categories_category_id',
            to_regclass('corp.idx_sphere_curated_categories_category_id') IS NOT NULL,
            'idx_sphere_curated_categories_sphere_position',
            to_regclass('corp.idx_sphere_curated_categories_sphere_position') IS NOT NULL,
            'catalog_lamps_agent_series_name_column',
            EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'corp'
                  AND table_name = 'v_catalog_lamps_agent'
                  AND column_name = 'series_name'
            ),
            'catalog_lamps_agent_series_consistent',
            CASE
                WHEN EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'corp'
                      AND table_name = 'v_catalog_lamps_agent'
                      AND column_name = 'series_name'
                ) THEN (
                    SELECT coalesce(
                        bool_and(
                            CASE
                                WHEN row_data->>'name' ILIKE 'LAD LED R320-2-% Ex'
                                    THEN row_data->>'series_name' = 'LAD LED R320 Ex'
                                WHEN row_data->>'name' ILIKE 'LAD LED R500-% 2Ex'
                                    THEN row_data->>'series_name' = 'LAD LED R500 2Ex'
                                ELSE true
                            END
                        ),
                        true
                    )
                    FROM (
                        SELECT to_jsonb(lamp_row) AS row_data
                        FROM corp.v_catalog_lamps_agent lamp_row
                    ) rows
                )
                ELSE false
            END,
            'curated_rows',
            CASE
                WHEN to_regclass('corp.sphere_curated_categories') IS NULL THEN NULL
                ELSE (SELECT count(*) FROM corp.sphere_curated_categories)
            END,
            'parent_links',
            CASE
                WHEN EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'corp'
                      AND table_name = 'categories'
                      AND column_name = 'parent_category_id'
                ) THEN (SELECT count(*) FROM corp.categories WHERE parent_category_id IS NOT NULL)
                ELSE NULL
            END
        )::text;
        """
        query_result = self._run_docker_compose(
            [
                "exec",
                "-T",
                "corp-db",
                "psql",
                "-U",
                os.getenv("CORP_DB_ADMIN_USER", "postgres"),
                "-d",
                os.getenv("CORP_DB_NAME", "corp_pg_db"),
                "-Atqc",
                query,
            ]
        )
        if query_result.returncode != 0:
            self.check(
                "corp_db_rfc026_schema",
                False,
                f"failed to query corp-db RFC-026 schema: {query_result.stderr.strip() or query_result.stdout.strip()}",
                "high",
                "Inspect corp-db logs and rerun the corp-db migrator",
            )
            return

        try:
            payload = json.loads(query_result.stdout.strip())
        except json.JSONDecodeError as exc:
            self.check(
                "corp_db_rfc026_schema",
                False,
                f"invalid corp-db RFC-026 schema payload: {exc}",
                "high",
                "Inspect doctor query output and corp-db logs",
            )
            return

        missing_objects = []
        object_checks = {
            "sphere_curated_categories_table": "corp.sphere_curated_categories",
            "categories_parent_category_id_column": "corp.categories.parent_category_id",
            "categories_parent_fk": "categories_parent_category_id_fkey",
            "idx_categories_parent_category_id": "idx_categories_parent_category_id",
            "idx_sphere_curated_categories_category_id": "idx_sphere_curated_categories_category_id",
            "idx_sphere_curated_categories_sphere_position": "idx_sphere_curated_categories_sphere_position",
            "catalog_lamps_agent_series_name_column": "corp.v_catalog_lamps_agent.series_name",
            "catalog_lamps_agent_series_consistent": "corp.v_catalog_lamps_agent canonical series ancestry",
        }
        for key, label in object_checks.items():
            if not payload.get(key):
                missing_objects.append(label)

        self.check(
            "corp_db_rfc026_schema_objects",
            not missing_objects,
            "RFC-026 schema objects present"
            if not missing_objects
            else f"Missing RFC-026 schema objects: {', '.join(missing_objects)}",
            "critical" if missing_objects else "low",
            "Run `docker compose up -d --build corp-db corp-db-migrator tools-api` to apply the live migration",
        )

        curated_rows = payload.get("curated_rows")
        expected_curated_rows = expected_counts["curated_rows"]
        self.check(
            "corp_db_rfc026_curated_seed",
            curated_rows == expected_curated_rows,
            f"curated sphere/category rows: {curated_rows}/{expected_curated_rows}",
            "high" if curated_rows != expected_curated_rows else "low",
            "Rerun `docker compose up -d corp-db-migrator` or inspect db/spheres.json drift",
        )

        parent_links = payload.get("parent_links")
        expected_parent_links = expected_counts["parent_links"]
        self.check(
            "corp_db_rfc026_parent_links",
            parent_links is not None and parent_links >= expected_parent_links,
            f"category parent links: {parent_links}/{expected_parent_links}",
            "high" if parent_links is None or parent_links < expected_parent_links else "low",
            "Rerun `docker compose up -d corp-db-migrator` or inspect db/categories.json drift",
        )

    def _expected_rfc026_counts(self) -> Optional[dict[str, int]]:
        categories_path = self.root / "db" / "categories.json"
        spheres_path = self.root / "db" / "spheres.json"
        if not categories_path.exists() or not spheres_path.exists():
            return None

        categories_payload = json.loads(categories_path.read_text(encoding="utf-8"))
        spheres_payload = json.loads(spheres_path.read_text(encoding="utf-8"))

        category_rows = [row for row in categories_payload.get("categories", []) if isinstance(row, dict)]
        valid_category_ids = {row.get("id") for row in category_rows if row.get("id") is not None}

        return {
            "parent_links": sum(
                1
                for row in category_rows
                if isinstance(row.get("parent"), dict)
                and row["parent"].get("id") is not None
                and row["parent"].get("id") in valid_category_ids
            ),
            "curated_rows": sum(
                len(row.get("curatedCategoryIds", []))
                for row in spheres_payload.get("spheres", [])
                if isinstance(row, dict)
            ),
        }

    def _run_docker_compose(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["docker", "compose", *args],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
    
    def print_summary(self):
        """Print summary of all checks"""
        passed = sum(1 for r in self.results if r.passed)
        failed = len(self.results) - passed
        
        critical = sum(1 for r in self.results if not r.passed and r.severity == "critical")
        high = sum(1 for r in self.results if not r.passed and r.severity == "high")
        
        print(f"\n{BOLD}📊 Summary{RESET}")
        print(f"   Total checks: {len(self.results)}")
        print(f"   {GREEN}✓ Passed: {passed}{RESET}")
        print(f"   {RED}✗ Failed: {failed}{RESET}")
        
        if critical > 0:
            print(f"\n{RED}{BOLD}🚨 CRITICAL ISSUES: {critical}{RESET}")
        if high > 0:
            print(f"{YELLOW}⚠️  HIGH ISSUES: {high}{RESET}")
        
        # Print failed checks
        if failed > 0:
            print(f"\n{BOLD}Failed checks:{RESET}")
            for r in self.results:
                if not r.passed:
                    color = RED if r.severity in ("critical", "high") else YELLOW
                    print(f"  {color}✗ [{r.severity.upper()}] {r.name}: {r.message}{RESET}")
                    if r.fix_hint:
                        print(f"    Fix: {r.fix_hint}")
        
        # Overall status
        print()
        if critical > 0:
            print(f"{RED}{BOLD}❌ SECURITY COMPROMISED{RESET}")
            print(f"{RED}   Fix critical issues immediately!{RESET}")
            return 1
        elif high > 0:
            print(f"{YELLOW}{BOLD}⚠️  SECURITY WARNINGS{RESET}")
            print(f"{YELLOW}   Review high-severity issues{RESET}")
            return 0
        else:
            print(f"{GREEN}{BOLD}✅ ALL CHECKS PASSED{RESET}")
            print(f"{GREEN}   Security configuration is solid.{RESET}")
            return 0
    
    def to_json(self) -> str:
        """Export results as JSON"""
        return json.dumps({
            "results": [
                {
                    "name": r.name,
                    "passed": r.passed,
                    "message": r.message,
                    "severity": r.severity,
                    "fix_hint": r.fix_hint
                }
                for r in self.results
            ],
            "summary": {
                "total": len(self.results),
                "passed": sum(1 for r in self.results if r.passed),
                "failed": sum(1 for r in self.results if not r.passed),
                "critical": sum(1 for r in self.results if not r.passed and r.severity == "critical"),
                "high": sum(1 for r in self.results if not r.passed and r.severity == "high"),
            }
        }, indent=2)


def main():
    parser = argparse.ArgumentParser(description="LocalTopSH Security Doctor")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--fix", action="store_true", help="Attempt to fix issues (not implemented)")
    args = parser.parse_args()
    
    # Find project root
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    
    # Check we're in right directory
    if not (project_root / "docker-compose.yml").exists():
        print(f"{RED}Error: Run from project root or scripts/ directory{RESET}")
        sys.exit(1)
    
    doctor = SecurityDoctor(project_root)
    doctor.run_all_checks()
    
    if args.json:
        print("\n" + doctor.to_json())
    
    sys.exit(doctor.print_summary())


if __name__ == "__main__":
    main()
