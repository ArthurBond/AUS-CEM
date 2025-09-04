# too difficult to do lead times I think (cost should be most of it)
# how to do system strength cost ?

# hydrogen out of scope

# add (initial) build limits (p_nom_extendable = True and p_nom_max = build limit for region)
# these limits can be augmented with REZ augmentations

# add MLFs -> not the best assumption bc these change as generation cluster changes

import pypsa
import pandas as pd
import matplotlib.pyplot as plt

import os
import re
import glob

# class ISP24:
#     def __init__(self,network,path,start,end,carrier,interval,interval_slicing)
#     this would be useful for different time slicing
#    e.g. if you wanted to do 3h freq you would slice the RefYears by [::6] or [::3hours/30min]
#    e.g. weightings for hydro dispatch should be set to frequency so that inflows are energy not power

# Snapshots

def create_snapshots(n = "network.nc", start = (2024,7,1), end = (2025,6,30), 
                     interval = '3h'):
    # class 

    # Test on first month
    # n.set_snapshots(pd.date_range(start=f"{start[0]}-{start[1]}-{start[2]} 00:00",
    #                               end=f"{end[0]}-{end[1]}-{end[2]} 23:30",freq='30min'))
    
    # Test on different 3 hourly intervals
    n.set_snapshots(pd.date_range(start=f"{start[0]}-{start[1]}-{start[2]} 00:00",
                                  end=f"{end[0]}-{end[1]}-{end[2]} 23:30",freq='3h'))
    # n.set_snapshots(pd.date_range(start=f"{start[0]}-{start[1]}-{start[2]} 01:00",
    #                               end=f"{end[0]}-{end[1]}-{end[2]} 23:30",freq='3h'))
    # n.set_snapshots(pd.date_range(start=f"{start[0]}-{start[1]}-{start[2]} 02:00",
    #                               end=f"{end[0]}-{end[1]}-{end[2]} 23:30",freq='3h'))

# Carriers

def add_carriers(n = "network.nc", fuels=['Coal','Renewables']):

    for fuel in fuels:
        n.add('Carrier',name=fuel)

    n.add("Carrier", "AC", co2_emissions=0.0)
    n.add("Carrier", "DC", co2_emissions=0.0)

# Links

def add_links(n = "network.nc", path = "./isp_sheets_23/",
              fn = "network_capability/flow_path_capability.csv",
              timeslices = "Traces/SC/timeslice_RefYear4006.csv"):

    linkdf = pd.read_csv(path + fn)

    for _,row in linkdf.iterrows():
        n.add("Link",row['Plain Name'],
            bus0 = row['Bus0'],
            bus1 = row['Bus1'],
            type = 'AC',
            carrier='AC',
            p_nom = row['Max forward'], # use this as an estimate
            p_min_pu = -row['Max reverse']/row['Max forward'])

    n.links.loc['NNSW-SQ Terranora','type'] = "DC"
    n.links.loc['VIC-CSA Murraylink','type'] = "DC"
    n.links.loc['TAS-VIC Basslink','type'] = "DC"
    n.links.loc['NNSW-SQ Terranora','carrier'] = "DC"
    n.links.loc['VIC-CSA Murraylink','carrier'] = "DC"
    n.links.loc['TAS-VIC Basslink','carrier'] = "DC"

# Generators

def _is_DUID(s):
    '''more to make sure it's not a rez'''
    pattern = r'^(?=.*[A-Z])(?=.*\d)[A-Z0-9]+$'
    return bool(re.match(pattern, s))

def _get_trace_fn(trName,files):
    for fn in files:
        if fn.startswith(trName):
            return fn
        
def _get_timeslices(tpath="./Traces/SC/timeslice_RefYear4006.csv",
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

        df = df[df["TIMESLICE"]==1].loc[:]

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

        timeslice[region] = out.set_index("DATETIME")[f"{start[0]}-{start[1]}-{start[2]}":f"{end[0]}-{end[1]}-{end[2]}"].copy()
    
    return regions,timeslice

def _region_timeslice(region,timeslice):
    "From timeslice for a region get day_type and day_type_short"

    # NAME and DAY_TYPE
    day_types = timeslice[region].copy()

    return day_types


def add_existing_generators(n, path, scenario = "SC",interval_slicing=6):
    '''
    Add existing generators and storage units to the network.

    Parameters
    ----------
    n : network
        PyPSA network with buses defined.
    path : str
        Path to data files.
    interval_slicing: int
        Snapshot relative to 30 mins (e.g. 3 hours/30mins = every 6 snapshots)

    Note: Hydro inflows are done in GWh by AEMO but PyPSA does it in MW.
    '''
        
    solarPath = f"./Traces/{scenario}/solar/"
    windPath = f"./Traces/{scenario}/wind/"
    solarTraces = os.listdir(solarPath)
    windTraces = os.listdir(windPath)
    # solarTraceNames = [s.split("_")[0] for s in solarTraces if s[:3]!="REZ"]
    # windTraceNames = [s.split("_")[0] for s in windTraces if len(s.split("_")[0])>2]

    trace_map = pd.read_csv(path + "summary_mapping/trace_map.csv")
    traceMap  = trace_map.set_index('GenName')['TraceName'].to_dict()

    # do this better
    # currently only using existing_gens for Generator name :/
    existing_gens = pd.read_csv(path + "maximum_capacity/existing_gen_caps.csv")
    existing_map  = pd.read_csv(path + "summary_mapping/existing.csv",index_col=0)
    existing_summary  = pd.read_csv(path + "generation_summary/existing_gen_summary.csv",index_col=0)
    existing_units  = pd.read_csv(path + "seasonal_ratings/existing_gen_seasonal_ratings.csv")

    # for fuel in existing_map['Fuel type'].unique():
    #     n.add('Carrier',name=fuel)

    # add gens
    # consider adding project status as part of carrier info
    year = 2025 # financial
    for idx,row in existing_gens.iterrows():
        genName = row['Generator']
        fuel = existing_map.loc[genName,"Fuel type"]
        busName = existing_summary.loc[genName,"ISP sub-region"]
        marginalCost = existing_summary.loc[genName,"SRMC ($/MWh)"]

        units = existing_units[existing_units['Generator']==genName]

        # take the minimum of the summer typical, summer peak, winter

        # re-scale p_max_pu according to 

        for unit,urow in units.iterrows():
            unitName = urow['DUID']
            summerTypical = urow[f'ST{year-1}-{str(year)[2:]}']

            # summerPeak = urow[f'SP{year-1}-{str(year)[2:]}']

            if fuel == 'Wind':
                df = pd.read_csv(windPath+_get_trace_fn(traceMap[genName],windTraces))
                newdf = df.set_index(["Year","Month","Day"])
                p_max_pu_vals = newdf.loc[start:end].values.flatten()
                n.add("Generator",
                    name = genName + ' (' + unitName + ')',
                    bus  = busName,
                    carrier = fuel,
                    marginal_cost = marginalCost,
                    p_nom = summerTypical,
                    p_max_pu = p_max_pu_vals[::interval_slicing])
            elif fuel == 'Solar':
                df = pd.read_csv(solarPath+_get_trace_fn(traceMap[genName],solarTraces))
                newdf = df.set_index(["Year","Month","Day"])
                p_max_pu_vals = newdf.loc[start:end].values.flatten()
                n.add("Generator",
                    name = genName + ' (' + unitName + ')',
                    bus  = busName,
                    carrier = fuel,
                    marginal_cost = marginalCost,
                    p_nom = summerTypical,
                    p_max_pu = p_max_pu_vals[::interval_slicing])
            elif fuel == 'Water':
                n.add("Generator",
                    name = genName + ' (' + unitName + ')',
                    bus  = busName,
                    carrier = fuel,
                    marginal_cost = marginalCost,
                    p_nom = summerTypical)
                    # p_nom_max = summerPeak)
            elif fuel in ['Black Coal', 'Brown Coal', 'Gas', 'Liquid Fuel']:
                # outages are forced in manually using p_max_pu
                # randomly set p_max_pu to zero and include summer and winter differences
                n.add("Generator",
                    name = genName + ' (' + unitName + ')',
                    bus  = busName,
                    carrier = fuel,
                    marginal_cost = marginalCost,
                    p_nom = summerTypical)
                    # p_nom_max = summerPeak) 
                    # pnommax ignored anyway unless pnomextendable is True
            else:
                print(genName)
                print("Something else")

# Committed, Anticipated
def add_planned_generators(n, path, scenario = "SC",interval_slicing=6):
    ### anticipated
    anticipated_gens = pd.read_csv(path + "maximum_capacity/anticipated_gen_caps.csv")
    anticipated_map  = pd.read_csv(path + "summary_mapping/anticipated.csv",index_col=0)
    anticipated_summary  = pd.read_csv(path + "generation_summary/anticipated_gen_summary.csv",index_col=0)
    anticipated_units  = pd.read_csv(path + "seasonal_ratings/anticipated_gen_seasonal_ratings.csv")

    solarPath = f".Traces/{scenario}/solar/"
    windPath = f".Traces/{scenario}/wind/"
    solarTraces = os.listdir(solarPath)
    windTraces = os.listdir(windPath)

    trace_map = pd.read_csv(path + "summary_mapping/trace_map.csv")
    traceMap  = trace_map.set_index('GenName')['TraceName'].to_dict()

    # add gens
    # consider adding project status as part of carrier info
    year = 2025 # financial
    for idx,row in anticipated_gens.iterrows():
        genName = row['Generator']
        fuel = anticipated_map.loc[genName,"Fuel type"]
        busName = anticipated_summary.loc[genName,"ISP sub-region"]
        marginalCost = anticipated_summary.loc[genName,"SRMC ($/MWh)"]

        units = anticipated_units[anticipated_units['Generator']==genName]

        for unit,urow in units.iterrows():
            unitName = urow['DUID']
            summerTypical = urow[f'ST{year-1}-{str(year)[2:]}']
            summerPeak = urow[f'SP{year-1}-{str(year)[2:]}']

            if fuel == 'Wind':
                df = pd.read_csv(windPath+_get_trace_fn(traceMap[genName],windTraces))
                newdf = df.set_index(["Year","Month","Day"])
                p_max_pu_vals = newdf.loc[start:end].values.flatten()
                n.add("Generator",
                    name = genName + ' (' + unitName + ')',
                    bus  = busName,
                    carrier = fuel,
                    marginal_cost = marginalCost,
                    p_nom = summerTypical,
                    p_max_pu = p_max_pu_vals[::interval_slicing])
            elif fuel == 'Solar':
                df = pd.read_csv(solarPath+_get_trace_fn(traceMap[genName],solarTraces))
                newdf = df.set_index(["Year","Month","Day"])
                p_max_pu_vals = newdf.loc[start:end].values.flatten()
                n.add("Generator",
                    name = genName + ' (' + unitName + ')',
                    bus  = busName,
                    carrier = fuel,
                    marginal_cost = marginalCost,
                    p_nom = summerTypical,
                    p_max_pu = p_max_pu_vals[::interval_slicing],
                    retirement=x,)
            elif fuel == 'Water':
                n.add("Generator",
                    name = genName + ' (' + unitName + ')',
                    bus  = busName,
                    carrier = fuel,
                    marginal_cost = marginalCost,
                    p_nom = summerTypical)
                    # p_nom_max = summerPeak)
            elif fuel in ['Black Coal', 'Brown Coal', 'Gas', 'Liquid Fuel']:
                # outages are forced in manually using p_max_pu
                # randomly set p_max_pu to zero and include summer and winter differences
                n.add("Generator",
                    name = genName + ' (' + unitName + ')',
                    bus  = busName,
                    carrier = fuel,
                    marginal_cost = marginalCost,
                    p_nom = summerTypical)
                    # p_nom_max = summerPeak) 
                    # pnommax ignored anyway unless pnomextendable is True
            else:
                print(genName)
                print("Something else")

    ### committed
    committed_gens = pd.read_csv(path + "maximum_capacity/committed_gen_caps.csv")
    committed_map  = pd.read_csv(path + "summary_mapping/committed.csv",index_col=0)
    committed_summary  = pd.read_csv(path + "generation_summary/committed_gen_summary.csv",index_col=0)
    committed_units  = pd.read_csv(path + "seasonal_ratings/committed_gen_seasonal_ratings.csv")

    trace_map = pd.read_csv(path + "summary_mapping/trace_map.csv")
    traceMap  = trace_map.set_index('GenName')['TraceName'].to_dict()

    # add gens
    # consider adding project status as part of carrier info
    year = 2025 # financial
    for idx,row in committed_gens.iterrows():
        genName = row['Generator']
        fuel = committed_map.loc[genName,"Fuel type"]
        busName = committed_summary.loc[genName,"ISP sub-region"]
        marginalCost = committed_summary.loc[genName,"SRMC ($/MWh)"]

        units = committed_units[committed_units['Generator']==genName]

        for unit,urow in units.iterrows():
            unitName = urow['DUID']
            summerTypical = urow[f'ST{year-1}-{str(year)[2:]}']
            summerPeak = urow[f'SP{year-1}-{str(year)[2:]}']

            if fuel == 'Wind':
                df = pd.read_csv("../Downloads/Wind/"+_get_trace_fn(traceMap[genName],windTraces))
                newdf = df.set_index(["Year","Month","Day"])
                p_max_pu_vals = newdf.loc[start:end].values.flatten()
                n.add("Generator",
                    name = genName + ' (' + unitName + ')',
                    bus  = busName,
                    carrier = fuel,
                    marginal_cost = marginalCost,
                    p_nom = summerTypical,
                    p_max_pu = p_max_pu_vals[::interval_slicing])
            elif fuel == 'Solar':
                df = pd.read_csv("../Downloads/Solar/"+_get_trace_fn(traceMap[genName],solarTraces))
                newdf = df.set_index(["Year","Month","Day"])
                p_max_pu_vals = newdf.loc[start:end].values.flatten()
                n.add("Generator",
                    name = genName + ' (' + unitName + ')',
                    bus  = busName,
                    carrier = fuel,
                    marginal_cost = marginalCost,
                    p_nom = summerTypical,
                    p_max_pu = p_max_pu_vals[::interval_slicing])
            elif fuel == 'Water':
                n.add("Generator",
                    name = genName + ' (' + unitName + ')',
                    bus  = busName,
                    carrier = fuel,
                    marginal_cost = marginalCost,
                    p_nom = summerTypical)
                    # p_nom_max = summerPeak)
            elif fuel in ['Black Coal', 'Brown Coal', 'Gas', 'Liquid Fuel']:
                # outages are forced in manually using p_max_pu
                # randomly set p_max_pu to zero and include summer and winter differences
                n.add("Generator",
                    name = genName + ' (' + unitName + ')',
                    bus  = busName,
                    carrier = fuel,
                    marginal_cost = marginalCost,
                    p_nom = summerTypical)
                    # p_nom_max = summerPeak) 
                    # pnommax ignored anyway unless pnomextendable is True
            else:
                print(genName)
                print("Something else")


# Storage

def add_storage(n,path):
    # add batteries

    battery = pd.read_csv(path + "summary_mapping/batteries.csv",index_col=0)
    battery_summary  = pd.read_csv(path + "generation_summary/battery_gen_summary.csv",index_col=0)
    battery_ratings = pd.read_csv(path + "seasonal_ratings/battery_gen_seasonal_ratings.csv")
    battery_caps = pd.read_csv(path + "maximum_capacity/battery_caps.csv")

    battery_caps['Max storage hours'] = battery_caps['Energy (MWh)'] / battery_caps['Installed capacity (MW)']
    battery_caps_existing = battery_caps[battery_caps['Project status']=='Existing']
    battery_caps_new = battery_caps[~(battery_caps['Project status']=='Existing')]


    for idx,row in battery_caps_existing.iterrows():
        batName = row['Storage']
        fuel = battery.loc[batName,"Fuel type"]
        busName = battery_summary.loc[batName,"ISP sub-region"]
        marginalCost = battery_summary.loc[batName,"SRMC ($/MWh)"]
        
        units = battery_ratings[battery_ratings['Generator']==batName]

        for unit,urow in units.iterrows():
            unitName = urow['DUID']
            summerTypical = urow[f'ST{year-1}-{str(year)[2:]}']

            n.add("StorageUnit",
                    name = batName + ' (' + unitName + ')',
                    bus  = busName,
                    carrier = fuel,
                    marginal_cost = marginalCost,
                    p_nom = summerTypical,
                    max_hours = row['Max storage hours'])
            
    for idx,row in battery_caps_new.iterrows():
        batName = row['Storage']
        fuel = battery.loc[batName,"Fuel type"]
        busName = battery_summary.loc[batName,"ISP sub-region"]
        marginalCost = battery_summary.loc[batName,"SRMC ($/MWh)"]
        
        units = battery_ratings[battery_ratings['Generator']==batName]

        for unit,urow in units.iterrows():
            unitName = urow['DUID']
            summerTypical = urow[f'ST{year-1}-{str(year)[2:]}']

            n.add("StorageUnit",
                    name = batName + ' (' + unitName + ')',
                    bus  = busName,
                    carrier = fuel,
                    build_year = XXX,
                    marginal_cost = marginalCost,
                    p_nom = summerTypical,
                    max_hours = row['Max storage hours'])

# add battery and pumped hydro properties

# find out which hydro gens also have pumped hydro -> phes_properties

# do Kidston manually MAKE SURE TO INCLUDE PUMP CAPACITY

# check REZ hosting capacity increase of NQ2

# has a different pump capacity to generation capacity

# hydro with no pumping is just storageunit with p_min_pu = -1?

# see how pypsa-eur does hydro, just set p_min_pu to 0 and efficiency_store to 0

def attach_hydro(n, costs, ppl, profile_hydro, hydro_capacities, carriers, **params):
    add_missing_carriers(n, carriers)
    add_co2_emissions(n, costs, carriers)

    ppl = (
        ppl.query('carrier == "hydro"')
        .reset_index(drop=True)
        .rename(index=lambda s: f"{str(s)} hydro")
    )
    ror = ppl.query('technology == "Run-Of-River"')
    phs = ppl.query('technology == "Pumped Storage"')
    hydro = ppl.query('technology == "Reservoir"')

    country = ppl["bus"].map(n.buses.country).rename("country")

    inflow_idx = ror.index.union(hydro.index)
    if not inflow_idx.empty:
        dist_key = ppl.loc[inflow_idx, "p_nom"].groupby(country).transform(normed)

        with xr.open_dataarray(profile_hydro) as inflow:
            inflow_countries = pd.Index(country[inflow_idx])
            missing_c = inflow_countries.unique().difference(
                inflow.indexes["countries"]
            )
            assert missing_c.empty, (
                f"'{profile_hydro}' is missing "
                f"inflow time-series for at least one country: {', '.join(missing_c)}"
            )

            inflow_t = (
                inflow.sel(countries=inflow_countries)
                .rename({"countries": "name"})
                .assign_coords(name=inflow_idx)
                .transpose("time", "name")
                .to_pandas()
                .multiply(dist_key, axis=1)
            )

    if "ror" in carriers and not ror.empty:
        n.madd(
            "Generator",
            ror.index,
            carrier="ror",
            bus=ror["bus"],
            p_nom=ror["p_nom"],
            efficiency=costs.at["ror", "efficiency"],
            capital_cost=costs.at["ror", "capital_cost"],
            weight=ror["p_nom"],
            p_max_pu=(
                inflow_t[ror.index]
                .divide(ror["p_nom"], axis=1)
                .where(lambda df: df <= 1.0, other=1.0)
            ),
        )

    if "PHS" in carriers and not phs.empty:
        # fill missing max hours to params value and
        # assume no natural inflow due to lack of data
        max_hours = params.get("PHS_max_hours", 6)
        phs = phs.replace({"max_hours": {0: max_hours, np.nan: max_hours}})
        n.madd(
            "StorageUnit",
            phs.index,
            carrier="PHS",
            bus=phs["bus"],
            p_nom=phs["p_nom"],
            capital_cost=costs.at["PHS", "capital_cost"],
            max_hours=phs["max_hours"],
            efficiency_store=np.sqrt(costs.at["PHS", "efficiency"]),
            efficiency_dispatch=np.sqrt(costs.at["PHS", "efficiency"]),
            cyclic_state_of_charge=True,
        )

    if "hydro" in carriers and not hydro.empty:
        hydro_max_hours = params.get("hydro_max_hours")

        assert hydro_max_hours is not None, "No path for hydro capacities given."

        hydro_stats = pd.read_csv(
            hydro_capacities, comment="#", na_values="-", index_col=0
        )
        e_target = hydro_stats["E_store[TWh]"].clip(lower=0.2) * 1e6
        e_installed = hydro.eval("p_nom * max_hours").groupby(hydro.country).sum()
        e_missing = e_target - e_installed
        missing_mh_i = hydro.query("max_hours.isnull()").index

        if hydro_max_hours == "energy_capacity_totals_by_country":
            # watch out some p_nom values like IE's are totally underrepresented
            max_hours_country = (
                e_missing / hydro.loc[missing_mh_i].groupby("country").p_nom.sum()
            )

        elif hydro_max_hours == "estimate_by_large_installations":
            max_hours_country = (
                hydro_stats["E_store[TWh]"] * 1e3 / hydro_stats["p_nom_discharge[GW]"]
            )

        max_hours_country.clip(0, inplace=True)

        missing_countries = pd.Index(hydro["country"].unique()).difference(
            max_hours_country.dropna().index
        )
        if not missing_countries.empty:
            logger.warning(
                f'Assuming max_hours=6 for hydro reservoirs in the countries: {", ".join(missing_countries)}'
            )
        hydro_max_hours = hydro.max_hours.where(
            hydro.max_hours > 0, hydro.country.map(max_hours_country)
        ).fillna(6)

        if params.get("flatten_dispatch", False):
            buffer = params.get("flatten_dispatch_buffer", 0.2)
            average_capacity_factor = inflow_t[hydro.index].mean() / hydro["p_nom"]
            p_max_pu = (average_capacity_factor + buffer).clip(upper=1)
        else:
            p_max_pu = 1

        n.madd(
            "StorageUnit",
            hydro.index,
            carrier="hydro",
            bus=hydro["bus"],
            p_nom=hydro["p_nom"],
            max_hours=hydro_max_hours,
            capital_cost=costs.at["hydro", "capital_cost"],
            marginal_cost=costs.at["hydro", "marginal_cost"],
            p_max_pu=p_max_pu,  # dispatch
            p_min_pu=0.0,  # store
            efficiency_dispatch=costs.at["hydro", "efficiency"],
            efficiency_store=0.0,
            cyclic_state_of_charge=True,
            inflow=inflow_t.loc[:, hydro.index],
        )



# Load

def add_load(n,start,end,demandpath="./Traces/SC/demand/"):
    "add load to network"

    subregions = os.listdir(demandpath)

    for subregion in subregions:
        fn = demandpath + subregion
        
        if fn.endswith('.csv'):
            df = pd.read_csv(demandpath + subregion)
            newdf = df.set_index(["Year","Month","Day"])
            demand = newdf.loc[start:end].values.flatten()
            bus = subregion.split('_')[0]

            n.add("Load",
                name=f"Load_{bus}",
                bus=bus,
                p_set=demand)
            
# Add REZ zones

def add_rez(n,path,scenario = "SC",interval_slicing=6):
    "solar + wind rez capacity expansion"

    # use economic life for retirment

    # set up REZ zones for the first 5 years that have to retire in 2050,1,2,3,4,

    # for now imagine all wind turbines can repower    

    solarPath = f"./Traces/{scenario}/solar/"
    windPath = f"./Traces/{scenario}/wind/"
    solarTraces = os.listdir(solarPath)
    windTraces = os.listdir(windPath)

    # combine build costs and locational cost factors...

    rez_summary = pd.read_csv(path + "REZ/rez_summary.csv",index_col=0)
    
    for rez in rez_summary.index:

        rez_name = rez_summary.at[rez,"Name"]

        # solar
        solar_gen_types = glob.glob(solarPath + "REZ_" + str(rez_name) + "*.csv")

        # solar has CST and SAT

        for solar_gen in solar_gen_types:
            solar_name = solar_gen.split("_")[1:-1].join(" ")
            df = pd.read_csv(solar_gen)
            newdf = df.set_index(["Year","Month","Day"])
            p_max_pu_vals = newdf.loc[start:end].values.flatten()
            if ("SAT" in solar_gen) or ("FFP" in solar_gen):
                n.add("Generator",
                    name = solar_name,
                    p_nom=0,
                    p_nom_extendable=True,
                    p_max_pu=p_max_pu_vals[::interval_slicing]
                )
            elif "CST" in solar_gen:
                n.add("StorageUnit",
                      name = solar_gen,
                      p_nom = 0,
                      p_nom_opt=100, #?
                      p_nom_extendable=True,
                      p_max_pu=p_max_pu_vals[::interval_slicing],
                      max_hours=15)
            else:
                print("Something wrong... added solar tech in REZ other than SAT,FFP,CST")
        
        # wind has WM and WH (onshore medium and high wind speed) 
        # as well as WFL and WFX which is offshore wind floating and fixed
        
        # wind
        wind_gen_types = glob.glob(windPath + str(rez_name) + "*.csv")

        # wind has WM, WH, WFL, WFX
        # need to separate high from medium because there are different land (build) limits

        for solar_gen in solar_gen_types:
            solar_name = solar_gen.split("_")[1:-1].join(" ")
            df = pd.read_csv(solar_gen)
            newdf = df.set_index(["Year","Month","Day"])
            p_max_pu_vals = newdf.loc[start:end].values.flatten()
            if ("SAT" in solar_gen) or ("FFP" in solar_gen):
                n.add("Generator",
                    name = solar_name,
                    p_nom=0,
                    p_nom_extendable=True,
                    p_max_pu=p_max_pu_vals[::interval_slicing]
                )
            elif "CST" in solar_gen:
                n.add("StorageUnit",
                      name = solar_gen,
                      p_nom = 0,
                      p_nom_opt=100, #?
                      p_nom_extendable=True,
                      p_max_pu=p_max_pu_vals[::interval_slicing],
                      max_hours=15)
            else:
                print("Something wrong... added solar tech in REZ other than SAT,FFP,CST")

    # need to apply a soft constraint here non-rez connection assumes it is near sensitive
    # env / community / cultural land

    # e.g. objective += $1 million * MW of Non-REZ build in addition to build costs

    # NSW Medium build costs for solar (use summary mapping for stuff)

    n.model.objective += n.model.variables["Generator_p_nom"] * 1000

    # these have a max build of 699,1679
    # 291 699

    # don't need to split.

    # non-rez groups in NSW and VIC
    # handle non-rez wind
    wind_gen_types_non_rez = glob.glob(windPath + "[NV]0*.csv")

    # handle non-rez solar
    solar_gen_types_non_rez = glob.glob(windPath + "REZ_[NV]0*.csv")

def add_new_entrants(n,path):
    "add options for new gas entrants"

    n.add("Generator",
          name = "NSW - New CCGT 0",
          capital_cost = build_cost_annuitised,
          p_nom_extendable = True,
          p_nom_max = x) # don't need p_nom_max, split by units later
    


if __name__=="__main__":

    data_path = "./isp_sheets_23/" # run from AUS-CEM directory

    n = pypsa.Network()

    start = (2025,1,1)
    end = (2025,1,2)

    create_snapshots(n,start,end)

    fuels = ['Black Coal', 'Brown Coal', 'Gas', 'Liquid Fuel', 'Water', 'Solar', 'Wind', 'Battery']

    fuels = ['OCGT (small)','OCGT (large)','CCGT','CCGT (with CCS)','Biomass','Utility Solar',
             'Utility Wind','Wind Offshore','Wind Offshore','Solar Thermal',
             'Battery Storage (1hr)','Battery Storage (2hr)','Battery Storage (4hr)','Battery Storage (8hr)',
             'Pumped Hydro']

    add_carriers(n,fuels)

    print(n)

    # need to finish with n.optimize.create_model() before adding constraints

    # line constraint cost = [cost1,cost2]

    # m = n.model

    # m.add_constraints()

    # n.model.objective = m.objective + [cost1,...]*[aug1,...]
