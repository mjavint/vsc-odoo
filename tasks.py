import json
import logging
import platform
import shutil
from pathlib import Path
from typing import Any

from invoke import task
from yaml import Loader, load

# Logger configuration
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("▸ %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

# Cached configuration and paths
_CONFIG: dict[str, Any] | None = None
_PROJECT_ROOT = Path(__file__).parent.absolute()
_VENV_DIR = _PROJECT_ROOT / ".venv"


def _load_config() -> dict[str, Any] | None:
    """Load and cache configuration from config.yaml"""
    global _CONFIG
    if _CONFIG is None:
        try:
            config_path = _PROJECT_ROOT / "config.yaml"
            logger.info("📂 Loading configuration from %s", config_path)
            with open(config_path) as f:
                _CONFIG = load(f, Loader=Loader)
            logger.debug("✅ Configuration loaded successfully")
        except Exception as e:
            logger.error("❌ Failed to load configuration: %s", e)
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
        logger.error("❌ Missing configuration key: %s", keys)
        raise ValueError(f"Missing configuration key: {keys}") from e


def _get_config_path(*keys: str) -> Path:
    """Get a path from configuration with validation"""
    value = _get_config_value(*keys)
    path = _PROJECT_ROOT / str(value)
    if not path.exists():
        logger.warning("⚠️ Path does not exist: %s", path)
    return path


def _get_venv_python() -> Path:
    """Get path to virtual environment Python interpreter"""
    if platform.system() == "Windows":
        python_exe = _VENV_DIR / "Scripts" / "python.exe"
    else:
        python_exe = _VENV_DIR / "bin" / "python"

    if not python_exe.exists():
        raise FileNotFoundError(
            f"❌ Virtual environment Python not found at {python_exe}. "
            "Did you run the check task?"
        )
    return python_exe


def _run_in_venv(c, command: str):
    """Execute command in the activated virtual environment"""
    if platform.system() == "Windows":
        activate_script = _VENV_DIR / "Scripts" / "activate.bat"
        full_cmd = f'call "{activate_script}" && {command}'
        c.run(full_cmd)
    else:
        activate_script = _VENV_DIR / "bin" / "activate"
        full_cmd = f'source "{activate_script}" && {command}'
        c.run(full_cmd, shell="/bin/bash")


@task(
    help={
        "verbose": "Enable verbose output mode",
        "path": "Specify subdirectory to lint (default: project root)",
    }
)
def lint(c, verbose=False, path=""):
    """Run pre-commit linting checks"""
    try:
        base_cmd = [
            "pre-commit",
            "run",
            "--show-diff-on-failure",
            "--all-files",
            f"{path}",
            "--color=always",
        ]
        if verbose:
            base_cmd.append("--verbose")
            logger.info("🔍 Running linting in verbose mode...")
        else:
            logger.info("🔍 Running linting checks...")

        # target_dir = _PROJECT_ROOT / path
        # logger.debug("▸ Target directory: %s", target_dir)

        full_cmd = " ".join(base_cmd)

        _run_in_venv(c, full_cmd)
        # with c.cd(str(target_dir)):
        #     _run_in_venv(c, full_cmd)

        logger.info("✅ Linting completed successfully")
    except Exception as e:
        logger.error("❌ Linting failed: %s", e)
        raise


@task(help={"force": "Force recreation of virtual environment"})
def check(c, force=False):
    """Create virtual environment if needed"""
    try:
        python_version = _get_config_value("python")

        if force and _VENV_DIR.exists():
            shutil.rmtree(_VENV_DIR)
            logger.info("♻️ Removing existing virtual environment")

        if not _VENV_DIR.exists():
            logger.info("🛠️ Creating virtual environment with Python %s", python_version)
            c.run(f"uv venv {_VENV_DIR} --python {python_version}")
            logger.info("✅ Virtual environment created at: %s", _VENV_DIR)
        else:
            logger.info("✅ Virtual environment already exists: %s", _VENV_DIR)
    except Exception as e:
        logger.error("❌ Virtual environment creation failed: %s", e)
        raise


@task(pre=[check], help={"file": "Custom requirements file path"})
def deps(c, file="requirements.txt"):
    """Install additional Python dependencies"""
    try:
        requirements = _PROJECT_ROOT / file
        logger.info("📦 Installing dependencies from %s", requirements.name)
        _run_in_venv(c, f"uv pip install -r {requirements}")
        logger.info("✅ Dependencies installed successfully")
    except Exception as e:
        logger.error("❌ Dependency installation failed: %s", e)
        raise


@task(pre=[check])
def check_odoo(c):
    """Install Odoo core dependencies"""
    try:
        odoo_version = _get_config_path("odoo", "version")
        # requirements = odoo_path / "requirements.txt"
        req = _PROJECT_ROOT / "requirements.txt"
        if not req.exists():
            logger.info(
                f"📂 requirements.txt not found, downloading from OCA/OCB for Odoo {odoo_version}"
            )
            c.run(
                "curl -o requirements.txt https://raw.githubusercontent.com/OCA/OCB/17.0/requirements.txt && sed -i -E \"s/(gevent==)21\.8\.0( ; sys_platform != 'win32' and python_version == '3.10')/\\122.10.2\\2/;s/(greenlet==)1.1.2( ; sys_platform != 'win32' and python_version == '3.10')/\\12.0.2\\2/\" requirements.txt"
            )
        logger.info("📦 Installing Odoo dependencies...")
        _run_in_venv(c, "uv pip install -r requirements.txt")
        logger.info("✅ Odoo dependencies installed successfully")
    except Exception as e:
        logger.error("❌ Odoo dependency installation failed: %s", e)
        raise


@task(help={"config": "Custom repos configuration file"})
def aggregate(c, config="repos.yaml"):
    """Synchronize git repositories using git-aggregate"""
    try:
        repos_file = _PROJECT_ROOT / config
        logger.info("🔄 Synchronizing repositories with %s", repos_file.name)
        _run_in_venv(c, f"gitaggregate -c {repos_file}")
        logger.info("✅ Repository synchronization completed")
    except Exception as e:
        logger.error("❌ Repository synchronization failed: %s", e)
        raise


@task(help={"ide": "Generate configuration for specific IDE (vscode)"})
def config(c, ide="vscode"):
    """Generate development environment configuration files"""
    try:
        config = _load_config()
        odoo_config = config.get("odoo", {})
        repos_config = config.get("repos", [])

        odoo_path = Path(odoo_config.get("server", "")).resolve()
        enterprise_path = (
            Path(odoo_config.get("enterprise", "")).resolve()
            if odoo_config.get("enterprise")
            else None
        )

        logger.info("🔍 Validating core paths...")
        if not odoo_path.exists():
            raise FileNotFoundError(f"❌ Odoo path not found: {odoo_path}")

        server_addons_path = odoo_path / "addons"
        if not server_addons_path.exists():
            logger.warning("⚠️ Odoo addons directory missing: %s", server_addons_path)

        logger.info("📦 Processing repositories...")
        valid_repos = []
        seen_paths = set()

        for repo in repos_config:
            repo_path = Path(repo)
            if not repo_path.is_absolute():
                repo_path = _PROJECT_ROOT / repo_path
            repo_resolved = repo_path.resolve()

            if not repo_resolved.exists():
                logger.warning("⚠️ Repository path does not exist: %s", repo_resolved)
                continue

            if repo_resolved == odoo_path:
                logger.info("⏩ Skipping server path in repos: %s", repo_resolved)
                continue

            if repo_resolved in seen_paths:
                logger.info("⏩ Skipping duplicate path: %s", repo_resolved)
                continue

            seen_paths.add(repo_resolved)
            valid_repos.append(repo_resolved)
            logger.debug("▸ Valid repository: %s", repo_resolved)

        # Generate pyrightconfig.json
        pyright_config = _PROJECT_ROOT / "pyrightconfig.json"
        logger.info("🛠️ Generating %s", pyright_config.name)

        analysis_paths = [str(server_addons_path)]
        if (
            enterprise_path
            and enterprise_path.exists()
            and enterprise_path != odoo_path
        ):
            analysis_paths.append(str(enterprise_path))
        analysis_paths.extend(str(repo) for repo in valid_repos)

        with open(pyright_config, "w") as f:
            analysis_paths.append(str(odoo_path))
            json.dump({"extraPaths": analysis_paths}, f, indent=4)
        logger.info(
            "✅ %s created with %d paths", pyright_config.name, len(analysis_paths)
        )

        # Generate VSCode configuration
        if ide.lower() == "vscode":
            vscode_dir = _PROJECT_ROOT / ".vscode"
            vscode_dir.mkdir(exist_ok=True)
            vscode_settings = vscode_dir / "settings.json"

            logger.info("🛠️ Generating %s", vscode_settings.name)
            settings = {
                "settings": {
                    "python.autoComplete.extraPaths": analysis_paths,
                    "python.analysis.extraPaths": analysis_paths,
                    "python.languageServer": "None",
                    "[python]": {
                        "editor.formatOnSave": True,
                        "editor.codeActionsOnSave": {
                            "source.fixAll": "explicit",
                            "source.organizeImports": "explicit",
                        },
                        "editor.defaultFormatter": "charliermarsh.ruff",
                    },
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
                    "[json]": {"editor.defaultFormatter": "esbenp.prettier-vscode"},
                    "[jsonc]": {"editor.defaultFormatter": "esbenp.prettier-vscode"},
                    "[markdown]": {"editor.defaultFormatter": "esbenp.prettier-vscode"},
                    "[yaml]": {"editor.defaultFormatter": "esbenp.prettier-vscode"},
                    "[xml]": {"editor.formatOnSave": False},
                    "workbench.editor.customLabels.patterns": {
                        "**/security/**": "${filename} - Security",
                        "**/security/*.csv": "${filename}.${extname} - Security",
                        "**/models/**": "${filename} - Model",
                        "**/data/*.csv": "${filename}.${extname} - Data",
                        "**/data/**": "${filename} - Data",
                        "**/demo/**": "${filename} - Demo",
                        "**/controllers/**": "${filename} - Controller",
                        "**/wizard/**": "${filename} - Wizard",
                        "**/wizards/**": "${filename} - Wizard",
                        "**/reports/**": "${filename} - Report",
                        "**/report/**": "${filename} - Report",
                        "**/tests/**": "${filename} - Test",
                        "**/views/**": "${filename} - View",
                        "**/static/src/**/*.js": "${filename} - Component ",
                        "**/static/src/**/*.xml": "${filename} - Template",
                        "**/static/src/**/*.scss": "${filename} - Style",
                        "**/__manifest__.py": "${dirname} - Odoo Manifest",
                        "**/__init__.py": "${dirname} - Module",
                        "**/docs/**": "${dirname} - Docs",
                        "**/doc/**": "${dirname} - Docs",
                    },
                }
            }

            with open(vscode_settings, "w") as f:
                json.dump(settings, f, indent=4)
            logger.info("✅ %s created", vscode_settings.name)

        # Update odoo.conf
        odoo_conf_path = _PROJECT_ROOT / "odoo.conf"
        logger.info("🛠️ Updating %s", odoo_conf_path.name)

        addons_paths = [str(server_addons_path)]
        if enterprise_path and enterprise_path.exists():
            addons_paths.append(str(enterprise_path))
        addons_paths.extend(str(repo) for repo in valid_repos)

        new_addons_line = f"addons_path = {','.join(addons_paths)}\n"

        # Original update logic
        conf_lines = []
        if odoo_conf_path.exists():
            with open(odoo_conf_path) as f:
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

        with open(odoo_conf_path, "w") as f:
            f.writelines(new_conf)

        logger.info("✅ %s updated successfully", odoo_conf_path.name)
        logger.debug("▸ New addons_path line: %s", new_addons_line.strip())
        logger.info("🎉 Configuration completed!")
        logger.debug("▸ Total repositories: %d", len(valid_repos))
        logger.debug(
            "▸ Addons paths:\n%s", "\n".join(f"• {path}" for path in addons_paths)
        )

    except Exception as e:
        logger.error("❌ Configuration failed: %s", e)
        raise


@task(pre=[check])
def check_uv(c):
    """Verify uv installation and install if missing"""
    try:
        uv_path = shutil.which("uv")
        if uv_path:
            logger.info("✅ uv already installed: %s", uv_path)
            return

        logger.info("📦 Installing uv...")
        if platform.system() == "Windows":
            c.run('powershell -c "irm https://astral.sh/uv/install.ps1 | iex"')
        else:
            c.run("curl -LsSf https://astral.sh/uv/install.sh | sh")
        logger.info("✅ uv installed successfully")
    except Exception as e:
        logger.error("❌ uv installation failed: %s", e)
        raise


@task(
    help={
        "skip_deps": "Skip dependency installation (default: False)",
        "skip_config": "Skip configuration generation (default: False)",
        "skip_aggregate": "Skip repository synchronization (default: False)",
    }
)
def install(
    c, skip_deps: bool = False, skip_config: bool = False, skip_aggregate: bool = False
):
    """Full development environment setup

    Examples:
        invoke install  # Run all steps
        invoke install --skip-aggregate  # Skip repository sync
        invoke install --skip-deps --skip-config  # Only sync repositories
    """
    try:
        # Validación inicial
        logger.info("🚀 Starting environment setup...")
        check(c)  # Siempre verificar el entorno

        # Diagrama de ejecución
        steps = {
            "Dependencies": (not skip_deps, lambda: (check_odoo(c))),
            "Configuration": (not skip_config, lambda: config(c)),
            "Repositories": (not skip_aggregate, lambda: aggregate(c)),
        }

        # Ejecutar pasos condicionalmente
        for step_name, (should_run, task_fn) in steps.items():
            if should_run:
                logger.info(f"⚙️ Running {step_name}...")
                task_fn()
            else:
                logger.warning(f"⏩ Skipping {step_name}")

        # Post-instalación
        logger.info("✅ Verification passed!")
        logger.info("🎉 Environment setup completed successfully")
        logger.info("➡️ Next step: Run Odoo with 🚀 invoke start")

    except Exception as e:
        logger.error("❌ Critical installation error: %s", e)
        logger.info("🔧 Troubleshooting tips:")
        logger.info("  - Check internet connection")
        logger.info("  - Validate config.yaml syntax")
        logger.info("  - Try 'invoke check --force' to rebuild environment")
        raise


@task(
    pre=[deps, aggregate, config],
    help={"update_deps": "Update all dependencies to latest versions"},
)
def update(c, update_deps=False):
    """Update development environment components"""
    try:
        if update_deps:
            logger.info("🔄 Updating dependencies...")
            _run_in_venv(c, "uv pip install --upgrade -r requirements.txt")
        aggregate(c)
        config(c)
        logger.info("✅ Environment update completed")
    except Exception as e:
        logger.error("❌ Update failed: %s", e)
        raise


@task(
    help={
        "options": 'Additional Odoo CLI options (e.g.: "--dev all --http-port=8080")',
        "config_file": "Custom Odoo configuration file (default: odoo.conf)",
    }
)
def start(c, options: str = "", config_file: str = "odoo.conf"):
    """Start Odoo development server

    Examples:
        invoke start
        invoke start --options="--dev all --test-enable"
        invoke start --config-file=my_config.conf
    """
    try:
        logger.info("🚀 Initializing Odoo server...")

        # 1. Load configuration
        config = _load_config()
        odoo_config = config.get("odoo", {})

        # 2. Validate Odoo installation
        odoo_path = Path(odoo_config.get("server", "")).resolve()
        odoo_bin = odoo_path / "odoo-bin"
        if not odoo_bin.exists():
            raise FileNotFoundError(f"❌ Odoo executable not found at {odoo_bin}")

        # 3. Validate config file
        config_path = _PROJECT_ROOT / config_file
        if not config_path.exists():
            logger.warning("⚠️ Configuration file not found: %s", config_path)
            raise FileNotFoundError(
                "Run 'invoke config' first to generate configuration"
            )

        # 4. Build command components
        venv_python = _get_venv_python()

        base_cmd = [f'"{venv_python}"', f"{odoo_bin}", "-c", f'"{config_path}"']

        base_cmd.append(options.strip())
        full_cmd = " ".join(base_cmd)

        # 5. Logging and execution
        logger.info("⚙️ Server configuration:")
        logger.debug("▸ Python: %s", venv_python)
        logger.debug("▸ Odoo bin: %s", odoo_bin)
        logger.debug("▸ Config file: %s", config_path)
        logger.info("▸ Command: %s", full_cmd)

        logger.info("🔄 Starting Odoo server...")
        with c.cd(str(_PROJECT_ROOT)):
            c.run(full_cmd, pty=True, echo=True)

    except Exception as e:
        logger.error("❌ Server startup failed: %s", e)
        logger.info("💡 Troubleshooting tips:")
        logger.info("  - Verify Odoo path in config.yaml")
        logger.info("  - Check if config file exists")
        logger.info("  - Ensure dependencies are installed with 'invoke install'")
        raise


def _get_backup_config():
    """Obtiene la configuración necesaria para el backup desde config.yaml

    Returns:
        tuple: (config_path, dest_dir, backup_format, odoo_server_path, target_dir)
    """
    config = _load_config()
    database_config = config.get("database", {})
    odoo_config = config.get("odoo", {})
    target_dir = None  # Inicializar para manejo de errores

    config_path = Path(database_config["odoo_conf"]).resolve()
    dest_dir = Path(database_config["dest_dir"])
    odoo_server_path = Path(odoo_config.get("server", "")).resolve()

    return {
        "config_path": config_path,
        "dest_dir": dest_dir,
        "odoo_server_path": odoo_server_path,
        "target_dir": target_dir,
    }


def _make_cmd(cmd: str, config_path: Path, odoo_server_path: Path) -> list:
    if not odoo_server_path.exists():
        raise FileNotFoundError(f"❌ Ruta de Odoo no encontrada: {odoo_server_path}")
    if not config_path.exists():
        raise FileNotFoundError(
            f"❌ Archivo de configuración no encontrado: {config_path}"
        )
    venv_python = _get_venv_python()

    # 3. Construir comando con parámetros de config.yaml
    base_cmd = [
        f'"{venv_python}"',
        "-m",
        f"click_odoo_contrib.{cmd}",
        "-c",
        f'"{config_path}"',
    ]
    return base_cmd or []


@task
def backupdb(c, dbname, format="zip"):
    """
    Ejecuta click-odoo-backupdb desde el entorno virtual
    """
    try:
        # Obtener configuración de backup
        config = _get_backup_config()

        if not dbname:
            raise ValueError("❌ Se requiere el nombre de la base de datos")

        if format in ["zip", "dump"]:
            target_dir = config["dest_dir"] / f"{dbname}.{format}"
            # Eliminar archivo existente si es zip o dump
            if target_dir.exists():
                logger.info(f"♻️ Eliminando archivo existente: {target_dir}")
                target_dir.unlink()
        else:
            target_dir = config["dest_dir"] / dbname
            # Para formato folder, eliminar directorio si existe
            if target_dir.exists():
                logger.info(f"♻️ Eliminando directorio existente: {target_dir}")
                shutil.rmtree(target_dir)

        target_dir.parent.mkdir(parents=True, exist_ok=True)

        base_cmd = _make_cmd(
            "backupdb", config["config_path"], config["odoo_server_path"]
        )
        base_cmd.extend([dbname, str(target_dir), "--format", str(format)])
        full_cmd = " ".join(base_cmd)

        # 5. Ejecutar backup desde directorio de Odoo
        logger.info("⚙️ Ejecutando backup de base de datos...")
        logger.debug("▸ Configuración: %s", config["config_path"])
        logger.debug("▸ Destino: %s", target_dir)
        logger.debug("▸ Formato: %s", format)

        with c.cd(str(config["odoo_server_path"])):
            c.run(full_cmd, pty=True, echo=True)

    except Exception as e:
        logger.error("❌ Error al salvar la base de datos: %s", e)
        logger.info(
            "  - Validar nombre de BD y permisos en %s",
            target_dir.resolve()
            if target_dir and target_dir.exists()
            else "directorio de destino",
        )
        logger.info("💡 Solución de problemas:")
        logger.info("  - Verificar configuración en database: de config.yaml")
        logger.info("  - Validar ruta de Odoo en config.yaml")
        logger.info("  - Asegurar click-odoo-contrib instalado")
        raise


@task
def dropdb(c, dbname, exists: bool = False):
    """
    Ejecuta click-odoo-dropdb desde el entorno virtual
    """
    try:
        # Obtener configuración
        config = _get_backup_config()

        if not dbname:
            raise ValueError("❌ Se requiere el nombre de la base de datos")

        base_cmd = _make_cmd(
            "dropdb", config["config_path"], config["odoo_server_path"]
        )

        if exists:
            base_cmd.append("--if-exists")

        base_cmd.append(dbname)

        full_cmd = " ".join(base_cmd)

        # 5. Ejecutar backup desde directorio de Odoo
        logger.info("🗑️ Eliminando la base de datos...")
        logger.debug("▸ Configuración: %s", config["config_path"])

        with c.cd(str(config["odoo_server_path"])):
            c.run(full_cmd, pty=True, echo=True)
            logger.info("✅ Base de datos %s eliminada correctamente", dbname)

    except Exception as e:
        logger.error("❌ Error al eliminar la base de datos: %s", e)
        logger.info("💡 Solución de problemas:")
        logger.info("  - Verificar configuración en database: de config.yaml")
        logger.info("  - Validar ruta de Odoo en config.yaml")
        logger.info("  - Validar nombre de BD ")
        logger.info("  - Asegurar click-odoo-contrib instalado")
        raise


@task
def listdb(c):
    """
    Ejecuta click-odoo-listdb desde el entorno virtual
    """
    try:
        # Obtener configuración
        config = _get_backup_config()

        base_cmd = _make_cmd(
            "listdb", config["config_path"], config["odoo_server_path"]
        )

        full_cmd = " ".join(base_cmd)

        # 5. Ejecutar backup desde directorio de Odoo
        logger.info("📋 Listando todas las bases de datos...")
        logger.debug("▸ Configuración: %s", config["config_path"])

        with c.cd(str(config["odoo_server_path"])):
            c.run(full_cmd, pty=True, echo=True)

    except Exception as e:
        logger.error("❌ Error al eliminar la base de datos: %s", e)
        logger.info("💡 Solución de problemas:")
        logger.info("  - Verificar configuración en database: de config.yaml")
        logger.info("  - Validar ruta de Odoo en config.yaml")
        logger.info("  - Validar nombre de BD ")
        logger.info("  - Asegurar click-odoo-contrib instalado")
        raise


@task
def initdb(c, dbname, modules=None, demo=True, cache=False):
    """
    Init an Odoo database using click-odoo-initdb.
    """
    try:
        # Obtener configuración
        config = _get_backup_config()

        if not dbname:
            raise ValueError("❌ Se requiere el nombre de la base de datos")

        # 3. Construir comando con parámetros de config.yaml
        base_cmd = _make_cmd(
            "initdb", config["config_path"], config["odoo_server_path"]
        )

        if demo:
            base_cmd.append("--demo")
        else:
            base_cmd.append("--no-demo")

        if cache:
            base_cmd.append("--cache")
        else:
            base_cmd.append("--no-cache")

        if modules is not None:
            base_cmd.extend(["--modules", modules])

        base_cmd.extend(["-n", dbname])

        full_cmd = " ".join(base_cmd)

        # 5. Ejecutar backup desde directorio de Odoo
        logger.info("📋 Inicializando la base de datos %s", dbname)
        logger.debug("▸ Configuración: %s", config["config_path"])

        with c.cd(str(config["odoo_server_path"])):
            c.run(full_cmd, pty=True, echo=True)

    except Exception as e:
        logger.error("❌ Error al Inicializar la base de datos: %s", e)
        logger.info("💡 Solución de problemas:")
        logger.info("  - Verificar configuración en database: de config.yaml")
        logger.info("  - Validar ruta de Odoo en config.yaml")
        logger.info("  - Validar nombre de BD ")
        logger.info("  - Asegurar click-odoo-contrib instalado")
        raise


@task
def uninstall(c, dbname, modules=None):
    """
    Uninstall modules an Odoo database using click-odoo-initdb.
    """
    try:
        # Obtener configuración
        config = _get_backup_config()

        if not dbname:
            raise ValueError("❌ Se requiere el nombre de la base de datos")

        # 3. Construir comando con parámetros de config.yaml
        base_cmd = _make_cmd(
            "uninstall", config["config_path"], config["odoo_server_path"]
        )

        if modules is not None:
            base_cmd.extend(["--modules", modules])

        base_cmd.extend(["-d", dbname])

        full_cmd = " ".join(base_cmd)

        # 5. Ejecutar backup desde directorio de Odoo
        logger.info("📋 Desinstalando modulos la base de datos %s", dbname)
        logger.debug("▸ Configuración: %s", config["config_path"])

        with c.cd(str(config["odoo_server_path"])):
            c.run(full_cmd, pty=True, echo=True)

    except Exception as e:
        logger.error("❌ Error al desinstalar modulos de la base de datos: %s", e)
        logger.info("💡 Solución de problemas:")
        logger.info("  - Verificar configuración en database: de config.yaml")
        logger.info("  - Validar ruta de Odoo en config.yaml")
        logger.info("  - Validar nombre de BD ")
        logger.info("  - Asegurar click-odoo-contrib instalado")
        raise


# @task
# def restoredb(c, dbname, copy=True, force=False, neutralize=False, jobs=None):
#     """
#     Restore an Odoo database using click-odoo-restoredb.
#     """
#     try:
#         # Obtener configuración
#         config = _get_backup_config()

#         base_cmd = _make_cmd("restoredb", config['config_path'], config['odoo_server_path'])

#         if copy:
#             base_cmd.append("--copy")
#         else:
#             base_cmd.append("--move")

#         if force:
#             base_cmd.append("--force")

#         if neutralize:
#             base_cmd.append("--neutralize")

#         if jobs is not None:
#             base_cmd.extend(["--jobs", str(jobs)])

#         source = f'{config['dest_dir']}/{dbname}.zip'
#         logger.info("💡 Source de la base de datos %s", source)

#         base_cmd.extend([dbname, source])

#         full_cmd = " ".join(base_cmd)

#         # 5. Ejecutar backup desde directorio de Odoo
#         logger.info("📋 Restaurando la base de datos %s", dbname)
#         logger.debug("▸ Configuración: %s", config['config_path'])

#         with c.cd(str(config['odoo_server_path'])):
#             c.run(full_cmd, pty=True, echo=True)

#     except Exception as e:
#         logger.error("❌ Error al eliminar la base de datos: %s", e)
#         logger.info("💡 Solución de problemas:")
#         logger.info("  - Verificar configuración en database: de config.yaml")
#         logger.info("  - Validar ruta de Odoo en config.yaml")
#         logger.info("  - Validar nombre de BD ")
#         logger.info("  - Asegurar click-odoo-contrib instalado")
#         raise
