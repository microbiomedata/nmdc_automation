from functools import lru_cache
import tomli
from typing import Union
import yaml
from pathlib import Path
import warnings

WORKFLOWS_DIR = Path(__file__).parent / "workflows"

class UserConfig:
    def __init__(self, path):
        warnings.warn(
            "UserConfig is deprecated and will be removed in a future release. Use SiteConfig instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        with open(path, "rb") as file:
            self.config_data = tomli.load(file)

    @property
    def base_url(self):
        return self.config_data["api"]["base_url"]

    @property
    def username(self):
        return self.config_data["api"]["username"]

    @property
    def password(self):
        return self.config_data["api"]["password"]

class SiteConfig:
    def __init__(self, path: Union[str, Path]):
        with open(path, "rb") as file:
            self.config_data = tomli.load(file)

    @property
    def cromwell_url(self):
        return self.config_data["cromwell"]["cromwell_url"]

    @property
    def cromwell_api(self):
        return self.config_data["cromwell"]["cromwell_api"]

    @property
    def stage_dir(self):
        return self.config_data["directories"]["stage_dir"]

    @property
    def template_dir(self):
        return self.config_data["directories"]["template_dir"]

    @property
    def data_dir(self):
        return self.config_data["directories"]["data_dir"]

    @property
    def raw_dir(self):
        return self.config_data["directories"]["raw_dir"]

    @property
    def resource(self):
        return self.config_data["site"]["resource"]

    @property
    def site(self):
        return self.config_data["site"]["site"]

    @property
    def url_root(self):
        return self.config_data["nmdc"]["url_root"]

    @property
    def api_url(self):
        return self.config_data["nmdc"]["api_url"]

    @property
    def watch_state(self):
        return self.config_data["state"]["watch_state"]

    @property
    def agent_state(self):
        return self.config_data.get("state", {}).get("agent_state", None)

    @property
    def activity_id_state(self):
        return self.config_data["state"]["activity_id_state"]

    @property
    def workflows_config(self):
        return self.config_data["workflows"]["workflows_config"]

    @property
    def client_id(self):
        return self.config_data["credentials"]["client_id"]

    @property
    def client_secret(self):
        return self.config_data["credentials"]["client_secret"]

    @property
    def username(self):
        return self.config_data["credentials"].get("username", None)

    @property
    def password(self):
        return self.config_data["credentials"].get("password", None)

    @property
    def jaws_config(self):
        return self.config_data["jaws"]["jaws_config"]

    @property
    def jaws_token(self):
        return self.config_data["jaws"]["jaws_token"]


    @property
    def data_path_map(self):
        """Raw mapping block from TOML (optional)."""
        return self.config_data.get("data_path_map", {})

    @property
    def data_url_prefix(self) -> str:
        """URL prefix to detect; normalized to end with a single '/'."""
        m = self.data_path_map
        if not m or "url_prefix" not in m:
            return ""
        return m["url_prefix"].rstrip("/") + "/"

    @property
    def data_results_root(self) -> str:
        """Filesystem root to substitute; normalized to have no trailing '/'."""
        m = self.data_path_map
        return (m.get("results_root", "") or "").rstrip("/")

    def map_data_location(self, value: str) -> str:
        """
        If `value` starts with the configured URL prefix, rewrite it to the local
        results root (keeping the relative tail). Otherwise return `value` unchanged.
        """
        if not isinstance(value, str):
            return value
        prefix = self.data_url_prefix
        if prefix and value.startswith(prefix) and self.data_results_root:
            rel = value[len(prefix):].lstrip("/")
            rel = rel.replace("..", "").strip("/")  # hygiene
            return os.path.join(self.data_results_root, rel)
        return value

    @property
    @lru_cache(maxsize=None)
    def allowed_workflows(self):
        """Generate a list of allowed workflows."""
        workflows_config_file = self.config_data["workflows"]["workflows_config"]
        with open(WORKFLOWS_DIR / workflows_config_file, "r") as stream:
            workflows = yaml.safe_load(stream)

        # Initialize an empty list to store the results
        enabled_workflows = []

        # Iterate over the workflows
        for workflow in workflows["Workflows"]:
            # Check if the workflow is enabled
            if workflow.get("Enabled", True):
                # Concatenate name and version and append to list
                enabled_workflows.append(
                    f"{workflow['Name']}: {workflow.get('Version','')}"
                )

        # Return the results
        return enabled_workflows
