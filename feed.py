#!/usr/bin/env python3
"""
Living Lovely -> vergelijk.nl (Compare Group) productfeed.

Haalt alle actieve producten uit Shopify op (bulk operation), zet ze om naar het
Compare Group XML-formaat (handleiding v5.8, "complex XML") en schrijft:

  <out>/vergelijk.xml   de feed
  <out>/status.json     samenvatting van de run
  <out>/excluded.csv    producten die niet in de feed staan, met reden
  <out>/index.html      klein overzicht

Gebruik:
  python feed.py --out public
  python feed.py --out public --from-jsonl products.jsonl --shipping-json shipping.json   (offline test)

Authenticatie (een van beide):
  SHOPIFY_CLIENT_ID + SHOPIFY_CLIENT_SECRET   (Dev Dashboard-app, client credentials grant)
  SHOPIFY_ACCESS_TOKEN                        (bestaand Admin API-token)
"""

import argparse
import csv
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

try:
    from zoneinfo import ZoneInfo
    NL_TZ = ZoneInfo("Europe/Amsterdam")
except Exception:  # pragma: no cover
    NL_TZ = timezone.utc

HERE = Path(__file__).resolve().parent

# --------------------------------------------------------------------------- #
# Shopify API
# --------------------------------------------------------------------------- #

BULK_QUERY = """
{
  products(query: "status:active") {
    edges { node {
      id legacyResourceId title handle vendor productType status isGiftCard onlineStoreUrl tags
      descriptionHtml
      category { id fullName }
      materiaal: metafield(namespace: "my_fields", key: "materiaal") { value }
      dropColour: metafield(namespace: "droppery", key: "colour_") { value }
      dropMaterial: metafield(namespace: "droppery", key: "material_composition") { value }
      dropEan: metafield(namespace: "droppery", key: "ean") { value }
      preOrder: metafield(namespace: "custom", key: "pre_order") { value }
      preOrderDate: metafield(namespace: "custom", key: "pre_order_verwachte_leverdatum") { value }
      media { edges { node { __typename ... on MediaImage { image { url width height } } } } }
      variants { edges { node {
        id legacyResourceId title sku barcode price compareAtPrice availableForSale
        inventoryQuantity inventoryPolicy
        deliveryProfile { id }
        inventoryItem { tracked measurement { weight { value unit } } }
      } } }
    } }
  }
}
"""

BULK_RUN = """
mutation($q: String!) {
  bulkOperationRunQuery(query: $q, groupObjects: false) {
    bulkOperation { id status }
    userErrors { field message }
  }
}
"""

BULK_POLL = """
query($id: ID!) {
  bulkOperation(id: $id) { id status errorCode objectCount rootObjectCount url partialDataUrl }
}
"""

PROFILES_QUERY = """
query { deliveryProfiles(first: 50) { nodes { id name default } } }
"""

PROFILE_ZONES_QUERY = """
query($id: ID!, $after: String) {
  deliveryProfile(id: $id) {
    id name
    profileLocationGroups {
      locationGroupZones(first: 10, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          zone { name countries { code { countryCode } } }
          methodDefinitions(first: 20) { nodes {
            name active
            rateProvider { __typename ... on DeliveryRateDefinition { price { amount } } }
            methodConditions { field operator conditionCriteria {
              __typename ... on MoneyV2 { amount } ... on Weight { value unit }
            } }
          } }
        }
      }
    }
  }
}
"""


def log(msg):
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


def http_json(url, data=None, headers=None, form=False, retries=5):
    headers = dict(headers or {})
    body = None
    if data is not None:
        if form:
            body = urllib.parse.urlencode(data).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
    headers.setdefault("Accept", "application/json")
    for attempt in range(retries):
        req = urllib.request.Request(url, data=body, headers=headers, method="POST" if body else "GET")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                wait = 2 ** attempt * 2
                log(f"HTTP {e.code}, opnieuw over {wait}s")
                time.sleep(wait)
                continue
            raise RuntimeError(f"HTTP {e.code} op {url}: {detail}") from None
        except urllib.error.URLError as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt * 2)
                continue
            raise RuntimeError(f"Netwerkfout op {url}: {e}") from None


class Shopify:
    def __init__(self, shop, version):
        self.shop = shop
        self.version = version
        self.token = self._get_token()

    def _get_token(self):
        token = os.environ.get("SHOPIFY_ACCESS_TOKEN")
        if token:
            return token
        cid = os.environ.get("SHOPIFY_CLIENT_ID")
        secret = os.environ.get("SHOPIFY_CLIENT_SECRET")
        if not (cid and secret):
            sys.exit("Geen Shopify-gegevens: zet SHOPIFY_CLIENT_ID en SHOPIFY_CLIENT_SECRET (of SHOPIFY_ACCESS_TOKEN).")
        resp = http_json(
            f"https://{self.shop}/admin/oauth/access_token",
            {"grant_type": "client_credentials", "client_id": cid, "client_secret": secret},
            form=True,
        )
        if "access_token" not in resp:
            sys.exit(f"Geen access token ontvangen: {resp}")
        log(f"Token opgehaald (scopes: {resp.get('scope')})")
        return resp["access_token"]

    def gql(self, query, variables=None):
        url = f"https://{self.shop}/admin/api/{self.version}/graphql.json"
        for attempt in range(6):
            resp = http_json(url, {"query": query, "variables": variables or {}},
                             headers={"X-Shopify-Access-Token": self.token})
            errors = resp.get("errors")
            if errors:
                throttled = any((e.get("extensions") or {}).get("code") == "THROTTLED" for e in errors)
                if throttled and attempt < 5:
                    time.sleep(2 + attempt * 3)
                    continue
                raise RuntimeError(f"GraphQL-fout: {json.dumps(errors)[:800]}")
            return resp["data"]
        raise RuntimeError("GraphQL bleef throttled")

    # -- verzendregels ------------------------------------------------------ #
    def shipping_profiles(self, country):
        out = {"default": None, "profiles": {}}
        for p in self.gql(PROFILES_QUERY)["deliveryProfiles"]["nodes"]:
            if p["default"]:
                out["default"] = p["id"]
            out["profiles"][p["id"]] = {"name": p["name"], "methods": self._profile_methods(p["id"], country)}
        return out

    def _profile_methods(self, profile_id, country):
        methods = []
        group_idx, after = 0, None
        while True:
            data = self.gql(PROFILE_ZONES_QUERY, {"id": profile_id, "after": after})["deliveryProfile"]
            groups = data["profileLocationGroups"]
            if group_idx >= len(groups):
                break
            conn = groups[group_idx]["locationGroupZones"]
            for z in conn["nodes"]:
                codes = {c["code"]["countryCode"] for c in z["zone"]["countries"] if c.get("code")}
                if country not in codes:
                    continue
                for m in z["methodDefinitions"]["nodes"]:
                    methods.append(m)
            if conn["pageInfo"]["hasNextPage"]:
                after = conn["pageInfo"]["endCursor"]
            else:
                group_idx, after = group_idx + 1, None
        return methods

    # -- producten ---------------------------------------------------------- #
    def bulk_products(self, dest):
        for attempt in range(10):
            res = self.gql(BULK_RUN, {"q": BULK_QUERY})["bulkOperationRunQuery"]
            if not res["userErrors"]:
                op_id = res["bulkOperation"]["id"]
                break
            msg = "; ".join(e["message"] for e in res["userErrors"])
            if "already in progress" in msg.lower() and attempt < 9:
                log("Er loopt al een bulk-export, even wachten")
                time.sleep(30)
                continue
            raise RuntimeError(f"Bulk-export niet gestart: {msg}")
        log(f"Bulk-export gestart: {op_id}")
        deadline = time.time() + 25 * 60
        while time.time() < deadline:
            op = self.gql(BULK_POLL, {"id": op_id})["bulkOperation"]
            if op["status"] == "COMPLETED":
                log(f"Bulk-export klaar: {op['rootObjectCount']} producten, {op['objectCount']} objecten")
                if not op["url"]:
                    dest.write_text("")
                    return dest
                urllib.request.urlretrieve(op["url"], dest)
                return dest
            if op["status"] in ("FAILED", "CANCELED", "EXPIRED"):
                raise RuntimeError(f"Bulk-export {op['status']}: {op.get('errorCode')}")
            time.sleep(5)
        raise RuntimeError("Bulk-export duurde te lang")


# --------------------------------------------------------------------------- #
# Data inlezen
# --------------------------------------------------------------------------- #

def read_jsonl(path):
    products, order = {}, []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            parent = obj.get("__parentId")
            if parent is None:
                obj["_variants"], obj["_images"] = [], []
                products[obj["id"]] = obj
                order.append(obj["id"])
            elif parent in products:
                if "ProductVariant" in (obj.get("id") or ""):
                    products[parent]["_variants"].append(obj)
                elif obj.get("__typename") == "MediaImage":
                    products[parent]["_images"].append(obj)
    return [products[i] for i in order]


# --------------------------------------------------------------------------- #
# Omzetten
# --------------------------------------------------------------------------- #

WEIGHT_TO_KG = {"KILOGRAMS": 1.0, "GRAMS": 0.001, "POUNDS": 0.45359237, "OUNCES": 0.028349523125}
INVALID_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
PROMO = re.compile(
    r"gratis|korting|bestel (?:de |het |deze |dit )?\S*\s*(?:vandaag|nu)|bestel vandaag|bestel nu|"
    r"uit voorraad leverbaar|levertijd|snelle levering|binnen \d+ (?:werk)?dagen|living lovely",
    re.I,
)
LEAD_RANGE = re.compile(r"levertijd\s*:?\s*(\d{1,2})\s*(?:-|–|a|à|tot)\s*(\d{1,2})\s*(?:werk)?dag", re.I)
LEAD_SINGLE = re.compile(r"levertijd\s*:?\s*(\d{1,2})\s*(?:werk)?dag", re.I)


def clean_text(s):
    return INVALID_XML.sub("", s or "").strip()


def html_to_lines(fragment):
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", fragment or "")
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</(p|h[1-6]|li|ul|ol|div|tr)>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s).replace("\xa0", " ")
    lines = [re.sub(r"\s+([:;,.!?])", r"\1", re.sub(r"[ \t]+", " ", ln)).strip() for ln in s.split("\n")]
    return [ln for ln in lines if ln]


def spec_items(desc_html):
    """'Label: waarde' uit de <li>-regels van de specificatielijst."""
    specs = {}
    for li in re.findall(r"(?is)<li[^>]*>(.*?)</li>", desc_html or ""):
        text = " ".join(html_to_lines(li))
        m = re.match(r"^\s*([A-Za-zÀ-ÿ ]{2,25}?)\s*:\s*(.+)$", text)
        if m:
            specs.setdefault(m.group(1).strip().lower(), m.group(2).strip().rstrip("."))
    return specs


def lead_time_from_description(desc_html):
    text = " ".join(html_to_lines(desc_html))
    m = LEAD_RANGE.search(text)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if 0 < a <= b <= 60:
            return f"{a}-{b}" if a != b else str(a)
    m = LEAD_SINGLE.search(text)
    if m and 0 < int(m.group(1)) <= 60:
        return m.group(1)
    return None


def build_description(desc_html, limit):
    s = desc_html or ""
    s = re.sub(r"(?is)^\s*<h2[^>]*>.*?</h2>", "", s, count=1)          # titelkop
    s = re.split(r"(?is)<h[1-6][^>]*>[^<]*waarom bestellen bij", s)[0]  # promotieblok
    s = re.sub(r"(?is)<li[^>]*>(?:(?!</li>).)*?(?:leverbaar|levertijd|gratis)(?:(?!</li>).)*</li>", "", s)
    out = []
    for line in html_to_lines(s):
        sentences = re.split(r"(?<=[.!?])\s+", line)
        kept = [x for x in sentences if not PROMO.search(x)]
        if kept:
            out.append(" ".join(kept))
    text = "\n".join(out)
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return clean_text(text)


def clean_name(title, brand_names):
    name = re.sub(r"[™®©]", "", title or "")
    for b in sorted({b for b in brand_names if b}, key=len, reverse=True):
        name = re.sub(r"(?<![\w])" + re.escape(b) + r"(?![\w])", " ", name, flags=re.I)
    name = re.sub(r"\s+", " ", name)
    name = re.sub(r"\s*([-–|/])\s*(?:[-–|/]\s*)+", r" \1 ", name)
    name = re.sub(r"(?i)\s+(van|by|door|from)\s*$", "", name.strip())
    name = re.sub(r"(?i)^\s*(van|by)\s+", "", name)
    name = name.strip(" -–|,:/")
    name = re.sub(r"\s+", " ", name)
    return name[:1].upper() + name[1:] if name else name


def valid_gtin(code):
    code = re.sub(r"\s", "", code or "")
    if not code.isdigit():
        return None
    if len(code) == 12:
        code = "0" + code
    if len(code) not in (13, 14):
        return None
    digits = [int(c) for c in code]
    check = digits.pop()
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(digits)))
    return code if (10 - total % 10) % 10 == check else None


def parse_dimensions(value):
    out = {}
    if not value:
        return out
    v = value.replace(",", ".")
    for key, letter in (("length", "L"), ("width", "B"), ("height", "H")):
        m = re.search(r"(?<![A-Za-z])" + letter + r"\s*([\d.]+)\s*cm", v)
        if m:
            out[key] = f"{m.group(1).rstrip('.')} cm"
    m = re.search(r"(?:Ø|ø|\bD)\s*([\d.]+)\s*cm", v)
    if m:
        out["diameter"] = f"{m.group(1).rstrip('.')} cm"
    return out


def top_materials(composition):
    """'Mdf(1%),mango wood(95%),metal(4%)' -> 'mango wood, metal'"""
    parts = re.findall(r"([^,(]+)\((\d+)%\)", composition or "")
    if not parts:
        return clean_text(composition)[:80] if composition else None
    parts.sort(key=lambda p: -int(p[1]))
    return ", ".join(p[0].strip() for p in parts[:2])


def fmt_price(x):
    return f"{float(x):.2f}"


def fmt_num(x):
    return f"{x:.2f}".rstrip("0").rstrip(".")


class ShippingRules:
    def __init__(self, data):
        self.default = data.get("default")
        self.profiles = data.get("profiles", {})

    def price(self, profile_id, item_price, weight_kg):
        prof = self.profiles.get(profile_id or self.default) or self.profiles.get(self.default)
        if not prof:
            return None
        best = None
        for m in prof["methods"]:
            if not m.get("active"):
                continue
            rp = m.get("rateProvider") or {}
            if rp.get("__typename") != "DeliveryRateDefinition":
                continue
            if self._matches(m.get("methodConditions") or [], item_price, weight_kg):
                p = float(rp["price"]["amount"])
                best = p if best is None else min(best, p)
        return best

    @staticmethod
    def _matches(conditions, item_price, weight_kg):
        for c in conditions:
            crit = c.get("conditionCriteria") or {}
            if c["field"] == "TOTAL_PRICE":
                actual, limit = item_price, float(crit.get("amount", 0))
            elif c["field"] == "TOTAL_WEIGHT":
                actual = weight_kg
                limit = float(crit.get("value", 0)) * WEIGHT_TO_KG.get(crit.get("unit"), 1.0)
            else:
                return False
            op = c["operator"]
            ok = {
                "GREATER_THAN_OR_EQUAL_TO": actual >= limit - 1e-9,
                "LESS_THAN_OR_EQUAL_TO": actual <= limit + 1e-9,
                "GREATER_THAN": actual > limit,
                "LESS_THAN": actual < limit,
            }.get(op)
            if not ok:
                return False
        return True


def load_category_names(url):
    """Nederlandse categorienamen uit de publieke Shopify-taxonomie (gid -> pad)."""
    names = {}
    if not url:
        return names
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            for line in r.read().decode("utf-8").splitlines():
                if line.startswith("gid://") and " : " in line:
                    gid, path = line.split(" : ", 1)
                    names[gid.strip()] = path.strip()
    except Exception as e:
        log(f"Categorienamen niet opgehaald ({e}); Shopify-namen gebruikt")
    return names


def mf(product, alias):
    v = product.get(alias)
    return v.get("value") if isinstance(v, dict) else None


def build_offers(products, shipping, cfg, category_names=None):
    today = datetime.now(NL_TZ).date().isoformat()
    lead_table = {k.lower(): v for k, v in cfg["vendor_lead_times"].items()}
    display = {k.lower(): v for k, v in cfg.get("brand_display", {}).items()}
    aliases = {k.lower(): v for k, v in cfg.get("brand_aliases", {}).items()}
    excl_vendors = {v.lower() for v in cfg.get("exclude_vendors", [])}
    incl_vendors = {v.lower() for v in cfg.get("include_vendors", [])}
    excl_types = {t.lower() for t in cfg.get("exclude_product_types", [])}
    excl_handles = set(cfg.get("exclude_handles", []))
    suffix = cfg.get("delivery_time_suffix", "werkdagen")
    forced = {v.lower() for v in cfg.get("force_vendor_lead_time", [])}

    offers, excluded = [], []
    names_seen = Counter()

    def skip(p, reason, variant=None):
        excluded.append({
            "reden": reason,
            "merk": p.get("vendor") or "",
            "product": p.get("title") or "",
            "variant": (variant or {}).get("title", "") if variant else "",
            "url": p.get("onlineStoreUrl") or f"{cfg['store_url']}/products/{p.get('handle')}",
        })

    for p in products:
        vendor = (p.get("vendor") or "").strip()
        brand = display.get(vendor.lower(), vendor)
        if p.get("status") != "ACTIVE":
            continue
        if p.get("isGiftCard"):
            skip(p, "cadeaubon"); continue
        if incl_vendors and vendor.lower() not in incl_vendors and brand.lower() not in incl_vendors:
            skip(p, "merk niet in feedlijst"); continue
        if vendor.lower() in excl_vendors or (p.get("productType") or "").lower() in excl_types \
                or p.get("handle") in excl_handles:
            skip(p, "uitgesloten in config"); continue
        if not p.get("onlineStoreUrl"):
            skip(p, "niet gepubliceerd in de webshop"); continue
        if not brand:
            skip(p, "geen merk (vendor)"); continue
        if (mf(p, "preOrder") or "").lower() == "true" or (mf(p, "preOrderDate") or "") >= today:
            skip(p, "pre-order"); continue

        images = []
        for m in p.get("_images", []):
            img = m.get("image") or {}
            if img.get("url") and min(img.get("width") or 0, img.get("height") or 0) >= cfg["min_image_size"]:
                images.append(img["url"])
        images = images[: cfg["max_images"]]
        if not images:
            skip(p, "geen bruikbare foto (min. 500x500)"); continue

        desc_html = p.get("descriptionHtml") or ""
        table_lead = lead_table.get(vendor.lower()) or lead_table.get(brand.lower())
        if vendor.lower() in forced or brand.lower() in forced:
            lead = table_lead
        else:
            lead = lead_time_from_description(desc_html) or table_lead
        if not lead:
            skip(p, "geen levertijd bekend"); continue

        cat = p.get("category") or {}
        category_path = ((category_names or {}).get(cat.get("id")) or cat.get("fullName") or "").strip()
        category = ", ".join(x.strip() for x in category_path.split(">") if x.strip()) or (p.get("productType") or "").strip()
        if not category:
            skip(p, "geen categorie of producttype"); continue

        brand_names = [vendor, brand] + aliases.get(vendor.lower(), [])
        base_name = clean_name(p.get("title"), brand_names)
        description = build_description(desc_html, cfg["max_description_length"])
        specs = spec_items(desc_html)

        features = {}
        colour = specs.get("kleur") or mf(p, "dropColour")
        if colour:
            features["color"] = clean_text(colour)[:80]
        material = specs.get("materiaal") or specs.get("materialen") or mf(p, "materiaal") or top_materials(mf(p, "dropMaterial"))
        if material:
            features["material"] = clean_text(material)[:120]
        variants = p.get("_variants", [])
        multi = len(variants) > 1
        if not multi:  # bij varianten kloppen de productafmetingen niet per variant
            features.update(parse_dimensions(specs.get("afmetingen")))
        for v in variants:
            available = bool(v.get("availableForSale"))
            if not available and not cfg.get("include_out_of_stock"):
                skip(p, "niet op voorraad", v); continue
            tracked = ((v.get("inventoryItem") or {}).get("tracked"))
            if available and tracked and (v.get("inventoryQuantity") or 0) <= 0 \
                    and not cfg.get("include_backorders"):
                skip(p, "geen voorraad (doorverkopen staat aan)", v); continue
            try:
                price = float(v.get("price") or 0)
            except ValueError:
                price = 0
            if price <= 0:
                skip(p, "geen prijs", v); continue
            w = ((v.get("inventoryItem") or {}).get("measurement") or {}).get("weight") or {}
            weight_kg = float(w.get("value") or 0) * WEIGHT_TO_KG.get(w.get("unit"), 1.0)
            ship = shipping.price((v.get("deliveryProfile") or {}).get("id"), price, weight_kg)
            if ship is None:
                skip(p, "geen verzendtarief naar NL", v); continue

            vtitle = (v.get("title") or "").strip()
            name = base_name if (not multi or vtitle.lower() == "default title") else f"{base_name} {vtitle}"
            names_seen[name.lower()] += 1

            identifiers = []
            ean = valid_gtin(v.get("barcode")) or (valid_gtin(mf(p, "dropEan")) if not multi else None)
            if ean:
                identifiers.append(("EAN", ean))
            sku = (v.get("sku") or "").strip()
            if sku:
                identifiers.append(("SKU", sku))
            if not identifiers:
                skip(p, "geen EAN en geen SKU", v); continue

            vfeatures = dict(features)
            if weight_kg > 0:
                vfeatures["weight"] = f"{fmt_num(weight_kg)} kg"

            link = p["onlineStoreUrl"]
            params = []
            if multi:
                params.append(f"variant={v['legacyResourceId']}")
            if cfg.get("deeplink_utm"):
                params.append(cfg["deeplink_utm"])
            if params:
                link += ("&" if "?" in link else "?") + "&".join(params)

            original = None
            if v.get("compareAtPrice"):
                try:
                    if float(v["compareAtPrice"]) > price:
                        original = fmt_price(v["compareAtPrice"])
                except ValueError:
                    pass

            offers.append({
                "shopOfferId": str(v["legacyResourceId"]),
                "shopCategory": category,
                "name": clean_text(name),
                "description": description,
                "brand": brand,
                "identifiers": identifiers,
                "features": vfeatures,
                "variantGroup": p.get("handle") if multi else None,
                "basePrice": fmt_price(price),
                "originalPrice": original,
                "deepLink": link,
                "images": images,
                "inStock": "TRUE" if available else "FALSE",
                "deliveryTime": f"{lead} {suffix}".strip(),
                "deliveryPrice": fmt_price(ship),
            })

    dupes = sorted(n for n, c in names_seen.items() if c > 1)
    return offers, excluded, dupes


# --------------------------------------------------------------------------- #
# Schrijven
# --------------------------------------------------------------------------- #

def x(tag, value, indent):
    return f"{indent}<{tag}>{escape(clean_text(str(value)))}</{tag}>\n"


def write_xml(offers, path, cfg):
    with open(path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<feed>\n  <offers>\n')
        for o in offers:
            i3, i4, i5, i6, i7 = " " * 6, " " * 8, " " * 10, " " * 12, " " * 14
            f.write("    <offer>\n")
            f.write(x("shopReference", cfg.get("shop_reference", "livinglovely.nl"), i3))
            f.write(x("shopOfferId", o["shopOfferId"], i3))
            f.write(x("shopCategory", o["shopCategory"], i3))
            f.write(f"{i3}<products>\n{i4}<product>\n")
            f.write(x("name", o["name"], i5))
            if o["description"]:
                f.write(x("description", o["description"], i5))
            f.write(x("brand", o["brand"], i5))
            f.write(f"{i5}<identifiers>\n")
            for t, val in o["identifiers"]:
                f.write(f"{i6}<identifier>\n{x('type', t, i7)}{x('value', val, i7)}{i6}</identifier>\n")
            f.write(f"{i5}</identifiers>\n")
            if o["features"]:
                f.write(f"{i5}<features>\n")
                for k, val in o["features"].items():
                    f.write(f"{i6}<feature>\n{x('name', k, i7)}{x('value', val, i7)}{i6}</feature>\n")
                f.write(f"{i5}</features>\n")
            f.write(x("state", "NEW", i5))
            if o["variantGroup"]:
                f.write(x("variantGroup", o["variantGroup"], i5))
            f.write(f"{i4}</product>\n{i3}</products>\n")
            f.write(x("basePrice", o["basePrice"], i3))
            if o["originalPrice"]:
                f.write(x("originalPrice", o["originalPrice"], i3))
            f.write(x("deepLink", o["deepLink"], i3))
            f.write(f"{i3}<media>\n")
            for url in o["images"]:
                f.write(f"{i4}<medium>\n{x('type', 'IMAGE', i5)}{x('url', url, i5)}{i4}</medium>\n")
            f.write(f"{i3}</media>\n")
            f.write(x("inStock", o["inStock"], i3))
            f.write(f"{i3}<shippingOptions>\n{i4}<shippingOption>\n")
            f.write(x("countryCode", cfg["country"], i5))
            f.write(x("deliveryTime", o["deliveryTime"], i5))
            if cfg.get("shipping_description"):
                f.write(x("description", cfg["shipping_description"], i5))
            f.write(x("method", "DELIVERY", i5))
            f.write(x("price", o["deliveryPrice"], i5))
            f.write(f"{i4}</shippingOption>\n{i3}</shippingOptions>\n")
            f.write("    </offer>\n")
        f.write("  </offers>\n</feed>\n")


def write_reports(out, offers, excluded, products, dupes, started):
    reasons = Counter(e["reden"] for e in excluded)
    by_brand = Counter(o["brand"] for o in offers)
    status = {
        "gegenereerd": datetime.now(NL_TZ).strftime("%Y-%m-%d %H:%M"),
        "duur_seconden": round(time.time() - started),
        "actieve_producten": len(products),
        "offers_in_feed": len(offers),
        "uitgesloten": dict(reasons.most_common()),
        "offers_per_merk": dict(by_brand.most_common()),
        "dubbele_productnamen": len(dupes),
        "dubbele_productnamen_lijst": dupes[:100],
    }
    (out / "status.json").write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")
    with open(out / "excluded.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["reden", "merk", "product", "variant", "url"], delimiter=";")
        w.writeheader()
        w.writerows(sorted(excluded, key=lambda e: (e["reden"], e["merk"], e["product"])))
    rows = "".join(f"<tr><td>{escape(k)}</td><td>{v}</td></tr>" for k, v in reasons.most_common())
    (out / "index.html").write_text(f"""<!doctype html><meta charset="utf-8">
<meta name="robots" content="noindex"><title>Living Lovely feed</title>
<style>body{{font:15px/1.5 Arial,sans-serif;color:#1C1A18;max-width:640px;margin:40px auto;padding:0 16px}}
h1{{font-family:Georgia,serif;font-weight:600}}td{{padding:2px 12px 2px 0}}a{{color:#96836F}}</style>
<h1>vergelijk.nl feed</h1>
<p>Laatst gegenereerd: {status['gegenereerd']}<br>Offers in feed: <b>{len(offers)}</b> van {len(products)} actieve producten</p>
<p><a href="vergelijk.xml">vergelijk.xml</a> · <a href="status.json">status.json</a> · <a href="excluded.csv">excluded.csv</a></p>
<h3>Niet in de feed</h3><table>{rows}</table>
""", encoding="utf-8")
    return status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="public")
    ap.add_argument("--config", default=str(HERE / "config.json"))
    ap.add_argument("--from-jsonl", help="offline: bestaande bulk-export gebruiken")
    ap.add_argument("--shipping-json", help="offline: verzendregels uit bestand")
    args = ap.parse_args()

    started = time.time()
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if args.from_jsonl:
        jsonl = Path(args.from_jsonl)
        ship_data = json.loads(Path(args.shipping_json).read_text(encoding="utf-8"))
    else:
        api = Shopify(cfg["shop_domain"], cfg["api_version"])
        ship_data = api.shipping_profiles(cfg["country"])
        log(f"Verzendprofielen: {', '.join(p['name'] for p in ship_data['profiles'].values())}")
        jsonl = api.bulk_products(out.parent / "products.jsonl" if out.parent != out else Path("products.jsonl"))

    products = read_jsonl(jsonl)
    log(f"{len(products)} actieve producten ingelezen")
    category_names = load_category_names(cfg.get("category_names_url"))
    if category_names:
        log(f"{len(category_names)} Nederlandse categorienamen geladen")
    offers, excluded, dupes = build_offers(products, ShippingRules(ship_data), cfg, category_names)
    write_xml(offers, out / "vergelijk.xml", cfg)
    status = write_reports(out, offers, excluded, products, dupes, started)
    log(f"Feed: {len(offers)} offers. Uitgesloten: {status['uitgesloten']}")

    if len(offers) < cfg.get("min_offers", 0):
        sys.exit(f"STOP: maar {len(offers)} offers (minimum {cfg['min_offers']}). Feed wordt niet gepubliceerd.")


if __name__ == "__main__":
    main()
