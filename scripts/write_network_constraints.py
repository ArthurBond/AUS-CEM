from linopy import Variable

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