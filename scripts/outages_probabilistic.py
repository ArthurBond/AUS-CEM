# # create probabilistic outages using scheduled maintenance figures

# import numpy as np
# import pandas as pd
# import matplotlib.pyplot as plt

# # --- basic parameters ---
# n_units = 44
# units = [f"Coal{n+1}" for n in range(n_units)]
# # year = 2025
# outage_fraction = 0.0548               # 5% of the year per unit
# max_out_fraction = 0.20              # no more than 10% out at once
# hours_per_year = 8760 * 2           # 30min intervals

# # --- build hourly index ---
# index = pd.date_range(f"2024-07-01 00:00", f"2053-06-30 23:30", freq="30min")

# # --- initialize availability dataframe ---
# df = pd.DataFrame(1, index=index, columns=units)  # 1 = online

# # --- schedule outages with constraint ---
# outage_hours = int(len(index) * outage_fraction)
# max_out = int(n_units * max_out_fraction)

# for unit in units:
#     placed = False
#     rng = np.random.default_rng(hash(unit) % (2**32))
#     attempts = 0
#     while not placed and attempts < 1000:
#         start_hour = rng.integers(0, len(index) - outage_hours)
#         mask = np.ones(len(index), dtype=int)
#         mask[start_hour:start_hour + outage_hours] = 0

#         # Simulate the effect of this outage
#         temp_total_online = df.sum(axis=1) + (mask - 1)
#         if np.all(temp_total_online >= n_units - max_out):
#             df[unit] = mask
#             placed = True
#         attempts += 1
#     if not placed:
#         print(f"Warning: Could not place outage for {unit} without exceeding max_out constraint.")

# # use mask on hydro for outages that aren't 5.48% 

# # --- write to CSV for PyPSA ---
# df.to_csv("./isp_sheets_23/outages/5_48pc_outages.csv",index=False)
# print("Availability CSV written with 1 = online, 0 = offline")

# # --- plot a sample of units ---
# plt.figure(figsize=(15, 6))
# for unit in units[:10]:  # plot first 10 units for clarity
#     plt.plot(df.index, df[unit], label=unit, drawstyle="steps-post")
# plt.ylabel("Availability (1=online, 0=offline)")
# plt.xlabel("Time")
# plt.title("Coal Unit Availability (Probabilistic Outages, Sample Units)")
# plt.legend()
# plt.tight_layout()
# plt.show()

# # plt.savefig("../random_outages_2025_sample.png",dpi=200)


# # --- plot total online units over time ---
# plt.figure(figsize=(15, 6))
# plt.plot(df.index, df.sum(axis=1), label="Online units", color="black")
# plt.axhline(n_units - max_out, color="red", linestyle="--", label=r"Min online (max 10% out)")
# plt.ylabel("Number of online units")
# plt.xlabel("Time")
# plt.title("Total Online Coal Units Over Time")
# plt.legend()
# plt.tight_layout()
# plt.show()

# # plt.savefig("../random_outages_2025.png",dpi=200)

# create probabilistic outages using scheduled maintenance figures

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# --- basic parameters ---
n_units = 50
units = [f"Coal{n+1}" for n in range(n_units)]
outage_fraction = 0.0548               # 5.48% of the year per unit
max_out_fraction = 0.20                # no more than 20% out at once
hours_per_year = 8760 * 2              # 30min intervals

# --- build half-hourly index ---
index = pd.date_range("2024-07-01 00:00", "2053-06-30 23:30", freq="30min")
years = pd.Series(index.year.unique())

# --- initialize availability dataframe ---
df = pd.DataFrame(1, index=index, columns=units)  # 1 = online

# --- schedule outages with constraint: one outage per unit per year ---
max_out = int(n_units * max_out_fraction)
for unit in units:
    rng = np.random.default_rng(hash(unit) % (2**32))
    for year in years:
        # Get all indices for this year
        year_mask = (index.year == year)
        year_indices = np.where(year_mask)[0]
        n_year_steps = len(year_indices)
        outage_steps = int(n_year_steps * outage_fraction)
        placed = False
        attempts = 0
        while not placed and attempts < 1000:
            start_idx = rng.integers(year_indices[0], year_indices[-1] - outage_steps + 1)
            mask = np.ones(n_year_steps, dtype=int)
            mask[start_idx - year_indices[0]:start_idx - year_indices[0] + outage_steps] = 0

            # Simulate the effect of this outage
            temp_total_online = df.iloc[year_indices].sum(axis=1) + (mask - 1)
            if np.all(temp_total_online >= n_units - max_out):
                df.iloc[year_indices, df.columns.get_loc(unit)] = mask
                placed = True
            attempts += 1
        if not placed:
            print(f"Warning: Could not place outage for {unit} in {year} without exceeding max_out constraint.")

# --- write to CSV for PyPSA ---
df.to_csv("./isp_sheets_23/outages/5_48pc_outages.csv", index=False)
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

# --- plot total online units over time ---
plt.figure(figsize=(15, 6))
plt.plot(df.index, df.sum(axis=1), label="Online units", color="black")
plt.axhline(n_units - max_out, color="red", linestyle="--", label=r"Min online (max 20% out)")
plt.ylabel("Number of online units")
plt.xlabel("Time")
plt.title("Total Online Coal Units Over Time")
plt.legend()
plt.tight_layout()
plt.show()