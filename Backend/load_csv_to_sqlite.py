from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine

CSV_DIR = Path("data/synthea")
DB_PATH = "synthea.db"

engine = create_engine(f"sqlite:///{DB_PATH}")

for csv_file in CSV_DIR.glob("*.csv"):
    table_name = csv_file.stem.lower()

    print(f"Loading {csv_file.name} -> {table_name}")

    df = pd.read_csv(csv_file)

    # Easier for LLM-generated SQL
    df.columns = [col.lower() for col in df.columns]

    df.to_sql(
        table_name,
        engine,
        if_exists="replace",
        index=False
    )

print(f"Database created: {DB_PATH}")