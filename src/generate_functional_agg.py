import os
import requests
from pymongo import MongoClient


class AnnotationLine():

    def __init__(self, line, filter=None):
        self.id = None
        self.kegg = None
        self.cogs = None
        self.product = None
        self.ec_numbers = None

        if line.find("ko=") > 0:
            annotations = line.split("\t")[8].split(";")
            self.id = annotations[0][3:]
            if filter and self.id not in filter:
                return

            for anno in annotations:
                if anno.startswith("ko="):
                    kos = anno[3:].replace("KO:", "KEGG.ORTHOLOGY:")
                    self.kegg = kos.rstrip().split(',')
                elif anno.startswith("cog="):
                    self.cogs = anno[4:].split(',')
                elif anno.startswith("product="):
                    self.product = anno[8:]
                elif anno.startswith("ec_number="):
                    self.ec_numbers = anno[10:].split(",")


class MetaGenomeFuncAgg():
    _BASE_URL_ENV = "NMDC_BASE_URL"
    _base_url = "https://data.microbiomedata.org/data"
    _BASE_PATH_ENV = "NMDC_BASE_PATH"
    _base_dir = "/global/cfs/cdirs/m3408/results"

    def __init__(self):
        url = os.environ["MONGO_URL"]
        client = MongoClient(url, directConnection=True)
        self.db = client.nmdc
        self.agg_col = self.db.functional_annotation_agg
        self.act_col = self.db.metagenome_annotation_activity_set
        self.do_col = self.db.data_object_set
        self.base_url = os.environ.get(self._BASE_URL_ENV, self._base_url)
        self.base_dir = os.environ.get(self._BASE_PATH_ENV, self._base_dir)

    def get_kegg_terms(self, url):
        fn = url.replace(self.base_url, self.base_dir)

        if os.path.exists(fn):
            lines = open(fn)
        else:
            s = requests.Session()
            resp = s.get(url, headers=None, stream=True)
            if not resp.ok:
                raise OSError(f"Failed to read {url}")
            lines = resp.iter_lines()

        kos = {}
        for line in lines:
            if isinstance(line, bytes):
                line = line.decode()
            anno = AnnotationLine(line)
            if anno.kegg:
                for ko in anno.kegg:
                    if ko not in kos:
                        kos[ko] = 0
                    kos[ko] += 1
        return kos

    def find_anno(self, dos):
        """
        Find the GFF annotation URL
        input: list of data object IDs
        returns: GFF functional annotation URL
        """
        url = None
        for doid in dos:
            do = self.do_col.find_one({"id": doid})
            # skip over bad records
            if not do or 'data_object_type' not in do:
                continue
            if do['data_object_type'] == 'Functional Annotation GFF':
                url = do['url']
                break
        return url

    def process_activity(self, act):
        url = self.find_anno(act['has_output'])
        if not url:
            raise ValueError("Missing url")
        print(f"{act}: {url}")
        id = act['id']
        cts = self.get_kegg_counts(act, url)

        rows = []
        for func, ct in cts.items():
            rec = {
                'metagenome_annotation_id': id,
                'gene_function_id': func,
                'count': ct
                }
            rows.append(rec)
        print(f' - {len(rows)} terms')
        return rows

    def sweep(self):
        print("Getting list of indexed objects")
        done = self.agg_col.distinct("metagenome_annotation_id")
        for actrec in self.act_col.find({}):
            # New annotations should have this
            act_id = actrec['id']
            if act_id in done:
                continue
            try:
                rows = self.process_activity(actrec)
            except Exception as ex:
                # Continue on errors
                print(ex)
                continue
            if len(rows) > 0:
                print(' - %s' % (str(rows[0])))
                self.agg_col.insert_many(rows)
            else:
                print(f' - No rows for {act_id}')


if __name__ == "__main__":
    mg = MetaGenomeFuncAgg()
    mg.sweep()


# Schema
#
#        metagenome_annotation_id        |   gene_function_id    | count
# ---------------------------------------+-----------------------+-------
#  nmdc:006424afe19af3c36c50e2b2e68b9510 | KEGG.ORTHOLOGY:K00001 |   145
