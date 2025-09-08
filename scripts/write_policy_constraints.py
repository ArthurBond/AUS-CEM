import linopy
import pypsa

# group by carriers and select all renewables by carrier definition
# vre_gen >= 0.82 * total  ==> 0.18*vre_gen >= firming_gen (less variables in the constraint)

# limit the nominal capacity of generators of the same production carrier at the same bus.

# Therefore, we introduce a column nom_min_{carrier} and nom_max_{carrier} in the buses dataframe. 
# These are then used as lower and upper bounds of generators of the same carrier at the same bus

# use cap factors to do installed capacity coefficients

def add_82_pc_constraints(n,m,scenario="SC"):
    '''
    ensure 82 % is met by 2030

    Parameters
    ----------
    n : network
        PYPSA network
    n : model
        linopy model
    senario : Literal[str]
        "SC" or "PC"
    '''

    genVars = m.variables["Generators-p"] 

    # Step Change Scenario
    if scenario=="SC":
        m.add_constraints()

    elif scenario=="PC":
        m.add_constraints()

    else:
        print("Only Progressive Change or Step Change")
