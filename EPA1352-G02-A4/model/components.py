from mesa import Agent
from enum import Enum
import pandas as pd


# Class from which all infra components inherit
class Infra(Agent):
    def __init__(self, unique_id, model, length=0,
                 name='Unknown', road_name='Unknown'):
        super().__init__(unique_id, model)
        self.length = length
        self.name = name
        self.road_name = road_name
        self.vehicle_count = 0

    def step(self):
        pass

    def __str__(self):
        return type(self).__name__ + str(self.unique_id)


# Bridge class
class Bridge(Infra):
    def __init__(self, unique_id, model, length=0,
                 name='Unknown', road_name='Unknown', condition='Unknown'):
        super().__init__(unique_id, model, length, name, road_name)

        self.condition = condition if pd.notnull(condition) else 'Unknown'
        self.total_delay_caused = 0 #Delay counter
        self.breakdown_count = 0 #Breakdown counter

        # Probability is modelled as a chance during the total model run
        p = self.model.bridge_breakdown_probs.get(self.condition, 0.0) / 100
        if self.model.random.random() < p:
            self.is_broken = True
            self.breakdown_count = 1
        else:
            self.is_broken = False

    def step(self):
        pass


class Link(Infra):
    pass


#Sink infrastructure class
class Sink(Infra):
    def __init__(self, unique_id, model, length=0,
                 name='Unknown', road_name='Unknown'):
        super().__init__(unique_id, model, length, name, road_name)
        self.vehicle_removed_toggle = False

    def remove(self, vehicle):
        vehicle.removed_at_step = self.model.schedule.steps
        travel_time = vehicle.removed_at_step - vehicle.generated_at_step

        #Trips are stored here
        self.model.trip_records.append({
            "truck_id": vehicle.unique_id,
            "generated_at_step": vehicle.generated_at_step,
            "removed_at_step": vehicle.removed_at_step,
            "travel_time_min": travel_time,
            "travel_distance_m": vehicle.distance_travelled,
            "sink_id": self.unique_id
        })

        self.vehicle_count -= 1
        self.model.schedule.remove(vehicle)
        self.vehicle_removed_toggle = not self.vehicle_removed_toggle


#In this part the Source class is created
class Source(Infra):
    truck_counter = 0
    generation_frequency = 5 #every 5 steps

    def __init__(self, unique_id, model, length=0,
                 name='Unknown', road_name='Unknown'):
        super().__init__(unique_id, model, length, name, road_name)
        self.vehicle_generated_flag = False

    def step(self):
        if self.model.schedule.steps % self.generation_frequency == 0:
            self.generate_truck()
        else:
            self.vehicle_generated_flag = False

    #Generation of trucks, there is also a counter for the amount of trucks created per source
    def generate_truck(self):
        if self.unique_id not in self.model.sources:
            return
        try:
            agent = Vehicle('Truck' + str(Source.truck_counter), self.model, self)
            agent.set_path()

            if agent.path_ids is not None and len(agent.path_ids) > 0:
                self.model.schedule.add(agent)
                Source.truck_counter += 1
                self.vehicle_count += 1
                self.vehicle_generated_flag = True
            else:
                print(f"Skipping {agent.unique_id}: No valid path found")

        except Exception as e:
            print(f"Error generating truck: {e}")


# Aggregate class of the source and sink classes
class SourceSink(Source, Sink):
    pass


#Vehicle component
class Vehicle(Agent):
    speed = 48 * 1000 / 60
    step_time = 1

    class State(Enum):
        DRIVE = 1
        WAIT = 2

    def __init__(self, unique_id, model, generated_by,
                 location_offset=0, path_ids=None):
        super().__init__(unique_id, model)
        self.generated_by = generated_by
        self.generated_at_step = model.schedule.steps
        self.location = generated_by
        self.location_offset = location_offset
        self.pos = generated_by.pos
        self.path_ids = path_ids
        self.state = Vehicle.State.DRIVE
        self.location_index = 0
        self.waiting_time = 0 #Tracks waiting time
        self.waited_at = None
        self.removed_at_step = None
        self.distance_travelled = 0.0 #Distance travelled KPI

        self.location.vehicle_count += 1

    def set_path(self):
        self.path_ids = self.model.get_random_route(self.generated_by.unique_id)

    def step(self):
        if self.state == Vehicle.State.WAIT:
            self.waiting_time = max(self.waiting_time - 1, 0)
            if self.waiting_time == 0:
                self.waited_at = self.location
                self.state = Vehicle.State.DRIVE

        if self.state == Vehicle.State.DRIVE:
            self.drive()

    def drive(self):
        distance = Vehicle.speed * Vehicle.step_time
        distance_rest = self.location_offset + distance - self.location.length #Calculate remaining distance

        if distance_rest > 0: #only move if there is remaining distance left
            self.distance_travelled += (self.location.length - self.location_offset)
            self.drive_to_next(distance_rest)
        else:
            self.location_offset += distance
            self.distance_travelled += distance

    def drive_to_next(self, distance):
        max_hops = 2000
        hops = 0
        remaining = distance

        while remaining > 0:
            hops += 1
            if hops > max_hops:
                return

            self.location_index += 1
            if self.location_index >= len(self.path_ids):
                return

            next_id = self.path_ids[self.location_index]
            next_infra = self.model.schedule._agents[next_id]

            if isinstance(next_infra, Sink): #Check whether vehicle reaches a sink, remove if true
                self.arrive_at_next(next_infra, 0)
                next_infra.remove(self)
                return

            if isinstance(next_infra, Bridge) and next_infra.is_broken: #Check if vehicle reaches a bridge, delay if bridge is broken
                delay = self.get_delay_time_for_broken_bridge(next_infra)
                if delay > 0:
                    next_infra.total_delay_caused += delay
                    self.arrive_at_next(next_infra, 0)
                    self.waiting_time = delay
                    self.state = Vehicle.State.WAIT
                    return

            seg_len = float(getattr(next_infra, "length", 0) or 0)

            if seg_len <= 0:
                self.arrive_at_next(next_infra, 0)
                remaining -= 1e-6
                continue

            travelled = min(remaining, seg_len)
            self.distance_travelled += travelled

            if remaining < seg_len:
                self.arrive_at_next(next_infra, remaining)
                return
            else:
                self.arrive_at_next(next_infra, seg_len)
                remaining -= seg_len

    def get_delay_time_for_broken_bridge(self, bridge) -> int:
        L = float(getattr(bridge, "length", 0) or 0)

        if L > 200: #Bridge delays
            return int(self.model.random.triangular(60, 120, 240))
        elif 50 <= L <= 200:
            return int(self.model.random.randint(45, 90))
        elif 10 <= L < 50:
            return int(self.model.random.randint(15, 60))
        elif 0 < L < 10:
            return int(self.model.random.randint(10, 20))
        return 0

    def arrive_at_next(self, next_infra, location_offset):
        self.location.vehicle_count -= 1
        self.location = next_infra
        self.location_offset = location_offset
        self.location.vehicle_count += 1
        self.model.space.move_agent(self, next_infra.pos)
