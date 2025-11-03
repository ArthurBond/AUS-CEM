import pypsa
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import xarray as xr

# need a commercial or academic license
import gurobipy as gp

from collections import defaultdict as dd
import os
import re
import glob

class ISP24LT:
    '''
    capacity expansion model for Australia based on ISP24 inputs
    '''
    #! initialising !#

    def __init__(self,network_name,start=(2024,7,1),end=(2055,6,30),interval="3h",step=6,
                 data_path="./isp_sheets_23/",trace_path="./Traces/",scenario="SC",SSLT=False,DLT=False):
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

        if SSLT==True and DLT==True:
            raise AssertionError("Cannot combine a SSLT and DLT. SSLT is recommended as a starting point. Otherwise set both to False and use the sampling method.")

        self.isSSLT = SSLT
        self.isDLT = DLT

        if self.isSSLT or self.isDLT:
            self.sampling_type = "weights"
        else:
            self.sampling_type = "interval"

        self.path = data_path
        self.trace_path = trace_path
        self.trace_path_sc = trace_path + scenario + "/"
        # self.trace_path_sc = trace_path + "SC" + "/"


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

    def add_snapshots_interval(self):
        '''
        add snapshots using start, end, interval
        add multi_investment periods
        '''
        
        if self.sampling_type == "weights":
            raise AssertionError("Cannot call add_snapshots_interval if using load blocks")

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
        self.snapshot_years = snapshots.year

        # convert to multiindex and assign to network
        self.n.set_snapshots(pd.MultiIndex.from_arrays([snapshots.year, snapshots]))
        self.n.investment_periods = years

        # cyclic_state_of_charge_per_period (investment period needs to be days?)

        # add custom cyclic constraints?

        # adds snapshots in the sampling method only

        self.weights = [self.step / 2]*len(snapshots)
        self.n.snapshot_weightings.loc[:, :] = self.step / 2

        ws = [self.weights[0]]
        for w in self.weights[1:]:
            prev = ws[-1]
            ws.append(prev + w)
        self.slicer = ws

        # self._initialise_parameters()

        return self.n.snapshots
    
    def add_carriers(self,fn = "emissions_intensity/simple_intensity.csv"):
        '''
        add carriers
        '''
        cdf = pd.read_csv(self.path + fn)
        
        for _,row in cdf.iterrows():
            self.n.add("Carrier",name=row["Generator"],co2_emissions=row["Intensity"]/1000)

        self.n.add("Carrier", "AC", co2_emissions=0.0)
        self.n.add("Carrier", "DC", co2_emissions=0.0)

        self.n.add("Carrier", "Interconnectors", co2_emissions=0.0)
        self.n.add("Carrier", "Intra-regional Links", co2_emissions=0.0)

    def add_buses(self,fn = "network_representation/subregional_ref_nodes.csv"):
        '''
        add subregions to network model
        '''
        busdf = pd.read_csv(self.path + fn)

        for _,row in busdf.iterrows():
            self.n.add("Bus",row["Bus"],carrier="AC") # v_nom=row["Voltage (kV)"],

        return self.n.buses

    def add_loads(self):
        '''
        add load profile to the network

        also adds snapshots
        '''

        # scaling_factor = 1.2 if self.scenario == "PC" else 1.1

        if self.sampling_type == "weights":
            
            if self.isDLT:
                demandpath = self.trace_path_sc + "demand_blocks/8pDaySampled/"
            if self.isSSLT:
                demandpath = self.trace_path_sc + "demand_blocks/15pWkSampled/"
            subregions = os.listdir(demandpath)

            added_snapshot = False

            for subregion in subregions:
                fn = demandpath + subregion

                if fn.endswith(".csv"):
                    df = pd.read_csv(demandpath + subregion,index_col=0)
                    df.index = pd.to_datetime(df.index)
                    df = df.loc[f"{self.start[0]}-{self.start[1]}-{self.start[2]}":f"{self.end[0]}-{self.end[1]}-{self.end[2]}"]

                    demand = df.load.values

                    if not added_snapshot:
                        print("adding snapshots")

                        self.weights = df.weight.values
                        ws = [self.weights[0]]
                        for w in self.weights[1:]:
                            prev = ws[-1]
                            ws.append(prev + w)
                        self.slicer = ws

                        # print(self.slicer)

                        snapshots = df.index
                        self.snapshots = snapshots
                        # years = list(range(self.start[0],self.end[0]+1))

                        # convert to multiindex and assign to network
                        self.n.set_snapshots(pd.MultiIndex.from_arrays([snapshots.year, snapshots]))
                        self.n.investment_periods = snapshots.year.unique() 
                        self.snapshot_years = snapshots.year

                        self.n.snapshot_weightings.loc[:, "objective"] = np.array(self.weights)
                        self.n.snapshot_weightings.loc[:, "stores"] = np.array(self.weights)
                        self.n.snapshot_weightings.loc[:, "generators"] = np.array(self.weights)

                        # self.n.snapshot_weightings.loc[:, "NSW"] = np.array(self.weights)

                        # check sum of weights is roughly 8760
                        # print(self.n.snapshot_weightings.loc[2025, "objective"].sum())

                        added_snapshot=True

                    bus = subregion.split('_')[2] # skip number _ block

                    self.n.add("Load",
                        name=f"Load_{bus}",
                        bus=bus,
                        p_set=demand) #*scaling_factor)   

        else:

            self.add_snapshots_interval()

            demandpath = self.trace_path_sc + "demand/"
            subregions = os.listdir(demandpath)

            for subregion in subregions:
                fn = demandpath + subregion

                if "NEM" in fn:
                    continue
                
                if fn.endswith(".csv"):
                    df = pd.read_csv(demandpath + subregion)
                    newdf = df.set_index(["Year","Month","Day"])
                    demand = newdf.loc[self.start:self.end].values.flatten()[::self.step]
                    bus = subregion.split('_')[0]

                    self.n.add("Load",
                        name=f"Load_{bus}",
                        bus=bus,
                        p_set=demand) #*scaling_factor)
                    
               
    def add_links(self,fns=[
        "transmission_aug/inter_regional.csv",
        "transmission_aug/intra_regional.csv"]):
        '''
        transmission infrastructure
        '''
        # inter-regional links
        interdf = pd.read_csv(self.path + fns[0],index_col=0)

        for link in interdf.index.unique():
            self.n.add("Link",
                        link,
                        p_nom=1000,
                        bus0 = interdf.loc[link,'Bus0'].values[0],
                        bus1 = interdf.loc[link,'Bus1'].values[1],
                        carrier = 'Interconnectors',
                        efficiency=0.9)

        # intra-regional links
        intradf = pd.read_csv(self.path + fns[1],index_col=0)

        for link in intradf.index.unique():
            self.n.add("Link",
                        link,
                        p_nom=1000,
                        bus0 = intradf.loc[link,'Bus0'].values[0],
                        bus1 = intradf.loc[link,'Bus1'].values[1],
                        carrier = 'Intra-regional Links',
                        efficiency=1)

                    
    def add_lines(self,fns=[
        "transmission_aug/inter_regional.csv",
        "transmission_aug/intra_regional.csv"]):
        '''
        transmission infrastructure
        '''
        # inter-regional links
        interdf = pd.read_csv(self.path + fns[0],index_col=0)

        for link in interdf.index.unique():
            self.n.add("Line",
                        link,
                        x=0.01,
                        r=0.1,
                        bus0 = interdf.loc[link,'Bus0'].values[0],
                        bus1 = interdf.loc[link,'Bus1'].values[1],
                        carrier = 'Interconnectors',
                        efficiency=0.9)

        # intra-regional links
        intradf = pd.read_csv(self.path + fns[1],index_col=0)

        for link in intradf.index.unique():
            self.n.add("Line",
                        link,
                        x=0.01,
                        r=0.1,
                        bus0 = intradf.loc[link,'Bus0'].values[0],
                        bus1 = intradf.loc[link,'Bus1'].values[1],
                        carrier = 'Intra-regional Links',
                        efficiency=1)

    def _add_links(self,fn = "network_capability/flow_path_capability.csv",outage_maintenance = pd.read_csv("./isp_sheets_23/outages/5_48pc_outages.csv",index_col=0)):
        '''
        add links without constraints
        '''
        linkdf = pd.read_csv(self.path + fn)

        # Upper and lower are defined in constraints later

        for _,row in linkdf.iterrows():

            if row['Plain Name'] == "TAS-VIC Basslink":
                outage_mask = outage_maintenance.T.iloc[-1].values

                outage_mask = self._align_outages(outage_mask)

                # placeholder efficiency if transmission loss not modelled
                self.n.add("Link",
                        row['Plain Name'],
                        bus0 = row['Bus0'],
                        bus1 = row['Bus1'],
                        carrier = 'AC',
                        p_max_pu = outage_mask,
                        efficiency=0.9)
            
            elif row["Inter-regional"]:

                # placeholder efficiency if transmission loss not modelled
                self.n.add("Link",
                        row['Plain Name'],
                        bus0 = row['Bus0'],
                        bus1 = row['Bus1'],
                        carrier = 'AC',
                        efficiency=0.9)
            else:
                self.n.add("Link",row['Plain Name'],
                        bus0 = row['Bus0'],
                        bus1 = row['Bus1'],
                        carrier = 'AC',
                        efficiency=1)

        self.n.links.loc['NNSW-SQ Terranora','carrier'] = "DC"
        self.n.links.loc['VIC-CSA Murraylink','carrier'] = "DC"
        self.n.links.loc['TAS-VIC Basslink','carrier'] = "DC"

        # link loss constraints added later

    def add_transformers(self,s_nominal=1000):
        '''
        add transformers to network model 
        '''

        # Leave transformers unconstrained

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
    
    def _extract_storage_hours(s):
        """
        Extracts the number of hours from strings like 'All Battery storage (2hrs storage)'
        Returns int or None if not found.
        """
        match = re.search(r"\((\d+)hr", s)
        if match:
            return int(match.group(1))
        return None

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
    
    def _auxiliary_load(self,fn):
        """
        additional accounting of self power consumption by generator
        """
        srs = pd.read_csv(self.path + fn)
        self.auxiliary_load = srs.to_dict()
        return self.auxiliary_load
            
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
    
    def _create_trace_map(self,fn = "summary_mapping/trace_map.csv"):
        '''
        map of generator name in IASR to trace name in ./Traces/ files 
        '''
        trace_map = pd.read_csv(self.path + fn).set_index("GenName")["TraceName"].to_dict()
     
        self.traceMap = trace_map

        return trace_map
    
    def _calculate_weighted_average(self,p_max_pu_vals,block_sizes):
        """
        p_max_pu_vals: 1D array of full-resolution values (e.g. half-hourly)
        block_sizes: list/array of block sizes (number of points in each block)
        Returns: array of weighted averages, one per block
        """
        if block_sizes is None:
            block_sizes = self.weights * 2
        block_means = []
        idx = 0
        for size in block_sizes:
            # print(size)
            vals = p_max_pu_vals[idx:idx+int(size)]
            block_means.append(np.average(vals))
            idx += int(size)
        return np.array(block_means)
    
    def _reindex(self,list_with_full_trace_snapshots):
        '''
        Grab only the indicative load days
        '''

        pass

        # the max indexed week uses peak day from 7 day moving average

        # the min takes into account solar + wind / demand

        # keep timeslices the frame

        # switch to hourly sampling (don't have to worry about weights)


    def _get_cols(self,year_range=(2024,2053)):
        '''
        get columns
        '''

        if year_range is None:
            years = list(range(self.start[0],self.end[0]+1))
            
        years = list(range(year_range[0],year_range[1]))
        
        cols = [f"{year-1}-{str(year)[-2:]}" for year in years]

        self.cols = cols

        return cols
    
    def _instances_of_years(self,fy=True):
        '''
        duplicate cols to match snapshots
        '''

        cols = self.snapshot_years

        if fy:
            return [f"{year-1}-{str(year)[-2:]}" for year in cols]
        else:
            return cols
        
    def _align_outages(self, outages):
        """
        Align outages (half-hourly resolution) to load blocks.

        outages: 1D array/list of 0/1 values, length = full resolution (e.g. half-hourly)
        self.snapshots: DatetimeIndex of block start times
        self.weights: list/array of block lengths (in hours, or half-hours if that's your convention)

        Returns: 1D numpy array, length = number of blocks, with 0 if any outage in block, else 1
        """
        # If weights are in hours, convert to half-hours
        block_sizes = np.array(self.weights)
        block_sizes = (block_sizes * 2).astype(int)  # convert hours to half-hours

        aligned = []
        idx = 0
        for size in block_sizes:
            block = outages[idx:idx+size]
            # If any 0 in block, set block to 0, else 1
            aligned.append(0 if np.any(np.array(block) == 0) else 1)
            idx += size
        return np.array(aligned)

    def add_existing_generators(self,
                                fns = ["summary_mapping/existing.csv",
                                       "generation_summary/existing_gen_summary.csv",
                                       "seasonal_ratings/existing_gen_seasonal_ratings.csv",
                                       "outages/5_48pc_outages.csv",
                                       "fuel_price/existing_fuel_price.csv",
                                       "heat_rate/heat_rate.csv",
                                       "vom/vom.csv"]):
                                    #    "aux_load/aux_load.csv"]):
        '''
        add existing generators

        files required >

            0 : summary mapping
            1 : generation summary
            2 : seasonal ratings
            3 : outages
            4 : fuel price
            5 : heat rate
            6 : vom
        '''

        # read summary files
        existing_map     = pd.read_csv(self.path + fns[0],index_col=0)
        existing_summary = pd.read_csv(self.path + fns[1],index_col=0)
        existing_units   = pd.read_csv(self.path + fns[2])

        # read outage files

        outage_maintenance = pd.read_csv(self.path + fns[3],index_col=0)

        # read thermal gen files
        fuel_price = pd.read_csv(self.path + fns[4],index_col=0)
        heat_rate = pd.read_csv(self.path + fns[5],index_col=0)
        vom = pd.read_csv(self.path + fns[6],index_col=0)
        m_cols = self._instances_of_years(fy=True)

        # print(m_cols)
        outage_pattern = 0 # to vary the outage pattern for each generator

        # get timeslice info from here
        cap_col_dict = self._get_seasonal_columns_from_timeslice()

        # ! consider adding project status as part of carrier info
        for genName in existing_units.Generator.unique():

            print("adding",genName)

            # extract useful parameters
            fuel = existing_map.loc[genName,"Fuel type"]
            busName = existing_summary.loc[genName,"ISP sub-region"]
            MLF = existing_summary.loc[genName,"MLF"]
            aux_val = 1 - existing_summary.loc[genName,"Auxiliary load (%)"]/100

            if genName in vom.index:

                VOM       = [vom.loc[genName].values[0] for _ in m_cols]
                fuelCosts = [fuel_price.loc[genName,col] for col in m_cols]
                heatRate  = [heat_rate.loc[genName].values[0] for _ in m_cols]

                marginalCost = (np.array(VOM) + np.array(fuelCosts) * np.array(heatRate)) / MLF

                # print(marginalCost)

            else:
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

                        if self.sampling_type == "weights":
                            block_sizes = (self.weights * 2).astype(int)  # if weights are in hours and data is half-hourly
                            block_means = self._calculate_weighted_average(p_max_pu_vals, block_sizes)
                            p_max_pu_vals = block_means * (capacity_t / max_cap)

                        else:
                            p_max_pu_vals = p_max_pu_vals[::self.step] * (capacity_t / max_cap)

                        self.n.add("Generator",
                            name = genName + " (" + unitName + ")",
                            bus  = busName,
                            carrier = "Existing Wind",
                            marginal_cost = 0,
                            p_nom = max_cap * aux_val,
                            p_max_pu = p_max_pu_vals,
                            build_year = 2024,
                            lifetime = retirementYear - 2024)
                        
                    elif fuel == "Solar":
                        df = pd.read_csv(self.solarPath+self._get_trace_fn(self.traceMap[genName],self.solarTraces))
                        newdf = df.set_index(["Year","Month","Day"])
                        p_max_pu_vals = newdf.loc[self.start:self.end].values.flatten()

                        if self.sampling_type == "weights":
                            block_sizes = (self.weights * 2).astype(int)  # if weights are in hours and data is half-hourly
                            block_means = self._calculate_weighted_average(p_max_pu_vals, block_sizes)
                            p_max_pu_vals = block_means * (capacity_t / max_cap)
                        else:
                            p_max_pu_vals = p_max_pu_vals[::self.step] * (capacity_t / max_cap)

                        self.n.add("Generator",
                            name = genName + " (" + unitName + ")",
                            bus  = busName,
                            carrier = "Existing Utility Solar",
                            marginal_cost = 0,
                            p_nom = max_cap * aux_val,
                            p_max_pu = p_max_pu_vals,
                            build_year = 2024,
                            lifetime = retirementYear - 2024)
                        
                    elif fuel in ["Black Coal", "Brown Coal", "Gas", "Liquid Fuel"]:

                        mask = (self.snapshot_years < retirementYear).astype(int)
                        
                        # print(mask)

                        # scheduled maintenance

                        outage_mask = outage_maintenance.T.iloc[outage_pattern % 40].values

                        if self.sampling_type == "weights":
                            outage_mask = self._align_outages(outage_mask)

                        else:
                            outage_mask = outage_maintenance.T.iloc[outage_pattern].values[:len(self.n.snapshots)*self.step:self.step]
                    
                        outage_pattern += 1

                        # print(mask)

                        # outages are forced in manually using p_max_pu
                        self.n.add("Generator",
                            name = genName + ' (' + unitName + ')',
                            bus  = busName,
                            carrier = fuel, # see simple intensity emissions_intensity/intensity.csv
                            marginal_cost = marginalCost,
                            # p_nom_min = 250,
                            p_nom = max_cap * aux_val,
                            p_min_pu = 0.35 * (capacity_t / max_cap) * outage_mask * mask,
                            p_max_pu = (capacity_t / max_cap) * outage_mask * mask,
                            build_year = 2024,
                            lifetime = retirementYear - 2024)
                    else:
                        print(unitName,"Not added in this block.")
        # print(outage_pattern)
        # return self.n.generators

    def add_CER_capacity(self,fn="aggregated_energy_storages/CER.csv"):
        '''
        CER dispatch as VPPs
        '''

        split = {
            "NSW": {
            "CNSW": 0.04543585279173149,
            "NNSW": 0.015430724709305583,
            "SNSW": 0.029682794908995665,
            "SNW": 0.24916623351284717,
            },
            "QLD": {
            "NQ": 0.0304341005471293,
            "SQ": 0.1408911803702922,
            "CQ": 0.06543059933998016,
            "GG": 0.06455285760153315,
            },
            "SA": {
            "CSA": 0.0678925796148437,
            },
            "VIC": {
            "VIC": 0.2377725015867962,
            },
            "TAS": {
            "TAS": 0.053310575016545264,
            }
        }

        df = pd.read_csv(self.path + fn,index_col=0)

        for region in split.keys():

            for subr in split[region].keys():

                capacity = df.loc[region]

                p_nom_initial = capacity["2024-25"] * split[region][subr]

                cols = self._instances_of_years()

                p_max_pu_vals = [capacity[col] for col in cols] / p_nom_initial

                self.n.add("StorageUnit",
                         name = f"CER_{subr}",
                         bus=subr,
                         carrier="CER",
                         p_nom = p_nom_initial,
                         p_min_pu = -p_max_pu_vals,
                         p_max_pu = p_max_pu_vals,
                         marginal_cost = 0,
                         max_hours=2.2,
                         cyclic_state_of_charge = True,
                         build_year = 2024)

    def _produce_inflows(self,fpath,factor):
        # Read and clean the data
        df = pd.read_csv(fpath)

        if "Day" in df.columns:
            df = df.drop(columns=["Day"]).drop_duplicates()

        # Prepare a list to collect results
        records = []

        # IMPORTANT
        # Inflows are always in hours, because the parameter is in MW
        # The amount of storage added due to inflows is then adjusted by the weight parameter (how many hours)
        for _, row in df.iterrows():
            year = int(row["Year"])
            month = int(row["Month"])
            inflow = row["Inflows"]

            # Get number of days in this month
            days_in_month = pd.Period(f"{year}-{month:02d}").days_in_month
            n_hours = days_in_month * 24

            # Calculate inflow per hour
            inflow_per_half_hour = inflow / n_hours * (1 + factor[year])

            # Generate all half-hourly timestamps for this month
            start = pd.Timestamp(year=year, month=month, day=1)
            end = start + pd.offsets.MonthEnd(0)
            half_hourly_times = pd.date_range(start, end + pd.Timedelta(hours=23, minutes=30), freq="30min")

            # Only keep times within the month (in case the range overshoots)
            half_hourly_times = half_hourly_times[half_hourly_times.month == month]

            # Add records
            for t in half_hourly_times:
                records.append({"datetime": t, "inflow": inflow_per_half_hour})

        # Create the expanded DataFrame
        expanded_df = pd.DataFrame(records)

        # Optional: set datetime as index
        expanded_df = expanded_df.set_index("datetime")

        return expanded_df

    def _sampling_index_from_weightings(self):
        """
        Given a list/array/Series of snapshot weightings (in hours),
        return an array of indices to sample from a full-resolution (half-hourly) time series.
        Starts at 0, then adds each weighting * 2 (since 2 half-hours per hour).

        Example usage:
        snapshot_weightings = [1, 6, 2.5, 3]  # hours
        idx = sampling_index_from_weightings(snapshot_weightings)
        print(idx)  # [0, 2, 14, 19]
        """
        indices = [0]
        for w in self.n.snapshot_weightings:
            indices.append(indices[-1] + int(round(w * 2)))
        return np.array(indices[:-1])  # Exclude the last index (end of last block)

    def _hydro_climate_factor(self,region,years):
        """
        apply climate factor
        """
        # Grab climate factor
        fn = f"hydro_inflow/{self.scenario}_climate_factor.csv"

        df = pd.read_csv(self.path + fn)
        # Melt to long format
        df_long = df.melt(id_vars="Region", var_name="Year", value_name="Factor")
        # Filter for region
        df_long = df_long[df_long["Region"] == region].copy()
        # Convert '2023-24' to 2024, etc.
        df_long["Year"] = df_long["Year"].str.extract(r"(\d{4})").astype(int)
        # Convert '-3.0%' to -0.03
        df_long["Factor"] = df_long["Factor"].str.replace("%", "").astype(float) / 100
        # Map to year
        factor_map = dict(zip(df_long["Year"], df_long["Factor"]))
        # Build factor list for all years (default 0 if missing)

        return pd.Series(factor_map)
        

    def add_hydro_units(self, fns=["hydro/storageUnits.csv",
                                   "hydro/generators.csv"]):
        
        su = pd.read_csv(self.path + fns[0])
        gen = pd.read_csv(self.path + fns[1])
        tas_factor = self._hydro_climate_factor(region="Tasmania",
                                            years=list(range(self.start[0],self.end[0])))
        snowy_factor = self._hydro_climate_factor(region="South QLD / NSW / VIC",
                                            years=list(range(self.start[0],self.end[0])))
    
        hydro_map = dd(list)
        for f in os.listdir(self.trace_path_sc + "hydro/"):
                if "Anthony" in f:
                    hydro_map['Anthony'].append(self._produce_inflows(self.trace_path_sc + "hydro/" + f,tas_factor).inflow.values)
                
                if "Derwent" in f or "Tarraleah" in f or "Tungatinah" in f:
                    hydro_map['Derwent'].append(self._produce_inflows(self.trace_path_sc + "hydro/" + f,tas_factor).inflow.values)

                if "MF" in f:
                    hydro_map['Mersey Forth'].append(self._produce_inflows(self.trace_path_sc + "hydro/" + f,tas_factor).inflow.values)

                if f == "Snowy_natural_inflows.csv":
                    hydro_map['Snowy'].append(self._produce_inflows(self.trace_path_sc + "hydro/" + f,snowy_factor).inflow.values)

        for _,row in su.iterrows():

            inflows = np.sum(hydro_map[row["Hydro Group"]],axis=0)

            # indexed at every hour hence i*2 and forgot to convert to MWh so multiply by 1e3
            inflow = [inflows[int(i*2)]*1000 for i in self.slicer] # should be sliced using weights pos and multiplied 

            self.n.add("StorageUnit",
                    name = row["Hydro Group"],
                    bus="SNSW" if row["Hydro Group"] == "Snowy" else "TAS",
                    p_nom = row["Discharge capacity"],
                    carrier = "Existing Hydro",
                    p_min_pu = 0, # force it to dispatch more
                    max_hours = row["Storage (GWh)"] / (row["Discharge capacity"]/1e3),
                    state_of_charge_initial = row["Storage (GWh)"]/2*1e3, # random choice (MWh)
                    marginal_cost = 8.58,
                    cyclic_state_of_charge = False,
                    cyclic_state_of_charge_per_period = False,
                    inflow = inflow,
                    build_year = 2024)
        # gen should be done in existing
        for _,row in gen.iterrows():
            
            self.n.add("Generator",
                       name = row["Hydro Group"],
                       bus = row["Bus"],
                       carrier = "Existing Hydro",
                       p_nom = row["Group Capacity"],
                       marginal_cost = 8.58,
                       build_year = 2024)
                       
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
                        if self.sampling_type == "weights":
                            block_sizes = (self.weights * 2).astype(int)  # if weights are in hours and data is half-hourly
                            block_means = self._calculate_weighted_average(p_max_pu_vals, block_sizes)
                            p_max_pu_vals = block_means * (capacity_t / max_cap)
                        else:
                            p_max_pu_vals = p_max_pu_vals[::self.step] * (capacity_t / max_cap)
                        self.n.add("Generator",
                            name = genName + " (" + unitName + ")",
                            bus  = busName,
                            carrier = "Planned Wind",
                            marginal_cost = marginalCost,
                            p_nom = max_cap,
                            p_max_pu = p_max_pu_vals,
                            build_year = buildYear,
                            lifetime = retirementYear - 2024)
                    elif fuel == "Solar":
                        df = pd.read_csv(self.solarPath+self._get_trace_fn(self.traceMap[genName],self.solarTraces))
                        newdf = df.set_index(["Year","Month","Day"])
                        p_max_pu_vals = newdf.loc[self.start:self.end].values.flatten()
                        if self.sampling_type == "weights":
                            block_sizes = (self.weights * 2).astype(int)  # if weights are in hours and data is half-hourly
                            block_means = self._calculate_weighted_average(p_max_pu_vals, block_sizes)
                            p_max_pu_vals = block_means * (capacity_t / max_cap)
                        else:
                            p_max_pu_vals = p_max_pu_vals[::self.step] * (capacity_t / max_cap)
                        self.n.add("Generator",
                            name = genName + " (" + unitName + ")",
                            bus  = busName,
                            carrier = "Planned Utility Solar",
                            marginal_cost = marginalCost,
                            p_nom = max_cap,
                            p_max_pu = p_max_pu_vals,
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
                            lifetime = retirementYear - 2024,
                            cyclic_state_of_charge=True)
                    elif fuel in ["Gas", "Liquid Fuel"]:

                        # outages are forced in manually using p_max_pu
                        self.n.add("Generator",
                            name = genName + ' (' + unitName + ')',
                            bus  = busName,
                            carrier = fuel, # see emissions_intensity/intensity.csv
                            marginal_cost = marginalCost,
                            p_nom = max_cap,
                            p_max_pu = (capacity_t / max_cap),
                            build_year = buildYear,
                            lifetime = retirementYear - 2024)
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
                        if self.sampling_type == "weights":
                            block_sizes = (self.weights * 2).astype(int)  # if weights are in hours and data is half-hourly
                            block_means = self._calculate_weighted_average(p_max_pu_vals, block_sizes)
                            p_max_pu_vals = block_means * (capacity_t / max_cap)
                        else:
                            p_max_pu_vals = p_max_pu_vals[::self.step] * (capacity_t / max_cap)
                        self.n.add("Generator",
                            name = genName + " (" + unitName + ")",
                            bus  = busName,
                            carrier = "Planned Wind",
                            marginal_cost = marginalCost,
                            p_nom = max_cap,
                            p_max_pu = p_max_pu_vals,
                            build_year = buildYear,
                            lifetime = retirementYear - 2024)
                    elif fuel == "Solar":
                        df = pd.read_csv(self.solarPath+self._get_trace_fn(self.traceMap[genName],self.solarTraces))
                        newdf = df.set_index(["Year","Month","Day"])
                        p_max_pu_vals = newdf.loc[self.start:self.end].values.flatten()
                        if self.sampling_type == "weights":
                            block_sizes = (self.weights * 2).astype(int)  # if weights are in hours and data is half-hourly
                            block_means = self._calculate_weighted_average(p_max_pu_vals, block_sizes)
                            p_max_pu_vals = block_means * (capacity_t / max_cap)
                        else:
                            p_max_pu_vals = p_max_pu_vals[::self.step] * (capacity_t / max_cap)
                        self.n.add("Generator",
                            name = genName + " (" + unitName + ")",
                            bus  = busName,
                            carrier = "Planned Utility Solar",
                            marginal_cost = marginalCost,
                            p_nom = max_cap,
                            p_max_pu = p_max_pu_vals,
                            build_year = buildYear,
                            lifetime = retirementYear - 2024)
                    elif fuel == "Water":
                        self.n.add("StorageUnit",
                            name = genName + " (" + unitName + ")",
                            bus  = busName,
                            carrier = "Pumped Hydro (24hrs storage)",
                            marginal_cost = marginalCost,
                            p_nom = max_cap,
                            p_max_pu = capacity_t / max_cap,
                            build_year = buildYear,
                            lifetime = retirementYear - 2024,
                            cyclic_state_of_charge=True)
                    elif fuel in ["Black Coal", "Brown Coal", "Gas", "Liquid Fuel"]:
                        
                        self.n.add("Generator",
                            name = genName + ' (' + unitName + ')',
                            bus  = busName,
                            carrier = genName, # see emissions_intensity/intensity.csv
                            marginal_cost = marginalCost,
                            p_nom = max_cap,
                            p_max_pu = (capacity_t / max_cap),
                            build_year = buildYear,
                            lifetime = retirementYear - 2024)
                    else:
                        print("Not added")
                        print(genName)
                        

        # return self.n.generators

    def add_additional_projects(self,fns = ["summary_mapping/additional_projects.csv",
                                       "generation_summary/additional_gen_summary.csv",
                                       "seasonal_ratings/additional_gen_seasonal_ratings.csv",
                                       "maximum_capacity/additional_gen_caps.csv"]):
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
                        if self.sampling_type == "weights":
                            block_sizes = (self.weights * 2).astype(int)  # if weights are in hours and data is half-hourly
                            block_means = self._calculate_weighted_average(p_max_pu_vals, block_sizes)
                            p_max_pu_vals = block_means * (capacity_t / max_cap)
                        else:
                            p_max_pu_vals = p_max_pu_vals[::self.step] * (capacity_t / max_cap)
                        self.n.add("Generator",
                            name = genName + " (" + unitName + ")",
                            bus  = busName,
                            carrier = "Planned Wind",
                            marginal_cost = marginalCost,
                            p_nom = max_cap,
                            p_max_pu = p_max_pu_vals,
                            build_year = buildYear,
                            lifetime = retirementYear - 2024)
                    elif fuel == "Solar":
                        df = pd.read_csv(self.solarPath+self._get_trace_fn(self.traceMap[genName],self.solarTraces))
                        newdf = df.set_index(["Year","Month","Day"])
                        p_max_pu_vals = newdf.loc[self.start:self.end].values.flatten()
                        if self.sampling_type == "weights":
                            block_sizes = (self.weights * 2).astype(int)  # if weights are in hours and data is half-hourly
                            block_means = self._calculate_weighted_average(p_max_pu_vals, block_sizes)
                            p_max_pu_vals = block_means * (capacity_t / max_cap)
                        else:
                            p_max_pu_vals = p_max_pu_vals[::self.step] * (capacity_t / max_cap)
                        self.n.add("Generator",
                            name = genName + " (" + unitName + ")",
                            bus  = busName,
                            carrier = "Planned Utility Solar",
                            marginal_cost = marginalCost,
                            p_nom = max_cap,
                            p_max_pu = p_max_pu_vals,
                            build_year = buildYear,
                            lifetime = retirementYear - 2024)
                    elif fuel == "Water":
                        self.n.add("StorageUnit",
                            name = genName + " (" + unitName + ")",
                            bus  = busName,
                            carrier = "Pumped Hydro",
                            marginal_cost = marginalCost,
                            p_nom = max_cap,
                            p_max_pu = capacity_t / max_cap,
                            build_year = 2024,
                            lifetime = retirementYear - 2024,
                            cyclic_state_of_charge=True)
                    elif fuel == "Battery Storage":
                    
                        # outages are forced in manually using p_max_pu
                        self.n.add("StorageUnit",
                            name = genName + ' (' + unitName + ')',
                            bus  = busName,
                            carrier = genName, # see emissions_intensity/intensity.csv
                            marginal_cost = marginalCost,
                            p_nom = max_cap,
                            p_max_pu = (capacity_t / max_cap),
                            max_hours = self._extract_storage_hours(map.loc[genName,"Forced outage rate - Partial outage (% of time) Until 2022"]), # Extract from forced outage ,Forced outage rate - Partial outage (% of time) Until 2022
                            build_year = buildYear,
                            lifetime = retirementYear - 2024,
                            cyclic_state_of_charge=True)
                    else:
                        print(genName)
                        print("Something else")

    def add_storage_units(self):
        '''
        adding storage units
        force units to be zero until starting month for indicative commisioning date
        '''
        # battery = pd.read_csv(self.path + "summary_mapping/batteries.csv",index_col=0)
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
                        max_hours = row['Max storage hours'],
                        cyclic_state_of_charge=True)
        
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
                        max_hours = row['Max storage hours'],
                        cyclic_state_of_charge=True)
                
    def add_new_entrants(self,fns =["build_costs/{}_regional_build_costs_tech.csv",
                                    "new_entrants/new_entrants_summary.csv",
                                    "seasonal_ratings/new_gen_tech_seasonal_ratings.csv",
                                    "REZ/rez_summary.csv"]):
        # "summary_mapping/new_entrants.csv",
        '''
        add new entrants
        '''

        # read files
        # map     = pd.read_csv(self.path + fns[0],index_col=0)
        costdf = pd.read_csv(self.path + fns[0].format(self.scenario))
        summary = pd.read_csv(self.path + fns[1],index_col=0)
        ratings   = pd.read_csv(self.path + fns[2],index_col=0)
        rez_summary = pd.read_csv(self.path + fns[3],index_col=1)

        ratings.columns = ["Hot Day","Typical Summer","Winter"]
        # max_caps = pd.read_csv(self.path + fns[3],index_col=0)
         
        # cols = self._instances_of_years(fy=True)

        def get_rez_trace(name,tech,traces):
            for trace in traces:
                if name.upper() in trace.replace("_"," ").upper() and tech in trace:
                    # print(name,trace)
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

        rezMap = rez_summary['ID'].to_dict()

        # print(rezMap)

        self.rez_id_map = rezMap

        rez_gen_map = dd(list)
        
        for gen,row in summary.iterrows():

            if "Hydrogen" in gen:
                continue

            fuel = row["Generator type"]
            busName = row["ISP sub-region"]
            # lifeTime = summary[summary["ISP sub-region"]==busName].loc[gen,"Economic life (years)"]

            # if not (costdf["Technology type"]==gen).any():
            #     continue


            if row['REZ location'] is not np.nan:
                print(busName,gen,row['REZ location'])

                genName = "_".join((gen,row["ISP sub-region"],row['REZ location'])).replace(" ","_")
                costrow = costdf[(costdf["Sub-region"]==busName) & (costdf["Technology type"]==gen) & (costdf["Candidate REZ"]==row["REZ location"])].iloc[0]
                # lifeTime = summary[(summary["ISP sub-region"]==busName) & (summary["REZ location"]==row["REZ location"])].loc[gen,"Economic life (years)"]
            else:
                genName = "_".join((gen,row["ISP sub-region"])).replace(" ","_")
                try:
                    costrow = costdf[(costdf["Sub-region"]==busName) & (costdf["Technology type"]==gen)].iloc[0]
                except IndexError:
                    continue

            marginalCost = row["SRMC ($/MWh)"]
            # buildYear = int(row["Indicative commissioning date"][-4:])
            buildYear = 2025

            # buildCosts = [costrow[cost_col]*1000 for cost_col in cols] # $/kW -> $/MW
            # don't bother modelling retirement

            # print(buildCosts[:10])
            # buildCosts = 5e5

            lifeTime = 1

            cap_map = ratings.loc[gen]
            tslice = tdict[row["Region"]]
            capacity_t = tslice["DAY_TYPE"].map(cap_map)
            expanded = expand_daily_to_snapshots(capacity_t,self.snapshots).values
            max_cap = expanded.max()

            genNameOriginal = genName

            for year in self.n.investment_periods:

                genName = genNameOriginal

                genName += f"_{year}"

                # print(year,genName)

                mask = self.n.snapshots.get_level_values(0) >= year

                pmaxmask = np.where(mask, 1, 0)

                if year < buildYear:
                    # print(genName)
                    continue
            
                buildCosts = costrow[f"{year-1}-{str(year)[-2:]}"] * 1000 # $/kW -> $/MW

                if fuel == "Solar" or fuel == "Utility Solar" or fuel == "Solar Thermal (15hrs storage)":
                
                    if "PV" in genName:

                        try:
                            if "Non-REZ" in row["REZ location"]:
                                if year < 2035:
                                    continue
                                if "NSW" in row["REZ location"]:
                                    df = pd.read_csv(self.solarPath+get_rez_trace("NSW_Non-REZ","SAT",self.solarTraces))
                                if "VIC" in row["REZ location"]:
                                    df = pd.read_csv(self.solarPath+get_rez_trace("VIC_Non-REZ","SAT",self.solarTraces))
                                # print(row["REZ location"])
                                buildCosts = 1e6
                                buildYear = 2026
                            else:
                                df = pd.read_csv(self.solarPath+get_rez_trace(row['REZ location'],"SAT",self.solarTraces))
                        except TypeError:
                            # no rez trace found
                            print("no trace found for",genName,row['REZ location'])
                            continue

                        print("adding",genName)

                        fuel = "Utility Solar"

                        newdf = df.set_index(["Year","Month","Day"])
                        p_max_pu_vals = newdf.loc[self.start:self.end].values.flatten()
                        if self.sampling_type == "weights":
                            block_sizes = (self.weights * 2).astype(int)  # if weights are in hours and data is half-hourly
                            block_means = self._calculate_weighted_average(p_max_pu_vals, block_sizes)
                            p_max_pu_vals = (block_means * (expanded / max_cap))
                        else:
                            p_max_pu_vals = p_max_pu_vals[::self.step] * (expanded / max_cap)

                        rez_gen_map[row['REZ location']].append(genName) 

                        # print(year)

                        self.n.add("Generator",
                            name = genName,
                            bus  = busName,
                            carrier = fuel,
                            build_year = year,
                            lifetime = lifeTime,
                            marginal_cost = 0,
                            capital_cost = buildCosts,
                            p_nom_extendable = True,
                            p_min_pu = 0.7 * p_max_pu_vals* pmaxmask,
                            p_max_pu = p_max_pu_vals * pmaxmask)

                    elif "Solar Thermal" in gen:

                        try:
                            if "Non-REZ" in row["REZ location"]:
                                # print(genName,"WHY")
                                if year < 2035:
                                    continue
                                if "NSW" in row["REZ location"]:
                                    df = pd.read_csv(self.solarPath+get_rez_trace("NSW_Non-REZ","CST",self.solarTraces))
                                if "VIC" in row["REZ location"]:
                                    df = pd.read_csv(self.solarPath+get_rez_trace("VIC_Non-REZ","CST",self.solarTraces))
                                # print(row["REZ location"])
                                buildCosts = 1e6
                                buildYear = 2026
                            else:
                                df = pd.read_csv(self.solarPath+get_rez_trace(row['REZ location'],"CST",self.solarTraces))
                        except TypeError:
                            # no rez trace found
                            print("no trace found for",genName,row['REZ location'])
                            continue

                        print("adding",genName)

                        fuel = "Solar Thermal (15hrs storage)"

                        newdf = df.set_index(["Year","Month","Day"])
                        p_max_pu_vals = newdf.loc[self.start:self.end].values.flatten()
                        if self.sampling_type == "weights":
                            block_sizes = (self.weights * 2).astype(int)  # if weights are in hours and data is half-hourly
                            block_means = self._calculate_weighted_average(p_max_pu_vals, block_sizes)
                            p_max_pu_vals = (block_means * (expanded / max_cap))
                        else:
                            p_max_pu_vals = p_max_pu_vals[::self.step] * (expanded / max_cap)

                        rez_gen_map[row['REZ location']].append(genName) 

                        # print(year)

                        self.n.add("Generator",
                                name = genName,
                                bus  = busName,
                                carrier = fuel,
                                build_year = year,
                                lifetime = lifeTime,
                                marginal_cost = 0,
                                capital_cost = buildCosts,
                                p_nom_extendable = True,
                                p_min_pu = 0.7 * p_max_pu_vals* pmaxmask,
                                p_max_pu = p_max_pu_vals * pmaxmask)
                    
                if (fuel == "Wind") and (year > 2026):

                    suffix = "_WH"
                
                    try:
                        if "Non-REZ" in row["REZ location"]:
                            if year < 2035:
                                    continue
                            if "NSW" in row["REZ location"]:
                                df = pd.read_csv(self.solarPath+get_rez_trace("NSW_Non-REZ","WH",self.solarTraces))
                            if "VIC" in row["REZ location"]:
                                df = pd.read_csv(self.solarPath+get_rez_trace("VIC_Non-REZ","WH",self.solarTraces))
                            # print(row["REZ location"])
                            buildCosts = 1e6
                            buildYear = 2026
                        else:
                            try:
                                df = pd.read_csv(self.windPath+get_rez_trace(row['REZ location'],"WH",self.windTraces))
                            except TypeError:
                                try:
                                    suffix = "_WFL"
                                    df = pd.read_csv(self.windPath+get_rez_trace(row['REZ location'],"WFL",self.windTraces))
                                except TypeError:
                                    suffix = "_WFX"
                                    df = pd.read_csv(self.windPath+get_rez_trace(row['REZ location'],"WFX",self.windTraces))
                                if year < 2035:
                                    continue
                    except TypeError:
                        # no rez trace found
                        print("no trace found for",genName,row['REZ location'])
                        continue
                    
                    genName += suffix
                    
                    print("adding",genName)

                    rez_gen_map[row['REZ location']].append(genName) 

                    newdf = df.set_index(["Year","Month","Day"])
                    p_max_pu_vals = newdf.loc[self.start:self.end].values.flatten()
                    if self.sampling_type == "weights":
                        block_sizes = (self.weights * 2).astype(int)  # if weights are in hours and data is half-hourly
                        block_means = self._calculate_weighted_average(p_max_pu_vals, block_sizes)
                        p_max_pu_vals = (block_means * (expanded / max_cap))
                    else:
                        p_max_pu_vals = p_max_pu_vals[::self.step] * (expanded / max_cap) 

                    self.n.add("Generator",
                            name = genName,
                            bus  = busName,
                            carrier = fuel,
                            build_year = year,
                            lifetime = lifeTime,
                            marginal_cost = 0,
                            capital_cost=buildCosts,
                            p_nom_extendable = True,
                            p_min_pu = 0.7 * p_max_pu_vals * pmaxmask,
                            p_max_pu = p_max_pu_vals * pmaxmask)
                    
                    if "WFL" in suffix or "WFX" in suffix:
                        continue
                    
                    suffix = "_WM"
                    try:
                        if "Non-REZ" in row["REZ location"]:
                            if year < 2035:
                                    continue
                            if "NSW" in row["REZ location"]:
                                df = pd.read_csv(self.solarPath+get_rez_trace("NSW_Non-REZ","WM",self.solarTraces))
                            if "VIC" in row["REZ location"]:
                                df = pd.read_csv(self.solarPath+get_rez_trace("VIC_Non-REZ","WM",self.solarTraces))
                            # print(row["REZ location"])
                            buildCosts = 1e6
                            buildYear = 2026

                        else:
                            try:
                                df = pd.read_csv(self.windPath+get_rez_trace(row['REZ location'],"WM",self.windTraces))
                            except TypeError:
                                try:
                                    suffix = "_WFL"
                                    df = pd.read_csv(self.windPath+get_rez_trace(row['REZ location'],"WFL",self.windTraces))
                                except TypeError:
                                    suffix = "_WFX"
                                    df = pd.read_csv(self.windPath+get_rez_trace(row['REZ location'],"WFX",self.windTraces))

                    except TypeError:
                        # no rez trace found
                        print("no trace found for",genName,row['REZ location'])
                        continue

                    genName = genName[:-3] + suffix

                    print("adding",genName)

                    rez_gen_map[row['REZ location']].append(genName) 

                    newdf = df.set_index(["Year","Month","Day"])
                    p_max_pu_vals = newdf.loc[self.start:self.end].values.flatten()
                    if self.sampling_type == "weights":
                        block_sizes = (self.weights * 2).astype(int)  # if weights are in hours and data is half-hourly
                        block_means = self._calculate_weighted_average(p_max_pu_vals, block_sizes)
                        p_max_pu_vals = (block_means * (expanded / max_cap))
                    else:
                        p_max_pu_vals = p_max_pu_vals[::self.step] * (expanded / max_cap)

                    self.n.add("Generator",
                            name = genName,
                            bus  = busName,
                            carrier = fuel,
                            build_year = year,
                            lifetime = lifeTime,
                            marginal_cost = 0,
                            capital_cost=buildCosts,
                            p_nom_extendable = True,
                            p_min_pu = 0.7 * p_max_pu_vals* pmaxmask,
                            p_max_pu = p_max_pu_vals* pmaxmask)

                if (fuel == "Gas") and (year > 2026):
                    print("adding",genName)
                    self.n.add("Generator",
                        name = genName,
                        bus  = busName,
                        carrier = gen,
                        build_year = year,
                        lifetime = lifeTime,
                        marginal_cost = marginalCost,
                        capital_cost= buildCosts,
                        p_min_pu = 0.46 * (expanded / max_cap) * pmaxmask,
                        p_nom_extendable = True,
                        p_max_pu = (expanded / max_cap) * pmaxmask)
                    
                # add PHES build limits

                if fuel == "Battery":

                    print("adding",genName)
                    
                    storage_hours = int(re.search(r"\((\d+)hr", gen).group(1))

                    self.n.add("StorageUnit",
                                name = genName,
                                bus  = busName,
                                carrier = gen,
                                build_year = year,
                                # lifetime = lifeTime,
                                marginal_cost = 0,
                                capital_cost= buildCosts,
                                p_min_pu = -pmaxmask, # * (storage_hours/8),
                                p_max_pu = pmaxmask,  # * (storage_hours/8),
                                p_nom_extendable=True,
                                cyclic_state_of_charge=True,
                                max_hours = storage_hours) # *8
                                # grab max storage hrs from name 

                    if pd.notna(row['REZ location']): 
                            rezID = rezMap[row['REZ location']]
                            if (storage_hours==2 or storage_hours==8) & (rezID =="N2" or rezID=="T3"):
                                rez_gen_map[row['REZ location']].append(genName)
                    
                if (fuel == "Water") and (year > 2030): 
                    # print(row['REZ location'])
                    if "BOTN" in gen:
                        storage_hours = 20
                    else:
                        storage_hours = int(re.search(r"\((\d+)hr", gen).group(1))

                    self.n.add("StorageUnit",
                            name = genName,
                            bus  = busName,
                            carrier = gen,
                            build_year = year,
                            lifetime = lifeTime,
                            marginal_cost = 0,
                            capital_cost= buildCosts,
                            p_min_pu = -pmaxmask,
                            p_max_pu = pmaxmask,
                            p_nom_extendable=True,
                            cyclic_state_of_charge=True,
                            max_hours = storage_hours) # grab max storage hrs from name
                        
        self.rez_gen_map = rez_gen_map
        

        # print(self.rez_gen_map)

    def add_rez_variables(self,fns=["REZ_augmentation/rez_initial.csv",
        "REZ_augmentation/rez_single_aug_max.csv",
        "REZ_augmentation/rez_single_aug_min.csv",
        "REZ_augmentation/rez_single_aug_costs.csv",
        "REZ_augmentation/soft_and_hard_limits.csv"]):

        # read limit files

        initial_limit = pd.read_csv(self.path + fns[0],index_col=1)
        aug_max = pd.read_csv(self.path  + fns[1],index_col=0)
        aug_min = pd.read_csv(self.path  + fns[2],index_col=0)
        aug_cost = pd.read_csv(self.path  + fns[3],index_col=0)

        soft_hard_limit = pd.read_csv(self.path  + fns[4])

        rezIDmap = soft_hard_limit.set_index("REZ Name")['REZ ID'].to_dict()

        # new entrants
        rez_gen_map = self.rez_gen_map

        for _,row in soft_hard_limit.iterrows():

            name = row['REZ Name']

            rezID = rezIDmap[name]

            # pattern1 = ""
            # pattern2 = ""
            pattern3 = ""

            # if name in rez_to_gens.keys():
            #     pattern1 = "|".join([re.escape(p) for p in rez_to_gens[name]])
            
            # if name in rez_to_storage.keys():
            #     pattern2 = "|".join([re.escape(p) for p in rez_to_storage[name]])

            if name in rez_gen_map.keys():
                pattern3 = "|".join([re.escape(p) for p in rez_gen_map[name]])

            # Suppose you have a list of patterns, e.g.:
            # patterns = [pattern1, pattern2, pattern3]
            patterns = [pattern3]

            # To join them with "|" but avoid leading/trailing "|":
            pattern_str = "|".join([p for p in patterns if p])

            # print(pattern_str)

            rez_gens = self.n.generators[self.n.generators.index.str.contains(pattern_str,regex=True)].index.to_list()

            WH = [rez_gen for rez_gen in rez_gens if '_WH' in rez_gen]
            WM = [rez_gen for rez_gen in rez_gens if '_WM' in rez_gen]
            SAT = [rez_gen for rez_gen in rez_gens if 'Large_scale_Solar_PV' in rez_gen]

            # print(WH,WM,SAT)

            if len(WH) > 0:

                # print("\n\n\nADDED HERE\n\n\n\n")

                self.n.add("Generator",
                           name = f"{rezID}_WH_PENALTY",
                           bus = "TAS",
                           carrier = "Penalty",
                           capital_cost = 1e6 * (row['Resource penalty'] + row['Transmission expansion penalty']),
                           build_year = 0, 
                           lifeTime=1,
                           p_nom_extendable=True)
                
                # print("added")
                
                # Try changing this to a p_nom_extendable generator and set the generation to zero I guess?

            if len(WM) > 0:

                self.n.add("Generator",
                           name = f"{rezID}_WM_PENALTY",
                           bus = "TAS",
                           carrier = "Penalty",
                           capital_cost = 1e6 * (row['Resource penalty'] + row['Transmission expansion penalty']),
                           build_year = 0,
                           lifeTime=1,
                           p_nom_extendable=True)

            if len(SAT) > 0:
                self.n.add("Generator",
                           name = f"{rezID}_SAT_PENALTY",
                           bus = "TAS",
                           carrier = "Penalty",
                           capital_cost = 1e6 * (row['Resource penalty'] + row['Transmission expansion penalty']),
                           build_year = 0,
                           lifeTime=1,
                           p_nom_extendable=True)

        
            if rezID in initial_limit.index:

                aug_cost_t = aug_cost[aug_cost["ID"]==rezID]

                for aname,arow in aug_cost_t.iterrows():

                    date_to = pd.to_datetime(arow["Date To"],dayfirst=True,errors="coerce")

                    # start_timestamp = pd.Timestamp(year=self.start[0], month=self.start[1], day=self.start[2])
                    # end_timestamp = pd.Timestamp(year=self.end[0], month=self.end[1], day=self.end[2])

                    # if date_from > end_timestamp or date_from < start_timestamp:
                    #     continue

                    if date_to.year in self.n.investment_periods:

                    # print(date_from)

                        date_from = pd.to_datetime(arow["Date From"],dayfirst=True,errors="coerce")

                        if aname in aug_min.index:

                            amin = aug_min.loc[aname,"Min"]

                        else:

                            amin = 0

                        if pd.to_datetime(aug_max.loc[aname,"Date From"]) > date_from:
                            continue

                        amax = aug_max.loc[aname,"Max"]

                        # AUG_VAR = m.add_variables(lower = amin, upper = amax, name = f"{aname}-{date_from.year}-{date_to.year}")#, coords=REZ_p_VAR[:,0].coords)
                        self.n.add(
                            "Generator",
                            bus = "TAS",
                            carrier = "Augmentation",
                            name = f"{aname}-{date_from.year}-{date_to.year}",
                            p_nom_min = amin,
                            p_nom_max = amax,
                            p_nom_extendable=True,
                            capital_cost = arow["Build Cost"] * 1000,
                            build_year = 0, # should be generationless
                            lifeTime = 1
                        )

                        print("REZ VAR ADDED",f"{aname}-{date_from.year}-{date_to.year}")

    #! creating the network !#

    def add_PHES_build_limits(self):

        m = self.n.model

        build_limits = {
                # Format: (subregion, storage_hours): limit
                ("NNSW", 8): 1275,
                ("NNSW", 24): 500,
                ("NNSW", 48): 500,
                ("CNSW", 8): 1750,
                ("CNSW", 24): 235,
                ("CNSW", 48): 83,
                ("SNSW", 8): 2500,
                ("SNSW", 24): 583,
                ("SNSW", 48): 167,
                ("SNW", 8): 0,
                ("SNW", 24): 0,
                ("SNW", 48): 0,
                ("NQ", 8): 1250,
                ("NQ", 24): 278,
                ("NQ", 48): 111,
                ("CQ", 8): 1000,
                ("CQ", 24): 5000,
                ("CQ", 48): 89,
                ("GG", 8): 0,
                ("GG", 24): 0,
                ("GG", 48): 0,
                ("SQ", 8): 1750,
                ("SQ", 24): 0,
                ("SQ", 48): 300,
                ("VIC", 8): 2700,
                ("VIC", 24): 700,
                ("VIC", 48): 400,
                ("CSA", 8): 698,
                ("CSA", 24): 200,
                ("CSA", 48): 0,
                ("SESA", 8): 0,
                ("SESA", 24): 0,
                ("SESA", 48): 0,
                ("TAS", 8): 1625,
                ("TAS", 24): 1200,
                ("TAS", 48): 371,
            }
        # Define build limits for each ISP sub region and storage type

        for (subregion, hours), limit in build_limits.items():
            # Find all Pumped Hydro StorageUnits in the subregion with the specified hours
            storage_mask = self.n.storage_units.index.str.startswith(
                f"Pumped_Hydro_({hours}hrs_storage)_{subregion}"
            )
            ph_storage_units = self.n.storage_units.index[storage_mask]
            if len(ph_storage_units) > 0:
                ph_vars = m.variables["StorageUnit-p_nom"].loc[ph_storage_units]
                m.add_constraints(
                    ph_vars.sum() <= limit,
                    name=f"{subregion}_PH_{hours}hr_build_limit"
                )

        # Constraint BOTN_-_Cethana in TAS to 750 MW
        botn_mask = self.n.storage_units.index.str.startswith("BOTN")
        botn_gens = self.n.storage_units.index[botn_mask]
        if len(botn_gens) > 0:
            botn_vars = m.variables["StorageUnit-p_nom"].loc[botn_gens]
            m.add_constraints(
                botn_vars.sum() <= 750,
                name="BOTN_Cethana_TAS_build_limit"
            )

    def add_battery_storage_constraint(self):
        '''
        hard coded for 2030
        '''
        m = self.n.model

        # Find all battery generators by subregion and storage hours
        for subregion in self.n.buses.index:
            for hours in [1, 2, 4, 8]:
                if hours == 1:
                    pattern = f"Battery_Storage_({hours}hr_storage)_{subregion}"
                else:
                    pattern = f"Battery_Storage_({hours}hrs_storage)_{subregion}"
                bat_gens = self.n.storage_units.index[self.n.storage_units.index.str.startswith(pattern)]
                if len(bat_gens) > 0:
                    bat_vars = m.variables["StorageUnit-p_nom"].loc[bat_gens]
                    m.add_constraints(
                    bat_vars.sum() <= 10000,
                    name=f"{subregion}_Battery_{hours}hr_build_limit"
                    )

    def add_hydro_min_storage_constraint(self):
        '''
        Hydro reservoir cannot go below 30% generation capacity
        '''

        m = self.n.model

        hydro_units = self.n.storage_units[self.n.storage_units['carrier'] == "Existing Hydro"].index

        for h in hydro_units:
            # p_nom = self.n.storage_units.loc[h, "p_nom"]
            # max_hours = self.n.storage_units.loc[h, "max_hours"]

            init_soc = self.n.storage_units.loc[h,"state_of_charge_initial"]
            soc_vars = m.variables['StorageUnit-state_of_charge'].loc[:, h]
            
            m.add_constraints(
                soc_vars >= 0.3 * 2 * init_soc, #p_nom * max_hours,
                name=f"Hydro-Min-Storage-{h}"
            )

    def add_federal_targets(self,fn="rooftop_PV/rooftop_PV_energy.csv"):

        # Federal renewable capacity share targets by year (from 2024 to 2030)
        # federal_targets = [0.43, 0.50, 0.56, 0.63, 0.69, 0.76, 0.82]
        # target_years = list(range(2024, 2024 + len(federal_targets)))

        # no idea why net zero target not working

        federal_targets = []

        if self.scenario == "SC":

            federal_targets = [0.56,0.82,0.83,0.85,0.9,0.95] # SC

        elif self.scenario == "PC":
        
            federal_targets = [0.56,0.7,0.75,0.82,0.85,0.9] # PC

        # target_years = list(range(2030, 2030 + len(federal_targets)))

        target_years = (2026,2030,2035,2040,2045,2050)

        # print(target_years)

        pv_regions = pd.read_csv(self.path + fn,index_col=0)

        # Map target years to correct columns in pv_regions
        pv_columns = [f"{year-1}-{str(year)[-2:]}" for year in target_years]
        pv_targets = pv_regions[pv_columns].sum().values  # Sum across regions for each year

        m = self.n.model

        # Define renewable carriers to exclude from thermal
        renewable_carriers = ["Existing Wind", "Existing Utility Solar", "Wind", "Utility Solar", "Planned Wind",
                              "Planned Utility Solar",
                              "Solar Thermal (15hrs storage)", "Existing Hydro", "Biomass"]

        # storage doesn't count so no CER or Battery Storage etc

        for i, target_year in enumerate(target_years):

            if target_year not in self.n.investment_periods:
                continue

            pv_target = pv_targets[target_years.index(target_year)]

            # Get snapshots for the target year
            snapshots = self.n.snapshots[self.n.snapshots.get_level_values(0) == target_year]

            # Identify renewable generators
            renewable_gens = self.n.generators[self.n.generators.carrier.isin(renewable_carriers)].index

            # Identify thermal generators (everything else)
            thermal_gens = self.n.generators[~self.n.generators.carrier.isin(renewable_carriers)].index

            # Get variables for renewable and thermal generation in the target year
            renewable_gen = m.variables["Generator-p"].loc[snapshots, renewable_gens]
            thermal_gen = m.variables["Generator-p"].loc[snapshots, thermal_gens]

            # Get StorageUnit dispatch for hydro units
            hydro_units = ["Snowy", "Derwent", "Mersey Forth", "Anthony"]
            existing_hydro_dispatch = m.variables["StorageUnit-p_dispatch"].loc[snapshots, hydro_units]

            # Get all pumped hydro StorageUnits (names start with 'BOTN' or 'Pumped_')
            pumped_hydro_units = [name for name in self.n.storage_units.index if name.startswith("BOTN") or name.startswith("Pumped_")]
            pumped_hydro_dispatch = m.variables["StorageUnit-p_dispatch"].loc[snapshots, pumped_hydro_units]

            # Get all pumped hydro StorageUnits (names start with 'BOTN' or 'Pumped_')
            battery_units = [name for name in self.n.storage_units.index if name.startswith("Battery_") or name.startswith("CER_")]
            battery_dispatch = m.variables["StorageUnit-p_dispatch"].loc[snapshots, battery_units]

            # Get snapshot weightings for the target year
            weights = self.n.snapshot_weightings.loc[snapshots, "generators"]

            # print(renewable_gen)

            # Constraint: weighted renewable share + rooftop PV <= thermal generation
            # Compute weighted sum for each generator, then sum across generators
            thermal_gen_weighted = (thermal_gen * weights).sum()
            renewable_gen_weighted = (renewable_gen * weights).sum()
            existing_hydro_dispatch_weighted = (existing_hydro_dispatch * weights).sum()
            pumped_hydro_dispatch_weighted = (pumped_hydro_dispatch * weights).sum()
            battery_dispatch_weighted = (battery_dispatch * weights).sum()

            m.add_constraints(
                thermal_gen_weighted <= (renewable_gen_weighted + existing_hydro_dispatch_weighted + pumped_hydro_dispatch_weighted + battery_dispatch_weighted + pv_target/1000) * (1-federal_targets[i]),
                name=f"Renewable_Share_Limit_{target_year}"
            )

    def add_carbon_budget_constraint(self):

        # stupid implementation
        target_years = (2024,2026,2030,2035,2040,2045,2050)

        emit_limit = []
        if self.scenario == "SC":
            emit_limit = [140.5, 134.6, 128.8, 111.5, 91.7, 71.9, 52.2]
        elif self.scenario == "PC":
            emit_limit = [160.5, 154.6, 148.8, 131.5, 111.7, 91.9, 72.2]

        for i,year in enumerate(target_years):

            if year not in self.n.investment_periods:
                continue

            self.n.add(
                    "GlobalConstraint",
                    name=f"CO2Budget_{year}",
                    carrier_attribute="co2_emissions",
                    sense="<=",
                    constant=emit_limit[i], # in Mega tonnes
                    investment_period=year
                )

    def create_network(self):
        '''
        create model in one step
        '''

        # easy to debug simple network components

        # self.snapshots_w_investment_periods = self.add_snapshots_interval()

        print("Adding Carriers...")

        self.carriers  = self.add_carriers()

        print("...Finished with Carriers")

        print("Adding Buses...")

        self.buses  = self.add_buses()

        print("...Finished with Buses")

        print("Adding Loads...")

        self.load  = self.add_loads()

        print("...Finished with Loads")

        print("Adding Links...")

        self.links  = self.add_links()
        # self.links  = self.add_lines()

        print("...Finished with Links")

        # print("Adding Transformers...")
        
        # self.transformers = self.add_transformers()

        # print("...Finished with Transformers")

        # create trace map before adding gens

        print("Creating Trace Map...")

        self._create_trace_map()

        print("...Finished with Trace Map")

        # add existing and planned generators

        print("Adding CER...")

        self.add_CER_capacity()

        print("...Finished with CER")

        print("Adding Existing Generators...")

        self.generators = self.add_existing_generators()

        print("...Finished with Existing Generators")

        print("Adding Hydro Units...")

        self.hydro_units = self.add_hydro_units()

        print("...Finished with Hydro Units")

        self._get_seasonal_columns_from_timeslice()

        self.add_committed_generators()

        self.add_anticipated_generators()

        # add storage
        self.add_storage_units()
        
        # add new entrants
        self.add_new_entrants()
        
        # add rez variables
        self.add_rez_variables()
        
        # add constraints
        print("Creating model...")
        self.n.optimize.create_model()
        print("...Finished creating model")

        # hydro max energy constraint
        print("Adding Hydro Constraints...")
        self.add_hydro_constraints()
        self.add_hydro_min_storage_constraint()
        print("...Finished adding Hydro Constraints")

        # transmission flow constraint
        print("Adding Transmission Constraints...")
        self.add_transmission_constraints()
        print("...Finished adding Transmission Constraints")

        # rez limit constraint
        print("Adding REZ Constraints...")
        self.add_rez_constraints()
        # self._add_rez_constraints()
        print("...Finished adding REZ Constraints")

        # carbon budget constraint
        print("Adding Carbon Budget Constraints...")
        self.add_carbon_budget_constraint()
        print("...Finished adding Carbon Budget Constraints")

        # carbon PHES and Battery Storage Build Limit
        print("Adding PHES and Battery Storage Build Limit Constraints...")
        self.add_PHES_build_limits()
        # self.add_battery_storage_constraint()
        print("...Finished adding PHES and Battery Storage Build Limit Constraints")

        # add 82pc constraint
        # self.add_82pc_constraint()
        print("Adding federal 82 pc target Constraints...")
        self.add_federal_targets()
        print("...Finished adding federal 82 pc target Constraints...")

        # TEST / IMPROVE

        # print("Adding transmission losses")
        # self.transmission_losses()
        # print("...Finished adding transmission losses")

        # add limits for solar and wind and pumped hydro build in 2040 to 2050 to 10, 8, 5 GW
        # try adding policy constraints maybe ? 

        # run PC scenarios

        # done

        # model becomes infeasible if coal and gas generation is 0.4 p_min_pu

        return self.n
    
    def create_network_without_constraints(self):
        
        print("Adding Carriers...")

        self.carriers  = self.add_carriers()

        print("...Finished with Carriers")

        print("Adding Buses...")

        self.buses  = self.add_buses()

        print("...Finished with Buses")

        print("Adding Loads...")

        self.load  = self.add_loads()

        print("...Finished with Loads")

        print("Adding Links...")

        self.links  = self.add_links()
        # self.links  = self.add_lines()

        print("...Finished with Links")

        print("Adding Transformers...")
        
        self.transformers = self.add_transformers()

        print("...Finished with Transformers")

        # create trace map before adding gens

        print("Creating Trace Map...")

        self._create_trace_map()

        print("...Finished with Trace Map")

        # add existing and planned generators

        print("Adding CER...")

        self.add_CER_capacity()

        print("...Finished with CER")

        print("Adding Existing Generators...")

        self.generators = self.add_existing_generators()

        print("...Finished with Existing Generators")

        print("Adding Hydro Units...")

        self.hydro_units = self.add_hydro_units()

        print("...Finished with Hydro Units")

        self._get_seasonal_columns_from_timeslice()

        self.cgenerators = self.add_committed_generators()

        self.agenerators = self.add_anticipated_generators()

        # add storage
        self.storage_units = self.add_storage_units()
        
        # add new entrants
        self.new_entrants = self.add_new_entrants()
        
        # add rez variables
        self.add_rez_variables()
    
    def add_gas_constraints(self):

        m = self.n.model

        # Find all gas generators (carrier contains 'Gas')
        gas_gens = self.n.generators[self.n.generators.carrier.str.contains("OCGT (small GT)|OCGT (large GT)|CCGT|CCGT with CCS")].index

        for year in self.n.investment_periods:
            gas_vars = m.variables["Generator-p_nom"].loc[gas_gens]
            # Only constrain new builds in this year
            build_mask = self.n.generators.build_year == year
            gas_gens_year = self.n.generators.index[build_mask & self.n.generators.carrier.str.contains("Gas")]
            if len(gas_gens_year) > 0:
                gas_vars_year = m.variables["Generator-p_nom"].loc[gas_gens_year]

                print(gas_vars_year)
                m.add_constraints(
                    gas_vars_year.sum() <= 1000,
                    name=f"Gas_Build_Limit_{year}"
                )

    #! adding constraints !#

    def add_hydro_constraints(self):

        m = self.n.model

        hydro_max_energy = pd.read_csv(self.trace_path_sc + "hydro/MaxEnergyYear_LT_RefYear4006_StepChange.csv",index_col=0)
        hydro_max_energy.columns = hydro_max_energy.columns.str.replace(" Constraint","").str.replace("HT ","").str.replace(" Storage","").str.replace("-","/")

        hydro = self.n.generators[self.n.generators['carrier']=="Existing Hydro"].index

        for h in hydro:
            for yr in self.n.investment_periods:
                h_p_group = m.variables['Generator-p'].loc[yr,h]
                # weighted generation to give MWh
                lhs = self.n.snapshot_weightings.loc[:,"generators"].loc[yr] * h_p_group
                rhs = hydro_max_energy.loc[yr,h]

                m.add_constraints(lhs<=rhs,name = f"Hydro-Max-Energy-{h.replace(" ","-")}-{yr}")

    def _get_region_mapping(self,fn="./Traces/timeslice_RefYear4006.csv"):
        # Load timeslice file
        df = pd.read_csv(fn, parse_dates=["DATETIME"], dayfirst=True)

        # Sort by NAME then DATETIME
        df = df.sort_values(["NAME", "DATETIME"]).reset_index(drop=True)

        # Build periods per NAME
        ranges = {}
        for name, group in df.groupby("NAME"):
            group = group.sort_values("DATETIME").reset_index(drop=True)
            start=pd.to_datetime('2024-07-01')
            periods = []
            for _, row in group.iterrows():
                if row["TIMESLICE"] == -1:
                    start = row["DATETIME"]
                elif row["TIMESLICE"] == 0:
                    end = row["DATETIME"]
                    periods.append((start, end))
            ranges[name] = periods

        # Now map to snapshots in the PyPSA model
        snapshots = self.n.snapshots.get_level_values(1)  # all model datetimes
        region_mapping = {}

        for name, periods in ranges.items():
            all_snaps = []
            for start, end in periods:
                mask = (snapshots >= start) & (snapshots <= end)
                all_snaps.extend(self.n.snapshots[mask]) # to capture multiindex
            region_mapping[name] = pd.Index(all_snaps)

        return region_mapping

    def add_transmission_constraints(self,fns=[
        "transmission_aug/inter_regional.csv",
        "transmission_aug/intra_regional.csv"]):
        '''
        add transmission constraints
        '''

        m = self.n.model

        interdf = pd.read_csv(self.path + fns[0],index_col=0)
        intradf = pd.read_csv(self.path + fns[1],index_col=0)

        # m.remove_constraints("Line-fix-s-lower")
        # m.remove_constraints("Line-fix-s-upper")

        m.remove_constraints("Link-fix-p-lower")
        m.remove_constraints("Link-fix-p-upper")

        region_day_type = self._get_region_mapping()

        for link,row in interdf.iterrows():

            dates = region_day_type[row['Day Type']]

            from_date = pd.to_datetime(row["Date From"],dayfirst=True,errors="coerce")

            # if from_date.year > self.end[0]:# or from_date.year < self.start[0]:
            #     continue

            to_date = pd.to_datetime(row["Date To"],dayfirst=True,errors="coerce")

            mask = (dates >= (from_date.year,from_date)) & (dates < (to_date.year,to_date))

            cap_dates = dates[mask]

            # link_vars = m.variables['Line-s'].loc[cap_dates,link]
            link_vars = m.variables['Link-p'].loc[cap_dates,link]

            if link_vars.size > 0:

                if row["Max or Min"] == "Max Flow":

                    m.add_constraints(link_vars <= row["Capability"],name=f"{link}-{from_date}-{to_date}-{row['Day Type']}-max")

                if row["Max or Min"] == "Min Flow":

                    m.add_constraints(-link_vars <= -1*row["Capability"],name=f"{link}-{from_date}-{to_date}-{row['Day Type']}-min")

                # print(link_vars) -x = 450 

        for link,row in intradf.iterrows():

            dates = region_day_type[row['Day Type']]

            from_date = pd.to_datetime(row["Date From"],dayfirst=True,errors="coerce")

            # if from_date.year > self.end[0]:# or from_date.year < self.start[0]:
            #     continue

            to_date = pd.to_datetime(row["Date To"],dayfirst=True,errors="coerce")

            mask = (dates >= (from_date.year,from_date)) & (dates < (to_date.year,to_date))

            cap_dates = dates[mask]

            # link_vars = m.variables['Line-s'].loc[cap_dates,link]
            link_vars = m.variables['Link-p'].loc[cap_dates,link]

            if link_vars.size > 0:

                if row["Max or Min"] == "Max Flow":

                    m.add_constraints(link_vars <= row["Capability"],name=f"{link}-{from_date}-{to_date}-{row['Day Type']}-max")

                if row["Max or Min"] == "Min Flow":

                    m.add_constraints(-link_vars <= -1*row["Capability"],name=f"{link}-{from_date}-{to_date}-{row['Day Type']}-min")

                # print(link_vars)

    def add_rez_constraints(self,fns=["REZ_augmentation/rez_initial.csv",
        "REZ_augmentation/rez_single_aug_max.csv",
        "REZ_augmentation/rez_single_aug_min.csv",
        "REZ_augmentation/rez_single_aug_costs.csv",
        "REZ_augmentation/soft_and_hard_limits.csv"]):

        m = self.n.model

        initial_limit = pd.read_csv(self.path + fns[0],index_col=1)
        aug_max = pd.read_csv(self.path  + fns[1],index_col=0)
        # aug_min = pd.read_csv(self.path  + fns[2],index_col=0)
        aug_cost = pd.read_csv(self.path  + fns[3],index_col=0)

        soft_hard_limit = pd.read_csv(self.path  + fns[4])

        rezIDmap = soft_hard_limit.set_index("REZ Name")['REZ ID'].to_dict()

        rez_gen_map = self.rez_gen_map

        nonRezGenMap = {}
        for key in ['New South Wales Non-REZ', 'Victoria Non-REZ']:
            nonRezGenMap[key] = rez_gen_map.pop(key)

        for key in nonRezGenMap.keys():

            wind = [w for w in nonRezGenMap[key] if "Wind" in w]

            solar = [s for s in nonRezGenMap[key] if "Solar" in s]

            # PENALTY = 1e6 # already put as build cost
            
            wind_var = m.variables['Generator-p_nom'].loc[wind]

            solar_var = m.variables['Generator-p_nom'].loc[solar]

            if "Victoria" in key:

                m.add_constraints(
                    wind_var.sum() <= 291, name = "Victoria Non-REZ Wind Hard Limit"
                )

                m.add_constraints(
                    solar_var.sum() <= 699, name = "Victoria Non-REZ Solar Hard Limit"
                )

            if "New South Wales" in key:

                m.add_constraints(
                    wind_var.sum() <= 699, name = "New South Wales Non-REZ Wind Hard Limit"
                )

                m.add_constraints(
                    solar_var.sum() <= 1679, name = "New South Wales Non-REZ Solar Hard Limit"
                )

        snaps = self.n.snapshots

        for _,row in soft_hard_limit.iterrows():

            name = row['REZ Name']

            rezID = rezIDmap[name]

            pattern3 = ""

            if name in rez_gen_map.keys():
                pattern3 = "|".join([re.escape(p) for p in rez_gen_map[name]])

            patterns = [pattern3]

            # To join them with "|" but avoid leading/trailing "|":
            pattern_str = "|".join([p for p in patterns if p])

            # print(pattern_str)

            rez_gens = self.n.generators[self.n.generators.index.str.contains(pattern_str,regex=True)].index.to_list()
            
            # print(rez_gens)

            WH = m.variables['Generator-p_nom'].loc[[rez_gen for rez_gen in rez_gens if '_WH' in rez_gen]]
            WM = m.variables['Generator-p_nom'].loc[[rez_gen for rez_gen in rez_gens if '_WM' in rez_gen]]
            WFX = m.variables['Generator-p_nom'].loc[[rez_gen for rez_gen in rez_gens if '_WFX' in rez_gen]]
            WFL = m.variables['Generator-p_nom'].loc[[rez_gen for rez_gen in rez_gens if '_WFL' in rez_gen]]

            SAT = m.variables['Generator-p_nom'].loc[[rez_gen for rez_gen in rez_gens if 'Large_scale_Solar_PV' in rez_gen]]
            CST = m.variables['Generator-p_nom'].loc[[rez_gen for rez_gen in rez_gens if 'Solar_Thermal' in rez_gen]]

            wind_group = []
            solar_group = []

            if WH.size > 0:

                # print(WH)
                # trick so that network saves
                WH_PENALTY = m.variables['Generator-p_nom'].loc[f"{rezID}_WH_PENALTY"]
                # Try changing this to a p_nom_extendable generator and set the generation to zero I guess?
                # print(WH_PENALTY)

                m.add_constraints(
                    WH.sum() <= row['WH'] + WH_PENALTY, name = f"{rezID}-WH-soft_limit"
                )

                WH_PENALTY_GENERATION = m.variables['Generator-p'].loc[:,f"{rezID}_WH_PENALTY"]

                m.add_constraints(
                    WH_PENALTY_GENERATION <= 0, name = f"{rezID}-WH-no-penalty-generation"
                )

                wind_group.append(WH.sum())

            if WM.size > 0:
                WM_PENALTY = m.variables['Generator-p_nom'].loc[f"{rezID}_WM_PENALTY"]

                m.add_constraints(
                    WM.sum() <= row['WM'] + WM_PENALTY, name = f"{rezID}-WM-soft_limit"
                )

                WM_PENALTY_GENERATION = m.variables['Generator-p'].loc[:,f"{rezID}_WM_PENALTY"]

                m.add_constraints(
                    WM_PENALTY_GENERATION <= 0, name = f"{rezID}-WM-no-penalty-generation"
                )

                wind_group.append(WM.sum())

            if WFX.size > 0:

                m.add_constraints(
                    WFX.sum() <= row['WFX'], name = f"{rezID}-WFX-hard_limit"
                )

            if WFL.size > 0:

                m.add_constraints(
                    WFL.sum() <= row['WFL'], name = f"{rezID}-WFL-hard_limit"
                )

            if SAT.size > 0:

                SAT_PENALTY = m.variables['Generator-p_nom'].loc[f"{rezID}_SAT_PENALTY"]

                m.add_constraints(
                    SAT.sum() <= row['SAT'] + SAT_PENALTY, name = f"{rezID}-SAT-soft_limit"
                )

                SAT_PENALTY_GENERATION = m.variables['Generator-p'].loc[:,f"{rezID}_SAT_PENALTY"]

                m.add_constraints(
                    SAT_PENALTY_GENERATION <= 0, name = f"{rezID}-SAT-no-penalty-generation"
                )

                solar_group.append(SAT.sum())

                if CST.size > 0:
                    solar_group.append(CST.sum())

            if wind_group:
                # + rezCapWind[name] <- no, new only
                m.add_constraints(
                    sum(wind_group) <= row["Wind Hard Limit"], name = f"{rezID}-Wind-hard_limit"
                )

            if solar_group:
                # + rezCapSolar[name] <- no, new only
                m.add_constraints(
                    sum(solar_group) <= row["Solar Hard Limit"], name = f"{rezID}-Solar-hard_limit"
                )

            # print(initial_limit.index)

            if rezID in initial_limit.index:

                # print(rezID)

                # REZ_VAR = m.variables['Generator-p_nom'].loc[rez_gens]

                INITIAL = initial_limit.loc[rezID,"Limit"]

                # implement day type slicing
                val = initial_limit.loc[rezID, "Day Type"]

                if (pd.notna(val).any() if hasattr(val, "__iter__") and not isinstance(val, str)
                    else pd.notna(val)):
                    # print("True")
                    # print(INITIAL)

                    INITIAL = initial_limit.loc[rezID,"Limit"].iloc[0]

                aug_cost_ts = aug_cost[aug_cost["ID"]==rezID]

                # REZ_p_nom_VAR_all_years = m.variables['Generator-p_nom'].loc[rez_gens] 

                # anames = aug_cost_ts.index.unique()

                # for unique_name in anames:

                #     aug_cost_t = aug_cost_ts.loc[unique_name]

                #     print(aug_cost_t)
                
                for year in self.n.investment_periods:

                    # print(year,rezID)

                    AUG_VARS = []

                    REZ_VARS = []

                    # print(aug_cost_ts["Date To"])
                    # print(pd.to_datetime(aug_cost_ts["Date To"],dayfirst=True).dt.year)

                    aug_cost_t = aug_cost_ts[pd.to_datetime(aug_cost_ts["Date To"],dayfirst=True,errors="coerce").dt.year == year]

                    rez_gens_year = [rez_gen for rez_gen in rez_gens if str(year) in rez_gen]

                    # print(rez_gens_year)

                    REZ_p_nom_VAR = m.variables['Generator-p_nom'].loc[rez_gens_year] 

                    REZ_VARS.append(REZ_p_nom_VAR.sum())

                    # print(REZ_VARS)

                    # get all aug vars in this year
                    for aname,arow in aug_cost_t.iterrows():

                        # print(aname)

                        date_to = pd.to_datetime(arow["Date To"],dayfirst=True,errors="coerce")

                        # start_timestamp = pd.Timestamp(year=self.start[0], month=self.start[1], day=self.start[2])
                        # end_timestamp = pd.Timestamp(year=self.end[0], month=self.end[1], day=self.end[2])

                        # if date_from > end_timestamp or date_from < start_timestamp:
                        #     continue

                        # if date_to.year in self.n.investment_periods:

                            # print(date_from)
                        date_from = pd.to_datetime(arow["Date From"],dayfirst=True,errors="coerce")

                        # if there isn't enough lead time, constrain by the initial limit only
                        if pd.to_datetime(aug_max.loc[aname,"Date From"]) <= date_from:

                            # REZ vars are by year which is why the one constraint works
                            AUG_VAR = m.variables["Generator-p_nom"].loc[f"{aname}-{date_from.year}-{date_to.year}"]

                            AUG_VARS.append(AUG_VAR)

                        # else:

                            try:
                                print("Adding no aug generation constraint!")

                                AUG_GENERATION = m.variables['Generator-p'].loc[:,f"{aname}-{date_from.year}-{date_to.year}"]

                                m.add_constraints(
                                    AUG_GENERATION <= 0, name = f"{aname}-{date_from.year}-{date_to.year}-no-augmentation-generation"
                                )

                            except ValueError:
                                print("Already added")

                    print(year,AUG_VARS)

                    if AUG_VARS==[]:
                        print("Initial REZ Limit")
                        print(aname,INITIAL)

                        # summed bc individually constrained already
                        m.add_constraints(
                            sum(REZ_VARS) <= INITIAL, name = f"Single-REZ-Limit-{rezID}-{year-1}-{year}"
                        )

                    else:
                        print("Adding REZ Limit")
                        print(aname,INITIAL,AUG_VARS)
                        
                        # # REZ vars are by year which is why the one constraint works
                        # AUG_VAR = m.variables["Generator-p_nom"].loc[f"{aname}-{date_from.year}-{date_to.year}"]

                        # AUG_VARS.append(AUG_VAR)
                        
                        # rez var years are constrained by respective augmentation years in monotonically increasing fashion
                        m.add_constraints(
                            sum(REZ_VARS) <= INITIAL + sum(AUG_VARS), name = f"Single-REZ-Limit-{rezID}-{year-1}-{year}"
                        )

                        # AUG_GENERATION = m.variables['Generator-p'].loc[:,f"{aname}-{year-1}-{year}"]

                        # m.add_constraints(
                        #     AUG_GENERATION <= 0, name = f"{aname}-{year-1}-{year}-no-augmentation-generation"
                        # )
            # else:
            #     # may not need bc resource limits modelled and group constraints ignored
            #     m.add_constraints(
            #         REZ_p_nom_VAR_all_years.sum() <= 10000, name = f"Single-REZ-Default-Limit"
            #     )
                # print(REZ_VARS)

                # print(AUG_VARS)

    def add_rez_gen_constraints(self):#,fn = "REZ_augmentation/soft_and_hard_limits.csv"):

        '''
        Generators cannot 
        '''

        m = self.n.model


        for year in self.n.investment_periods:
            mask = (
                    self.n.generators.index.str.contains(str(year)) &
                    ~self.n.generators.index.str.contains("augmentation|option|penalty", case=False)
                    )
            gens = self.n.generators[mask]

            snapshots_mask = (self.n.snapshots.get_level_values(1).year >= year)

            snaps = self.n.snapshots[snapshots_mask]

            REZ_GENS = m.variables['Generator-p'].loc[snaps,gens]

            m.add_constraints(
                REZ_GENS <= 0, f"Zero-REZ-gen-limit-{year}"
            )


    def add_hydro_gen_constraints(self):
        '''
        Hydro can't store energy
        '''
        pass

    def _add_rez_constraints(self,fns=["REZ_augmentation/rez_initial.csv",
        "REZ_augmentation/rez_single_aug_max.csv",
        "REZ_augmentation/rez_single_aug_min.csv",
        "REZ_augmentation/rez_single_aug_costs.csv",
        "REZ_augmentation/soft_and_hard_limits.csv"]):

        m = self.n.model

        # read limit files

        initial_limit = pd.read_csv(self.path + fns[0],index_col=1)
        aug_max = pd.read_csv(self.path  + fns[1],index_col=0)
        aug_min = pd.read_csv(self.path  + fns[2],index_col=0)
        aug_cost = pd.read_csv(self.path  + fns[3],index_col=0)

        soft_hard_limit = pd.read_csv(self.path  + fns[4])

        rezIDmap = soft_hard_limit.set_index("REZ Name")['REZ ID'].to_dict()

        # new entrants
        rez_gen_map = self.rez_gen_map
        nonRezGenMap = {}
        for key in ['New South Wales Non-REZ', 'Victoria Non-REZ']:
            nonRezGenMap[key] = rez_gen_map.pop(key)

        # Get solar and wind rezs
        
        # rezGenMap = gens[~gens['REZ location'].isna()]['REZ location'].to_dict()

        # rezCapSolar = dd(float)
        # rezCapWind = dd(float)

        # for key in rezGenMap.keys():

        #     # print(rezGenMapDF.at[key,"Fuel type"])

        #     if gens.at[key,"Fuel type"] == "Solar":

        #         rezCapSolar[rezGenMap[key]] += maxs.at[key,"Installed capacity (MW)"] 

        #     if gens.at[key,"Fuel type"] == "Wind":

        #         rezCapWind[rezGenMap[key]] += maxs.at[key,"Installed capacity (MW)"] 

        # Constraint Non-REZ

        for key in nonRezGenMap.keys():

            wind = [w for w in nonRezGenMap[key] if "Wind" in w]

            solar = [s for s in nonRezGenMap[key] if "Solar" in s]

            # PENALTY = 1e6 # already put as build cost
            
            wind_var = m.variables['Generator-p_nom'].loc[wind]

            solar_var = m.variables['Generator-p_nom'].loc[solar]

            if "Victoria" in key:

                m.add_constraints(
                    wind_var.sum() <= 291, name = "Victoria Non-REZ Wind Hard Limit"
                )

                m.add_constraints(
                    solar_var.sum() <= 699, name = "Victoria Non-REZ Solar Hard Limit"
                )

            if "New South Wales" in key:

                m.add_constraints(
                    wind_var.sum() <= 699, name = "New South Wales Non-REZ Wind Hard Limit"
                )

                m.add_constraints(
                    solar_var.sum() <= 1679, name = "New South Wales Non-REZ Solar Hard Limit"
                )

        snaps = self.n.snapshots

        for _,row in soft_hard_limit.iterrows():

            name = row['REZ Name']

            rezID = rezIDmap[name]

            # pattern1 = ""
            # pattern2 = ""
            pattern3 = ""

            # if name in rez_to_gens.keys():
            #     pattern1 = "|".join([re.escape(p) for p in rez_to_gens[name]])
            
            # if name in rez_to_storage.keys():
            #     pattern2 = "|".join([re.escape(p) for p in rez_to_storage[name]])

            if name in rez_gen_map.keys():
                pattern3 = "|".join([re.escape(p) for p in rez_gen_map[name]])

            # Suppose you have a list of patterns, e.g.:
            # patterns = [pattern1, pattern2, pattern3]
            patterns = [pattern3]

            # To join them with "|" but avoid leading/trailing "|":
            pattern_str = "|".join([p for p in patterns if p])

            # print(pattern_str)

            rez_gens = self.n.generators[self.n.generators.index.str.contains(pattern_str,regex=True)].index.to_list()

            WH = m.variables['Generator-p_nom'].loc[[rez_gen for rez_gen in rez_gens if '_WH' in rez_gen]]
            WM = m.variables['Generator-p_nom'].loc[[rez_gen for rez_gen in rez_gens if '_WM' in rez_gen]]
            WFX = m.variables['Generator-p_nom'].loc[[rez_gen for rez_gen in rez_gens if '_WFX' in rez_gen]]
            WFL = m.variables['Generator-p_nom'].loc[[rez_gen for rez_gen in rez_gens if '_WFL' in rez_gen]]

            SAT = m.variables['Generator-p_nom'].loc[[rez_gen for rez_gen in rez_gens if 'Large_scale_Solar_PV' in rez_gen]]
            CST = m.variables['Generator-p_nom'].loc[[rez_gen for rez_gen in rez_gens if 'Solar_Thermal' in rez_gen]]

            wind_group = []
            solar_group = []

            if WH.size > 0:
                # coords trick so that network saves
                WH_PENALTY = m.add_variables(lower=0,name=f"{rezID}-WH-penalty") #,coords=WH[:1].coords)

                # Try changing this to a p_nom_extendable generator and set the generation to zero I guess?

                m.add_constraints(
                    WH.sum() <= row['WH'] + WH_PENALTY, name = f"{rezID}-WH-soft_limit"
                )

                m.objective += 1e6 * (row['Resource penalty'] + row['Transmission expansion penalty']) * WH_PENALTY

                wind_group.append(WH.sum())

            if WM.size > 0:
                WM_PENALTY = m.add_variables(lower=0,name=f"{rezID}-WM-penalty") #,coords=WM[:1].coords)

                m.add_constraints(
                    WM.sum() <= row['WM'] + WM_PENALTY, name = f"{rezID}-WM-soft_limit"
                )

                m.objective += 1e6 * (row['Resource penalty'] + row['Transmission expansion penalty']) * WM_PENALTY

                wind_group.append(WM.sum())

            if WFX.size > 0:
                # WFX_PENALTY = m.add_variables(lower=0,name=f"{rezID}-WFX-penalty")

                m.add_constraints(
                    WFX.sum() <= row['WFX'], name = f"{rezID}-WFX-hard_limit"
                )

                # m.objective += 1000 * (row['Resource penalty'] + row['Transmission expansion penalty']) * WFX_PENALTY

                # wind_group.append(WFX.sum())

            if WFL.size > 0:
                # WFL_PENALTY = m.add_variables(lower=0,name=f"{rezID}-WFL-penalty")

                m.add_constraints(
                    WFL.sum() <= row['WFL'], name = f"{rezID}-WFL-hard_limit"
                )

                # m.objective += 1000 * (row['Resource penalty'] + row['Transmission expansion penalty']) * WFL_PENALTY

                # wind_group.append(WFL.sum())

            if SAT.size > 0:
                SAT_PENALTY = m.add_variables(lower=0,name=f"{rezID}-SAT-penalty") #,coords=SAT[:1].coords)

                m.add_constraints(
                    SAT.sum() <= row['SAT'] + SAT_PENALTY, name = f"{rezID}-SAT-soft_limit"
                )

                m.objective += 1e6 * (row['Resource penalty'] + row['Transmission expansion penalty']) * SAT_PENALTY

                solar_group.append(SAT.sum())

                if CST.size > 0:
                    solar_group.append(CST.sum())

            if wind_group:
                # + rezCapWind[name]
                m.add_constraints(
                    sum(wind_group) <= row["Wind Hard Limit"], name = f"{rezID}-Wind-hard_limit"
                )

            if solar_group:
                # + rezCapSolar[name]
                m.add_constraints(
                    sum(solar_group) <= row["Solar Hard Limit"], name = f"{rezID}-Solar-hard_limit"
                )

            if rezID in initial_limit.index:

                # REZ_VAR = m.variables['Generator-p_nom'].loc[rez_gens]

                INITIAL = initial_limit.loc[rezID,"Limit"]

                # implement day type slicing
                val = initial_limit.loc[rezID, "Day Type"]

                if (pd.notna(val).any() if hasattr(val, "__iter__") and not isinstance(val, str)
                    else pd.notna(val)):
                    # print("True")
                    # print(INITIAL)

                    INITIAL = initial_limit.loc[rezID,"Limit"].iloc[0]

                aug_cost_t = aug_cost[aug_cost["ID"]==rezID]

                AUG_VARS = []
                augMAX = 0
                for aname,arow in aug_cost_t.iterrows():

                    # aname = arow["Name"] 

                    # row["ID"]

                    # row["Build Cost"]

                    date_from = pd.to_datetime(arow["Date From"],dayfirst=True,errors="coerce")

                    if date_from.year > self.end[0] or date_from.year < self.start[0]:
                        continue

                    # skip adding a cost if the expansion can't even happen
                    # different options require different lead times
                    if date_from.year <  pd.to_datetime(aug_max.loc[aname,"Date From"]).year:
                        continue

                    # print(date_from)

                    date_to = pd.to_datetime(arow["Date To"],dayfirst=True,errors="coerce")

                    # REZ_p_VAR = m.variables['Generator-p'].loc[date_range,rez_gens]
                    REZ_p_nom_VAR = m.variables['Generator-p_nom'].loc[rez_gens]

                    # print(REZ_p_VAR)

                    if aname in aug_min.index:

                        amin = aug_min.loc[aname,"Min"]

                    else:

                        amin = 0

                    amax = aug_max.loc[aname,"Max"]

                    # print(amax)
                    # print(amin)

                    # print(REZ_p_VAR[:,0])
                    # print(REZ_p_VAR[:,0].coords)
                    # print(REZ_p_VAR[:,0].dims)

                    AUG_VAR = m.add_variables(lower = amin, upper = amax, name = f"{aname}-{date_from.year}-{date_to.year}")#, coords=REZ_p_VAR[:,0].coords)
                    
                    # summed bc individually constrained already
                    m.add_constraints(
                        REZ_p_nom_VAR.sum() <= INITIAL + AUG_VAR, name = f"Single-REZ-Limit-{aname}-{date_from.year}-{date_to.year}"
                    )

                    # print(test)

                    m.objective += AUG_VAR * arow["Build Cost"] * 1000

                    # AUG_VARS.append(AUG_VAR)

                    # augMAX = amax

                # if AUG_VARS:

                #     # print(sum(AUG_VARS))

                #     # print(augMAX)

                #     # cannot enforce the same maximum to all vars
                #     m.add_constraints(
                #         sum(AUG_VARS) <= augMAX, name = f"{aname}-MAX"
                #     )

        # each storage unit is constrained by some build limit

    def force_build_solar_wind(self):
        '''
        min solar build required each year
        '''

        pass

    def transmission_expansion(self):
        '''
        allow transmission expansion
        '''

        pass

    def transmission_losses(self):
        '''
        make loss variables and re-do nodal balance
        '''

        m = self.n.model

        # Add loss variables

        mask = self.n.links.carrier=="Interconnectors"

        loss_group = self.n.links[mask].index.to_list()

        # m.add_variables(lower = 0, upper = 1000,
        #                 coords= m.variables["Link-p"].loc[:,loss_group].coords,
        #                 name = "Link-loss")
        
        # Add loss tangents

        # Add linearization constraints for each tangent segment
        # for k in range(1, tangents + 1):
        #     # Calculate linearization parameters for segment k
        #     p_k = k / tangents * s_max_pu * s_nom_max
        #     loss_k = r_pu_eff * p_k**2 # point where the line is
        #     slope_k = 2 * r_pu_eff * p_k
        #     offset_k = loss_k - slope_k * p_k

        #     # Add constraints for both positive and negative flow
        #     for sign in [-1, 1]:
        #         lhs = n.model.linexpr((1, loss), (sign * slope_k, flow))
        #         n.model.add_constraints(
        #             lhs >= offset_k, name=f"{c.name}-loss_tangents-{k}-{sign}", mask=active
        #         )

        # Remove existing nodal balance constraints
        
        m.remove_constraints("Bus-nodal_balance")
        m.remove_constraints("Bus-meshed-nodal_balance")

        # Add in nodal balance with links loss

        _pypsaList = [
            ["Generator", "p", "bus", 1],
            ["StorageUnit", "p_dispatch", "bus", 1],
            ["StorageUnit", "p_store", "bus", -1],
            ["Link", "p", "bus0", -1],
            ["Link", "p", "bus1", 1],
            ["Link", "loss", "bus0", -0.5],
            ["Link", "loss", "bus1", -0.5],
        ]

        for bus in self.n.buses.index:

            print(bus)

            # Fundamental

            gens_idx = self.n.generators[self.n.generators.bus == bus].index
            gens = m.variables["Generator-p"].loc[:,gens_idx] # 1
            gen_bus = self.n.generators.bus.loc[gens_idx].rename("Bus")

            su_idx = self.n.storage_units[self.n.storage_units.bus == bus].index
            su_dispatch = m.variables["StorageUnit-p_dispatch"].loc[:,su_idx] #
            su_d_bus = self.n.storage_units.bus.loc[su_idx].rename("Bus")
            # su_dispatch = m.variables["StorageUnit-p_dispatch"].loc[:,self.n.storage_units[self.n.storage_units.bus == bus].index] # 1

            su_store = m.variables["StorageUnit-p_store"].loc[:,su_idx] # -1
            su_s_bus = self.n.storage_units.bus.loc[su_idx].rename("Bus")
            # su_store = m.variables["StorageUnit-p_store"].loc[:,self.n.storage_units[self.n.storage_units.bus == bus].index] # -1

            l0_idx = self.n.links[self.n.links.bus0 == bus].index
            from_links = m.variables["Link-p"].loc[:,l0_idx] # -1
            from_links_bus = self.n.links.bus0.loc[l0_idx].rename("Bus")

            l1_idx = self.n.links[self.n.links.bus1 == bus].index
            to_links = m.variables["Link-p"].loc[:,l1_idx] # 1
            to_links_bus = self.n.links.bus1.loc[l1_idx].rename("Bus")

            # Losses

            # from_links_loss_mask = [link for link in from_links.coords['Link'].values if link in loss_group]
            # from_links_loss = m.variables["Link-loss"].loc[:,from_links_loss_mask] # -0.5
            # from_links_loss_bus = self.n.links.bus0.loc[from_links_loss_mask].rename("Bus")

            # to_links_loss_mask = [link for link in to_links.coords['Link'].values if link in loss_group]
            # to_links_loss = m.variables["Link-loss"].loc[:,to_links_loss_mask] # -0.5
            # to_links_loss_bus = self.n.links.bus1.loc[to_links_loss_mask].rename("Bus")

            # RHS

            load = self.n.loads_t.p_set[f"Load_{bus}"].values

            # Add Constraints

            lhsC = 0

            if gens.size > 0:
                print("Adding gens...")
                gen_bus_map = gens.groupby(gen_bus).sum()
                lhsC += gen_bus_map
            if su_dispatch.size > 0:
                print("Adding storage dispatch...")
                su_d_bus_map = su_dispatch.groupby(su_d_bus).sum()
                lhsC += su_d_bus_map
            if su_store.size > 0:
                print("Adding storage store...")
                su_s_bus_map = su_store.groupby(su_s_bus).sum()
                lhsC -= su_s_bus_map
            if from_links.size > 0:
                print("Adding from links...")
                from_links_bus_map = from_links.groupby(from_links_bus).sum()
                lhsC -= from_links_bus_map
            if to_links.size > 0:
                print("Adding to links...")
                to_links_bus_map = to_links.groupby(to_links_bus).sum()
                lhsC += to_links_bus_map
            # if from_links_loss.size > 0:
            #     print("Adding from links loss...")
            #     from_links_loss_bus_map = from_links_loss.groupby(from_links_loss_bus).sum()
            #     lhsC -= (0.5 * from_links_loss_bus_map)
            # if to_links_loss.size > 0:
            #     print("Adding to links loss...")
            #     to_links_bus_map = to_links_loss.groupby(to_links_loss_bus).sum()
            #     lhsC -= (0.5 * to_links_bus_map)

            print(lhsC)

            m.add_constraints(
                lhs= lhsC, #gens + su_dispatch - su_store - from_links + to_links - (0.5*to_links_loss) - (0.5*from_links_loss),
                sign="=",
                rhs = load,
                name = f"Bus-{bus}-nodal_balance_w_losses"
            )


        # try removing transformer (use same v_nom should not matter honestly)

        # Minimum 3 tangents (can test with 1 or 2)

        # for each link:

        #     create loss variable but need to save in model.solution

        # for k in range(1, tangents + 1):
        #     # Calculate linearization parameters for segment k
        #     p_k = k / tangents * s_max_pu * s_nom_max
        #     loss_k = r_pu_eff * p_k**2 # point where the line is
        #     slope_k = 2 * r_pu_eff * p_k
        #     offset_k = loss_k - slope_k * p_k

        #     # Add constraints for both positive and negative flow
        #     for sign in [-1, 1]:
        #         lhs = n.model.linexpr((1, loss), (sign * slope_k, flow))
        #         n.model.add_constraints(
        #             lhs >= offset_k, name=f"{c.name}-loss_tangents-{k}-{sign}", mask=active
        #         )

    # dodo > 2026 to 2030 compare with 2026 to 2050

    # do vic offshore wind target should be easy

    # quickly do pc if possible

    # work on preso


    def add_82pc_constraint(self):
        '''
        add 82pc constraint
        '''

        m = self.n.model

        snaps = self.n.snapshots

        dates = snaps[snaps >= (2030,)]
        
        vre_gens = self.n.generators[self.n.generators.carrier.str.contains("Wind|Solar|BOTN|Hydro|Battery")].index

        thermal_gens = self.n.generators[~self.n.generators.carrier.str.contains("Wind|Solar|BOTN|Hydro|Battery")].index

        VRE_GENS_2030 = m.variables['Generator-p'].loc[dates,vre_gens]

        THERMAL_GENS_2030 = m.variables['Generator-p'].loc[dates,thermal_gens]

        # calculate the p_noms of generators before etc

        m.add_constraints(
            THERMAL_GENS_2030.sum() <= 0.18*VRE_GENS_2030.sum(), name="82 Percent Target"
        )

        # dates = snaps[snaps > (2050,)]

        # THERMAL_GENS_2050 = m.variables['Generator-p'].loc[dates,thermal_gens]

        # m.add_constraints(
        #     THERMAL_GENS_2050.sum() == 0, name="Net Zero Target"
        # )

    def ISP_Constraints(self,network,snapshots):

        # hydro max energy constraint
        print("Adding Hydro Constraints...")
        self.add_hydro_constraints(n=network,snapshots=snapshots)
        print("...Finished adding Hydro Constraints")

        # transmission flow constraint
        print("Adding Transmission Constraints...")
        self.add_transmission_constraints(n=network,snapshots=snapshots)
        print("...Finished adding Transmission Constraints")

        # rez limit constraint
        print("Adding REZ Constraints...")
        # self.add_rez_constraints(n=network,snapshots=snapshots)
        # self._add_rez_constraints()
        print("...Finished adding REZ Constraints")

        # carbon budget constraint
        print("Adding Carbon Budget Constraints...")
        self.add_carbon_budget_constraint(n=network,snapshots=snapshots)
        print("...Finished adding Carbon Budget Constraints")

        # carbon PHES and Battery Storage Build Limit
        print("Adding PHES and Battery Storage Build Limit Constraints...")
        self.add_PHES_build_limits(n=network,snapshots=snapshots)
        # self.add_battery_storage_constraint(n=network,snapshots=snapshots)
        print("...Finished adding PHES and Battery Storage Build Limit Constraints")

        # add 82pc constraint
        # self.add_82pc_constraint()
        print("Adding federal 82 pc target Constraints...")
        self.add_federal_targets(n=network,snapshots=snapshots)
        print("...Finished adding federal 82 pc target Constraints...")

    #! save network !#

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

if __name__ == "__main__":

    # 2025 to 2030 worked -> rerun with proper transmission constraints to see the effect
    # battery and PHES storage constraints not working
    # add CER storage as batteries in each sub region, split by demand allocation
    # change p_max_pu with columns
    # model no longer creating off shore wind
    # add VIC offshore constraint

    # ISP24MODEL = ISP24LT("isp24_SSLT_SC_y_g_V1",start=(2026,1,1),end=(2050,12,31), SSLT=True, scenario="SC") #, interval="12h",step=24)
    ISP24MODEL = ISP24LT("isp24_test",start=(2030,1,1),end=(2035,12,31), SSLT=True, scenario="SC") #, interval="12h",step=24)

    network = ISP24MODEL.create_network()

    # network.export_to_netcdf("./networks/isp24_basic_2026_2050_SSLT_feasiblity_final.nc")

    print(network.model.objective)

    # g_env = gp.Env()
    # Optionally set parameters
    # g_env.setParam('Threads', 8)     
    # g_env.setParam('Presolve', 2) 
    # g_env.setParam('Method', 2) # Barrier only
    # g_env.setParam('Method', 1)  # if memory is tight use dual simplex
    # If Method not 3 (concurrent) ignores threads
    # g_env.setParam('Crossover', 0)
    # g_env.setParam('NumericFocus', 1)
    # MemLimit
    # Concurrent Method
    # g_env.start()

    network.optimize.solve_model(#solver_name="highs",solver_options={"solver":"ipm","log_file":"highs.log","threads":4,"presolve":"on","run_crossover":"off","user_objective_scale":-3,"user_bound_scale":-3}) 
    solver_name="gurobi",solver_options={
        "Method" : 2,         # Barrier (interior point)
        "Threads" : 4,       # Want to run multiple in parallel
        # "Crossover" : 0,     # Ok if not optimal, just want a feasible point, but can affect barrier performance
        # "BarConvTol": 1e-8,    # Optimality tolerance, set the same as highs
        "LogFile" : "./log/gurobi.log"
        # "ResultFile": "./result.sol",
        # "NumericFocus":1,
        # "BarOrder" : 0, # approximate minimum degree ordering, sometimes ordering takes forever
        # "TimeLimit": 60, # 2 hours to return a feasible solution
    })

    # network.model.print_infeasibilities()

    # network.optimize.optimize_with_rolling_horizon(extra_functionalities=ISP24MODEL.ISP_Constraints(),horizon=800,overlap=100,
    #     solver_name="gurobi",solver_options={
    #     "Method":2,
    #     "LogFile": "./gurobi.log"
    # })

    # network.model.solve(solver_name="gurobi",log_fn = "./gurobi.log",env=g_env)

    # network.model.solution.reset_index(dims_or_levels="period").to_netcdf("./solutions/isp24_SSLT_run_2026_to_2050_final_SC.nc")

    # rolling optimisation on 4 years but with 8 blocks a day (maybe too much?)
    # network.export_to_netcdf("./networks/isp24_basic_v4_transmission_feasiblity.nc")

    # rolling optimisation on 4 years but with 5 blocks a day
    # network.model.to_netcdf("./networks/isp24_basic_v3_transmission_feasiblity.nc")
    # network.export_to_netcdf("./networks/isp24_month_2026_2050_SSLT_solved_SC_highs_final_v2.nc")
    # network.export_to_netcdf("./networks/isp24_month_2026_2050_SSLT_solved_SC_gurobi_final_v2.nc")

    # network.export_to_netcdf("./networks/isp24_year_2026_2050_SSLT_solved_SC_gurobi_final_crossover_v3.nc")
    # network.export_to_netcdf("./networks/isp24_year_2026_2050_SSLT_solved_PC_gurobi_final_v2.nc")
    network.export_to_netcdf("./networks/isp24_year_2026_2050_SSLT_solved_PC_gurobi_final_crossover_v3.nc")

