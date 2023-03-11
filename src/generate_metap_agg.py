import os
import sys
import requests
from pymongo import MongoClient


_base_url = "https://data.microbiomedata.org/data"
_base_fn = "/global/cfs/cdirs/m3408/results"


def init_nmdc_mongo():
    url = os.environ["MONGO_URL"]
    client = MongoClient(url, directConnection=True)
    nmdc = client.nmdc
    return nmdc


def do_line(line, gene_list):
    if line.find("ko=") > 0:
        annotations = line.split("\t")[8].split(";")
        id = annotations[0][3:]
        if id not in gene_list:
            return None, None

        for anno in annotations:
            if anno.startswith("ko="):
                ko = anno[3:].replace("KO:", "KEGG.ORTHOLOGY")
                return id, ko
    return None, None


def get_kegg_terms(url, gene_list):
    # Yes: We could do a json load but that can be slow for these large
    # files.  So let's just grab what we need
    kos = {}
    fn = url.replace(_base_url, _base_fn)

    if os.path.exists(fn):
        with open(fn) as f:
            for line in f:
                id, ko_line = do_line(line, gene_list)
                if ko_line:
                    kos[id] = ko_line.rstrip().split(",")
    else:
        # It looks like some of the data objects have
        # an error
        s = requests.Session()
        with s.get(url, headers=None, stream=True) as resp:
            if not resp.ok:
                print(f"Failed: {url}")
                return []
            for line in resp.iter_lines():
                ko = do_line(line.decode(), gene_list)
                if ko:
                    kos[id] = ko
    return kos

def find_anno(nmdc, dos):
    for doid in dos:
        do = nmdc.data_object_set.find_one({"id": doid})
        if not do:
            continue
        if 'data_object_type' not in do:
            continue
        if do['data_object_type'] == 'Annotation Amino Acid FASTA':
            return do['url'].replace("_proteins.faa", "_functional_annotation.gff")
    return None

def process_act(nmdc, act):
    # Get the URL and ID
    url = find_anno(nmdc, act['has_input'])
    if not url:
        raise ValueError("Missing url")
    url_id = url.split('/')[-1].replace("nmdc_", "nmdc:").split('_')[0]
    last_id = None
    id_list = set()
    # Get the filter list
    for pep in act['has_peptide_quantifications']:
        mid = pep['all_proteins'][0].split('_')[0]
        if not mid.startswith(url_id):
            continue
        if last_id and last_id != mid:
            raise ValueError(f"changing reference {last_id} {mid}")
            continue
        for prot in pep['all_proteins']:
            id_list.add(prot)
        last_id = mid
    proteins = get_kegg_terms(url, id_list)
    kegg_recs = {}
    for pep in act['has_peptide_quantifications']:
        mid = pep['all_proteins'][0].split('_')[0]
        if not mid.startswith(url_id):
            continue
        for prot in pep['all_proteins']:
            if prot not in proteins:
                continue
            kos = proteins[prot]
            for ko in kos:
                if ko not in kegg_recs:
                    kegg_recs[ko] = {"metaproteomic_analysis_id": act['id'],
                                     "gene_function_id": ko,
                                     "count": 0,
                                     "best_protein": False}
                kegg_recs[ko]["count"] += 1
                if prot == pep['best_protein']:
                    kegg_recs[ko]["best_protein"] = True
    for ko in kegg_recs:
        print(kegg_recs[ko])

if __name__ == "__main__":
    nmdc = init_nmdc_mongo()
    act_recs = {}
    acts = []
    print("get acts")
    for actrec in nmdc.metaproteomics_analysis_activity_set.find({}):
        # New annotations should have this
        act = actrec['id']
        print(act)
        acts.append(act)
        act_recs[act] = actrec
        try:
            process_act(nmdc, actrec)
        except Exception as ex:
            print(ex)
    sys.exit()

    print("Getting list of indexed objects")
    done = nmdc.metap_gene_function_aggregation.distinct("metaproteomic_analysis_id ")
    for act in acts:
        if act in done:
            continue
        break
        continue

        if len(rows) > 0:
            print(' - %s' % (str(rows[0])))
            nmdc.functional_annotation_agg.insert_many(rows)
        else:
            print(f' - No rows for {act}')
