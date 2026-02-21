############################################################################################################
# This script takes the input of a full workflow_execution_set query and outputs
# 4 files: the workflow IDs, data object IDs, and their respective deletion request bodies.
# Docstring / Doctest Reference: https://docs.python.org/3/library/doctest.html
############################################################################################################

import os
import json
from typing import List, Tuple, Dict, Union


def list_functions(verbose: bool = False) -> List[str]:
    """
    Return a list of function names defined in this module.

    If ``verbose`` is True, also print the functions to stdout.

    Example:
        >>> 'make_deletion_descriptors' in list_functions()
        True
    """
    import inspect

    module = inspect.getmodule(list_functions)
    functions = [
        name
        for name, obj in inspect.getmembers(module, inspect.isfunction)
        if obj.__module__ == __name__
    ]
    if verbose:
        for name in functions:
            print(name)
    return functions


def help():
    """
    Print the available functions in this module.

    This is called automatically when the module is imported for interactive use.
    """
    funcs = list_functions()
    print("Available functions:")
    for f in funcs:
        print(f)


def make_deletion_descriptors(collection_names_and_document_ids: List[Tuple[str, List[str]]], key: str = "id", limit: int = 1) -> Dict[str, List[Dict]]:
    """
    Creates deletion descriptors grouped by collection name.

    Each descriptor is a dictionary used in a request to the `/queries:run` endpoint of the Runtime API in JSON format.
    Descriptors are grouped by collection, as the endpoint processes one collection per request.

    Args:
        collection_names_and_document_ids (list of tuples): Each tuple is (collection_name, document_ids).
        key (str): The document field to query against. Defaults to "id".
        limit (int): Maximum number of documents to delete per descriptor. Defaults to 1.

    Returns:
        dict: A dictionary where each key is a collection name and each value is a list of deletion descriptors.

    Examples:
        >>> make_deletion_descriptors([])
        {}
        >>> make_deletion_descriptors([("my_collection", "my_id")])
        {'my_collection': [{'q': {'id': 'my_id'}, 'limit': 1}]}
        >>> make_deletion_descriptors([("my_collection", "id1"), ("my_collection", "id2")])
        {'my_collection': [{'q': {'id': 'id1'}, 'limit': 1}, {'q': {'id': 'id2'}, 'limit': 1}]}
        >>> make_deletion_descriptors([("coll1", ["a", "B", "c"]), ("coll2", "b")])
        {'coll1': [{'q': {'id': 'a'}, 'limit': 1}, {'q': {'id': 'B'}, 'limit': 1}, {'q': {'id': 'c'}, 'limit': 1}], 'coll2': [{'q': {'id': 'b'}, 'limit': 1}]}
    """

    deletion_descriptors = {}
    for collection_name, document_ids in collection_names_and_document_ids:
        deletion_descriptors.setdefault(collection_name, [])
        # Normalize to list if not already
        if not isinstance(document_ids, list):
            document_ids = [document_ids]
        for doc_id in document_ids:
            descriptor = {"q": {key: doc_id}, "limit": limit}
            deletion_descriptors[collection_name].append(descriptor)
    return deletion_descriptors


def make_request_body(collection_name: str, descriptors: List[Dict]) -> Dict:
    """
    Wraps deletion descriptors in a request body for the Runtime API.

    Args:
        collection_name (str): The MongoDB collection name.
        its_deletion_descriptors (list): A list of deletion descriptors for this collection.

    Returns:
        dict: A deletion request body with the structure expected by `/queries:run`.

    Examples:
        >>> make_request_body("my_collection", [])
        {'delete': 'my_collection', 'deletes': []}
        >>> make_request_body("my_collection", [{'q': {'id': 'abc'}, 'limit': 1}])
        {'delete': 'my_collection', 'deletes': [{'q': {'id': 'abc'}, 'limit': 1}]}
    """

    return {"delete": collection_name, "deletes": descriptors}



def read_id_list(list_file: str) -> list:
    """
    Read a text file and return a list of stripped lines (IDs).

    Parameters:
        list_file (str): Path to the input text file.

    Returns:
        list: A list of strings with leading/trailing whitespace removed.

    Example:
        >>> import os
        >>> with open("test_ids.txt", "w") as f:
        ...     _ = f.write("id1\\n")
        ...     _ = f.write("id2\\n")
        ...     _ = f.write("id3\\n")
        >>> read_id_list("test_ids.txt")
        ['id1', 'id2', 'id3']
        >>> os.remove("test_ids.txt")  # cleanup
    """
    id_list = []
    with open(list_file, "r") as f:
        id_list = [line.strip() for line in f]
    return id_list

def write_id_quotes(id_list: list, filename: str) -> list:
    """
    Write a list of IDs to a file, each wrapped in single quotes and followed by a comma.

    Parameters:
        id_list (list): List of string IDs to write.
        filename (str): Path to the output file.

    Returns:
        str: The filename written to.

    Doctest:
        >>> test_ids = ['id1', 'id2']
        >>> write_id_quotes(test_ids, 'quoted_ids.txt')
        'quoted_ids.txt'
        >>> with open('quoted_ids.txt') as f:
        ...     print(f.read())
        'id1',
        'id2',
        <BLANKLINE>
        >>> os.remove("quoted_ids.txt")  # cleanup
    """
    with open(filename, "w") as f:
        for id in id_list:
            f.write(f"'{id}',\n")
    return filename

def grab_id_list(data: list, field: str) -> list:
    """
    Extracts a list of values for a given field from a list of JSON objects.

    Args:
        data (list): A list of dictionaries.
        field (str): The field whose values should be collected.

    Returns:
        list: List of values for the given field.

    Example:
        >>> grab_id_list([{"id": "x"}, {"id": "y"}], "id")
        ['x', 'y']
        >>> grab_id_list([{"id": ["x", "y", "z"]}, {"id": "a"}], "id")
        ['x', 'y', 'z', 'a']
    """
    id_list = []
    for entry in data:
        val = entry[field]
        if isinstance(val, list):
            id_list.extend(val)
        else:
            id_list.append(val)
    return id_list


def grab_unique_ids(data: List[Dict], field: str) -> Tuple[List[str], List[str]]:
    """
    Extracts unique and duplicate values for a given field from a list of JSON objects.

    Args:
        data (list): A list of dictionaries.
        field (str): The field to evaluate for duplicates.

    Returns:
        tuple: (list of unique values, list of duplicates)

    Example:
        >>> grab_unique_ids([{"id": "x"}, {"id": "x"}, {"id": "y"}], "id")
        (['x', 'y'], ['x'])
    """
    seen, duplicates = set(), []
    unique = []
    for entry in data:
        val = entry[field]
        if val in seen:
            duplicates.append(val)
        else:
            seen.add(val)
            unique.append(val)
    return unique, duplicates

def make_mult_descr(descr_sets: List[Tuple[str, str]]) -> Dict:
    """
    Wrapper around make_deletion_descriptors for multiple collection-ID pairs.

    Args:
        descr_sets (list): List of (collection, id) tuples.

    Returns:
        dict: Mapping of collection names to deletion descriptor lists.
    
    Examples:
        >>> make_mult_descr([("col1", "x")])
        {'col1': [{'q': {'id': 'x'}, 'limit': 1}]}
        >>> make_mult_descr([("col1", ["x", "y"]), ("col2", "z")])
        {'col1': [{'q': {'id': 'x'}, 'limit': 1}, {'q': {'id': 'y'}, 'limit': 1}], 'col2': [{'q': {'id': 'z'}, 'limit': 1}]}
    """
    return make_deletion_descriptors(descr_sets)


def make_mult_reqs(descriptors: Dict[str, List[Dict]]) -> Dict[str, Dict]:
    """
    Constructs request bodies from deletion descriptors.

    Args:
        descriptors (dict): Output from make_deletion_descriptors. Contains 
            col: collection name
            desc: deletion descriptor

    Returns:
        dict: Mapping of collection names to request bodies.
    Examples:
        >>> make_mult_reqs({'col1': [{'q': {'id': 'x'}, 'limit': 1}]})
        {'col1': {'delete': 'col1', 'deletes': [{'q': {'id': 'x'}, 'limit': 1}]}}
        >>> make_mult_reqs({'col1': [{'q': {'id': 'x'}, 'limit': 1}, {'q': {'id': 'y'}, 'limit': 1}], 'col2': [{'q': {'id': 'z'}, 'limit': 1}]})
        {'col1': {'delete': 'col1', 'deletes': [{'q': {'id': 'x'}, 'limit': 1}, {'q': {'id': 'y'}, 'limit': 1}]}, 'col2': {'delete': 'col2', 'deletes': [{'q': {'id': 'z'}, 'limit': 1}]}}
    """
    return {col: make_request_body(col, desc) for col, desc in descriptors.items()}


def write_req_json(req_sets: List[Tuple[str, str]], requests: Dict[str, Dict]) -> List[str]:
    """
    Writes deletion request bodies to files.

    Args:
        req_sets (list): List of (filepath, collection_name) tuples.
        requests (dict): Mapping of collection names to request bodies.

    Returns:
        list: List of file paths written.
    """
    written = []
    for filepath, col_name in req_sets:
        with open(filepath, 'w') as f:
            json.dump(requests[col_name], f, indent=4)
        written.append(filepath)
    return written


def write_lists(list_sets: list):
    """
    Writes plain-text lists of IDs to files.

    Args:
        list_sets (list): List of (filepath, list_of_strings) tuples.

    Returns:
        list: List of file paths written.
    """
    written = []
    for filepath, values in list_sets:
        with open(filepath, 'w') as f:
            f.write("\n".join(str(v) for v in values))
        written.append(filepath)
    return written

def resolve_collection(collection_type: str, collection_dict: dict = {
        "fa": "functional_annotation_agg",
        "do": "data_object_set",
        "wf": "workflow_execution_set",
        "job": "jobs"
    }) -> str:
    """
    Resolve the actual collection name given shorthand or full name.

    Raises ValueError if not found.
    """
    if collection_type in collection_dict:
        return collection_dict[collection_type]
    if collection_type in collection_dict.values():
        return collection_type
    raise ValueError(f"Collection type must be in {list(collection_dict.keys())} or values {list(collection_dict.values())}")


def gen_reqs_from_list(collection_type: str, req_file: str, ids: Union[str, list[str]], key: str = "id", limit: int = 1): 
    """
    Generate and write a deletion request JSON file for a given list of IDs or an ID file.

    The function accepts either a list of IDs or a path to a file containing one ID per line.
    It generates a deletion descriptor and writes a formatted JSON request to the given output file.

    Parameters:
        collection_type (str): The shorthand of the collection. "fa", "do", or "wf"
        req_file (str): Path to the output JSON file.
        ids (Union[str, list]): Either a path to a file with IDs (one per line), or a list of IDs.
        key (str): The key used in the descriptor objects. Defaults to "id". (can also be "was_generated_by", "was_informed_by")
        limit (int): The number of items per request batch. Defaults to 1. (0 for deleting all related to ID)

    Raises:
        TypeError: If `ids` is neither a string nor a list.

    Example:
        >>> gen_reqs_from_list("data_object_set", "test_req.json", ["nmdc:xyz-1", "nmdc:xyz-2"])
        >>> os.path.exists("test_req.json")
        True
        >>> with open("test_req.json") as f:
        ...     req = json.load(f)
        >>> isinstance(req, dict)
        True
        >>> os.remove("test_req.json")

        >>> with open("test_ids.txt", 'w') as f:
        ...     _ = f.write("nmdc:xyz-1\\n")
        ...     _ = f.write("nmdc:xyz-2\\n")
        >>> gen_reqs_from_list("data_object_set", "test_req.json", "test_ids.txt")
        >>> os.path.exists("test_req.json")
        True
        >>> with open("test_req.json") as f:
        ...     req = json.load(f)
        >>> isinstance(req, dict)
        True
        >>> os.remove("test_req.json")
        >>> os.remove("test_ids.txt")
    """
    collection = resolve_collection(collection_type)

    if isinstance(ids, str):
        id_list = read_id_list(ids)
    elif isinstance(ids, list):
        id_list = ids
    else:
        raise TypeError("Third argument must be either a file path (str) or a list of IDs.")

    descriptor = make_deletion_descriptors([(collection, id_list)], key, limit)
    request = make_mult_reqs(descriptor)
    with open (req_file, 'w') as file: 
        json.dump(request[collection], file, indent = 4)

class Mongo_Collection:
    """
    Represents a set of workflow and data object documents, and creates deletion request files from them.

    Attributes:
        collection_type (str): Name of the workflow collection (default: workflow_execution_set).
        object_set (str): Name of the data object collection (default: data_object_set).
    """
    collection_type = "workflow_execution_set"
    object_set = "data_object_set"

    def __init__(self, record_file: str, prefix: str):
        """
        Initializes paths, loads data, and sets up output files and lists.

        Args:
            record_file (str): Path to the input JSON file.
            prefix (str): Prefix for output files.
        """
        wrk_dir = os.path.dirname(record_file)
        path = os.path.join(wrk_dir, prefix)
        os.makedirs(path, exist_ok=True)

        self.wf_list, self.obj_list, self.list_sets, self.req_sets, self.descr_sets = [], [], [], [], []
        self.requests, self.descriptors = {}, {}

        self.files = {
            "wf_ids": os.path.join(path, f"{prefix}_wf_ids.txt"),
            "obj_ids": os.path.join(path, f"{prefix}_obj_ids.txt"),
            "wf_req": os.path.join(path, f"{prefix}_wf_req.json"),
            "obj_req": os.path.join(path, f"{prefix}_obj_req.json")
        }

        with open(record_file, 'r') as file:
            self.data = json.load(file)

    def fill_lists(self):
        """
        Extracts workflow and data object IDs from the input data.
        """
        self.wf_list = grab_id_list(self.data, "id")
        self.obj_list = grab_id_list(self.data, "has_output")



    def write_req(self):
        """
        Generates deletion descriptors and request bodies.
        """
        self.descr_sets = [
            (self.collection_type, self.wf_list),
            (self.object_set, self.obj_list)
        ]
        self.descriptors = make_mult_descr(self.descr_sets)
        self.requests = make_mult_reqs(self.descriptors)

    def generate_files(self):
        """
        Writes all ID and request files.
        """
        self.list_sets = [
            (self.files["wf_ids"], self.wf_list),
            (self.files["obj_ids"], self.obj_list)
        ]
        self.req_sets = [
            (self.files["wf_req"], self.collection_type),
            (self.files["obj_req"], self.object_set)
        ]
        write_req_json(self.req_sets, self.requests)
        write_lists(self.list_sets)

    def run_all(self):
        """
        Runs the full process: extract IDs, build requests, and write files.
        """
        self.fill_lists()
        self.write_req()
        self.generate_files()



# Print available functions when module is imported for use (not when run as script)
if __name__ != "__main__":
    # Avoid printing during doctest execution
    try:
        help()
    except Exception:
        pass

if __name__ == "__main__":
    import doctest
    doctest.testmod()