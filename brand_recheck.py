import polars as pl
import pymysql
import os

DB_HOST = os.getenv("DB_HOST", "YOUR_HOST_HERE")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "YOUR_USER_HERE")
DB_PASS = os.getenv("DB_PASS", "YOUR_PASSWORD_HERE")
DB_NAME = os.getenv("DB_NAME", "YOUR_DB_NAME_HERE")


def main():
    print("1. Loading universal_keywords_final.csv...")
    df = pl.read_csv("universal_keywords_final.csv")
    keywords = df.select("Search Term").to_series().to_list()
    print(f"   {len(keywords)} keywords to check")

    print("2. Connecting to DB...")
    conn = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME,
    )
    cursor = conn.cursor()

    batch_size = 500
    brand_keywords = set()

    print("3. Checking brands...")
    for i in range(0, len(keywords), batch_size):
        batch = keywords[i : i + batch_size]
        placeholders = ", ".join(["%s"] * len(batch))
        query = f"""
            SELECT DISTINCT keyword
            FROM keyword
            WHERE keyword IN ({placeholders})
            AND brand_app IS NOT NULL
        """
        cursor.execute(query, batch)
        for row in cursor.fetchall():
            brand_keywords.add(row[0])
        print(f"   {min(i + batch_size, len(keywords))}/{len(keywords)} — brands found: {len(brand_keywords)}")

    cursor.close()
    conn.close()

    print(f"\n4. Results:")
    print(f"   Brand: {len(brand_keywords)}")
    print(f"   Remaining universal: {len(keywords) - len(brand_keywords)}")

    if brand_keywords:
        print(f"\n   Brand examples: {list(brand_keywords)[:20]}")

    df_result = df.with_columns(
        pl.col("Search Term").is_in(list(brand_keywords)).alias("Is_Brand")
    )
    df_result.filter(pl.col("Is_Brand") == False).write_csv("universal_keywords_final.csv")
    df_result.filter(pl.col("Is_Brand") == True).write_csv("brands_caught_recheck.csv")
    print(f"\n   Updated: universal_keywords_final.csv")
    print(f"   New brands: brands_caught_recheck.csv")


if __name__ == "__main__":
    main()
