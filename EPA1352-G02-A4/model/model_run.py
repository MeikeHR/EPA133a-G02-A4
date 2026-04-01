import pandas as pd
from pathlib import Path
from model import BangladeshModel
from components import Bridge  # NEW

# Instead of using the old categories, the new vulnerability levels are now used
scenarios = {
    "S0": {"Low": 0.0, "Medium-Low": 0.0,  "Medium-High": 0.0,  "High": 0.0},
    "S1": {"Low": 0.0, "Medium-Low": 0.0,  "Medium-High": 0.0,  "High": 5.0},
    "S2": {"Low": 0.0, "Medium-Low": 0.0,  "Medium-High": 5.0,  "High": 10.0},
    "S3": {"Low": 0.0, "Medium-Low": 5.0,  "Medium-High": 10.0, "High": 20.0},
    "S4": {"Low": 5.0, "Medium-Low": 10.0, "Medium-High": 20.0, "High": 40.0},
}

seed = 1234567
run_length = 5 * 24 * 60
roads_to_include = ["N1", "N2"] #Use roads N1 and N2

def run_all_scenarios():
    current_dir = Path(__file__).resolve().parent
    results_dir = current_dir / "results simulation"
    results_dir.mkdir(exist_ok=True)

    #extract the breakdown probabilities
    for scenario_name, bridge_breakdown_probs in {"S0": scenarios["S0"]}.items(): #sanity-check
    #for scenario_name, bridge_breakdown_probs in scenarios.items():
        print(f"\n=== Running {scenario_name} ===")

        all_replications = []
        bridge_delays_scenario = []

        for replication in range(1): #sanity-check
        #for replication in range(10):
            model = BangladeshModel(
                seed=seed + replication, #make the seed change every replication
                bridge_breakdown_probs=bridge_breakdown_probs,
                roads_to_include=roads_to_include,
                two_directional=True,
            )

            for _ in range(run_length):
                model.step()

            df = pd.DataFrame(model.trip_records)

            if not df.empty:
                df["scenario"] = scenario_name
                df["replication"] = replication

            all_replications.append(df)

            #Saving the bridge information into a dataframe
            for agent in model.schedule.agents:
                if isinstance(agent, Bridge):
                    bridge_delays_scenario.append({
                        "scenario": scenario_name,
                        "replication": replication,
                        "bridge_id": agent.unique_id,
                        "bridge_name": agent.name,
                        "road": agent.road_name,
                        "condition": agent.condition,
                        "vulnerability_score": agent.vulnerability_score,  #we added this
                        "vuln_level": agent._get_vulnerability_level(agent.vulnerability_score),  # and this
                        "total_delay_min": agent.total_delay_caused,
                        "breakdown_count": agent.breakdown_count,
                        "trucks_passed": agent.trucks_passed  #we also added this for the simulation criticality
                    })

        if all_replications:
            df_all = pd.concat(all_replications, ignore_index=True)
        else:
            df_all = pd.DataFrame()
        #make a csv per scenario for trip results simulation
        out_path = results_dir / f"{scenario_name}.csv"
        df_all.to_csv(out_path, index=False)
        #make a csv per scenario for bridges
        if bridge_delays_scenario:
            df_bridges = pd.DataFrame(bridge_delays_scenario)
            df_bridges.to_csv(results_dir / f"bridges_{scenario_name}.csv", index=False)


if __name__ == "__main__":
    run_all_scenarios()