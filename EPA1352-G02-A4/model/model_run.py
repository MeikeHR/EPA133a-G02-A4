import pandas as pd
from pathlib import Path
from model import BangladeshModel


scenarios = {
    "S0": {"A": 0.0,  "B": 0.0,  "C": 0.0,  "D": 0.0},
    "S1": {"A": 0.0,  "B": 0.0,  "C": 0.0,  "D": 5.0},
    "S2": {"A": 0.0,  "B": 0.0,  "C": 0.0,  "D": 10.0},
    "S3": {"A": 0.0,  "B": 0.0,  "C": 5.0,  "D": 10.0},
    "S4": {"A": 0.0,  "B": 0.0,  "C": 10.0, "D": 20.0},
    "S5": {"A": 0.0,  "B": 5.0,  "C": 10.0, "D": 20.0},
    "S6": {"A": 0.0,  "B": 10.0, "C": 20.0, "D": 40.0},
    "S7": {"A": 5.0,  "B": 10.0, "C": 20.0, "D": 40.0},
    "S8": {"A": 10.0, "B": 20.0, "C": 40.0, "D": 80.0},
}

seed = 1234567
run_length = 5 * 24 * 60  # 5 days in minutes
roads_to_include = ["N1"]


def run_all_scenarios():
    current_dir = Path(__file__).resolve().parent
    results_dir = current_dir / "results"
    results_dir.mkdir(exist_ok=True)

    for scenario_name, bridge_breakdown_probs in scenarios.items():
        print(f"\n=== Running {scenario_name} | probs: {bridge_breakdown_probs} ===")

        all_replications = []
        bridge_delays_scenario = []

        for replication in range(10):  # 10 replications
            replication_seed = seed + replication

            model = BangladeshModel(
                seed=replication_seed,
                bridge_breakdown_probs=bridge_breakdown_probs,
                roads_to_include=roads_to_include,
                two_directional=False,
            )

            for _ in range(run_length):
                model.step()

            df = pd.DataFrame(model.trip_records)
            if not df.empty:
                df["scenario"] = scenario_name
                df["replication"] = replication
                df["seed"] = replication_seed
                df["run_length_ticks"] = run_length

            all_replications.append(df)
            for agent in model.schedule.agents:
                if agent.__class__.__name__ == 'Bridge':
                    bridge_delays_scenario.append({
                        "scenario": scenario_name,
                        "replication": replication,
                        "bridge_name": agent.name,
                        "total_delay": agent.total_delay_caused
                    })

        df_all = pd.concat(all_replications, ignore_index=True)
        out_path = results_dir / f"{scenario_name}.csv"
        df_all.to_csv(out_path, index=False)

        print(f"Saved {len(df_all)} trips to {out_path}")

        if not df_all.empty:
            print(f"  Mean:   {df_all['travel_time_min'].mean():.1f} min")
            print(f"  Median: {df_all['travel_time_min'].median():.1f} min")
            print(f"  Min/Max:{df_all['travel_time_min'].min():.1f} / {df_all['travel_time_min'].max():.1f} min")

        if bridge_delays_scenario:
            df_bridges = pd.DataFrame(bridge_delays_scenario)
            out_path_bridges = results_dir / f"bridges_{scenario_name}.csv"
            df_bridges.to_csv(out_path_bridges, index=False)
            print(f"Saved bridge delay data to {out_path_bridges}")

if __name__ == "__main__":
    run_all_scenarios()