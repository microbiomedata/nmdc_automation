from src.generate_functional_agg import AnnotationLine
from src.generate_functional_agg import MetaGenomeFuncAgg


def test_parse():
    line = "nmdc:mga0e8jh10_scf_6212_c1	GeneMark.hmm-2 v1.05	CDS	562	1167	52.82	-	0	ID=nmdc:mga0e8jh10_scf_6212_c1_562_1167;translation_table=11;start_type=GTG;product=chorismate mutase/prephenate dehydrogenase;product_source=KO:K14187;cog=COG0287;ko=KO:K14187;ec_number=EC:1.3.1.12,EC:5.4.99.5;pfam=PF02153;superfamily=48179"
    anno = AnnotationLine(line)
    assert anno
    assert len(anno.kegg) > 0
    assert anno.id == "nmdc:mga0e8jh10_scf_6212_c1_562_1167"
    assert anno.kegg == ["KEGG.ORTHOLOGY:K14187"]


def test_kegg(monkeypatch):
    monkeypatch.setenv("MONGO_URL", "mongodb://db")
    mp = MetaGenomeFuncAgg()
    url = "https://data.microbiomedata.org/data/nmdc:mga03eyz63/annotation/nmdc_mga03eyz63_functional_annotation.gff"
    terms = mp.get_kegg_terms(url)
    assert len(terms) == 3608
    assert terms["KEGG.ORTHOLOGY:K03088"] == 359
