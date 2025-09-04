### calculate upper manually using inflows

# inflows are in terms of GWh

# do sensitivity analysis of starting with different initial states of charge

# e.g. 100% of max hours, 75%, 50% + random mixes

# find water storage levels

def add_simple_hydro_constraints(n,m,names):
    "Constraints for simple hydro scheme (top and bottom)"

    gens = n.generators.index[n.generators.carrier.isin(names)]

    m.add_constraints()

    if initial:
        gen <= initial + inflow
    else
        gen <= inflow + previous_gen

def add_two_chain_hydro_constraints(n,m):
    "Constraints for hydro scheme with 2 top reservoirs linked"


## HYDRO IDEA

# add a storageunit with storage only (efficiency dispatch is 0)
# then add a 


import pypsa
import pandas as pd

n = pypsa.Network()
hours = pd.date_range("2025-01-01", periods=24, freq="h")
n.set_snapshots(hours)

# ----------------------------
# Buses
# ----------------------------
n.add("Bus", "electricity")
n.add("Bus", "water")  # virtual bus for reservoir water

# ----------------------------
# Reservoir (UpperDerwent)
# ----------------------------
n.add(
    "StorageUnit",
    "UpperDerwent",
    bus="water",
    p_nom=0,  # no direct dispatch to grid
    max_hours=10,  # storage_hours
    efficiency_store=1.0,
    efficiency_dispatch=1.0,
    capital_cost=0,
)

# inflow time series (MWh per hour)
n.storage_units_t.inflow["UpperDerwent"] = [50] * len(hours)

# ----------------------------
# Hydro plants (Generators)
# ----------------------------
for plant in ["Tarraleah", "Tungatinah"]:
    n.add(
        "Generator",
        plant,
        bus="electricity",
        p_nom=100,
        efficiency=0.9,  # water->electricity efficiency
        capital_cost=0,
    )

# ----------------------------
# Add custom shared-reservoir constraint
# ----------------------------
m = n.optimize.create_model()

soc = m.variables["StorageUnit-state_of_charge"]
dispatch = m.variables["Generator-p"]

plants = ["Tarraleah", "Tungatinah"]

gen_dispatch = sum(dispatch[:, g] / n.generators.at[g, "efficiency"] for g in plants)
inflow = n.storage_units_t.inflow["UpperDerwent"]

m.add_constraints(
    soc[:, "UpperDerwent"].diff("t") == inflow - gen_dispatch,
    name="SharedReservoir",
)

# Solve
status, cond = m.solve()
n.optimize.update_results()

# Check results
print(n.results["StorageUnit"]["state_of_charge"].head())
print(n.results["Generator"]["p"].head())
