# AUS-CEM

The Australian Capacity Expansion model, pronounced Awe(z)-Some. 

## Usage Notes

### Clone Repository

Use the command `git clone` to clone this repository.

### Data Download

Download Traces from AEMO. Solar and wind are downloaded separately to demand, hydro, and timeslice, which are within the model.


## Notes


### PYPSA

This uses PyPSA as the framework, which is a flexible power and energy system optimiser. It is being used as an energy system optimiser for this project.

See PyPSA-AU for an example of power flows for the Australian Network using PyPSA.

### AEMO IASR 2023 and IASR 2025

The capacity expansion model is based on AEMO's LT model built in PLEXOS. It is a linear program, with inputs from the Australian Market Operator's Inputs, Assumptions and Scenarios workbook. The IASR published in 2023 is a guide to what is used in the 2024 ISP, and the IASR pulished in 2025 is reflective of what is modelled in the 2026 ISP 