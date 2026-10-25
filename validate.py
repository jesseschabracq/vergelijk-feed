#!/usr/bin/env python3
"""
Controleert de feed:
  1. Basischeck: welgevormde XML en alle verplichte velden per offer aanwezig.
  2. XSD-check tegen het schema van Compare Group (als dat te downloaden is).

Exit 1 bij fouten, zodat GitHub Actions de feed dan niet publiceert.
"""
import sys
import urllib.request
from pathlib import Path
from lxml import etree

XSD_URL = "https://sc.vergelijk.nl/webshops/CG_feedmodel_schema_v1.4.xsd"
REQUIRED = [
    "shopOfferId", "shopCategory", "products/product/name", "products/product/brand",
    "products/product/identifiers/identifier/value", "products/product/state", "basePrice", "deepLink",
    "media/medium/url", "inStock", "shippingOptions/shippingOption/countryCode",
    "shippingOptions/shippingOption/deliveryTime", "shippingOptions/shippingOption/method",
    "shippingOptions/shippingOption/price",
]


def main(path):
    doc = etree.parse(path)
    offers = doc.findall("offers/offer")
    problems = []
    ids = set()
    for o in offers:
        oid = o.findtext("shopOfferId")
        if oid in ids:
            problems.append(f"dubbele shopOfferId {oid}")
        ids.add(oid)
        for field in REQUIRED:
            if not (o.findtext(field) or "").strip():
                problems.append(f"offer {oid}: {field} ontbreekt")
    print(f"{len(offers)} offers gecontroleerd, {len(problems)} problemen in de basischeck")
    for p in problems[:30]:
        print("  -", p)

    xsd_raw = b""
    try:
        with urllib.request.urlopen(XSD_URL, timeout=30) as r:
            xsd_raw = r.read()
            schema = etree.XMLSchema(etree.fromstring(xsd_raw))
    except Exception as e:  # schema niet bereikbaar: lokale kopie gebruiken
        local = Path(__file__).resolve().parent / "tests" / "cg_schema.xsd"
        if local.exists():
            print(f"::warning::XSD niet opgehaald ({e}); lokale kopie gebruikt")
            xsd_raw = local.read_bytes()
            schema = etree.XMLSchema(etree.fromstring(xsd_raw))
        else:
            print(f"::warning::XSD niet opgehaald ({e}); alleen basischeck uitgevoerd")
            schema = None

    xsd_errors = []
    if schema is not None:
        if schema.validate(doc):
            print("XSD-validatie: OK")
        else:
            xsd_errors = list(schema.error_log)
            print(f"XSD-validatie: {len(xsd_errors)} fouten")
            seen = {}
            for err in xsd_errors:
                seen.setdefault(err.message, err.line)
            for msg, line in list(seen.items())[:30]:
                print(f"  - {msg} (eerste keer op regel {line})")
            if "--show-xsd" in sys.argv:
                print("----- XSD -----")
                print(xsd_raw.decode("utf-8", errors="replace"))
                print("----- einde XSD -----")

    beslist_problems = check_beslist(Path(path).with_name("beslist.xml"))
    if problems or xsd_errors or beslist_problems:
        sys.exit(1)


G = "{http://base.google.com/ns/1.0}"
BESLIST_REQUIRED = [G + "id", "title", "link", G + "image_link", G + "price", G + "availability", G + "brand",
                    "levertijd", "weergave"]


def check_beslist(path):
    """Basischeck beslist.xml: welgevormd, verplichte velden, unieke id's, weergave 0/1."""
    if not path.exists():
        return []
    doc = etree.parse(str(path))
    items = doc.findall("channel/item")
    problems, ids = [], set()
    for it in items:
        iid = it.findtext(G + "id")
        if iid in ids:
            problems.append(f"dubbele id {iid}")
        ids.add(iid)
        for field in BESLIST_REQUIRED:
            if not (it.findtext(field) or "").strip():
                problems.append(f"item {iid}: {field.replace(G, 'g:')} ontbreekt")
        if it.findtext("weergave") not in ("0", "1"):
            problems.append(f"item {iid}: weergave moet 0 of 1 zijn")
    shown = sum(1 for it in items if it.findtext("weergave") == "1")
    print(f"beslist.xml: {len(items)} items, {shown} zichtbaar, {len(problems)} problemen")
    for pr in problems[:30]:
        print("  -", pr)
    return problems


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(args[0] if args else "public/vergelijk.xml")
