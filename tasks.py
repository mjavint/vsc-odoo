import json
from pathlib import Path
from invoke import task
from yaml import Loader, load


# Root directory of the project
PROJECT_ROOT = Path(__file__).parent.absolute()


def _load_config():
    with open(PROJECT_ROOT / "config.yaml") as f:
        config = load(f, Loader=Loader)
    return config


def _get_path_odoo():
    return _load_config().get("repos").get("odoo")


def _create_pyright_config():
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


@task
def deps(c):
    c.run(
        "cp /Users/mjavint/Repos/Odoo/odoo/odoo.16.0/requirements.txt requirements/requirements-odoo.in"
    )
    c.run("source venv/bin/activate")
    c.run("uv pip install pip-tools")
    c.run(
        "uv run pip-compile --generate-hashes --resolver=backtracking --upgrade requirements/requirements.in"
    )
    c.run(
        "uv run pip-compile --generate-hashes --resolver=backtracking --upgrade requirements/requirements-odoo.in"
    )
    c.run("uv pip install -r requirements/requirements.txt")
    c.run("uv pip install -r requirements/requirements-odoo.txt")


@task
def confs(c):
    _create_pyright_config()


_load_config()
