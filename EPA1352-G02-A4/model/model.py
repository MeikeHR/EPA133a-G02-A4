from mesa import Model
from mesa.time import BaseScheduler
from mesa.space import ContinuousSpace
from components import Source, Sink, SourceSink, Bridge, Link
import pandas as pd
from collections import defaultdict
from pathlib import Path
import re
import networkx as nx

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"


def set_lat_lon_bound(lat_min, lat_max, lon_min, lon_max, edge_ratio=0.02):
    """
    Give the min and max latitudes and Longitudes for the simulation space creation
    """
    lat_edge = (lat_max - lat_min) * edge_ratio
    lon_edge = (lon_max - lon_min) * edge_ratio

    x_max = lon_max + lon_edge
    y_max = lat_min - lat_edge
    x_min = lon_min - lon_edge
    y_min = lat_max + lat_edge
    return y_min, y_max, x_min, x_max

def extract_road_name(name: str):
    """Extract N-road name from a segment name string."""
    if not isinstance(name, str) or not name:
        return None
    m = re.search(r"N\d+", name)
    return m.group(0).strip() if m else None


#Our data preprocessing
def preprocess_data(df, roads_to_include):
    df = df.copy()

    # Filter to selected roads
    if roads_to_include is not None:
        roads_to_include = [str(r).strip() for r in roads_to_include]
        df = df[df["road"].isin(roads_to_include)].copy()
        if df.empty:
            raise ValueError(f"No data found for roads: {roads_to_include}")

    # These two columns are not in roads_enriched yet
    df["target_road"] = df["name"].apply(extract_road_name)
    df["is_junction"] = df["type_simple"].apply(
        lambda t: isinstance(t, str) and (t == "CrossRoad" or t.startswith("SideRoad"))
    )

    return df.sort_values(by=["road", "chainage"]).reset_index(drop=True)


# Here our model starts
class BangladeshModel(Model):

    step_time = 1

    def __init__(self, seed=None,
                 two_directional=None,
                 roads_to_include=None,
                 bridge_breakdown_probs=None):

        super().__init__(seed=seed)

        self.two_directional = two_directional #So vehicles can move in both directions
        self.main_roads = roads_to_include if roads_to_include is not None else ["N1", "N2"] #Only N1 and N2

        if bridge_breakdown_probs is None:
            bridge_breakdown_probs = {"A": 0.0, "B": 0.0, "C": 0.0, "D": 0.0} #back up breakdown probabilities
        self.bridge_breakdown_probs = bridge_breakdown_probs

        self.schedule = BaseScheduler(self)
        self.running = True
        self.path_ids_dict = defaultdict(lambda: pd.Series())
        self.space = None
        self.sources = []
        self.sinks = []
        self.trip_records = []

        self.generate_model()

    def get_long_side_roads(self, raw_df, main_roads, min_length_m=25000):
    #function to filter the side roads
        junction_data = raw_df[
            (raw_df["road"].isin(main_roads)) &
            (raw_df["type"].str.contains("CrossRoad|SideRoad", case=False, na=False))
            ]

        #Extract potential road names from the junction name field
        side_road_names = []
        for name in junction_data["name"].dropna().unique():
            result = extract_road_name(name)
            if result:
                side_road_names.append(result)

        #filter by length, >25km
        long_roads = []
        for road in set(side_road_names):
            road_segments = raw_df[raw_df["road"] == road]
            if not road_segments.empty:
                total_length = (road_segments["chainage"].max() - road_segments["chainage"].min()) * 1000
                if total_length > min_length_m:
                    long_roads.append(road)

        return long_roads

    def generate_model(self):
        roads_enriched = pd.read_csv("../data/new_data/roads_after_dataanalysis.csv")

        #automatically find side roads > 25km as a backup
        long_side_roads = self.get_long_side_roads(roads_enriched, self.main_roads, 25000)
        self.roads_to_include = list(set(self.main_roads + long_side_roads))

        #print included roads and their lengths (now N1, N2, and sideroads longer than 25km)
        for road in sorted(self.roads_to_include):
            segments = roads_enriched[roads_enriched["road"] == road]
            length_km = (segments["chainage"].max() - segments["chainage"].min())
            print(f"Including road {road}: {length_km:.1f} km")

        roads_after_preprocessing = preprocess_data(roads_enriched, self.roads_to_include)
        # df_final = preprocess_data(roads_enriched, bridge_info, self.roads_to_include)
        roads_after_preprocessing.to_csv(DATA_DIR / "new_data/roads_after_preprocessing.csv", index=False)

        print("Bridge lengths (first 10):")

        Source.truck_counter = 0

        # Creation of road endpoints and path_ids_dict
        df_objects_all = []
        road_endpoints = {}

        for road in self.roads_to_include:
            df_road = roads_after_preprocessing[roads_after_preprocessing["road"] == road].sort_values("chainage").copy()
            if df_road.empty:
                continue

            road_endpoints[road] = {
                "start": int(df_road.iloc[0]["id"]),
                "end": int(df_road.iloc[-1]["id"])
            }
            df_objects_all.append(df_road)

            road_slice = df_road.reset_index(drop=True)
            id_to_idx = {int(id_): idx for idx, id_ in enumerate(road_slice["id"])}

            road_ss_ids = road_slice[
                road_slice["type_simple"].isin(["Others", "CrossRoad", "Ferry-ghatStart"])
            ]["id"].tolist()
            road_ss_ids = [int(i) for i in road_ss_ids]
            road_ss_ids.extend([road_endpoints[road]["start"], road_endpoints[road]["end"]])
            road_ss_ids = list(set(road_ss_ids))

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

        df_plot = pd.concat(df_objects_all)

        y_min, y_max, x_min, x_max = set_lat_lon_bound(
            df_plot["lat"].min(), df_plot["lat"].max(),
            df_plot["lon"].min(), df_plot["lon"].max(), 0.05
        )
        self.space = ContinuousSpace(x_max, y_max, True, x_min, y_min)

        #We made this a dictionary instead of pandas in our earlier model, so computational time is limited
        self.agent_dict = {}

        # Creating agents
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

                if not self.two_directional:
                    if is_end:
                        self.sources.append(rid)
                    if is_start:
                        self.sinks.append(rid)
                else:
                    self.sources.append(rid)
                    self.sinks.append(rid)
            else:
                agent = Link(rid, self, row["length"], row["name"], road_name)

            self.schedule.add(agent)
            self.space.place_agent(agent, (row["lon"], row["lat"]))
            agent.pos = (row["lon"], row["lat"])

            self.agent_dict[rid] = agent

        print(f"Model initialized: {len(self.sources)} sources, {len(self.sinks)} sinks.")

        # Building the network
        self.G = nx.Graph()

        for i in range(len(df_plot) - 1):
            row_current = df_plot.iloc[i]
            row_next = df_plot.iloc[i + 1]

            if row_current["road"] == row_next["road"]:
                self.G.add_edge(int(row_current["id"]), int(row_next["id"]),
                                weight=row_next["length"])

        junctions = df_plot[df_plot["is_junction"] == True] #using junctions to connect
        for _, junc in junctions.iterrows():
            target_name = junc["target_road"]

            if target_name in self.roads_to_include:
                target_road_nodes = df_plot[df_plot["road"] == target_name]
                if not target_road_nodes.empty:
                    target_node_id = int(target_road_nodes.iloc[0]["id"])
                    self.G.add_edge(int(junc["id"]), target_node_id, weight=0)


    def get_random_route(self, source_id):
        """
        Finds a shortest path using NetworkX and caches it in path_ids_dict
        """

        #Select a destination that isn't the origin
        available_sinks = [s for s in self.sinks if s != source_id]
        if not available_sinks:
            return None
        sink_id = self.random.choice(available_sinks)

        # Check path_ids_dict to see if path already exists
        if (source_id, sink_id) in self.path_ids_dict:
            return self.path_ids_dict[(source_id, sink_id)]

        try:
            #Compute shortest path using the NetworkX model where weight = length
            path_list = nx.shortest_path(self.G, source=source_id, target=sink_id, weight='weight')

            #  Convert to pandas Series for the Vehicle logic
            path_series = pd.Series(path_list)

            #Save discovered path to the dictionary
            self.path_ids_dict[(source_id, sink_id)] = path_series
            return path_series

        except nx.NetworkXNoPath:
            return None

    def step(self):
        """
        Advance the simulation by one step.
        """
        self.schedule.step()
