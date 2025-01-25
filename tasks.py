import json
import logging
import platform
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional
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
    """Generate IDE configuration files"""
    try:
        # Obtener paths necesarios
        odoo_path = _get_config_path("odoo", "server")
        enterprise_path = _get_config_path("odoo", "enterprise")
        repo_paths = [
            _PROJECT_ROOT / Path(repo)
            for repo in _get_config_value("repos")
        ]

        # Generar paths para la configuración
        paths = [
            odoo_path,
            odoo_path / "addons",
            enterprise_path,
            *repo_paths
        ]
        extra_paths = [str(p.resolve()) for p in paths if p.exists()]

        # 1. Generar pyrightconfig.json
        pyright_config = _PROJECT_ROOT / "pyrightconfig.json"
        logger.info("Generating %s", pyright_config)
        with open(pyright_config, "w") as f:
            json.dump({"extraPaths": extra_paths}, f, indent=4)

        # 2. Generar configuración de VSCode
        vscode_dir = _PROJECT_ROOT / ".vscode"
        vscode_dir.mkdir(exist_ok=True)

        vscode_settings = vscode_dir / "settings.json"
        logger.info("Generating %s", vscode_settings)

        # Configuración base
        settings = {
            "settings": {
                "python.autoComplete.extraPaths": extra_paths,
                "python.analysis.extraPaths": extra_paths,
                "python.formatting.provider": "none",
                "python.linting.flake8Enabled": True,
                "python.linting.ignorePatterns": [
                    f"{odoo_path}/**/*.py"
                ],
                "python.linting.pylintArgs": [
                    f"--init-hook=\"import sys;sys.path.append('{odoo_path}')\"",
                    "--load-plugins=pylint_odoo"
                ],
                "python.linting.pylintEnabled": True,
                "python.defaultInterpreterPath": str(_get_venv_python()),
                "restructuredtext.confPath": "",
                "search.followSymlinks": False,
                "search.useIgnoreFiles": False,
                "[python]": {
                    "editor.defaultFormatter": "ms-python.black-formatter"
                },
                "[json]": {
                    "editor.defaultFormatter": "esbenp.prettier-vscode"
                },
                "[jsonc]": {
                    "editor.defaultFormatter": "esbenp.prettier-vscode"
                },
                "[markdown]": {
                    "editor.defaultFormatter": "esbenp.prettier-vscode"
                },
                "[yaml]": {
                    "editor.defaultFormatter": "esbenp.prettier-vscode"
                },
                "[xml]": {
                    "editor.formatOnSave": False
                }
            }
        }

        with open(vscode_settings, "w") as f:
            json.dump(settings, f, indent=4)

        logger.info("VSCode configuration created successfully")

    except Exception as e:
        logger.error("Configuration generation failed: %s", e)
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
