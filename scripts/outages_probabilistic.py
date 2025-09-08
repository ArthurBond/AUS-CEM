# create probabilistic outages using scheduled maintenance figures

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# --- basic parameters ---
n_units = 200
units = [f"Coal{n+1}" for n in range(n_units)]
# year = 2025
outage_fraction = 0.0548               # 5% of the year per unit
max_out_fraction = 0.10              # no more than 10% out at once
hours_per_year = 8760 // 3           # 3h intervals

# --- build hourly index ---
index = pd.date_range(f"2024-07-01 00:00", f"2032-06-30 23:30", freq="3h")

# --- initialize availability dataframe ---
df = pd.DataFrame(1, index=index, columns=units)  # 1 = online

# --- schedule outages with constraint ---
outage_hours = int(len(index) * outage_fraction)
max_out = int(n_units * max_out_fraction)

for unit in units:
    placed = False
    rng = np.random.default_rng(hash(unit) % (2**32))
    attempts = 0
    while not placed and attempts < 1000:
        start_hour = rng.integers(0, len(index) - outage_hours)
        mask = np.ones(len(index), dtype=int)
        mask[start_hour:start_hour + outage_hours] = 0

        # Simulate the effect of this outage
        temp_total_online = df.sum(axis=1) + (mask - 1)
        if np.all(temp_total_online >= n_units - max_out):
            df[unit] = mask
            placed = True
        attempts += 1
    if not placed:
        print(f"Warning: Could not place outage for {unit} without exceeding max_out constraint.")

# use mask on hydro for outages that aren't 5.48% 

# --- write to CSV for PyPSA ---
df.to_csv("./isp_sheets_23/outages/5_48pc_outages.csv",index=False)
print("Availability CSV written with 1 = online, 0 = offline")

# --- plot a sample of units ---
plt.figure(figsize=(15, 6))
for unit in units[:10]:  # plot first 10 units for clarity
    plt.plot(df.index, df[unit], label=unit, drawstyle="steps-post")
plt.ylabel("Availability (1=online, 0=offline)")
plt.xlabel("Time")
plt.title("Coal Unit Availability (Probabilistic Outages, Sample Units)")
plt.legend()
plt.tight_layout()
plt.show()

# plt.savefig("../random_outages_2025_sample.png",dpi=200)


# --- plot total online units over time ---
plt.figure(figsize=(15, 6))
plt.plot(df.index, df.sum(axis=1), label="Online units", color="black")
plt.axhline(n_units - max_out, color="red", linestyle="--", label=r"Min online (max 10% out)")
plt.ylabel("Number of online units")
plt.xlabel("Time")
plt.title("Total Online Coal Units Over Time")
plt.legend()
plt.tight_layout()
plt.show()

# plt.savefig("../random_outages_2025.png",dpi=200)