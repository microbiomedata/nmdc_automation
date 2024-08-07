import logging
from typing import List
from .workflows import Workflow
from semver.version import Version


warned_objects = set()


def _load_data_objects(db, workflows: List[Workflow]):
    """
    Read all of the data objects and generate
    a map by ID

    TODO: In the future this will probably need to be redone
    since the number of data objects could get very large.
    """

    # Build up a filter of what types are used
    required_types = set()
    for wf in workflows:
        required_types.update(set(wf.do_types))

    data_objs_by_id = dict()
    for rec in db.data_object_set.find():
        do = DataObject(rec)
        if do.data_object_type not in required_types:
            continue
        data_objs_by_id[do.id] = do
    return data_objs_by_id


def _within_range(ver1: str, ver2: str) -> bool:
    """
    Determine if two workflows are within a major and minor
    version of each other.
    """

    def get_version(version):
        v_string = version.lstrip("b").lstrip("v").rstrip("-beta")
        return Version.parse(v_string)

    v1 = get_version(ver1)
    v2 = get_version(ver2)
    if v1.major == v2.major and v1.minor == v2.minor:
        return True
    return False


def _check(match_types, data_object_ids, data_objs):
    """
    This iterates through a list of data objects and
    checks the type against the match types.
    """
    if not data_object_ids:
        return False
    if not match_types or len(match_types) == 0:
        return True
    match_set = set(match_types)
    do_types = set()
    for doid in data_object_ids:
        if doid in data_objs:
            do_types.add(data_objs[doid].data_object_type)
    return match_set.issubset(do_types)


def _filter_skip(wf, rec, data_objs):
    """
    Some workflows require specific inputs or outputs.  This
    implements the filtering for those.
    """
    match_in = _check(wf.filter_input_objects,
                      rec.get("has_input"),
                      data_objs)
    match_out = _check(wf.filter_output_objects,
                       rec.get("has_output"),
                       data_objs)
    return not (match_in and match_out)


def _read_acitivites(db, workflows: List[Workflow],
                     data_objects: dict, filter: dict):
    """
    Read in all the activities for the defined workflows.
    """
    activities = []
    for wf in workflows:
        logging.debug(f"Checking {wf.name}:{wf.version}")
        q = filter
        q["git_url"] = wf.git_repo
        for rec in db[wf.collection].find(q):
            if wf.version and not _within_range(rec["version"], wf.version):
                logging.debug(f"Skipping {wf.name} {wf.version} {rec['version']}")
                continue
            if wf.collection == "omics_processing_set" and \
               rec["id"].startswith("gold"):
                continue
            if _filter_skip(wf, rec, data_objects):
                continue
            act = Activity(rec, wf)
            activities.append(act)
    return activities


def _resolve_relationships(activities, data_obj_act):
    """
    Find the parents and children relationships
    between the activities
    """
    # We now have a list of all the activites and
    # a map of all of the data objects they generated.
    # Let's use this to find the parent activity
    # for each child activity
    for act in activities:
        logging.debug(f"Processing {act.id} {act.name} {act.workflow.name}")
        act_pred_wfs = act.workflow.parents
        if not act_pred_wfs:
            logging.debug("- No Predecessors")
            continue
        # Go through its inputs
        for do_id in act.has_input:
            if do_id not in data_obj_act:
                # This really shouldn't happen
                if do_id not in warned_objects:
                    logging.warning(f"Missing data object {do_id}")
                    warned_objects.add(do_id)
                continue
            parent_act = data_obj_act[do_id]
            # This is to cover the case where it was a duplicate.
            # This shouldn't happen in the future.
            if not parent_act:
                logging.warning("Parent act is none")
                continue
            # Let's make sure these came from the same source
            # This is just a safeguard
            if act.was_informed_by != parent_act.was_informed_by:
                logging.warning("Mismatched informed by for "
                                f"{do_id} in {act.id} "
                                f"{act.was_informed_by} != "
                                f"{parent_act.was_informed_by}")
                continue
            # We only want to use it as a parent if it is the right
            # parent workflow. Some inputs may come from ancestors
            # further up
            if parent_act.workflow in act_pred_wfs:
                # This is the one
                act.parent = parent_act
                parent_act.children.append(act)
                logging.debug(f"Found parent: {parent_act.id}"
                              f" {parent_act.name}")
                break
        if len(act.workflow.parents) > 0 and not act.parent:
            logging.warning(f"Didn't find a parent for {act.id}")
    # Now all the activities have their parent
    return activities


def _find_data_object_activities(activities, data_objs_by_id):
    """
    Find the activity that generated each data object to
    use in the relationship method.
    """
    data_obj_act = dict()
    for act in activities:
        for do_id in act.has_output:
            if do_id in data_objs_by_id:
                do = data_objs_by_id[do_id]
                act.add_data_object(do)
            # If its a dupe, set it to none
            # so we can ignore it later.
            # Once we re-id the data objects this
            # shouldn't happen
            if do_id in data_obj_act:
                if do_id not in warned_objects:
                    logging.warning(f"Duplicate output object {do_id}")
                    warned_objects.add(do_id)
                data_obj_act[do_id] = None
            else:
                data_obj_act[do_id] = act
    return data_obj_act


def load_activities(db, workflows: list[Workflow], filter: dict = {}):
    """
    This reads the activities from Mongo.  It also
    finds the parent and child relationships between
    the activities using the has_output and has_input
    to connect things.

    Finally it creates a map of data objects by type
    for each activity.

    Inputs:
    db: mongo database
    workflow: workflow
    """

    # This is map from the data object ID to the activity
    # that created it.
    data_objs_by_id = _load_data_objects(db, workflows)

    # Build up a set of relevant activities and a map from
    # the output objects to the activity that generated them.
    activities = _read_acitivites(db, workflows, data_objs_by_id, filter)
    data_obj_act = _find_data_object_activities(activities, data_objs_by_id)

    # Now populate the parent and children values for the
    # activities
    _resolve_relationships(activities, data_obj_act)
    return activities


class DataObject(object):
    """
    Data Object Class
    """

    _FIELDS = [
        "id",
        "name",
        "description",
        "url",
        "md5_checksum",
        "file_size_bytes",
        "data_object_type",
    ]

    def __init__(self, rec: dict):
        for f in self._FIELDS:
            setattr(self, f, rec.get(f))


class Activity(object):
    """
    Activity Object Class
    """

    _FIELDS = [
        "id",
        "name",
        "git_url",
        "version",
        "has_input",
        "has_output",
        "was_informed_by",
        "type",
    ]

    def __init__(self, activity_rec: dict, wf: Workflow):
        self.parent = None
        self.children = []
        self.data_objects_by_type = dict()
        self.workflow = wf
        for f in self._FIELDS:
            setattr(self, f, activity_rec.get(f))
        if self.type == "nmdc:OmicsProcessing":
            self.was_informed_by = self.id

    def add_data_object(self, do: DataObject):
        self.data_objects_by_type[do.data_object_type] = do
