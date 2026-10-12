"""Bouwt een kleine testset in het formaat van de Shopify bulk-export (JSONL).
Velden komen uit echte Living Lovely-producten (okt 2026); prijzen/gewichten van
producten die niet zijn opgevraagd en het multi-variant-product zijn fictief."""
import json, pathlib
here = pathlib.Path(__file__).parent
DEF = "gid://shopify/DeliveryProfile/68139843744"
LAM = "gid://shopify/DeliveryProfile/103916306780"
POL = "gid://shopify/DeliveryProfile/124522070364"

def img(name, w=2000, h=2000):
    return {"__typename": "MediaImage", "image": {"url": f"https://cdn.shopify.com/s/files/1/0496/6006/8000/files/{name}.jpg", "width": w, "height": h}}

def var(vid, title, sku, barcode, price, avail=True, weight=0, profile=DEF, cap=None, qty=5, policy="DENY"):
    return {"id": f"gid://shopify/ProductVariant/{vid}", "legacyResourceId": str(vid), "title": title, "sku": sku,
            "barcode": barcode, "price": price, "compareAtPrice": cap, "availableForSale": avail,
            "inventoryQuantity": qty if avail else 0, "inventoryPolicy": policy,
            "deliveryProfile": {"id": profile},
            "inventoryItem": {"tracked": True, "measurement": {"weight": {"value": weight, "unit": "KILOGRAMS"}}}}

def prod(pid, title, handle, vendor, ptype, cat, desc, variants, images, **mf):
    p = {"id": f"gid://shopify/Product/{pid}", "legacyResourceId": str(pid), "title": title, "handle": handle,
         "vendor": vendor, "productType": ptype, "status": "ACTIVE", "isGiftCard": mf.pop("gift", False),
         "onlineStoreUrl": f"https://livinglovely.nl/products/{handle}", "tags": [], "descriptionHtml": desc,
         "category": {"fullName": cat} if cat else None}
    for k in ("materiaal", "dropColour", "dropMaterial", "dropEan", "preOrder", "preOrderDate"):
        p[k] = {"value": mf[k]} if k in mf else None
    rows = [p]
    for i in images:
        rows.append(dict(i, __parentId=p["id"]))
    for v in variants:
        rows.append(dict(v, __parentId=p["id"]))
    return rows

STD = lambda naam, merk, specs, lever: (
    f"<h2>{naam} van {merk}</h2>\n<p>Breng rust in je interieur met dit item. Bestel vandaag nog en geniet snel.</p>\n"
    "<h3>Specificaties</h3>\n<ul>\n" + "".join(f"<li>{s}</li>\n" for s in specs) +
    f'<li>Merk: <a href="https://livinglovely.nl/collections/merk-x">{merk}</a></li>\n<li>{lever}</li>\n</ul>\n'
    f"<h3>Waarom kiezen voor de {naam}?</h3>\n<p>Stevig en tijdloos. Gratis bezorgd en 10% korting.</p>\n"
    "<h3>Waarom bestellen bij Living Lovely?</h3>\n<p>Scherpe prijzen, snelle levering uit voorraad.</p>")

rows = []
rows += prod(1, "J-Line salontafel Vincent mango hout zwart medium", "table-vincent-mango-wood-black-medium", "J-Line", "Salontafel",
    "Meubelen > Tafels > Accenttafels > Salontafels",
    STD("Salontafel Vincent Mango Hout Zwart Medium", "J-Line", ["Materiaal: Mangohout", "Afmetingen: L80cm x B80cm x H39,5cm", "Kleur: Zwart", "Gewicht: 22 kg"],
        "Uit voorraad leverbaar - Gratis thuis bezorgd - Levertijd 1-2 dagen"),
    [var(31479, "Default Title", "31479", "5400924314798", "398.00", weight=22)],
    [img("j-line-salontafel-vincent-mango-hout-zwart-medium", 1936, 1936), img("j-line-salontafel-vincent-mango-hout-zwart-medium2", 1960, 1960)],
    dropColour="Black", dropMaterial="Mdf(1%),mango wood(95%),metal(4%)", dropEan="5400924314798")
rows += prod(2, "Bijzettafel Tiana Aluminium Goud J-Line", "bijzettafel-tiana-aluminium-goud-j-line", "J-Line", "Bijzettafel",
    "Meubelen > Tafels > Accenttafels > Bijzettafels",
    "<p>Geef je interieur een vleugje glamour met de Bijzettafel Tiana van J-Line.</p>",
    [var(36319, "Default Title", "36319", "5400924363192", "159.00", weight=4.3)],
    [img("bijzettafel-tiana-aluminium-goud-j-line")], dropColour="Gold", dropMaterial="Aluminium(100%)")
rows += prod(3, "Kae Gold Aluminium Koffietafel 2 Laags Zwart Frame PTMD", "salontafel-kae-ptmd", "PTMD", "Salontafel",
    "Meubelen > Tafels > Accenttafels > Salontafels", "<p>De PTMD Kae 2-lagen salontafel is een stijlvolle toevoeging.</p>",
    [var(685867, "Default Title", "685867", "8716109910042", "625.00", weight=21)],
    [img("685867-0"), img("685867-1", 1365, 2048), img("tiny", 300, 300)], materiaal="Metaal")
rows += prod(4, "New Khine Creme koffietafel PTMD", "new-khine-creme-koffietafel-ptmd", "PTMD", "Salontafel",
    "Meubelen > Tafels > Accenttafels > Salontafels", "<p>Ronde salontafel set.</p>",
    [var(696216, "Default Title", "696216", "8720014221452", "1760.00", avail=False)], [img("696216-0")])
rows += prod(5, "Eetkamerstoel Bella Stof Off White Met Armleuning Starfurn", "eetkamerstoel-bella-starfurn", "Starfurn", "Eetkamerstoel",
    "Meubelen > Stoelen > Keuken- en eetkamerstoelen",
    '<h2>Eetkamerstoel Bella Off White van Starfurn</h2>\n<p>Zoek je een eetkamerstoel die zacht zit? Je ontvangt twee stoelen per bestelling.</p>\n<h3>Specificaties</h3>\n<ul>\n<li>Materiaal: stof Cremona 01 met metalen onderstel in de kleur sand</li>\n<li>Afmetingen: L64cm x B65cm x H83cm</li>\n<li>Kleur: Off white</li>\n<li>Merk: <a href="https://livinglovely.nl/collections/merk-starfurn">Starfurn</a>\n</li>\n<li>Uit voorraad leverbaar - Gratis thuis bezorgd - Levertijd 1-3 werkdagen</li>\n</ul>\n<h3>Waarom kiezen voor de Eetkamerstoel Bella Off White?</h3>\n<p>De zithoogte van 51 cm sluit mooi aan op een standaard eettafel. Het draagvermogen is 120 kg.</p>\n<h3>Waarom bestellen bij Living Lovely?</h3>\n<p>Bij Living Lovely koop je meubels tegen scherpe prijzen.</p>',
    [var(900005, "Default Title", "BELLA-OW", "", "449.00", weight=14)], [img("bella-1")])
rows += prod(6, "Handgeknoopte Parasol Fringes  Zwart 250cm", "parasol-fringes-zwart", "Todo Bien", "Parasol", None,
    '<p data-mce-fragment="1">De parasol is gemaakt van teakhout.</p>\n<p data-mce-fragment="1">Gratis thuis bezorgd.</p>',
    [var(900006, "Default Title", "TB-FR-250", None, "495.00")], [img("fringes")])
rows += prod(7, "Lamelio Houtlook Wandpaneel - Asti Zilver", "lamelio-asti-zilver", "Lamelio", "Wandpaneel", "Huis en tuin > Decoratie",
    '<p>De houtlook wandpanelen van Lamelio zijn gemaakt van 80% gerecycled kunststof.</p>\n<p><span class="product-usp-title">SNELLE LEVERING! </span><span class="product-usp-subtext">Binnen 5 dagen geleverd indien op voorraad!</span></p>',
    [var(900007, "Default Title", "LAM-ASTI-ZI", "8720618360057", "89.95", profile=LAM)], [img("asti")])
rows += prod(8, "Ornament Indonesische Schelpentoren Bayu Zalm Roze - Pole To Pole", "schelpentoren-bayu-zalm-roze", "Pole To Pole", "Ornament",
    "Huis en tuin > Decoratie > Ornamenten",
    '<p>Haal de schoonheid met deze Indonesische schelpentoren.</p>\n<h3>Specificaties</h3>\n<ul>\n<li>\n<strong>Afmetingen</strong>: 9,5 cm breed, 8,5 cm diep, 52 cm hoog.</li>\n<li>\n<strong>Materialen</strong>: Schelpen, touw en metaal.</li>\n<li>\n<strong>Kleur</strong> Zalm Roze</li>\n<li>\n<strong>Uit voorraad leverbaar</strong> - Levertijd 1 a 2 dagen</li>\n</ul>\n<p>Bestel vandaag en voeg een vleugje Indonesische charme toe aan jouw huis.</p>',
    [var(900008, "Default Title", "PTP-BAYU-ZR", "1234567890123", "39.95", weight=1.2)], [img("bayu")])
rows += prod(9, "Loungebank Kos - Laui Lounge™", "loungebank-kos-laui-lounge", "Laui Lounge", "Bank", "Meubelen > Buitenmeubels > Loungebanken",
    STD("Loungebank Kos", "Laui Lounge", ["Afmetingen: L200cm x B90cm x H70cm"], "Uit voorraad leverbaar - Gratis thuis bezorgd - Levertijd 5-10 werkdagen"),
    [var(900091, "200 cm", "LL-KOS-200", "8721234567892", "1299.00", weight=45, cap="1499.00"),
     var(900092, "160 cm", "LL-KOS-160", "", "1099.00", weight=38),
     var(900093, "Kussen los", "LL-KOS-K", "", "59.00", weight=35)],
    [img("kos-1"), img("kos-2")])
rows += prod(10, "Wandrek Bryce Zwart DTP Interiors", "wandrek-bryce-dtp", "DTP Home", "Wandrek", "Meubelen > Planken",
    "<p>Wandrek.</p>", [var(900010, "Default Title", "BL 741145", "", "129.00")], [img("bryce")], preOrderDate="2099-01-15")
rows += prod(11, "Cadeaubon", "cadeaubon", "Living Lovely", "Cadeaubon", None, "", [var(900011, "€50", "", "", "50.00")], [img("cb")], gift=True)
rows += prod(12, "Stoel Pila Zwart PTMD", "stoel-pila-ptmd", "PTMD", "Eetkamerstoel", "Meubelen > Stoelen",
    "<p>Stoel.</p>", [var(900012, "Default Title", "700001", "8716109910049", "189.00", profile=POL)], [img("pila")])

rows += prod(13, "DTP Home Classic Salontafel Icon 130cm", "dtp-icon-130", "DTP Home", "Salontafel", "Meubelen > Tafels",
    "<p>Salontafel.</p>", [var(900013, "Default Title", "BM 120130", "", "899.00", qty=0, policy="CONTINUE")], [img("icon")])

with open(here / "products.jsonl", "w", encoding="utf-8") as fh:
    for r in rows:
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")

W = lambda lo, hi=None: [{"field": "TOTAL_WEIGHT", "operator": "GREATER_THAN_OR_EQUAL_TO", "conditionCriteria": {"__typename": "Weight", "value": lo, "unit": "KILOGRAMS"}}] + (
    [{"field": "TOTAL_WEIGHT", "operator": "LESS_THAN_OR_EQUAL_TO", "conditionCriteria": {"__typename": "Weight", "value": hi, "unit": "KILOGRAMS"}}] if hi is not None else [])
P = lambda lo: [{"field": "TOTAL_PRICE", "operator": "GREATER_THAN_OR_EQUAL_TO", "conditionCriteria": {"__typename": "MoneyV2", "amount": str(lo)}}]
M = lambda name, price, cond: {"name": name, "active": True, "rateProvider": {"__typename": "DeliveryRateDefinition", "price": {"amount": str(price)}}, "methodConditions": cond}
shipping = {"default": DEF, "profiles": {
    DEF: {"name": "Algemeen profiel", "methods": [M("Standaard verzending", 5.95, W(0, 20)), M("GRATIS VERZENDING", 0.0, P(75)), M("Standaard verzending+", 9.95, W(20, 30))]},
    LAM: {"name": "Lamelio", "methods": [M("Standaard verzending+", 50.0, [])]},
    POL: {"name": "PTMD Chairs Poland", "methods": []},
}}
(here / "shipping.json").write_text(json.dumps(shipping, indent=1), encoding="utf-8")
print(len(rows), "regels")
