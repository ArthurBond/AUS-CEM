from linopy import Variable

def add_flow_path_augmentation_constraints(n):

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