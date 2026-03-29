from mesa import Agent
from enum import Enum


# ---------------------------------------------------------------
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


# ---------------------------------------------------------------
class Bridge(Infra):
    def __init__(self, unique_id, model, length=0,
                 name='Unknown', road_name='Unknown', condition='Unknown'):
        super().__init__(unique_id, model, length, name, road_name)

        import pandas as pd
        self.condition = condition if pd.notnull(condition) else 'Unknown'

        # "Repair delay" is only applied if the bridge breaks down
        if self.length > 200:
            # Triangular(1, 2, 4) hours -> minutes
            self.repair_delay_time = int(self.random.triangular(60, 120, 240))
        elif 50 <= self.length <= 200:
            self.repair_delay_time = int(self.random.randint(45, 90))
        elif 10 <= self.length < 50:
            self.repair_delay_time = int(self.random.randint(15, 60))
        elif 0 < self.length < 10:
            self.repair_delay_time = int(self.random.randint(10, 20))
        else:
            self.repair_delay_time = 0

    def get_delay_time(self) -> int:
        """
        Scenario logic:
        - Not broken => 0 delay
        - Broken => repair_delay_time
        Breakdown probability is set on the model: model.bridge_breakdown_probs
        """
        p = self.model.bridge_breakdown_probs.get(self.condition, 0.0)
        if self.model.random.random() < p:
            return int(self.repair_delay_time)
        return 0


# ---------------------------------------------------------------
class Link(Infra):
    pass


# ---------------------------------------------------------------
class Sink(Infra):
    vehicle_removed_toggle = False

    def remove(self, vehicle):
        # mark removal time
        vehicle.removed_at_step = self.model.schedule.steps

        # compute travel time (1 tick = 1 minute)
        travel_time = vehicle.removed_at_step - vehicle.generated_at_step

        # store record for CSV export
        self.model.trip_records.append({
            "truck_id": vehicle.unique_id,
            "generated_at_step": vehicle.generated_at_step,
            "removed_at_step": vehicle.removed_at_step,
            "travel_time_min": travel_time,
            "sink_id": self.unique_id
        })

        # remove from scheduler
        self.model.schedule.remove(vehicle)

        # toggle/log
        self.vehicle_removed_toggle = not self.vehicle_removed_toggle
        print(str(self) + ' REMOVE ' + str(vehicle))


# ---------------------------------------------------------------
class Source(Infra):
    truck_counter = 0
    generation_frequency = 5
    vehicle_generated_flag = False

    def step(self):
        if self.model.schedule.steps % self.generation_frequency == 0:
            self.generate_truck()
        else:
            self.vehicle_generated_flag = False

    def generate_truck(self):
        try:
            agent = Vehicle('Truck' + str(Source.truck_counter), self.model, self)

            # set path before adding
            agent.set_path()

            if agent.path_ids is not None and len(agent.path_ids) > 0:
                self.model.schedule.add(agent)
                Source.truck_counter += 1
                self.vehicle_count += 1
                self.vehicle_generated_flag = True
                print(f"{self} GENERATE {agent}")
            else:
                print(f"Skipping {agent.unique_id}: No valid path found from {self.unique_id}")

        except Exception as e:
            print(f"Error generating truck: {e}")


# ---------------------------------------------------------------
class SourceSink(Source, Sink):
    pass


# ---------------------------------------------------------------
class Vehicle(Agent):
    # 48 km/h translated into meter per min
    speed = 48 * 1000 / 60
    step_time = 1  # 1 tick = 1 minute

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
        self.waiting_time = 0
        self.waited_at = None
        self.removed_at_step = None

    def __str__(self):
        return "Vehicle" + str(self.unique_id) + \
               " +" + str(self.generated_at_step) + " -" + str(self.removed_at_step) + \
               " " + str(self.state) + '(' + str(self.waiting_time) + ') ' + \
               str(self.location) + '(' + str(self.location.vehicle_count) + ') ' + str(self.location_offset)

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

        print(self)

    def drive(self):
        distance = Vehicle.speed * Vehicle.step_time
        distance_rest = self.location_offset + distance - self.location.length

        if distance_rest > 0:
            self.drive_to_next(distance_rest)
        else:
            self.location_offset += distance

    def drive_to_next(self, distance):
        """
        Move forward along the path using an iterative loop (no recursion).
        Guards against zero-length infrastructure causing infinite loops.
        """
        # Hard guard to prevent infinite loops in a single tick
        max_hops = 2000
        hops = 0

        remaining = distance

        while remaining > 0:
            hops += 1
            if hops > max_hops:
                # Prevent lock-up; stop the vehicle for this tick
                # (You can also raise an error if you prefer)
                self.location_offset = min(self.location_offset, self.location.length)
                return

            self.location_index += 1

            # End of path safety
            if self.location_index >= len(self.path_ids):
                return

            next_id = self.path_ids.iloc[self.location_index]
            next_infra = self.model.schedule._agents[next_id]

            # Arrive at Sink
            if isinstance(next_infra, Sink):
                self.arrive_at_next(next_infra, 0)
                next_infra.remove(self)
                return

            # Bridge delay (only if broken)
            if isinstance(next_infra, Bridge):
                delay = next_infra.get_delay_time()
                if delay > 0:
                    self.arrive_at_next(next_infra, 0)
                    self.waiting_time = delay
                    self.state = Vehicle.State.WAIT
                    return
                # no delay => continue moving

            # Guard: if length is zero (or missing), treat as tiny step forward
            seg_len = float(getattr(next_infra, "length", 0) or 0)
            if seg_len <= 0:
                # move onto it but don't consume distance; consume a tiny epsilon to progress
                self.arrive_at_next(next_infra, 0)
                remaining -= 1e-6
                continue

            if remaining < seg_len:
                # Stop within this infra
                self.arrive_at_next(next_infra, remaining)
                remaining = 0
            else:
                # Traverse entire infra and continue
                self.arrive_at_next(next_infra, seg_len)
                remaining -= seg_len

    def arrive_at_next(self, next_infra, location_offset):
        self.location.vehicle_count -= 1
        self.location = next_infra
        self.location_offset = location_offset
        self.location.vehicle_count += 1