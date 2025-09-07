from linopy import Variable

def add_flow_path_augmentation_constraints(n, years, augmentations):
    """
    n: PyPSA network with a linopy model
    years: list of years (e.g., [2025, 2030, 2035])
    augmentations: dict, e.g. {"aug1": {"cost": 100, "capacity": 200}, ...}
    """
    # Binary variable: x[aug, year] == 1 if augmentation aug is chosen in year or earlier
    x = n.model.add_variables(
        coords={"aug": list(augmentations.keys()), "year": years},
        binary=True,
        name="augment_option"
    )

    link = "NQ-CQ"
    link_flow = n.model["Link-p"].loc[:, link]

    # don't know if I need the below

    # just get the model to pick one year to expand

    # For each augmentation, ensure the variable is non-decreasing over years
    for aug in augmentations:
        for i in range(len(years) - 1):
            n.model.add_constraints(
                x.loc[aug, years[i]] <= x.loc[aug, years[i + 1]]
            )

    prerequisites = {
        "CQ Option 1": ["CQ Option 2"],
        "CQ Option 2": ["CQ Option 3"],
        # Add more prerequisites as needed
    }

    

    for aug in augs:
        if aug in prerequisites.keys():
            # add augmentation condition 
            aug >= prerequisites[aug] # aug can only happen if prerequisite has happened

    
    # Have an binary variable that is linked to every year
    # But variable must be chosen for that year because it is linked to cost
    # It should work fine

    # Apply augmentation capacity if chosen in a year
    for t, year in enumerate(years):
        for aug, augdata in augmentations.items():
            cap = augdata["capacity"]
            # If augmentation is chosen in this year or earlier, it applies
            n.model.add_constraints(
                link_flow.loc[year] <= n.links.at[link, "p_nom"] + cap * x.loc[aug, year]
            )
            n.model.add_constraints(
                link_flow.loc[year] >= -n.links.at[link, "p_nom"] - cap * x.loc[aug, year]
            )

    # Only one augmentation per year
    for year in years:
        n.model.add_constraints(
            x.loc[:, year].sum() <= 1
        )

    # Example: aug2 can only be chosen if aug1 is chosen (for all years)
    for year in years:
        if "aug1" in augmentations and "aug2" in augmentations:
            n.model.add_constraints(
                x.loc["aug2", year] <= x.loc["aug1", year]
            )

def add_flow_path_augmentation_constraints(n):

    # Suppose options is a list of expansion options like ["NQ-CQ_aug1", "NQ-CQ_aug2"]
    x = n.model.add_variables(lower=0, upper=1, binary=True, name="augment_option")

    link = "NQ-CQ"
    Δf = {  "aug1": {'cost':100,
                   'capacity':200}, 
                   
            "aug2": {'cost':100,
                   'capacity':200}, }  # MW increments

    link_flow = n.model["Link-p"].loc[:, link]

    # Check if this works without augmentation bit

    # Implement with timeslice to get hot days

    for aug, cap in Δf.items():
        n.model.add_constraints(
            link_flow <= n.links.at[link, "p_nom"] + cap * x.loc[aug]
        )
        n.model.add_constraints(
            link_flow >= -n.links.at[link, "p_nom"] - cap * x.loc[aug]
        )

    # careful, you have to add different costs for different years

    # add an extra constraint that limits only one aug per year

    # yikes 
    
    # start with aug from 2030 onwards. could simplify

    for aug_option in augs.keys():
        aug_var = n.model.add_variables(lower=0, upper=1, binary=True, name=aug_option)

        # add cost of adding the aug option
        n.model.objective += augs[aug_option]['cost']*aug_var

        n.model.add_constraints(
            link_flow <= n.links.at[link, "p_nom"] + cap * x.loc[aug]
        )
        n.model.add_constraints(
            link_flow >= -n.links.at[link, "p_nom"] - cap * x.loc[aug]
        )


    # Some augmentations only occur if others have occured

    n.model.add_constraints(x.loc["aug2"] <= x.loc["aug1"])

    # group constraints can be written as 

    n.model.add_constraints(x.loc["aug2"] + x.loc["aug22"] + x.loc["aug12"] >= 2+x.loc["aug31"])

    # check above , could be better to do this

    n.model.add_constraints(x.loc["aug12"] >= x.loc["groupaug1"])
    n.model.add_constraints(x.loc["aug22"] >= x.loc["groupaug1"])
    n.model.add_constraints(x.loc["aug32"] >= x.loc["groupaug1"])

    # all can be on but group aug doesn't have to be on (so what's the point)

    # maybe not needed

    # committed and anticipated network capability hard code but will need to add back in cost to get actual objecive value

def add_REZ_augmentation_constraints(n):

    # Suppose options is a list of expansion options like ["NQ-CQ_aug1", "NQ-CQ_aug2"]
    x = n.model.add_variables(lower=0, upper=1, binary=True, name="augment_option")

    link = "NQ-CQ"
    Δf = {"aug1": 500, "aug2": 1000}  # MW increments

    link_flow = n.model["Link-p"].loc[:, link]

    # Check if this works without augmentation bit

    # Implement with timeslice to get hot days

    for aug, cap in Δf.items():
        n.model.add_constraints(
            link_flow <= n.links.at[link, "p_nom"] + cap * x.loc[aug]
        )
        n.model.add_constraints(
            link_flow >= -n.links.at[link, "p_nom"] - cap * x.loc[aug]
        )

    # Some augmentations only occur if others have occured

    n.model.add_constraints(x.loc["aug2"] <= x.loc["aug1"])

    # Add tech types in each REZ zone

    # e.g. REZ1 has wind, solar, battery, REZ2 has wind, solar, battery, hydrogen
    # REZ1 <= constrained by initial hostingl limit + augmentation from flow path + augmentation from rez 

    rez_increase_from_transmission = {
            'CNSW-SNSW Option 1':200,
            'CNSW-SNSW Option 2':400,
            # etc
        }
    # flow path can increase REZ hosting capacity so need to add that
    # flow_path_decisions is the decision variables by year
    for flow_path_decision in flow_path_decisions:
        if flow_path_decision in rez_increase_from_transmission.keys():
            # add constraint that REZ capacity can increase by this amount if this decision is made
            rez_capacity += rez_increase_from_transmission[flow_path_decision]*flow_path_decision