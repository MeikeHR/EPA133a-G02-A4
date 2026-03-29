from mesa.visualization.ModularVisualization import ModularServer
from ContinuousSpace.SimpleContinuousModule import SimpleCanvas
from model import BangladeshModel
from components import Source, Sink, SourceSink, Bridge, Link, Vehicle


def agent_portrayal(agent):
    portrayal = {
        "Shape": "circle",
        "Filled": "true",
        "Color": "Khaki",
        "r": 1,
        "Layer": 0
    }

    if isinstance(agent, Vehicle):
        portrayal["Color"] = "yellow"
        portrayal["r"] = 2
        portrayal["Layer"] = 2

    elif isinstance(agent, SourceSink):
        if agent.vehicle_generated_flag:
            portrayal["Color"] = "green"
        elif agent.vehicle_removed_toggle:
            portrayal["Color"] = "Red"
        else:
            portrayal["Color"] = "LightSkyBlue"
        portrayal["r"] = 5
        portrayal["Layer"] = 1
        portrayal["Text"] = agent.name
        portrayal["Text_color"] = "DarkSlateGray"
        portrayal["font_size"] = 7

    elif isinstance(agent, Source):
        portrayal["Color"] = "green" if agent.vehicle_generated_flag else "red"
        portrayal["r"] = 5
        portrayal["Layer"] = 1
        portrayal["Text"] = agent.name
        portrayal["Text_color"] = "DarkSlateGray"
        portrayal["font_size"] = 7

    elif isinstance(agent, Sink):
        portrayal["Color"] = "Red"
        portrayal["r"] = 5
        portrayal["Layer"] = 1
        portrayal["Text"] = agent.name
        portrayal["Text_color"] = "DarkSlateGray"
        portrayal["font_size"] = 7

    elif isinstance(agent, Bridge):
        portrayal["Color"] = "red" if agent.is_broken else "mediumpurple"
        portrayal["r"] = max(agent.vehicle_count * 2, 2)

    else:  # Links
        portrayal["Color"] = "tan"
        portrayal["r"] = max(agent.vehicle_count *2, 2)

    return portrayal

# Breakdown probabilities per scenario
scenarios = {
    "S0": {"A": 0.0, "B": 0.0, "C": 0.0,  "D": 0.0},
    "S1": {"A": 0.0, "B": 0.0, "C": 0.0,  "D": 5.0},
    "S2": {"A": 0.0, "B": 0.0, "C": 5.0,  "D": 10.0},
    "S3": {"A": 0.0, "B": 5.0, "C": 10.0, "D": 20.0},
    "S4": {"A": 5.0, "B": 10.0, "C": 20.0, "D": 40.0},
}

canvas_width = 800
canvas_height = 800

space = SimpleCanvas(agent_portrayal, canvas_width, canvas_height)

# Variables
scenario_to_visualise = "S0"
seed = 1234567
roads_to_include = ["N1", "N2"] #model can later be expanded by including more roads
two_directional = True
bridge_breakdown_probs = scenarios[scenario_to_visualise]

server = ModularServer(
    BangladeshModel,
    [space],
    "Transport Model Demo",
    {"seed": seed,
     "roads_to_include": roads_to_include,
     "two_directional": two_directional,
     "bridge_breakdown_probs": bridge_breakdown_probs}
)

server.port = 8521
server.launch()