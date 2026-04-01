# Bangladesh Road Network Simulation — EPA1352 Group 02 Assignment 4

Created by: Yilin HUANG
Edited by: EPA133a Group 02

| Name            | Student Number |
|:---------------:|:---------------|
| Jay van Dam     | 5097002        |
| Meike Bos       | 5111390        |
| Marijn Geldof   | 5402654        |
| Tijn Koning     | 5323681        |
| Tyler Al-khfage | 5119510        |

Version: 2.0

---

## Introduction

This project simulates truck logistics and infrastructure reliability on the Bangladeshi national road network using Agent-Based Modeling (ABM) in Mesa. The pipeline consists of two stages: a data analysis notebook that enriches the road and bridge data, and a Mesa simulation model that uses that output to run scenario experiments.

---

## Pipeline Overview

```
notebook/Data Analysis 2.ipynb
        │
        └──► data/roads_after_dataanalysis.csv (vulnerability + criticality scores per LRP, intermediate, after merge step)
             notebook/results data analysis/   (figures and maps)

model/model.py  (reads roads_after_dataanalysis.csv, selects roads based on configuration)
        │
        └──► data/roads_after_preprocessing.csv   (filtered network used in simulation)
             model/results simulation/            (trip records per scenario)
```

---

## How to Set Up

### 1. Create a virtual environment

In PyCharm:
1. Go to Settings → Project → Python Interpreter
2. Click Add Interpreter → Add Local Interpreter → Virtualenv Environment → New
3. Set Base interpreter to Python 3.11 and click OK

Then install dependencies via the terminal:

```
pip install -r requirements.txt
```

### 2. Place the data files

All data files go in the `data/` folder. The following files are required:

| File | Description |
|------|-------------|
| `_roads3.csv` | Raw road network data (LRP points) |
| `BMMS_overview.xlsx` | Bridge Management and Maintenance System data |
| `traffic/` | Folder containing `.traffic.htm` files with AADT counts |
| `flood shapefile/` | Flood hazard polygons (SPARRSO) |
| `earthquake shapefile/` | Seismic hazard polygons (SPARRSO) |

---

## Step 1: Run the Data Analysis Notebook

Open and run all cells in:

```
notebook/Data Analysis 2.ipynb
```

This notebook:
- Merges road and bridge data, computes segment lengths, and aggregates bridge conditions
- Loads RMMS traffic data and computes freight-weighted criticality scores per road segment
- Performs spatial joins with flood and earthquake shapefiles to assign hazard values
- Computes a vulnerability score per LRP: `vulnerability = condition_score × max(flood_mult, seismic_mult)`
- Exports the enriched dataset to `data/roads_after_dataanalysis.csv`
- Saves all figures and maps to `notebook/results data analysis/`

---

## Step 2: Run the Simulation

### With visualisation

```
python model/model_viz.py
```

### Without visualisation (batch runs)

```
python model/model_run.py
```

The model reads `data/roads_after_dataanalysis.csv`, selects the relevant roads based on the scenario configuration, and writes the filtered network to `data/roads_after_preprocessing.csv`. Simulation results are stored per scenario in `model/results simulation/`.

---

## How the Model Works

### Environment

The model represents the road network as a Mesa Continuous Space. The network is built from LRP point data and stitched into a NetworkX graph. Vehicles request shortest paths dynamically via this graph.

Infrastructure agents:
- **Link** — a road segment between two LRP points
- **Bridge** — a road segment identified as a bridge, with a condition rating (A–D) and vulnerability score
- **Source / Sink** — entry and exit points for vehicles

### Vehicle Movement

Each simulation tick represents 1 minute. Vehicles move at a constant speed (default 48 km/h / 800 m per minute). Within a single tick, a vehicle may hop across multiple short segments to ensure smooth movement regardless of segment length.

Vehicle states: `DRIVE` (moving normally) or `WAIT` (delayed at a broken bridge).

### Bridge Failure and Delays

At the start of each replication, each bridge is assigned a breakdown probability based on its condition rating. If a bridge breaks, it remains broken for the entire run. Vehicles encountering a broken bridge enter the `WAIT` state for a delay sampled from:

- Large bridges (>200 m): Triangular distribution (60–240 min)
- Medium/small bridges: Uniform integer range (e.g. 10–20 min)

The vulnerability and criticality scores from the data analysis are used to inform scenario configurations (which bridges to target, which roads matter most).

---

## Data Collection

Each completed trip is logged with: truck ID, start time, end time, travel time, replication number, seed, and sink ID. Results are saved as `S0.csv`, `S1.csv`, etc. in `model/results simulation/`. Bridge delay events are stored in separate `bridges_Sx.csv` files.

---

## File Structure

```
EPA1352-G02-A4/
├── data/
│   ├── _roads3.csv                      Raw road network
│   ├── BMMS_overview.xlsx               Bridge data
│   ├── traffic/                         RMMS traffic files (.traffic.htm)
│   ├── flood shapefile/                 Flood hazard shapefile
│   ├── earthquake shapefile/            Seismic hazard shapefile
│   ├── roads_enriched.csv               Output of data analysis (used by model)
│   ├── roads_after_dataanalysis.csv     Intermediate merge output
│   └── roads_after_preprocessing.csv   Road selection output (generated by model)
│
├── notebook/
│   ├── Data Analysis 2.ipynb            Full data analysis pipeline
│   └── results data analysis/           Figures and maps from the notebook
│
└── model/
│   ├── model.py                         BangladeshModel: loads data, builds network, runs simulation
│   ├── components.py                    Agent definitions (Link, Bridge, Source, Sink, Vehicle)
│   ├── model_viz.py                     Visualization server
│   ├── model_run.py                     Batch run executor (no visualisation)
│   ├── results simulation/              Trip and bridge delay CSVs per scenario
│   └── ContinuousSpace/                 Custom Mesa canvas module for geo-visualisation
│    
└── report/
    └── EPA133a-G02-A4.pdf               Final report for assignment 4
    
```

---

## Results

- Data analysis figures (vulnerability maps, criticality maps, quadrant plots): `notebook/results data analysis/`
- Simulation trip records: `model/results simulation/S0.csv`, `S1.csv`, etc.
- Result analysis: open `Results.ipynb` in the notebook folder
