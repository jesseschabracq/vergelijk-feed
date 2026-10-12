# vergelijk.nl feed – Living Lovely

Maakt 4x per dag een productfeed voor vergelijk.nl (Compare Group) uit de Shopify-shop
en zet die op een vaste URL:

```
https://<github-gebruikersnaam>.github.io/vergelijk-feed/vergelijk.xml
```

Op dezelfde plek staan ook:

| Bestand | Wat |
|---|---|
| `index.html` | overzicht van de laatste run |
| `status.json` | aantallen per merk en per reden van uitsluiting |
| `excluded.csv` | alle producten die niet in de feed staan, met reden (opent in Excel) |

## Hoe het werkt

1. `feed.py` haalt via de Shopify API alle actieve producten op (bulk-export) en de verzendtarieven naar NL.
2. Per variant wordt een offer gemaakt volgens het Compare Group-formaat (handleiding v5.8).
3. `validate.py` controleert de feed (verplichte velden en het XSD-schema van Compare Group).
4. Alleen als alles klopt, wordt de feed gepubliceerd. Anders blijft de vorige versie staan en krijg je een mail van GitHub.

### Regels in de feed

- **Productnaam:** Shopify-titel zonder merknaam (eis van Compare Group). Bij varianten komt de varianttitel erachter.
- **Beschrijving:** zonder HTML, zonder titelkop, zonder het blok "Waarom bestellen bij Living Lovely" en zonder promotiezinnen (gratis, korting, levertijd).
- **Levertijd:** eerst de regel "Levertijd X-Y dagen" uit de productbeschrijving, anders de merktabel in `config.json`. Geen van beide = niet in de feed.
- **Verzendkosten:** berekend met de echte verzendprofielen uit Shopify (prijs en gewicht van één stuk), dus gelijk aan wat de klant in de checkout ziet.
- **Categorie:** de Shopify-productcategorie (bijv. `Meubelen, Tafels, Accenttafels, Salontafels`), anders het producttype.
- **EAN:** alleen geldige EAN's (controlecijfer klopt). SKU gaat altijd mee.
- **Link:** productpagina met UTM-tags (`utm_source=vergelijk.nl`), bij varianten met `?variant=`.

### Niet in de feed

Niet gepubliceerd in de webshop, niet op voorraad, voorraad 0 met "doorverkopen" aan,
pre-order (verwachte leverdatum in de toekomst), geen verzendtarief naar NL, geen foto van
minimaal 500x500, geen levertijd bekend, cadeaubonnen en wat in `config.json` is uitgesloten.

## Aanpassen

Alles wat je zelf wilt kunnen wijzigen staat in `config.json`. Wijzig het bestand op GitHub
(potloodje), sla op en de volgende run gebruikt het. Meest gebruikt:

- `vendor_lead_times`: levertijd per merk in werkdagen.
- `exclude_vendors` / `exclude_product_types` / `exclude_handles`: dingen uitsluiten.
- `include_out_of_stock` / `include_backorders`: ook niet-voorradige producten meenemen.
- `min_offers`: minder offers dan dit = feed wordt niet gepubliceerd (vangnet).

## Eenmalige installatie

### 1. Shopify-app (leesrechten)

1. Shopify-admin → Instellingen → Apps → Apps ontwikkelen → open het Dev Dashboard.
2. Maak een app, bijv. **vergelijk-feed**.
3. Maak een versie met deze scopes: `read_products`, `read_inventory`, `read_shipping`. App-URL mag de standaard blijven. Klik **Release**.
4. Klik **Install app** en kies de Living Lovely-winkel.
5. Ga naar **Settings** van de app en kopieer de **Client ID** en het **Client secret**.

### 2. GitHub

1. Maak (als je die nog niet hebt) een account op github.com.
2. Nieuwe repository: naam `vergelijk-feed`, **Public** (gratis hosting via GitHub Pages werkt alleen bij publieke repo's; er staan geen wachtwoorden in de code).
3. **Add file → Upload files**: sleep `feed.py`, `validate.py`, `config.json`, `README.md`, `.gitignore` en de map `tests` erin. Commit.
4. **Add file → Create new file**: typ als naam `.github/workflows/feed.yml`, plak de inhoud van dat bestand. Commit.
5. **Settings → Secrets and variables → Actions → New repository secret**:
   - `SHOPIFY_CLIENT_ID` = Client ID uit stap 1
   - `SHOPIFY_CLIENT_SECRET` = Client secret uit stap 1
6. **Settings → Pages → Source: GitHub Actions**.
7. **Actions → vergelijk.nl feed → Run workflow** voor de eerste run (duurt een paar minuten).

Daarna draait hij vanzelf 4x per dag. Gaat een run mis, dan mailt GitHub je.

## Lokaal testen

```
python tests/make_fixture.py
python feed.py --out /tmp/out --from-jsonl tests/products.jsonl --shipping-json tests/shipping.json
python validate.py /tmp/out/vergelijk.xml
```

De testset heeft maar een handvol producten, dus de laatste regel meldt dat het minimum niet
gehaald is. Dat is bij deze test de bedoeling.
