from mesa import Model
from mesa.time import BaseScheduler
from mesa.space import ContinuousSpace
from scenario_components import Source, Sink, SourceSink, Bridge, Link
import pandas as pd
from collections import defaultdict

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]   # EPA133a-G02-A3
DATA_DIR = BASE_DIR / "data"


# ---------------------------------------------------------------
def set_lat_lon_bound(lat_min, lat_max, lon_min, lon_max, edge_ratio=0.02):
    """
    Set the HTML continuous space canvas bounding box (for visualization)
    give the min and max latitudes and Longitudes in Decimal Degrees (DD)

    Add white borders at edges (default 2%) of the bounding box
    """

    lat_edge = (lat_max - lat_min) * edge_ratio
    lon_edge = (lon_max - lon_min) * edge_ratio

    x_max = lon_max + lon_edge
    y_max = lat_min - lat_edge
    x_min = lon_min - lon_edge
    y_min = lat_max + lat_edge
    return y_min, y_max, x_min, x_max


# ---------------------------------------------------------------
import pandas as pd

def preprocess_data(raw_df, bridge_info):
    """
    Returns df_final: the fully prepared dataframe for the model build.
    Includes:
    - id creation
    - length computation from chainage
    - type_simple cleaning
    - bridge_info aggregation + merge on LRPName
    - bridge length overwrite (BMMS)
    - filter to N1 and sort travel direction (high -> low chainage)
    """

    raw_df = raw_df.copy()
    bridge_info = bridge_info.copy()

    # Base preprocessing roads df ---
    raw_df["id"] = range(len(raw_df))

    # length = abs(diff(chainage)) * 1000 (km -> m)
    raw_df["length"] = (
        raw_df.groupby("road")["chainage"]
        .diff()
        .abs()
        .fillna(0) * 1000
    )

    # Clean/simplify types
    raw_df["type_simple"] = raw_df["type"].apply(
        lambda x: "Bridge" if isinstance(x, str) and "bridge" in x.lower()
        else str(x).split(" / ")[0].split("%")[0]
    )

    # Make sure LRP strings are consistent
    raw_df["lrp"] = raw_df["lrp"].astype(str).str.strip()

    # Clean + aggregate bridge_info
    bridge_info.columns = bridge_info.columns.str.strip()
    bridge_info["LRPName"] = bridge_info["LRPName"].astype(str).str.strip()

    def aggregate_bridge_group(group: pd.DataFrame) -> pd.Series:
        names_str = " ".join(group["name"].astype(str).tolist()).upper()
        is_lr_pair = ("(L)" in names_str or " L " in names_str) and ("(R)" in names_str or " R " in names_str)

        if is_lr_pair:
            final_length = group["length"].median()
        else:
            final_length = group["length"].mean()

        return pd.Series({
            "length": final_length,
            "condition": group["condition"].max(),  # worst condition (D > A)
            "name": group["name"].iloc[0]
        })

    bridge_info_clean = (
        bridge_info.groupby("LRPName", dropna=False)
        .apply(aggregate_bridge_group)
        .reset_index()
    )

    # Rename to avoid confusion after merge
    bridge_info_clean = bridge_info_clean.rename(columns={"length": "length_bmms"})

    # Combine BMMS into roads df
    df = raw_df.merge(
        bridge_info_clean,
        left_on="lrp",
        right_on="LRPName",
        how="left",
        suffixes=("", "_bmms")
    )

    # finalize bridges attributes
    mask_bridge = df["type_simple"] == "Bridge"
    mask_has_bmms_len = df["length_bmms"].notna()

    # Overwrite computed length with BMMS length when available
    df.loc[mask_bridge & mask_has_bmms_len, "length"] = df.loc[mask_bridge & mask_has_bmms_len, "length_bmms"]

    # If your roads df already had a 'condition' column, this keeps it consistent.
    # If BMMS condition is missing, fill with 'Unknown'
    if "condition_bmms" in df.columns:
        df.loc[mask_bridge, "condition"] = df.loc[mask_bridge, "condition_bmms"]
    df.loc[mask_bridge, "condition"] = df.loc[mask_bridge, "condition"].fillna("Unknown")

    # Filter to N1 + sort travel direction (Chittagong -> Dhaka)
    df_road = df[df["road"]].sort_values(by="chainage", ascending=False).copy()
    if df_road.empty:
        raise ValueError("No data found for road N1")


    df_final = df_road.reset_index(drop=True)
    return df_final

class BangladeshModel(Model):
    """
    The main (top-level) simulation model

    One tick represents one minute; this can be changed
    but the distance calculation need to be adapted accordingly

    Class Attributes:
    -----------------
    step_time: int
        step_time = 1 # 1 step is 1 min

    path_ids_dict: defaultdict
        Key: (origin, destination)
        Value: the shortest path (Infra component IDs) from an origin to a destination

        Since there is only one road in the Demo, the paths are added with the road info;
        when there is a more complex network layout, the paths need to be managed differently

    sources: list
        all sources in the network

    sinks: list
        all sinks in the network

    """

    step_time = 1

    def __init__(self, seed=None, x_max=500, y_max=500, x_min=0, y_min=0,
                 bridge_breakdown_probs= None):

        # Seeded: needed because Bridge uses self.model.random.random()
        super().__init__(seed=seed)

        self.schedule = BaseScheduler(self)
        self.running = True
        self.path_ids_dict = defaultdict(lambda: pd.Series())
        self.space = None
        self.sources = []
        self.sinks = []

        # For results output (filled by Sink.remove)
        self.trip_records = []

        if bridge_breakdown_probs is None:
            bridge_breakdown_probs = {"A": 0.0, "B": 0.0, "C": 0.0, "D": 0.0}
        self.bridge_breakdown_probs = bridge_breakdown_probs

        self.generate_model()

    def generate_model(self):
        raw_df = pd.read_csv(DATA_DIR / "_roads3.csv")
        bridge_info = pd.read_excel(DATA_DIR / "BMMS_overview.xlsx")

        df_final = preprocess_data(raw_df, bridge_info)

        print("Bridge lengths (first 10):")
        print(df_final[df_final["type_simple"] == "Bridge"][["name", "length", "condition"]].head(10))

        # Source/Sink selection based on df_final order
        source_id = int(df_final.iloc[0]["id"])  # max chainage (start)
        sink_id = int(df_final.iloc[-1]["id"])  # min chainage (end)

        self.sources = [source_id]
        self.sinks = [sink_id]

        # Full path in travel order
        path_fwd = df_final["id"].reset_index(drop=True)
        self.path_ids_dict[(source_id, sink_id)] = path_fwd

        # Space boundaries
        y_min, y_max, x_min, x_max = set_lat_lon_bound(
            df_final["lat"].min(), df_final["lat"].max(),
            df_final["lon"].min(), df_final["lon"].max(),
            0.05
        )
        self.space = ContinuousSpace(x_max, y_max, True, x_min, y_min)

        # Create agents
        for _, row in df_final.iterrows():
            rid = int(row["id"])
            m_type = row["type_simple"]

            if rid == source_id:
                agent = Source(rid, self, row["length"], row["name"], row["road"])
            elif rid == sink_id:
                agent = Sink(rid, self, row["length"], row["name"], row["road"])
            elif m_type == "Bridge":
                agent = Bridge(
                    rid, self,
                    row["length"],
                    row["name"],
                    row["road"],
                    row.get("condition", "Unknown")
                )
            else:
                agent = Link(rid, self, row["length"], row["name"], row["road"])

            self.schedule.add(agent)
            self.space.place_agent(agent, (row["lon"], row["lat"]))
            agent.pos = (row["lon"], row["lat"])

    def get_random_route(self, source):
        sink_id = self.sinks[0]
        return self.path_ids_dict.get((source, sink_id))

    def step(self):
        """
        Advance the simulation by one step.
        """
        self.schedule.step()


# EOF -----------------------------------------------------------
