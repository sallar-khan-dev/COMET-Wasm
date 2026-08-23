from dataclasses import dataclass
@dataclass
class ModelProfile:
    compute_intensity: float; memory_intensity: float; latency_sensitivity: float; tenant_pressure: float; model_size: float; density_sensitivity: float; cold_start_sensitivity: float
@dataclass
class BackendProfile:
    name: str; compute_capability: float; available_memory: float; tenant_capacity: float; sla_compliance: float; startup_efficiency: float; current_memory: float; current_tenants: int; p95_latency: float
@dataclass
class Constraints:
    memory_budget: float; sla_latency: float; tenant_capacity: int

def comet_score(m, b, lambdas=None):
    if lambdas is None: lambdas = [1.0, 1.0, 1.0, 1.0, 1.0]
    l1, l2, l3, l4, l5 = lambdas
    return l1*m.compute_intensity*b.compute_capability + l2*m.memory_intensity*b.available_memory + l3*m.tenant_pressure*b.tenant_capacity + l4*m.latency_sensitivity*b.sla_compliance + l5*m.cold_start_sensitivity*b.startup_efficiency

def feasible(b, c): return b.current_memory <= c.memory_budget and b.p95_latency <= c.sla_latency and b.current_tenants <= c.tenant_capacity

def select_backend(model, backends, constraints):
    candidates = [b for b in backends if feasible(b, constraints)]
    return None if not candidates else max(candidates, key=lambda b: comet_score(model, b))

if __name__ == "__main__":
    model = ModelProfile(0.2, 0.1, 0.8, 0.9, 0.1, 0.9, 0.8)
    backends = [BackendProfile("wasmtime",0.7,0.9,0.95,0.9,0.95,0.4,10,0.4), BackendProfile("docker",0.9,0.6,0.55,0.75,0.4,0.7,10,0.7), BackendProfile("wasi-nn",0.95,0.8,0.7,0.9,0.6,0.5,5,0.5)]
    selected = select_backend(model, backends, Constraints(1.0, 1.0, 20))
    print("Selected backend:", selected.name if selected else "none")
