from mesa import Model
from mesa.time import BaseScheduler
from mesa.space import ContinuousSpace
from components import Source, Sink, SourceSink, Bridge, Link
import pandas as pd
from collections import defaultdict
from pathlib import Path
import re

BASE_DIR = Path(__file__).resolve().parents[1]
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
def preprocess_data(raw_df, bridge_info, roads_to_include):
    """
    Returns:
    - df_final: prepared dataframe for model build.

    Includes:
    - id creation
    - length computation from chainage
    - type_simple cleaning
    - bridge_info aggregation + merge on LRPName
    - bridge length overwrite (BMMS)
    - filter to selected roads
    - helper columns for junction parsing
    """
    raw_df = raw_df.copy()
    bridge_info = bridge_info.copy()

    #set id in df
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

    # Make sure strings are consistent
    raw_df["road"] = raw_df["road"].astype(str).str.strip()
    raw_df["lrp"] = raw_df["lrp"].astype(str).str.strip()
    raw_df["name"] = raw_df["name"].astype(str).fillna("").str.strip()

    # Clean aggregate bridges
    bridge_info.columns = bridge_info.columns.str.strip()
    bridge_info["LRPName"] = bridge_info["LRPName"].astype(str).str.strip()

    def aggregate_bridge_group(group: pd.DataFrame) -> pd.Series:
        names_str = " ".join(group["name"].dropna().astype(str).tolist()).upper()
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
    bridge_info_clean = bridge_info_clean.rename(columns={"length": "length_bmms"})

    # BMMS merge to roads df
    df = raw_df.merge(
        bridge_info_clean,
        left_on="lrp",
        right_on="LRPName",
        how="left",
        suffixes=("", "_bmms")
    )

    # Bridges attributes
    mask_bridge = df["type_simple"] == "Bridge"
    mask_has_bmms_len = df["length_bmms"].notna()

    df.loc[mask_bridge & mask_has_bmms_len, "length"] = df.loc[mask_bridge & mask_has_bmms_len, "length_bmms"]

    if "condition_bmms" in df.columns:
        df.loc[mask_bridge, "condition"] = df.loc[mask_bridge, "condition_bmms"]
    df.loc[mask_bridge, "condition"] = df.loc[mask_bridge, "condition"].fillna("Unknown")

    # Filter to selected roads
    if roads_to_include is not None:
        roads_to_include = [str(r).strip() for r in roads_to_include]
        df = df[df["road"].isin(roads_to_include)].copy()
        if df.empty:
            raise ValueError(f"No data found for roads: {roads_to_include}")

    # Check if SideRoad/CrossRoad + target road in name
    def extract_target_road(name: str):
        if not isinstance(name, str) or not name:
            return None
        m = re.search(r"\(([^)]+)\)", name)
        return m.group(1).strip() if m else None

    df["target_road"] = df["name"].apply(extract_target_road)
    df["is_junction"] = df["type_simple"].apply(
        lambda t: isinstance(t, str) and (t == "CrossRoad" or t.startswith("SideRoad"))
    )

    # Sort by road and chainage
    df_final = df.sort_values(by=["road", "chainage"], ascending=[True, True]).reset_index(drop=True)

    return df_final


# ---------------------------------------------------------------
class BangladeshModel(Model):
    """
    The main (top-level) simulation model

    One tick represents one minute; this can be changed
    but the distance calculation need to be adapted accordingly

    Parameters
    ----------
    seed : int, optional
    two_directional : bool
        If True, road endpoints act as both Source and Sink (bidirectional traffic).
        If False (default), start = Source only, end = Sink only.
    roads_to_include : list of str, optional
        Which roads to load, e.g. ['N1']. Default: ['N1'].
    bridge_breakdown_probs : dict, optional
        Per-condition daily breakdown probability (%). E.g. {"A": 0, "B": 1, "C": 5, "D": 20}.
    """

    step_time = 1

    def __init__(self, seed=None,
                 two_directional=False,
                 roads_to_include=None,
                 bridge_breakdown_probs=None):

        super().__init__(seed=seed)

        self.two_directional = two_directional
        self.roads_to_include = roads_to_include

        if bridge_breakdown_probs is None:
            bridge_breakdown_probs = {"A": 0.0, "B": 0.0, "C": 0.0, "D": 0.0}
        self.bridge_breakdown_probs = bridge_breakdown_probs

        self.schedule = BaseScheduler(self)
        self.running = True
        self.path_ids_dict = defaultdict(lambda: pd.Series())
        self.space = None
        self.sources = []
        self.sinks = []
        self.trip_records = []

        self.generate_model()

    def generate_model(self):
        raw_df = pd.read_csv(DATA_DIR / "_roads3.csv")
        bridge_info = pd.read_excel(DATA_DIR / "BMMS_overview.xlsx")

        # Preprocessing -> returns single filtered + sorted dataframe
        df_final = preprocess_data(raw_df, bridge_info, self.roads_to_include)

        print("Bridge lengths (first 10):")
        #print(df_final[df_final["type_simple"] == "Bridge"][["name", "length", "condition"]].head(10))

        Source.truck_counter = 0

        # Build road endpoints and path_ids_dict
        df_objects_all = []
        road_endpoints = {}

        for road in self.roads_to_include:
            df_road = df_final[df_final["road"] == road].sort_values("chainage").copy()
            if df_road.empty:
                continue

            road_endpoints[road] = {
                "start": int(df_road.iloc[0]["id"]),
                "end": int(df_road.iloc[-1]["id"])
            }
            df_objects_all.append(df_road)

            road_slice = df_road.reset_index(drop=True)
            id_to_idx = {int(id_): idx for idx, id_ in enumerate(road_slice["id"])}

            # Potential source/sink nodes: endpoints + CrossRoads/Others/Ferry
            road_ss_ids = road_slice[
                road_slice["type_simple"].isin(["Others", "CrossRoad", "Ferry-ghatStart"])
            ]["id"].tolist()
            road_ss_ids = [int(i) for i in road_ss_ids]
            road_ss_ids.extend([road_endpoints[road]["start"], road_endpoints[road]["end"]])
            road_ss_ids = list(set(road_ss_ids))

            # path_ids_dict for every pair on this road
            for start_node in road_ss_ids:
                idx_start = id_to_idx[start_node]
                for end_node in road_ss_ids:
                    if start_node == end_node:
                        continue
                    idx_end = id_to_idx[end_node]

                    if idx_start <= idx_end:
                        path = road_slice.loc[idx_start:idx_end, "id"]
                    else:
                        path = road_slice.loc[idx_start:idx_end:-1, "id"]

                    self.path_ids_dict[(start_node, end_node)] = path.reset_index(drop=True)

        # use separate var to avoid overwriting df_final
        df_plot = pd.concat(df_objects_all)
        y_min, y_max, x_min, x_max = set_lat_lon_bound(
            df_plot["lat"].min(), df_plot["lat"].max(),
            df_plot["lon"].min(), df_plot["lon"].max(), 0.05
        )
        self.space = ContinuousSpace(x_max, y_max, True, x_min, y_min)

        # create agents
        for _, row in df_plot.iterrows():
            rid = int(row["id"])
            m_type = row["type_simple"]
            road_name = row["road"]

            is_start = rid == road_endpoints.get(road_name, {}).get("start")
            is_end = rid == road_endpoints.get(road_name, {}).get("end")

            if m_type == "Bridge":
                agent = Bridge(
                    rid, self, row["length"], row["name"],
                    road_name, row.get("condition", "Unknown")
                )
            elif is_start or is_end:
                agent = SourceSink(rid, self, row["length"], row["name"], road_name)

                # Source is in Chittagong (although highest chainage)
                if not self.two_directional:
                    if is_end:  # the end is added to the sources list (reverse direction in terms of chainage)
                        self.sources.append(rid)
                    if is_start:  # the start is added to the sink list (reverse direction in terms of chainage)
                        self.sinks.append(rid)
                else:
                    self.sources.append(rid)
                    self.sinks.append(rid)
            else:
                agent = Link(rid, self, row["length"], row["name"], road_name)

            self.schedule.add(agent)
            self.space.place_agent(agent, (row["lon"], row["lat"]))
            agent.pos = (row["lon"], row["lat"])

        print(f"Model initialized: {len(self.sources)} sources, {len(self.sinks)} sinks.")

    def get_random_route(self, source_id):
        """
        Pick a random sink that has a valid path from this source.
        Returns the path (pd.Series), or None if no valid route exists.
        """
        available_sinks = [s for s in self.sinks if s != source_id]
        if not available_sinks:
            return None

        sink_id = self.random.choice(available_sinks)
        return self.path_ids_dict.get((source_id, sink_id))

    def step(self):
        """
        Advance the simulation by one step.
        """
        self.schedule.step()


# EOF -----------------------------------------------------------
