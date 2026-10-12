#!/usr/bin/env python3
"""
Controleert de feed:
  1. Basischeck: welgevormde XML en alle verplichte velden per offer aanwezig.
  2. XSD-check tegen het schema van Compare Group (als dat te downloaden is).

Exit 1 bij fouten, zodat GitHub Actions de feed dan niet publiceert.
"""
import sys
import urllib.request
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
    except Exception as e:  # schema niet bereikbaar: niet blokkeren
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

    if problems or xsd_errors:
        sys.exit(1)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(args[0] if args else "public/vergelijk.xml")
