import polars as pl
import requests
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

API_TOKEN = os.getenv("API_TOKEN")
API_BASE_ENDPOINT = os.getenv("API_BASE_ENDPOINT", "https://api.example.com/keyword-ranking/{country_code}/keyword-metadata")


def check_brand(keyword, country_code):
    url = API_BASE_ENDPOINT.format(country_code=country_code)
    params = {"keyword": keyword, "token": API_TOKEN}
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        return data.get("brandApp") is not None
    except Exception:
        return None


def main():
    print("1. Loading universal keywords...")
    df = pl.read_csv("universal_keywords_output.csv")
    print(f"   {len(df)} universal keywords found")

    PRIORITY_COUNTRIES = ["US", "GB", "TR", "KR", "JP"]

    term_to_countries = {}
    for row in df.iter_rows(named=True):
        codes = [c.strip() for c in row["country_codes"].split(",") if c.strip()]
        all_codes = PRIORITY_COUNTRIES + [c for c in codes if c not in PRIORITY_COUNTRIES]
        term_to_countries[row["Search Term"]] = all_codes[:5]

    print(f"2. Checking brand status for {len(term_to_countries)} keywords...")
    results = {}
    total = len(term_to_countries)
    done = 0
    failed = 0

    def check_brand_multi(term, country_codes):
        for code in country_codes:
            result = check_brand(term, code)
            if result is True:
                return True
            time.sleep(0.05)
        return False

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(check_brand_multi, term, codes): term
            for term, codes in term_to_countries.items()
        }
        for future in as_completed(futures):
            term = futures[future]
            done += 1
            is_brand = future.result()
            if is_brand is None:
                failed += 1
                results[term] = False
            else:
                results[term] = is_brand
            if done % 500 == 0:
                print(f"   Progress: {done}/{total} (failed: {failed})")

    print(f"   Completed: {done}/{total} (failed: {failed})")

    brand_data = [
        {"Search Term": term, "Is_Brand": is_brand}
        for term, is_brand in results.items()
    ]
    brand_df = pl.DataFrame(brand_data)

    df_with_brand = df.join(brand_df, on="Search Term", how="left")
    df_with_brand = df_with_brand.with_columns(
        pl.col("Is_Brand").fill_null(False)
    )

    brand_count = df_with_brand.filter(pl.col("Is_Brand") == True).height
    non_brand_count = df_with_brand.filter(pl.col("Is_Brand") == False).height
    print(f"\n3. Results:")
    print(f"   Brand: {brand_count}")
    print(f"   Non-brand (true universal): {non_brand_count}")

    df_with_brand.write_csv("universal_keywords_with_brand.csv")
    df_with_brand.filter(pl.col("Is_Brand") == False).write_csv("universal_keywords_final.csv")
    print("   Saved: universal_keywords_with_brand.csv and universal_keywords_final.csv")


if __name__ == "__main__":
    main()
