import polars as pl
import pycountry
import requests
import os
import time
from countryinfo import CountryInfo
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed

API_TOKEN = os.getenv("API_TOKEN")
API_BASE_ENDPOINT = os.getenv("API_BASE_ENDPOINT", "https://api.example.com/keyword-ranking/{country_code}/keyword-metadata")

COUNTRY_NAME_TO_ALPHA2 = {
    "Korea": "KR",
    "Macau": "MO",
}


def build_country_alpha2_map(country_names):
    result = {}
    for name in country_names:
        if name in COUNTRY_NAME_TO_ALPHA2:
            result[name] = COUNTRY_NAME_TO_ALPHA2[name]
            continue
        try:
            match = pycountry.countries.search_fuzzy(name)[0]
            result[name] = match.alpha_2
        except LookupError:
            result[name] = None
    return result


@lru_cache(maxsize=None)
def get_country_languages(country_name):
    alpha2 = COUNTRY_NAME_TO_ALPHA2.get(country_name)
    if not alpha2:
        try:
            alpha2 = pycountry.countries.search_fuzzy(country_name)[0].alpha_2
        except LookupError:
            return [f"lang_{country_name.replace(' ', '')}"]
    try:
        languages = CountryInfo(alpha2).languages()
        if languages:
            return languages
    except (KeyError, Exception):
        pass
    return [f"lang_{alpha2}"]


def fetch_keyword_language(keyword, country_code):
    url = API_BASE_ENDPOINT.format(country_code=country_code)
    params = {"keyword": keyword, "token": API_TOKEN}
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        lang = data.get("languageCode")
        if lang:
            return lang.lower()
    except Exception:
        pass
    return None


def fetch_languages_batch(term_country_pairs, max_workers=8):
    results = {}
    total = len(term_country_pairs)
    done = 0
    failed = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for term, countries in term_country_pairs.items():
            futures[executor.submit(_try_countries, term, countries)] = term

        for future in as_completed(futures):
            term = futures[future]
            done += 1
            lang = future.result()
            results[term] = lang if lang else "unknown_term_lang"
            if not lang:
                failed += 1
            if done % 500 == 0:
                print(f"  API progress: {done}/{total} (failed: {failed})")

    print(f"  API completed: {done}/{total} (failed: {failed})")
    return results


def _try_countries(term, country_codes):
    for code in country_codes:
        if not code:
            continue
        lang = fetch_keyword_language(term, code)
        if lang:
            return lang
        time.sleep(0.05)
    return None


def main():
    file_path = "data.csv"

    print("1. Loading CSV file...")
    try:
        df = pl.read_csv(file_path, ignore_errors=True)
    except Exception as e:
        print(f"Error: Could not read file: {e}")
        return

    search_col = "Search Term"
    country_col = "Country or Region"
    pop_col = "Search Popularity (1-100)"

    print("2. Filtering out Popularity < 20...")
    df = df.filter(pl.col(pop_col) >= 20)

    print("3. Mapping countries to alpha_2 codes...")
    unique_countries = df.select(country_col).drop_nulls().unique().to_series().to_list()
    country_to_alpha2 = build_country_alpha2_map(unique_countries)
    print(f"   {len(country_to_alpha2)} countries mapped")

    print("4. Building country-to-language lookup table...")
    lookup_data = [
        {country_col: c, "Languages": get_country_languages(c)}
        for c in unique_countries
    ]
    lookup_df = pl.DataFrame(lookup_data)

    print("5. Identifying universal candidates (5+ countries)...")
    country_to_alpha2_series = pl.DataFrame({
        country_col: list(country_to_alpha2.keys()),
        "country_code": list(country_to_alpha2.values()),
    })
    df = df.join(country_to_alpha2_series, on=country_col, how="left")

    term_country_counts = df.group_by(search_col).agg(
        total_countries=pl.col(country_col).n_unique(),
        country_list=pl.col("country_code").unique(),
        avg_popularity=pl.col(pop_col).mean(),
        max_popularity=pl.col(pop_col).max(),
    )
    candidates = term_country_counts.filter(pl.col("total_countries") >= 5)
    candidate_terms = set(candidates.select(search_col).to_series().to_list())
    print(f"   {len(candidate_terms)} candidate keywords found")

    print("6. Fetching languageCode from keyword metadata API for candidates...")
    df_candidates = df.filter(pl.col(search_col).is_in(list(candidate_terms)))
    term_countries_for_api = (
        df_candidates.group_by(search_col)
        .agg(pl.col(country_col).unique().alias("countries"))
    )

    term_country_pairs = {}
    for row in term_countries_for_api.iter_rows(named=True):
        term = row[search_col]
        codes = [country_to_alpha2.get(c) for c in row["countries"] if country_to_alpha2.get(c)]
        term_country_pairs[term] = codes[:3]

    term_lang_map = fetch_languages_batch(term_country_pairs, max_workers=8)

    term_lang_data = [
        {search_col: term, "SearchTerm_Language": lang}
        for term, lang in term_lang_map.items()
    ]
    term_lang_df = pl.DataFrame(term_lang_data)

    print("7. Merging language data and aggregating...")
    df_with_langs = (
        df_candidates.join(lookup_df, on=country_col, how="left")
        .explode("Languages")
        .join(term_lang_df, on=search_col, how="left")
        .rename({"Languages": "Language"})
    )

    unique_term_country_lang = df_with_langs.select([search_col, country_col, "Language"]).unique()
    lang_country_hits = unique_term_country_lang.group_by([search_col, "Language"]).agg(
        countries_with_this_lang=pl.col(country_col).n_unique()
    )
    max_lang_coverage = lang_country_hits.group_by(search_col).agg(
        max_shared_lang_countries=pl.col("countries_with_this_lang").max()
    )

    search_term_origin_lang_coverage = (
        df_with_langs.filter(pl.col("Language") == pl.col("SearchTerm_Language"))
        .group_by(search_col)
        .agg(countries_with_term_origin_lang=pl.col(country_col).n_unique())
    )

    agg_df = candidates.join(max_lang_coverage, on=search_col, how="left")
    agg_df = agg_df.join(search_term_origin_lang_coverage, on=search_col, how="left")
    agg_df = agg_df.join(term_lang_df, on=search_col, how="left")

    agg_df = agg_df.with_columns(
        top_shared_lang_pct=(
            pl.col("max_shared_lang_countries") / pl.col("total_countries")
        ).fill_nan(0.0)
    )
    agg_df = agg_df.with_columns(
        search_term_origin_lang_coverage_pct=(
            pl.col("countries_with_term_origin_lang").fill_null(0) / pl.col("total_countries")
        ).fill_nan(0.0)
    )

    print("8. Evaluating Universal Flag criteria...")
    final_df = agg_df.with_columns(
        Universal_Flag=(
            (pl.col("total_countries") >= 5)
            & (pl.col("top_shared_lang_pct") < 0.50)
            & (pl.col("search_term_origin_lang_coverage_pct") < 0.50)
        )
    )

    universal_terms = final_df.filter(pl.col("Universal_Flag") == True)

    print("9. Saving results to CSV...")
    universal_terms_out = universal_terms.rename({"country_list": "country_codes"}).with_columns(
        pl.col("country_codes").list.join(", ")
    )

    universal_terms_out.write_csv("universal_keywords_output.csv")

    print(f"\nDone! Universal keyword count: {len(universal_terms)}")
    print(f"Total candidates: {len(candidates)}, Universal: {len(universal_terms)}")


if __name__ == "__main__":
    main()
