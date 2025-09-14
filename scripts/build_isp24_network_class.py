import pypsa
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# need a commercial or academic license
import gurobipy

import os
import re
import glob

class ISP24:
    '''
    capacity expansion model for Australia based on ISP24 inputs
    '''
    #! initialising !#

    def __init__(self,network_name,start=(2024,7,1),end=(2055,6,30),interval="3h",step=6,
                 data_path="./isp_sheets_23/",trace_path="./Traces/",scenario="SC"):
        '''
        initialises the Long Term (LT) version of the ISP24, i.e. Capacity Expansion
        '''
        
        self.n    = pypsa.Network(name=network_name)
        self.name = network_name
        self.scenario = scenario

        self.start = start
        self.end   = end

        self.interval = interval
        self.step     = step

        self.path = data_path
        self.trace_path = trace_path

        self.solarPath = trace_path + "solar/"
        self.windPath  = trace_path + "wind/"
        self.solarTraces = os.listdir(self.solarPath)
        self.windTraces  = os.listdir(self.windPath)

        capital_fn = "build_costs/SC_regional_build_costs_tech.csv"
        # cdf = pd.read_csv(data_path + capital_fn,index_col=0)
        self.capital_costs = pd.read_csv(data_path + capital_fn,index_col=0)

    def __repr__(self):
        '''
        network name
        '''
        return self.name

    #! get network parameters !#

    def _get_capital_costs(self,fn="build_costs/{}_regional_build_costs_tech.csv"):
        """
        row: pandas Series (from the DataFrame)
        snapshots: pd.DatetimeIndex or list of date strings
        Returns: pd.Series of capital costs for each snapshot
        """
        df = pd.read_csv(self.path + fn.format(self.scenario))

        # Ensure snapshots are Timestamps
        snapshots = pd.to_datetime(self.snapshots)
        # Build financial year label for each snapshot
        years = snapshots.year
        fy_start = years.where(snapshots.month < 7, years)
        fy_end = years.where(snapshots.month < 7, years + 1)
        fy_labels = [f"{start}-{str(end)[-2:]}" for start, end in zip(fy_start, fy_end)]
        # Find all year columns in the row
        year_cols = [c for c in df.columns if '-' in c and c[:4].isdigit()]
        last_col = year_cols[-1]
        # For each snapshot, get the matching column or use last_col
        cost_cols = []
        for label in fy_labels:
            found = [c for c in year_cols if label in c]
            cost_cols.append(found[0] if found else last_col)

        self.build_cost_cols = cost_cols

        # add FOM

        return cost_cols
    
    def _get_build_costs(self,fn="build_costs/{}_regional_build_costs_tech.csv"):
        '''
        get capital build costs
        '''

        years = list(range(self.start[0],self.end[0]+1))
        
        cost_cols = [f"{year-1}-{str(year)[-2:]}" for year in years]

        self.build_cost_cols = cost_cols

        return cost_cols


    def _get_marginal_costs(self):
        '''
        add time varying marginal costs
        '''

    #! simple network components !#

    def _initialise_parameters(self):

        # self._get_build_costs()

        self._get_capital_costs()

    def add_snapshots(self):
        '''
        add snapshots using start, end, interval
        add multi_investment periods
        '''
        # create snapshots
        years = list(range(self.start[0],self.end[0]+1))
        snapshots = pd.DatetimeIndex([])
        period = pd.date_range(
            start=f"{self.start[0]}-{self.start[1]}-{self.start[2]} 00:00",
            end  =f"{self.end[0]}-{self.end[1]}-{self.end[2]} 23:30",
            freq =self.interval
        )
        snapshots = snapshots.append(period)

        self.snapshots = snapshots

        # convert to multiindex and assign to network
        self.n.set_snapshots(pd.MultiIndex.from_arrays([snapshots.year, snapshots]))
        self.n.investment_periods = years

        # if self.step % 2 == 1:
        #     raise ValueError("Step size must be even.") 

        self.n.snapshot_weightings.loc[:, :] = self.step / 2

        self._initialise_parameters()

        return self.n.snapshots
    
    def add_carriers(self,fn = "emissions_intensity/intensity.csv"):
        '''
        add carriers
        '''
        cdf = pd.read_csv(self.path + fn)
        
        for _,row in cdf.iterrows():
            self.n.add("Carrier",name=row["Generator"],co2_emissions=row["Intensity"]/1000)

        self.n.add("Carrier", "AC", co2_emissions=0.0)
        self.n.add("Carrier", "DC", co2_emissions=0.0)

    def add_buses(self,fn = "network_representation/subregional_ref_nodes.csv"):
        '''
        add subregions to network model
        '''
        busdf = pd.read_csv(self.path + fn)

        for _,row in busdf.iterrows():
            self.n.add("Bus",row["Bus"],v_nom=row["Voltage (kV)"],carrier="AC")

        return self.n.buses

    def add_loads(self):
        '''
        add load profile to the network
        '''
        demandpath = self.trace_path + self.scenario + "/demand/"
        subregions = os.listdir(demandpath)

        for subregion in subregions:
            fn = demandpath + subregion
            
            if fn.endswith(".csv"):
                df = pd.read_csv(demandpath + subregion)
                newdf = df.set_index(["Year","Month","Day"])
                demand = newdf.loc[self.start:self.end].values.flatten()[::self.step]
                bus = subregion.split('_')[0]

                # get average

                # flat = newdf.loc[self.start:self.end].values.flatten()

                # # Trim to a multiple of step
                # n = len(flat) // self.step * self.step
                # flat_trimmed = flat[:n]

                # # Reshape and average
                # demand = flat_trimmed.reshape(-1, self.step).mean(axis=1)

                # # If you want to keep the remainder (last chunk), average it too:
                # if len(flat) % self.step != 0:
                #     last_avg = flat[n:].mean()
                #     demand = np.concatenate([demand, [last_avg]])

                self.n.add("Load",
                    name=f"Load_{bus}",
                    bus=bus,
                    p_set=demand)

    def add_links(self,fn = "network_capability/flow_path_capability.csv"):
        '''
        add links without constraints
        '''
        linkdf = pd.read_csv(self.path + fn)

        # p_max_pu and p_min_pu shenanigans

        for _,row in linkdf.iterrows():
            
            if row["Inter-regional"]:
                #add efficiency with time series using timeslice
                # dont think about marginal cost its too much
                # might need to set active to be true
                # intraregional has efficiency of 1
            
                self.n.add("Link",row['Plain Name'],
                        bus0 = row['Bus0'],
                        bus1 = row['Bus1'],
                        type    = 'AC',
                        carrier = 'AC',
                        p_nom = 1e6, # use this as an estimate
                        p_min_pu = -1,
                        efficiency=0.9)
                    # p_nom_extendable=True)
            else:
                self.n.add("Link",row['Plain Name'],
                        bus0 = row['Bus0'],
                        bus1 = row['Bus1'],
                        type    = 'AC',
                        carrier = 'AC',
                        p_nom = 1e6, # use this as an estimate
                        p_min_pu = -1,
                        efficiency=1)
            # check if there's any difference with transmission losses or not

        self.n.links.loc['NNSW-SQ Terranora','type'] = "DC"
        self.n.links.loc['VIC-CSA Murraylink','type'] = "DC"
        self.n.links.loc['TAS-VIC Basslink','type'] = "DC"
        self.n.links.loc['NNSW-SQ Terranora','carrier'] = "DC"
        self.n.links.loc['VIC-CSA Murraylink','carrier'] = "DC"
        self.n.links.loc['TAS-VIC Basslink','carrier'] = "DC"

    def add_transformers(self,s_nominal=2000):
        '''
        add transformers to network model
        '''

        self.n.add("Transformer",name="Transformer_NNSW_SQ",bus0='NNSW',bus1='SQ',x=0.1,r=0.01,s_nom = s_nominal)
        self.n.add("Transformer",name="Transformer_SNSW_VIC",bus0='SNSW',bus1='VIC',x=0.1,r=0.01,s_nom = s_nominal)
        self.n.add("Transformer",name="Transformer_SNSW_CSA",bus0='SNSW',bus1='CSA',x=0.1,r=0.01,s_nom = s_nominal)
        self.n.add("Transformer",name="Transformer_SESA_VIC",bus0='SESA',bus1='VIC',x=0.1,r=0.01,s_nom = s_nominal)
        self.n.add("Transformer",name="Transformer_SESA_CSA",bus0='SESA',bus1='CSA',x=0.1,r=0.01,s_nom = s_nominal)
        self.n.add("Transformer",name="Transformer_VIC_TAS",bus0='VIC',bus1='TAS',x=0.1,r=0.01,s_nom = s_nominal)

        return self.n.transformers

    #! adding generators !#

    #  helper functions  !--

    def _is_DUID(self,s):
        '''more to make sure it's not a rez'''
        pattern = r'^(?=.*[A-Z])(?=.*\d)[A-Z0-9]+$'
        return bool(re.match(pattern, s))

    def _get_trace_fn(self,trName,files):
        '''get trace filename'''
        for fn in files:
            if fn.startswith(trName):
                return fn
        return None
                    
    def _get_regional_timeslices(self,fn = "timeslice_RefYear4006.csv"):
        '''
        return type of day for all days in the traces provided
        '''
        df = pd.read_csv(self.trace_path + fn)
        timeslice = {}
        regions = ("NSW","QLD","VIC","TAS","SA")
        self.regions = regions

        day_type_map = {
            "Hot Day" : "SP",
            "Typical Summer" : "ST",
            "Winter" : "W"
        }

        # group timeslices by regions
        for region in regions:
            timeslice[region] = df[df["NAME"].str.startswith(region)].copy()

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

            timeslice[region] = out.set_index("DATETIME")[f"{self.start[0]}-{self.start[1]}-{self.start[2]}":f"{self.end[0]}-{self.end[1]}-{self.end[2]}"].copy()
        
        self.timeslice_regions = timeslice

        return regions,timeslice
            
    def _get_seasonal_columns_from_timeslice(self):
        '''
        helper function to get corresponding seasonal ratings columns from type of day

        e.g. Typical Summer in 2024,11,1 in QLD -> ST2024-25
        e.g. Winter in 2024,7,1 in NSW -> W2024

        '''
        regions,tdict = self._get_regional_timeslices()

        # seasonal columns to map timeslices to
        seasonal_cols = {}

        for region in regions:

            temp_ts = tdict[region].copy()
                
            region_map = temp_ts.DAY_TYPE_SHORT.to_dict()

            snapshots_day = self.snapshots.strftime("%Y-%m-%d")

            snapshots_day_dt = pd.to_datetime(snapshots_day)
            day_types = snapshots_day_dt.map(lambda d: region_map.get(d, None))
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

            seasonal_cols[region] = cap_cols

        self.seasonal_rating_cols = seasonal_cols

        return seasonal_cols

    # --!
    
    def _create_trace_map(self,fn = "summary_mapping/trace_map.csv"):
        '''
        map of generator name in IASR to trace name in ./Traces/ files 
        '''
        trace_map = pd.read_csv(self.path + fn).set_index("GenName")["TraceName"].to_dict()
     
        self.traceMap = trace_map

        return trace_map

    def add_existing_generators(self,
                                fns = ["summary_mapping/existing.csv",
                                       "generation_summary/existing_gen_summary.csv",
                                       "seasonal_ratings/existing_gen_seasonal_ratings.csv",
                                       "outages/5_48pc_outages.csv"]):
        '''
        add existing generators

        files required >

            0 : summary mapping
            1 : generation summary
            2 : seasonal ratings
            3 : outages
        '''

        # read files
        existing_map     = pd.read_csv(self.path + fns[0],index_col=0)
        existing_summary = pd.read_csv(self.path + fns[1],index_col=0)
        existing_units   = pd.read_csv(self.path + fns[2])

        # get timeslice info from here
        cap_col_dict = self._get_seasonal_columns_from_timeslice()

        # track planned outage pattern usage
        # outage_pattern = 0
        # odf = pd.read_csv(self.path + fns[3]).T

        # ! consider adding project status as part of carrier info
        for genName in existing_units.Generator.unique():

            print("adding",genName)

            # extract useful parameters
            fuel = existing_map.loc[genName,"Fuel type"]
            busName = existing_summary.loc[genName,"ISP sub-region"]
            marginalCost = existing_summary.loc[genName,"SRMC ($/MWh)"]
            retirementYear = existing_summary.loc[genName,"Expected retirement year"]

            # add seasonal effects
            units = existing_units[existing_units["Generator"]==genName]

            for _,urow in units.iterrows():
                unitName   = urow["DUID"]
                unitRegion = urow["Region"]

                # get capacity columns e.g. 'SP2024-25' etc
                cap_cols = cap_col_dict[unitRegion]
                capacity_t = np.array([urow[col] for col in cap_cols])
                max_cap = max(capacity_t)

                if max_cap > 0:

                    if fuel == "Wind":
                        df = pd.read_csv(self.windPath+self._get_trace_fn(self.traceMap[genName],self.windTraces))
                        newdf = df.set_index(["Year","Month","Day"])
                        p_max_pu_vals = newdf.loc[self.start:self.end].values.flatten()
                        self.n.add("Generator",
                            name = genName + " (" + unitName + ")",
                            bus  = busName,
                            carrier = "Existing Wind",
                            marginal_cost = marginalCost,
                            p_nom = max_cap,
                            p_max_pu = p_max_pu_vals[::self.step] * (capacity_t / max_cap),
                            build_year = 2024,
                            lifetime = retirementYear - 2024)
                    elif fuel == "Solar":
                        df = pd.read_csv(self.solarPath+self._get_trace_fn(self.traceMap[genName],self.solarTraces))
                        newdf = df.set_index(["Year","Month","Day"])
                        p_max_pu_vals = newdf.loc[self.start:self.end].values.flatten()
                        self.n.add("Generator",
                            name = genName + " (" + unitName + ")",
                            bus  = busName,
                            carrier = "Existing Utility Solar",
                            marginal_cost = marginalCost,
                            p_nom = max_cap,
                            p_max_pu = p_max_pu_vals[::self.step] * (capacity_t / max_cap),
                            build_year = 2024,
                            lifetime = retirementYear - 2024)
                    elif fuel == "Water":
                        # fix this
                        # ignore -> will have to model it separately

                        # TAS done as three generators using inflows and long duration energy storage as upper

                        # small hydro gens modelled as gens with upper generation limit (no inflows)

                        # pumped hydro as closed system

                        # tumut 3 only has 600 mw pumping capacity but 1800 mw generation capacity e.g. p_min_pu = -0.3333

                        # Snowy 2.0 pumped hydro

                        # Snowy scheme is 

                        self.n.add("Generator",
                            name = genName + " (" + unitName + ")",
                            bus  = busName,
                            carrier = "Existing Hydro",
                            marginal_cost = marginalCost,
                            p_nom = max_cap,
                            p_max_pu = capacity_t / max_cap,
                            build_year = 2024,
                            lifetime = retirementYear - 2024)
                    elif fuel in ["Black Coal", "Brown Coal", "Gas", "Liquid Fuel"]:
                        
                        # ensure outages have the same start and end
                        # outage_mask = (0,)

                        # if existing_map.loc[genName,"Technology type"] in ("Black Coal", "Brown Coal", "CCGT"):
                        # outage_mask = odf.iloc[outage_pattern % 200].values

                        # print(outage_mask)

                        # outage_pattern += 1

                        # outages are forced in manually using p_max_pu
                        self.n.add("Generator",
                            name = genName + ' (' + unitName + ')',
                            bus  = busName,
                            carrier = genName, # see emissions_intensity/intensity.csv
                            marginal_cost = marginalCost,
                            p_nom = max_cap,
                            p_max_pu = (capacity_t / max_cap), #* outage_mask,
                            build_year = 2024,
                            lifetime = retirementYear - 2024)
                            # commitable=True,
                            # start_up_cost=,
                            # shut_down_cost=,
                            # min_up_time=,
                            # min_down_time=, ADD snapshots it needs to be down here!!!
                            # up_time_before=,
                            # down_time_before=,
                            # ramp_limit_up=,
                            # ramp_limit_down=,
                            # ramp_limit_start_up=,
                            # ramp_limit_shut_down=,)
                    else:
                        print(genName)
                        print("Something else")

        # return self.n.generators
    
    def add_committed_generators(self, fns = ["summary_mapping/committed.csv",
                                       "generation_summary/committed_gen_summary.csv",
                                       "seasonal_ratings/committed_gen_seasonal_ratings.csv",
                                       "maximum_capacity/committed_gen_caps.csv"]):
        '''
        adding committed generators
        similar to existing but including build year
        '''

        # read files
        map     = pd.read_csv(self.path + fns[0],index_col=0)
        summary = pd.read_csv(self.path + fns[1],index_col=0)
        ratings   = pd.read_csv(self.path + fns[2])
        max_caps = pd.read_csv(self.path + fns[3],index_col=0)

        # get timeslice info from here
        cap_col_dict = self._get_seasonal_columns_from_timeslice()

        # track planned outage pattern usage
        # outage_pattern = 0
        # odf = pd.read_csv(self.path + fns[3]).T

        # ! consider adding project status as part of carrier info
        for genName in ratings.Generator.unique():

            print("adding",genName)

            # extract useful parameters
            fuel = map.loc[genName,"Fuel type"]
            busName = summary.loc[genName,"ISP sub-region"]
            marginalCost = summary.loc[genName,"SRMC ($/MWh)"]
            buildMonth,buildYear = max_caps.loc[genName,"Commissioning date"].split(" ")
            retirementYear = summary.loc[genName,"Expected retirement year"]

            # add seasonal effects
            units = ratings[ratings["Generator"]==genName]

            for _,urow in units.iterrows():
                unitName   = urow["DUID"]
                unitRegion = urow["Region"]

                # get capacity columns e.g. 'SP2024-25' etc
                cap_cols = cap_col_dict[unitRegion]
                capacity_t = np.array([urow[col] for col in cap_cols])
                max_cap = max(capacity_t)

                if max_cap > 0:

                    if fuel == "Wind":
                        df = pd.read_csv(self.windPath+self._get_trace_fn(self.traceMap[genName],self.windTraces))
                        newdf = df.set_index(["Year","Month","Day"])
                        p_max_pu_vals = newdf.loc[self.start:self.end].values.flatten()
                        self.n.add("Generator",
                            name = genName + " (" + unitName + ")",
                            bus  = busName,
                            carrier = "Wind",
                            marginal_cost = marginalCost,
                            p_nom = max_cap,
                            p_max_pu = p_max_pu_vals[::self.step] * (capacity_t / max_cap),
                            build_year = buildYear,
                            lifetime = retirementYear - 2024)
                    elif fuel == "Solar":
                        df = pd.read_csv(self.solarPath+self._get_trace_fn(self.traceMap[genName],self.solarTraces))
                        newdf = df.set_index(["Year","Month","Day"])
                        p_max_pu_vals = newdf.loc[self.start:self.end].values.flatten()
                        self.n.add("Generator",
                            name = genName + " (" + unitName + ")",
                            bus  = busName,
                            carrier = "Utility Solar",
                            marginal_cost = marginalCost,
                            p_nom = max_cap,
                            p_max_pu = p_max_pu_vals[::self.step] * (capacity_t / max_cap),
                            build_year = buildYear,
                            lifetime = retirementYear - 2024)
                    elif fuel == "Water":
                        # fix this
                        self.n.add("StorageUnit",
                            name = genName + " (" + unitName + ")",
                            bus  = busName,
                            carrier = "Pumped Hydro (8hrs storage)",
                            marginal_cost = marginalCost,
                            p_nom = max_cap,
                            p_max_pu = capacity_t / max_cap,
                            build_year = buildYear,
                            lifetime = retirementYear - 2024)
                    elif fuel in ["Black Coal", "Brown Coal", "Gas", "Liquid Fuel"]:
                        
                        # ensure outages have the same start and end
                        # outage_mask = (0,)

                        # if existing_map.loc[genName,"Technology type"] in ("Black Coal", "Brown Coal", "CCGT"):
                        # outage_mask = odf.iloc[outage_pattern % 200].values

                        # print(outage_mask)

                        # outage_pattern += 1

                        # outages are forced in manually using p_max_pu
                        self.n.add("Generator",
                            name = genName + ' (' + unitName + ')',
                            bus  = busName,
                            carrier = genName, # see emissions_intensity/intensity.csv
                            marginal_cost = marginalCost,
                            p_nom = max_cap,
                            p_max_pu = (capacity_t / max_cap),
                            build_year = buildYear,
                            lifetime = retirementYear - 2024)
                            # commitable=True,
                            # start_up_cost=,
                            # shut_down_cost=,
                            # min_up_time=,
                            # min_down_time=,
                            # up_time_before=,
                            # down_time_before=,
                            # ramp_limit_up=,
                            # ramp_limit_down=,
                            # ramp_limit_start_up=,
                            # ramp_limit_shut_down=,)
                    else:
                        print(genName)
                        print("Something else")

        # return self.n.generators

    def add_anticipated_generators(self,fns = ["summary_mapping/anticipated.csv",
                                       "generation_summary/anticipated_gen_summary.csv",
                                       "seasonal_ratings/anticipated_gen_seasonal_ratings.csv",
                                       "maximum_capacity/anticipated_gen_caps.csv"]):
        '''
        adding anticipated generators
        similar to existing but including build year
        '''

        # read files
        map     = pd.read_csv(self.path + fns[0],index_col=0)
        summary = pd.read_csv(self.path + fns[1],index_col=0)
        ratings   = pd.read_csv(self.path + fns[2])
        max_caps = pd.read_csv(self.path + fns[3],index_col=0)

        # get timeslice info from here
        cap_col_dict = self._get_seasonal_columns_from_timeslice()

        # track planned outage pattern usage
        # outage_pattern = 0
        # odf = pd.read_csv(self.path + fns[3]).T

        # ! consider adding project status as part of carrier info
        for genName in ratings.Generator.unique():

            print("adding",genName)

            # extract useful parameters
            fuel = map.loc[genName,"Fuel type"]
            busName = summary.loc[genName,"ISP sub-region"]
            marginalCost = summary.loc[genName,"SRMC ($/MWh)"]
            buildMonth,buildYear = max_caps.loc[genName,"Indicative commissioning date"].split(" ")
            retirementYear = summary.loc[genName,"Expected retirement year"]

            # add seasonal effects
            units = ratings[ratings["Generator"]==genName]

            for _,urow in units.iterrows():
                # fix get tracename genName can map to multiple
                # probably just try DUID first then genName ?
                unitName   = urow["DUID"]
                unitRegion = urow["Region"]

                # get capacity columns e.g. 'SP2024-25' etc
                cap_cols = cap_col_dict[unitRegion]
                capacity_t = np.array([urow[col] for col in cap_cols])
                max_cap = max(capacity_t)

                if max_cap > 0:

                    if fuel == "Wind":
                        df = pd.read_csv(self.windPath+self._get_trace_fn(self.traceMap[genName],self.windTraces))
                        newdf = df.set_index(["Year","Month","Day"])
                        p_max_pu_vals = newdf.loc[self.start:self.end].values.flatten()
                        self.n.add("Generator",
                            name = genName + " (" + unitName + ")",
                            bus  = busName,
                            carrier = "Wind",
                            marginal_cost = marginalCost,
                            p_nom = max_cap,
                            p_max_pu = p_max_pu_vals[::self.step] * (capacity_t / max_cap),
                            build_year = buildYear,
                            lifetime = retirementYear - 2024)
                    elif fuel == "Solar":
                        df = pd.read_csv(self.solarPath+self._get_trace_fn(self.traceMap[genName],self.solarTraces))
                        newdf = df.set_index(["Year","Month","Day"])
                        p_max_pu_vals = newdf.loc[self.start:self.end].values.flatten()
                        self.n.add("Generator",
                            name = genName + " (" + unitName + ")",
                            bus  = busName,
                            carrier = "Utility Solar",
                            marginal_cost = marginalCost,
                            p_nom = max_cap,
                            p_max_pu = p_max_pu_vals[::self.step] * (capacity_t / max_cap),
                            build_year = buildYear,
                            lifetime = retirementYear - 2024)
                    elif fuel == "Water":
                        # fix adding hydrogen based gas
                        self.n.add("StorageUnit",
                            name = genName + " (" + unitName + ")",
                            bus  = busName,
                            carrier = "Pumped Hydro (24hrs storage)",
                            marginal_cost = marginalCost,
                            p_nom = max_cap,
                            p_max_pu = capacity_t / max_cap,
                            build_year = buildYear,
                            lifetime = retirementYear - 2024)
                    elif fuel in ["Black Coal", "Brown Coal", "Gas", "Liquid Fuel"]:
                        
                        # ensure outages have the same start and end
                        # outage_mask = (0,)

                        # if existing_map.loc[genName,"Technology type"] in ("Black Coal", "Brown Coal", "CCGT"):
                        # outage_mask = odf.iloc[outage_pattern % 200].values

                        # print(outage_mask)

                        # outage_pattern += 1

                        # outages are forced in manually using p_max_pu
                        self.n.add("Generator",
                            name = genName + ' (' + unitName + ')',
                            bus  = busName,
                            carrier = genName, # see emissions_intensity/intensity.csv
                            marginal_cost = marginalCost,
                            p_nom = max_cap,
                            p_max_pu = (capacity_t / max_cap),
                            build_year = buildYear,
                            lifetime = retirementYear - 2024)
                            # commitable=True,
                            # start_up_cost=,
                            # shut_down_cost=,
                            # min_up_time=,
                            # min_down_time=,
                            # up_time_before=,
                            # down_time_before=,
                            # ramp_limit_up=,
                            # ramp_limit_down=,
                            # ramp_limit_start_up=,
                            # ramp_limit_shut_down=,)
                    else:
                        print(genName)
                        print("Something else")

        # return self.n.generators

    def add_additional_projects(self,fns = ["summary_mapping/anticipated.csv",
                                       "generation_summary/anticipated_gen_summary.csv",
                                       "seasonal_ratings/anticipated_gen_seasonal_ratings.csv",
                                       "maximum_capacity/anticipated_gen_caps.csv"]):
        '''
        adding additional projects
        '''
        # read files
        map     = pd.read_csv(self.path + fns[0],index_col=0)
        summary = pd.read_csv(self.path + fns[1],index_col=0)
        ratings   = pd.read_csv(self.path + fns[2])
        max_caps = pd.read_csv(self.path + fns[3],index_col=0)

        # get timeslice info from here
        cap_col_dict = self._get_seasonal_columns_from_timeslice()

        # track planned outage pattern usage
        # outage_pattern = 0
        # odf = pd.read_csv(self.path + fns[3]).T

        # ! consider adding project status as part of carrier info
        for genName in ratings.Generator.unique():

            print("adding",genName)

            # extract useful parameters
            fuel = map.loc[genName,"Fuel type"]
            busName = summary.loc[genName,"ISP sub-region"]
            marginalCost = summary.loc[genName,"SRMC ($/MWh)"]
            buildMonth,buildYear = max_caps.loc[genName,"Indicative commissioning date"].split(" ")
            retirementYear = summary.loc[genName,"Expected retirement year"]

            # add seasonal effects
            units = ratings[ratings["Generator"]==genName]

            for _,urow in units.iterrows():
                unitName   = urow["DUID"]
                unitRegion = urow["Region"]

                # get capacity columns e.g. 'SP2024-25' etc
                cap_cols = cap_col_dict[unitRegion]
                capacity_t = np.array([urow[col] for col in cap_cols])
                max_cap = max(capacity_t)

                if max_cap > 0:

                    if fuel == "Wind":
                        df = pd.read_csv(self.windPath+self._get_trace_fn(self.traceMap[genName],self.windTraces))
                        newdf = df.set_index(["Year","Month","Day"])
                        p_max_pu_vals = newdf.loc[self.start:self.end].values.flatten()
                        self.n.add("Generator",
                            name = genName + " (" + unitName + ")",
                            bus  = busName,
                            carrier = "Wind",
                            marginal_cost = marginalCost,
                            p_nom = max_cap,
                            p_max_pu = p_max_pu_vals[::self.step] * (capacity_t / max_cap),
                            build_year = buildYear,
                            lifetime = retirementYear - 2024)
                    elif fuel == "Solar":
                        df = pd.read_csv(self.solarPath+self._get_trace_fn(self.traceMap[genName],self.solarTraces))
                        newdf = df.set_index(["Year","Month","Day"])
                        p_max_pu_vals = newdf.loc[self.start:self.end].values.flatten()
                        self.n.add("Generator",
                            name = genName + " (" + unitName + ")",
                            bus  = busName,
                            carrier = "Utility Solar",
                            marginal_cost = marginalCost,
                            p_nom = max_cap,
                            p_max_pu = p_max_pu_vals[::self.step] * (capacity_t / max_cap),
                            build_year = buildYear,
                            lifetime = retirementYear - 2024)
                    elif fuel == "Water":
                        # fix this
                        self.n.add("StorageUnit",
                            name = genName + " (" + unitName + ")",
                            bus  = busName,
                            carrier = "Pumped Hydro",
                            marginal_cost = marginalCost,
                            p_nom = max_cap,
                            p_max_pu = capacity_t / max_cap,
                            build_year = 2024,
                            lifetime = retirementYear - 2024)
                    elif fuel in ["Black Coal", "Brown Coal", "Gas", "Liquid Fuel"]:
                        
                        # ensure outages have the same start and end
                        # outage_mask = (0,)

                        # if existing_map.loc[genName,"Technology type"] in ("Black Coal", "Brown Coal", "CCGT"):
                        # outage_mask = odf.iloc[outage_pattern % 200].values

                        # print(outage_mask)

                        # outage_pattern += 1

                        # outages are forced in manually using p_max_pu
                        self.n.add("Generator",
                            name = genName + ' (' + unitName + ')',
                            bus  = busName,
                            carrier = genName, # see emissions_intensity/intensity.csv
                            marginal_cost = marginalCost,
                            p_nom = max_cap,
                            p_max_pu = (capacity_t / max_cap),
                            build_year = buildYear,
                            lifetime = retirementYear - 2024)
                            # commitable=True,
                            # start_up_cost=,
                            # shut_down_cost=,
                            # min_up_time=,
                            # min_down_time=,
                            # up_time_before=,
                            # down_time_before=,
                            # ramp_limit_up=,
                            # ramp_limit_down=,
                            # ramp_limit_start_up=,
                            # ramp_limit_shut_down=,)
                    else:
                        print(genName)
                        print("Something else")

    def add_storage_units(self):
        '''
        adding storage units
        force units to be zero until starting month for indicative commisioning date
        '''
        battery = pd.read_csv(self.path + "summary_mapping/batteries.csv",index_col=0)
        battery_summary  = pd.read_csv(self.path + "generation_summary/battery_gen_summary.csv",index_col=0)
        battery_ratings = pd.read_csv(self.path + "seasonal_ratings/battery_gen_seasonal_ratings.csv")
        battery_caps = pd.read_csv(self.path + "maximum_capacity/battery_caps.csv")

        battery_caps['Max storage hours'] = battery_caps['Energy (MWh)'] / battery_caps['Installed capacity (MW)']
        battery_caps_existing = battery_caps[battery_caps['Project status']=='Existing']
        battery_caps_new = battery_caps[~(battery_caps['Project status']=='Existing')]

        year = 2025

        print("\n adding existing storage units \n")

        for _,row in battery_caps_existing.iterrows():
            
            batName = row['Storage']

            print("adding",batName)

            # fuel = battery.loc[batName,"Fuel type"]
            busName = battery_summary.loc[batName,"ISP sub-region"]
            marginalCost = battery_summary.loc[batName,"SRMC ($/MWh)"]
            retirementYear = battery_summary.loc[batName,"Expected retirement year"]
            
            units = battery_ratings[battery_ratings['Generator']==batName]

            for _,urow in units.iterrows():
                unitName = urow['DUID']
                summerTypical = urow[f'ST{year-1}-{str(year)[2:]}']

                self.n.add("StorageUnit",
                        name = batName + ' (' + unitName + ')',
                        bus  = busName,
                        carrier = "Battery Storage",
                        build_year = 2024,
                        lifetime = retirementYear - 2024,
                        marginal_cost = marginalCost,
                        p_nom = summerTypical,
                        max_hours = row['Max storage hours'])
        
        print("\n adding planned storage units \n")

        for _,row in battery_caps_new.iterrows():

            batName = row['Storage']
            
            print("adding",batName)

            # fuel = battery.loc[batName,"Fuel type"]
            busName = battery_summary.loc[batName,"ISP sub-region"]
            marginalCost = battery_summary.loc[batName,"SRMC ($/MWh)"]
            buildYear = int(row["Indicative commissioning date"][-4:])
            retirementYear = battery_summary.loc[batName,"Expected retirement year"]
            
            units = battery_ratings[battery_ratings['Generator']==batName]

            for _,urow in units.iterrows():
                unitName = urow['DUID']
                summerTypical = urow[f'ST{year-1}-{str(year)[2:]}']

                self.n.add("StorageUnit",
                        name = batName + ' (' + unitName + ')',
                        bus  = busName,
                        carrier = "Battery Storage",
                        build_year = buildYear,
                        lifetime = retirementYear - buildYear,
                        marginal_cost = marginalCost,
                        p_nom = summerTypical,
                        max_hours = row['Max storage hours'])
                
    def add_new_entrants(self,fns =["build_costs/{}_regional_build_costs_tech.csv",
                                    "new_entrants/new_entrants_summary.csv",
                                    "seasonal_ratings/new_gen_tech_seasonal_ratings.csv"]):
        # "summary_mapping/new_entrants.csv",
        '''
        add new entrants
        '''

        # read files
        # map     = pd.read_csv(self.path + fns[0],index_col=0)
        costdf = pd.read_csv(self.path + fns[0].format(self.scenario))
        summary = pd.read_csv(self.path + fns[1],index_col=0)
        ratings   = pd.read_csv(self.path + fns[2],index_col=0)

        ratings.columns = ["Hot Day","Typical Summer","Winter"]
        # max_caps = pd.read_csv(self.path + fns[3],index_col=0)

        # costs = self._get_build_costs()
        costs = self._get_build_costs_w_snapshots()


        def get_rez_trace(name,tech,traces):
            for trace in traces:
                if name in trace.replace("_"," ") and tech in trace:
                    print(trace)
                    return trace
                
        def expand_daily_to_snapshots(daily_series, snapshots):
            """
            daily_series: pd.Series indexed by date (e.g., '2024-07-01'), values = daily values
            snapshots: pd.DatetimeIndex (e.g., '2024-07-01 00:00', '2024-07-01 12:00', ...)
            Returns: pd.Series indexed by snapshots, with values from daily_series
            """
            # Ensure daily_series index is datetime.date
            daily_series.index = pd.to_datetime(daily_series.index).date
            # Map each snapshot to its date
            snapshot_dates = snapshots.date
            # Use .reindex or .map to assign daily values to each snapshot
            expanded = pd.Series(
                [daily_series.get(date, pd.NA) for date in snapshot_dates],
                index=snapshots
            )
            return expanded
                
        tdict = self.timeslice_regions
        
        for gen,row in summary.iterrows():
            print(gen)

            if "BOTN" in gen:
                continue

            if "Hydrogen" in gen:
                continue

            fuel = row["Generator type"]
            busName = row["ISP sub-region"]
            lifeTime = summary[summary["ISP sub-region"]==busName].loc[gen,"Economic life (years)"]

            if row['REZ location'] is not np.nan:
                print((gen,row["ISP sub-region"],row['REZ location']))
                genName = "_".join((gen,row["ISP sub-region"],row['REZ location'])).replace(" ","_")
                costrow = costdf[(costdf["Sub-region"]==busName) & (costdf["Technology type"]==gen) & (costdf["Candidate REZ"]==row["REZ location"])].iloc[0]
                lifeTime = summary[(summary["ISP sub-region"]==busName) & (summary["REZ location"]==row["REZ location"])].loc[gen,"Economic life (years)"]
            else:
                genName = "_".join((gen,row["ISP sub-region"])).replace(" ","_")
                costrow = costdf[(costdf["Sub-region"]==busName) & (costdf["Technology type"]==gen)].iloc[0]
            
            marginalCost = row["SRMC ($/MWh)"]
            # buildYear = int(row["Indicative commissioning date"][-4:])
            buildYear = 2025

            buildCosts = [costrow[cost_col]*1000 for cost_col in costs] # $/kW -> $/MW
            # retirementYear = row["Expected retirement year"]

            # print(lifeTime)

            # seasonal ratings

            cap_map = ratings.loc[gen]
            tslice = tdict[row["Region"]]
            capacity_t = tslice["DAY_TYPE"].map(cap_map)
            expanded = expand_daily_to_snapshots(capacity_t,self.snapshots)
            max_cap = expanded.max()

            if fuel == "Solar":

                if "PV" in gen:
                    try:
                        df = pd.read_csv(self.solarPath+get_rez_trace(row['REZ location'],"SAT",self.solarTraces))
                    except TypeError:
                        # no rez trace found
                        continue

                    print("adding",genName)

                    fuel = "Utility Solar"

                    newdf = df.set_index(["Year","Month","Day"])
                    p_max_pu_vals = newdf.loc[self.start:self.end].values.flatten()

                elif "Solar Thermal" in gen:

                    try:
                        df = pd.read_csv(self.solarPath+get_rez_trace(row['REZ location'],"CST",self.solarTraces))
                    except TypeError:
                        # no rez trace found
                        continue

                    print("adding",genName)

                    fuel = "Solar Thermal (15hrs storage)"

                    newdf = df.set_index(["Year","Month","Day"])
                    p_max_pu_vals = newdf.loc[self.start:self.end].values.flatten()
                    
                self.n.add("Generator",
                        name = genName,
                        bus  = busName,
                        carrier = fuel,
                        build_year = buildYear,
                        lifetime = lifeTime,
                        marginal_cost = 0,
                        capital_cost = buildCosts,
                        p_nom_extendable = True,
                        p_nom_max = p_max_pu_vals[::self.step] * (expanded.values / max_cap))
                
            if fuel == "Wind":
                # FIX fixed and floating 

                try:
                    df = pd.read_csv(self.windPath+get_rez_trace(row['REZ location'],"W",self.windTraces))

                except TypeError:
                    # no rez trace found
                    continue

                print("adding",genName)

                newdf = df.set_index(["Year","Month","Day"])
                p_max_pu_vals = newdf.loc[self.start:self.end].values.flatten()

                self.n.add("Generator",
                        name = genName,
                        bus  = busName,
                        carrier = fuel,
                        build_year = buildYear,
                        lifetime = lifeTime,
                        marginal_cost = 0,
                        capital_cost=buildCosts,
                        p_nom_extendable = True,
                        p_nom_max = p_max_pu_vals[::self.step] * (expanded.values / max_cap))

            if fuel == "Gas":

                self.n.add("Generator",
                    name = genName,
                    bus  = busName,
                    carrier = gen,
                    build_year = buildYear,
                    lifetime = lifeTime,
                    marginal_cost = marginalCost,
                    capital_cost= buildCosts,
                    p_nom_extendable = True,
                    p_nom_max = (expanded.values / max_cap))
                

            # add PHES build limits

            if fuel in ("Battery","Pumped Hydro"):

                self.n.add("StorageUnit",
                            name = genName,
                            bus  = busName,
                            carrier = gen,
                            build_year = buildYear,
                            lifetime = lifeTime,
                            marginal_cost = 0,
                            capital_cost= buildCosts,
                            p_nom_extendable=True,
                            max_hours = int(re.search(r"\((\d+)hr", gen).group(1))) # grab max storage hrs from name
                
            # if fuel == "Pumped Hydro":
            #     # idk
            #     self.n.add("StorageUnit",
            #                 name = genName,
            #                 bus  = busName,
            #                 carrier = gen,
            #                 build_year = buildYear,
            #                 lifetime = lifeTime,
            #                 marginal_cost = marginalCost,
            #                 p_nom_extendable=True,
            #                 max_hours = int(re.search(r"\((\d+)hr", gen).group(1)))  # grab max storage hrs from name


            
    #! creating the network !#

    def create_network(self):
        '''
        create model in one step
        '''

        # easy to debug simple network components

        self.snapshots_w_investment_periods = self.add_snapshots()

        self.carriers  = self.add_carriers()

        self.buses  = self.add_buses()

        self.load  = self.add_loads()

        self.links  = self.add_links()
        
        self.transformers = self.add_transformers()

        # create trace map before adding gens

        self._create_trace_map()

        # add existing and planned generators

        self.generators = self.add_existing_generators()

        # self._get_seasonal_columns_from_timeslice()

        self.cgenerators = self.add_committed_generators()

        self.agenerators = self.add_anticipated_generators()

        # add storage

        self.storage_units = self.add_storage_units()
        
        # add new entrants

        self.new_entrants = self.add_new_entrants()

        return self.n
    
    #! adding constraints !#
    
    def add_82pc_constraint(self):
        '''
        add 82pc constraint
        '''

        # self.n.model ....
    
    def add_constraints(self):
        '''
        create an instance of the linopy model,
        then add constraints
        '''
        self.n.optimize.create_model()

        # remove automatic link constraints first

        self.n.model.remove_constraints("Link-fix-p-upper")

        # every 5 years from 2025 from GenCost 24-25 not scaled
        emissions_budgets = [143.5656493,200.8659894,219.2252441,224.1679551,228.4645936,231.1725631]

        # every 5 years from 2025 from GenCost 24-25 scaled to AEMO budget
        emissions_budgets_scaled = [422.302025,590.8524393,644.8566561,659.3957665,672.0344386,680]

        self.n.add(
            "GlobalConstraint",
            "CO2Limit",
            carrier_attribute="co2_emissions",
            sense="<=",
            constant=150,
            investment_period=list(range(2025,2030)))

        self.add_82pc_constraint()

        # etc ...

        return self.n.model.constraints

    #! initialising linopy model !#

    def save_network(self,save_dir = "./networks/"):
        '''
        Save to file with metadata
        '''
        # if name is taken increase version number
        version_no = 1

        file_name = f"./networks/isp24_v{version_no}_{self.interval}_{self.start[0]}-{self.start[1]}-{self.start[2]}_{self.end[0]}-{self.end[1]}-{self.end[2]}.nc"

        while file_name in os.listdir(save_dir):
            version_no += 1
            file_name = f"./networks/isp24_v{version_no}_{self.interval}_{self.start[0]}-{self.start[1]}-{self.start[2]}_{self.end[0]}-{self.end[1]}-{self.end[2]}.nc"

        self.n.export_to_netcdf(save_dir + file_name)


    #! initialising linopy model !#

    def _create_network_model(self):
        '''
        create an instance of the linopy model
        '''
        self.model = self.n.optimize.create_model()

        return self.model

if __name__ == "__main__":

    ISP24MODEL = ISP24("12h",start=(2024,7,1),end=(2032,6,30),interval="6h",step=12)

    network = ISP24MODEL.create_network()

    network.export_to_netcdf("./networks/isp24_v6_6h.nc")

    # # print(network)
    # network.optimize(solver_name="gurobi",
    #                  solver_options={"LogFile": "./gurobi.log"})
    
    # network.export_to_netcdf("./networks/isp24_v5_12h_solved.nc")



