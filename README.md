# Universal Keyword Finder

A pipeline that identifies **language-independent, truly universal keywords** from Apple Search Ads data. It filters out keywords that are popular only because of a shared language and optionally removes brand-name keywords.

## How It Works

```
data.csv
  -> [analyzer.py]       -> universal_keywords_output.csv
  -> [brand_check.py]    -> universal_keywords_final.csv + universal_keywords_with_brand.csv
  -> [brand_recheck.py]  -> universal_keywords_final.csv (cleaned) + brands_caught_recheck.csv
```

### Phase 1 — Universal Detection (`analyzer.py`)
1. Load Apple Search Ads CSV and filter out keywords with popularity < 20
2. Map countries to ISO alpha-2 codes and their spoken languages
3. Keep only keywords appearing in 5+ countries
4. Fetch each keyword's language from the keyword metadata API
5. Flag as **universal** if no single language explains the keyword's spread across countries

### Phase 2 — Brand Filtering via API (`brand_check.py`)
- Check each universal keyword against the keyword metadata API's `brandApp` field
- Keywords identified as brand names are separated out

### Phase 3 — Brand Filtering via Database (`brand_recheck.py`)
- Query an internal database to catch any remaining brand keywords missed by the API

## Universal Flag Criteria

A keyword is flagged as universal if **all** conditions are met:
- Appears in **5+ countries**
- No single language is spoken in **>50%** of those countries
- The keyword's own language is not spoken in **>50%** of those countries

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install polars pycountry countryinfo requests
```

## Usage

```bash
# Set API credentials
export API_TOKEN="your_token_here"
export API_BASE_ENDPOINT="https://your-api.com/keyword-ranking/{country_code}/keyword-metadata"

# Run the pipeline
python3 -u analyzer.py
python3 -u brand_check.py        # optional
python3 -u brand_recheck.py      # optional, requires DB access
```

## Input Format

CSV file (`data.csv`) with the following columns:
- `Country or Region`
- `Search Term`
- `Search Popularity (1-100)`

## Output

| File | Description |
|------|-------------|
| `universal_keywords_output.csv` | All universal keywords with metrics |
| `universal_keywords_final.csv` | Universal keywords after brand filtering |
| `brands_caught_recheck.csv` | Keywords identified as brands |
