import json
import logging
from pathlib import Path
from invoke import task
from yaml import Loader, load
import platform

# Logger configuration
handler = logging.StreamHandler()
# formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
formatter = logging.Formatter("[ %(levelname)s ] - %(message)s")
handler.setFormatter(formatter)
logger = logging.getLogger(__name__)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# Root directory of the project
PROJECT_ROOT = Path(__file__).parent.absolute()


def _load_config():
    try:
        logger.info("Loading configuration from config.yaml")
        with open(PROJECT_ROOT / "config.yaml") as f:
            config = load(f, Loader=Loader)
        return config
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")


def _get_path_odoo():
    try:
        path_odoo = _load_config().get("odoo").get("server")
        logger.info(f"Odoo path obtained: {path_odoo}")
        return path_odoo
    except Exception as e:
        logger.error(f"Failed to get Odoo path: {e}")


@task
def pyright(c):
    try:
        logger.info("Creating pyrightconfig.json")
        config = _load_config()
        repos = []
        for repo in config.get("repos").values():
            if isinstance(repo, list):
                repos.extend(repo)
            if isinstance(repo, str):
                repos.append(repo)
        repos.append(f"{_get_path_odoo()}/addons")
        data = {
            "extraPaths": repos,
        }
        with open("pyrightconfig.json", "w") as f:
            json.dump(data, f, indent=4)
        logger.info("pyrightconfig.json created successfully")
    except Exception as e:
        logger.error(f"Failed to create pyrightconfig.json: {e}")


@task
def check_odoo(c):
    try:
        logger.info("Installing Odoo dependencies")
        c.run(f"uv pip install -r {_get_path_odoo()}/requirements.txt")
        logger.info("Odoo dependencies installed successfully")
    except Exception as e:
        logger.error(f"Failed to install Odoo dependencies: {e}")


@task
def check_uv(c):
    try:
        logger.info("Checking uv installation")
        result = c.run("uv --version", warn=True, hide=True)
        if not result.ok:
            if platform.system() == "Windows":
                logger.info("Installing uv on Windows")
                c.run('powershell -c "irm https://astral.sh/uv/install.ps1 | iex"')
            else:
                logger.info("Installing uv on Unix")
                c.run("curl -LsSf https://astral.sh/uv/install.sh | sh")
        else:
            logger.info("uv is already installed")
    except Exception as e:
        logger.error(f"Failed to check/install uv: {e}")


@task
def deps(c):
    try:
        logger.info("Installing additional dependencies")
        c.run("uv pip install -r ./dependencies/pip.txt")
        logger.info("Additional dependencies installed successfully")
    except Exception as e:
        logger.error(f"Failed to install additional dependencies: {e}")


@task(pre=[check_uv])
def check(c):
    try:
        version = _load_config().get("python", "3.10")
        logger.info(f"Checking virtual environment with Python {version}")
        if not Path("venv").exists():
            logger.info("Creating virtual environment")
            c.run(f"uv venv venv --python {version}")
    except Exception as e:
        logger.error(f"Failed to check/create virtual environment: {e}")


@task(pre=[check, deps, check_odoo, pyright])
def install(c):
    logger.info("Finished installing development environment")


@task()
def lint(c, verbose=False, path=""):
    try:
        cmd = "uv run pre-commit run --show-diff-on-failure --all-files --color=always"
        if verbose:
            cmd += " --verbose"
        with c.cd(str(PROJECT_ROOT / path)):
            c.run(cmd)
    except Exception as e:
        logger.error(f"Failed to run lint: {e}")
