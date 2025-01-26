import json
import logging
import platform
import shutil
from pathlib import Path
from typing import Any, Dict, Optional
from invoke import task
from yaml import Loader, load

# Logger configuration
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[ %(levelname)s ] - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

# Cached configuration and paths
_CONFIG: Optional[Dict[str, Any]] = None
_PROJECT_ROOT = Path(__file__).parent.absolute()
_VENV_DIR = _PROJECT_ROOT / "venv"


def _load_config() -> Dict[str, Any]:
    """Load and cache configuration from config.yaml"""
    global _CONFIG
    if _CONFIG is None:
        try:
            config_path = _PROJECT_ROOT / "config.yaml"
            logger.info("Loading configuration from %s", config_path)
            with open(config_path) as f:
                _CONFIG = load(f, Loader=Loader)
        except Exception as e:
            logger.error("Failed to load configuration: %s", e)
            raise RuntimeError("Configuration load failed") from e
    return _CONFIG


def _get_config_value(*keys: str) -> Any:
    """Get a configuration value without path conversion"""
    try:
        value = _load_config()
        for key in keys:
            value = value[key]
        return value
    except KeyError as e:
        logger.error("Missing configuration key: %s", keys)
        raise ValueError(f"Missing configuration key: {keys}") from e


def _get_config_path(*keys: str) -> Path:
    """Get a path from configuration with validation"""
    value = _get_config_value(*keys)
    path = _PROJECT_ROOT / str(value)
    if not path.exists():
        logger.warning("Path does not exist: %s", path)
    return path


def _get_venv_python() -> Path:
    """Get path to virtual environment Python interpreter"""
    if platform.system() == "Windows":
        python_exe = _VENV_DIR / "Scripts" / "python.exe"
    else:
        python_exe = _VENV_DIR / "bin" / "python"

    if not python_exe.exists():
        raise FileNotFoundError(
            f"Virtual environment Python not found at {python_exe}. "
            "Did you run the check task?"
        )
    return python_exe


def _run_in_venv(c, command: str):
    """Ejecuta un comando en el entorno virtual activado"""
    if platform.system() == "Windows":
        activate_script = _VENV_DIR / "Scripts" / "activate.bat"
        full_cmd = f'call "{activate_script}" && {command}'
        c.run(full_cmd)
    else:
        activate_script = _VENV_DIR / "bin" / "activate"
        full_cmd = f'source "{activate_script}" && {command}'
        c.run(full_cmd, shell="/bin/bash")


@task
def aggregate(c):
    """Run git-aggregate using the virtual environment"""
    try:
        repos_file = _PROJECT_ROOT / "repos.yaml"
        logger.info("Running git-aggregate with %s", repos_file)
        _run_in_venv(c, f"gitaggregate -c {repos_file}")
        logger.info("Git aggregation completed successfully")
    except Exception as e:
        logger.error("Git aggregation failed: %s", e)
        raise


@task
def config(c):
    """Generate IDE configuration files and update Odoo config"""
    try:
        # Cargar configuración
        config = _load_config()
        odoo_config = config.get("odoo", {})
        repos_config = config.get("repos", [])

        # Obtener paths principales
        odoo_path = Path(odoo_config.get("server", "")).resolve()
        enterprise_path = (
            Path(odoo_config.get("enterprise", "")).resolve()
            if odoo_config.get("enterprise")
            else None
        )

        # Validar paths principales
        if not odoo_path.exists():
            raise FileNotFoundError(f"Odoo server path not found: {odoo_path}")

        server_addons_path = odoo_path / "addons"
        if not server_addons_path.exists():
            logger.warning("Odoo addons directory not found: %s", server_addons_path)

        # Procesar repositorios
        valid_repos = []
        seen_paths = set()

        for repo in repos_config:
            repo_path = Path(repo)

            # Convertir a path absoluto si es relativo
            if not repo_path.is_absolute():
                repo_path = _PROJECT_ROOT / repo_path

            repo_resolved = repo_path.resolve()

            # Validaciones
            if not repo_resolved.exists():
                logger.warning("⚠️ Repo path does not exist: %s", repo_resolved)
                continue

            if repo_resolved == odoo_path:
                logger.info("⏩ Skipping server path in repos: %s", repo_resolved)
                continue

            if repo_resolved in seen_paths:
                logger.info("⏩ Skipping duplicate path: %s", repo_resolved)
                continue

            seen_paths.add(repo_resolved)
            valid_repos.append(repo_resolved)
            logger.debug("✅ Added valid repo: %s", repo_resolved)

        # 1. Generar pyrightconfig.json
        pyright_config = _PROJECT_ROOT / "pyrightconfig.json"
        logger.info("📄 Generating %s", pyright_config)

        analysis_paths = [str(server_addons_path)]

        # Agregar enterprise si existe y es diferente
        if (
            enterprise_path
            and enterprise_path.exists()
            and enterprise_path != odoo_path
        ):
            analysis_paths.append(str(enterprise_path))

        # Agregar repos válidos
        analysis_paths.extend(str(repo) for repo in valid_repos)

        with open(pyright_config, "w") as f:
            analysis_paths.append(str(odoo_path))
            json.dump({"extraPaths": analysis_paths}, f, indent=4)
            logger.info("✅ Pyright config created with %d paths", len(analysis_paths))

        # 2. Generar configuración de VSCode
        vscode_dir = _PROJECT_ROOT / ".vscode"
        vscode_dir.mkdir(exist_ok=True)

        vscode_settings = vscode_dir / "settings.json"
        logger.info("📄 Generating %s", vscode_settings)

        settings = {
            "settings": {
                "python.autoComplete.extraPaths": analysis_paths,
                "python.analysis.extraPaths": analysis_paths,
                "python.formatting.provider": "none",
                "python.linting.flake8Enabled": True,
                "python.linting.ignorePatterns": [f"{odoo_path}/**/*.py"],
                "python.linting.pylintArgs": [
                    f"--init-hook=\"import sys;sys.path.append('{odoo_path}')\"",
                    "--load-plugins=pylint_odoo",
                ],
                "python.linting.pylintEnabled": True,
                "python.defaultInterpreterPath": str(_get_venv_python()),
                "restructuredtext.confPath": "",
                "search.followSymlinks": False,
                "search.useIgnoreFiles": False,
                "[python]": {"editor.defaultFormatter": "ms-python.black-formatter"},
                "[json]": {"editor.defaultFormatter": "esbenp.prettier-vscode"},
                "[jsonc]": {"editor.defaultFormatter": "esbenp.prettier-vscode"},
                "[markdown]": {"editor.defaultFormatter": "esbenp.prettier-vscode"},
                "[yaml]": {"editor.defaultFormatter": "esbenp.prettier-vscode"},
                "[xml]": {"editor.formatOnSave": False},
            }
        }

        with open(vscode_settings, "w") as f:
            json.dump(settings, f, indent=4)
            logger.info("✅ VSCode settings created")

        # 3. Actualizar odoo.conf
        odoo_conf_path = _PROJECT_ROOT / "odoo.conf"
        logger.info("🔧 Updating %s", odoo_conf_path)

        addons_paths = [str(server_addons_path)]

        if enterprise_path and enterprise_path.exists():
            addons_paths.append(str(enterprise_path))

        addons_paths.extend(str(repo) for repo in valid_repos)

        new_addons_line = f"addons_path = {','.join(addons_paths)}\n"

        # Leer y modificar el archivo
        conf_lines = []
        if odoo_conf_path.exists():
            with open(odoo_conf_path, "r") as f:
                conf_lines = f.readlines()

        in_options = False
        updated = False
        new_conf = []

        for line in conf_lines:
            stripped = line.strip()

            if stripped.startswith("[options]"):
                in_options = True
                new_conf.append(line)
                continue

            if in_options:
                if stripped.startswith("addons_path"):
                    new_conf.append(new_addons_line)
                    updated = True
                    continue
                elif stripped.startswith("[") and stripped.endswith("]"):
                    in_options = False

            new_conf.append(line)

        # Si no se actualizó, agregar en [options]
        if not updated:
            options_found = False
            for i, line in enumerate(new_conf):
                if line.strip().startswith("[options]"):
                    new_conf.insert(i + 1, new_addons_line)
                    options_found = True
                    break

            if not options_found:
                new_conf.append("\n[options]\n")
                new_conf.append(new_addons_line)

        # Escribir archivo
        with open(odoo_conf_path, "w") as f:
            f.writelines(new_conf)
            logger.info("✅ Odoo config updated with addons_path: %s", addons_paths)

        logger.info("🎉 Configuration completed successfully!")
        logger.info("📦 Total repos processed: %d", len(valid_repos))
        logger.info(
            "🚀 Paths in addons_path:\n%s",
            "\n".join(f"• {path}" for path in addons_paths),
        )

    except Exception as e:
        logger.error("❌ Configuration failed: %s", e)
        raise


@task
def check_odoo(c):
    """Install Odoo dependencies in virtual environment"""
    try:
        odoo_path = _get_config_path("odoo", "server")
        requirements = odoo_path / "requirements.txt"
        logger.info("Installing Odoo dependencies from %s", requirements)
        _run_in_venv(c, f"uv pip install -r {requirements}")
        logger.info("Odoo dependencies installed successfully")
    except Exception as e:
        logger.error("Odoo dependency installation failed: %s", e)
        raise


@task
def check_uv(c):
    """Ensure uv is installed globally for venv creation"""
    try:
        uv_path = shutil.which("uv")
        if uv_path:
            logger.info("uv found in system PATH: %s", uv_path)
            return

        logger.info("Installing uv...")
        if platform.system() == "Windows":
            c.run('powershell -c "irm https://astral.sh/uv/install.ps1 | iex"')
        else:
            c.run("curl -LsSf https://astral.sh/uv/install.sh | sh")

        logger.info("uv installed successfully")

    except Exception as e:
        logger.error("uv installation failed: %s", e)
        raise


@task
def deps(c):
    """Install additional dependencies in virtual environment"""
    try:
        requirements = _PROJECT_ROOT / "requirements.txt"
        logger.info("Installing additional dependencies from %s", requirements)
        _run_in_venv(c, f"uv pip install -r {requirements}")
        logger.info("Additional dependencies installed successfully")
    except Exception as e:
        logger.error("Dependency installation failed: %s", e)
        raise


@task(pre=[check_uv])
def check(c):
    """Create virtual environment if needed"""
    try:
        python_version = _get_config_value("python")

        if not _VENV_DIR.exists():
            logger.info("Creating virtual environment with Python %s", python_version)
            c.run(f"uv venv {_VENV_DIR} --python {python_version}")
            logger.info("Virtual environment created")
        else:
            logger.info("Virtual environment already exists")

    except Exception as e:
        logger.error("Virtual environment setup failed: %s", e)
        raise


@task(pre=[check, deps, check_odoo, aggregate, config])
def install(c):
    """Install complete development environment"""
    logger.info("Development environment setup completed successfully")


@task(pre=[deps, aggregate, config])
def update(c):
    """Update complete development environment"""
    logger.info("Development environment update completed successfully")


@task
def lint(c, verbose=False, path=""):
    """Run pre-commit linting"""
    try:
        cmd = "pre-commit run --show-diff-on-failure --all-files --color=always"
        if verbose:
            cmd += " --verbose"

        target_dir = _PROJECT_ROOT / path
        logger.info("Running lint in %s", target_dir)

        with c.cd(str(target_dir)):
            _run_in_venv(c, cmd)

    except Exception as e:
        logger.error("Linting failed: %s", e)
        raise
