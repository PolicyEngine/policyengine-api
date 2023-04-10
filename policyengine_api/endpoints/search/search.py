import pandas as pd
from pathlib import Path

folder = Path(__file__).parent

df = pd.read_csv(folder / "metadata.csv.gz", compression="gzip")

print(df.columns)