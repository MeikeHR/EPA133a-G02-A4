import pandas as pd
from pathlib import Path

from scenario_model import BangladeshModel


def run_scenario0(
    seed: int = 1234567,
    run_length: int = 5 * 24 * 60 ):

    current_dir = Path(__file__).resolve().parent
    results_dir = current_dir / "results"
    results_dir.mkdir(exist_ok=True)  # create if it doesn't exist
    out_path = results_dir / "scenario0.csv"

    bridge_breakdown_probs_S0 = {"A": 0.0, "B": 0.0, "C": 0.0, "D": 0.0}
    seed = 1234567

    model = BangladeshModel(seed=seed, bridge_breakdown_probs=bridge_breakdown_probs_S0 )

    for _ in range(run_length):
        model.step()

    df = pd.DataFrame(model.trip_records)

    if not df.empty:
        df["seed"] = seed
        df["run_length_ticks"] = run_length

    print("Saving to:", out_path)
    df.to_csv(out_path, index=False)

    print(f"[Scenario 0] Wrote {len(df)} completed trips.")

    if not df.empty:
        print("Mean travel_time_min:", df["travel_time_min"].mean())
        print("Median travel_time_min:", df["travel_time_min"].median())
        print("Min/Max travel_time_min:",
              df["travel_time_min"].min(),
              df["travel_time_min"].max())


if __name__ == "__main__":
    run_scenario0()