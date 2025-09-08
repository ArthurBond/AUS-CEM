# apply timeslice mask to capacity and cost
import pandas as pd 

def _get_timeslices(tpath="./Traces/timeslice_RefYear4006.csv",
                    start=(2024,7,1),
                    end  =(2055,6,30)):
    "return type of day for all days in the traces provided"

    # get timeslice df
    df = pd.read_csv(tpath)
    timeslice = {}
    regions = ("NSW","QLD","VIC","TAS","SA")

    day_type_map = {
        "Hot Day" : "SP",
        "Typical Summer" : "ST",
        "Winter" : "W"
    }

    # group timeslices by regions
    for region in regions:
        timeslice[region] = df[df.NAME.str.startswith(region)].copy()

    # create timeslice mask
    for region in regions:

        df = timeslice[region]

        df = df[df["TIMESLICE"]==-1].loc[:]

        # Ensure proper datetime
        df["DATETIME"] = pd.to_datetime(df["DATETIME"], dayfirst=True)

        # Sort by date
        df = df.sort_values("DATETIME").reset_index(drop=True)

        # Add "NEXT" column = next start date
        df["NEXT"] = df["DATETIME"].shift(-1)

        # Type of day compatible with data (ST, SP, or W)
        df["DAY_TYPE"] = df["NAME"].str.split(" ").str[1:].str.join(" ")
        df["DAY_TYPE_SHORT"] = df["DAY_TYPE"].map(day_type_map)

        # Expand each range into daily rows
        blocks = []
        for _, row in df.iterrows():
            start = row["DATETIME"]
            next_date = row["NEXT"]

            # If no next date, just keep the start
            end = start if pd.isna(next_date) else next_date - pd.Timedelta(days=1)

            # Generate daily range
            rng = pd.date_range(start, end, freq="D")
            block = pd.DataFrame({"DATETIME": rng, "DAY_TYPE": row["DAY_TYPE"], "DAY_TYPE_SHORT": row["DAY_TYPE_SHORT"]})
            blocks.append(block)

        out = pd.concat(blocks, ignore_index=True)

        timeslice[region] = out.set_index("DATETIME").sort_index().copy()
    
    return regions,timeslice

def _region_timeslice(region,timeslice):
    "From timeslice for a region get day_type and day_type_short"

    # NAME and DAY_TYPE
    return timeslice[region].copy()

regions,tdf = _get_timeslices()

nsw_ts = _region_timeslice('NSW',tdf)

print(nsw_ts)

# combine days to seasonal ratings and outages

cap = pd.read_csv("./isp_sheets_23/seasonal_ratings/existing_gen_seasonal_ratings.csv")

print(cap)


# snapshots

years = list(range(2024,2056))
freq = "3"
snapshots = pd.DatetimeIndex([])
period = pd.date_range(
    start="2024-07-01 00:00",
    end="2055-06-30 00:00",
    freq=f"{freq}h"
    # periods=8760 / float(freq),
)

snapshots = snapshots.append(period)

import pandas as pd

nsw_map = nsw_ts.DAY_TYPE_SHORT.to_dict()

snapshots_day = snapshots.strftime("%Y-%m-%d")

snapshots_day_dt = pd.to_datetime(snapshots_day)
day_types = snapshots_day_dt.map(lambda d: nsw_map.get(d, None))
years = snapshots_day_dt.year
fin_years = years.where(snapshots_day_dt.month < 7, years + 1)

cap_cols = []

for (dt, fy), y in zip(zip(day_types, fin_years),years):
    if dt == 'W':
        if y <= 2032:
            cap_cols.append(f"{dt}{y}")
        else:
            cap_cols.append(f"{dt}2032")
    else:
        if fy <= 2033:
            cap_cols.append(f"{dt}{fy-1}-{str(fy)[-2:]}")
        else:
            cap_cols.append(f"{dt}2032-33")

# Find the last available column in cap (e.g., 'W2032-33')
last_col = sorted([col for col in cap.columns if col[-5:] == '32-33'])[-1] if any(col[-5:] == '32-33' for col in cap.columns) else cap.columns[-1]

# Select the row for the desired DUID
cap_row = cap[cap["DUID"] == "KPP_1"].iloc[0]

# Build the capacity list, using last_col if the column is missing
capacity_list = [
    cap_row.get(col, cap_row[last_col]) if col in cap_row.index else cap_row[last_col]
    for col in cap_cols
]

# Build a capacity list for each region
