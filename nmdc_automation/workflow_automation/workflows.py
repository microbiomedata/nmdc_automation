from __future__ import annotations
from yaml import load
try:
    from yaml import CLoader as Loader
except ImportError:
    from yaml import Loader


def load_workflows(yaml_file) -> list[Workflow]:
    workflows = []
    data = load(open(yaml_file), Loader)
    for wf in data["Workflows"]:
        workflows.append(Workflow(wf))
    # Populate workflow dependencies
    for wf in workflows:
        for wf2 in workflows:
            if not wf2.predecessor:
                continue
            if wf.name == wf2.predecessor:
                wf.add_child(wf2)
                wf2.add_parent(wf)
    return workflows


class Workflow():
    """
    Workflow object class
    """

    _FIELDS = ["Name",
               "Type",
               "Enabled",
               "Git_repo",
               "Version",
               "WDL",
               "Collection",
               "Predecessor",
               "Input_prefix",
               "Inputs",
               "Activity",
               "Outputs"
               ]

    def __init__(self, wf: dict):
        """
        Create a workflow object from a
        dictionary
        """
        self.children = set()
        self.parents = set()
        self.do_types = []
        for f in self._FIELDS:
            attr_name = f.lower().replace(" ", "_")
            setattr(self, attr_name, wf[f])
        for _, inp_param in self.inputs.items():
            if inp_param.startswith("do:"):
                self.do_types.append(inp_param[3:])

    def add_child(self, child: Workflow):
        self.children.add(child)

    def add_parent(self, parent: Workflow):
        self.parents.add(parent)


if __name__ == "__main__":
    load_workflows("workflows.yaml")