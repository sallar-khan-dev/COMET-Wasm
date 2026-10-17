"""Approval-only constraint-first admission policy. Does not import or replace the existing scheduler.
Inputs are measured sparse anchor tables; unsupported ranges fail closed.
"""
from dataclasses import dataclass
from bisect import bisect_right
import math

class UnsupportedOperatingPoint(ValueError):
    pass

@dataclass(frozen=True)
class Estimate:
    memory_mib: float
    p95_ms: float
    capacity_rps: float
    error_rate: float = 0.0

def interpolate(anchors, x, *, log_x=False):
    """Piecewise linear interpolation, no extrapolation; anchors keyed by numeric coordinates."""
    pts=sorted((float(k),float(v)) for k,v in anchors.items())
    if not pts or x < pts[0][0] or x > pts[-1][0]:
        raise UnsupportedOperatingPoint(f'{x} outside measured [{pts[0][0]}, {pts[-1][0]}]' if pts else 'missing anchors')
    for k,v in pts:
        if x==k: return v
    i=bisect_right([a for a,_ in pts],x)
    x0,y0=pts[i-1]; x1,y1=pts[i]
    if log_x:
        if min(x,x0,x1)<=0: raise ValueError('log interpolation requires positive load')
        x,x0,x1=map(math.log2,(x,x0,x1))
    return y0+(y1-y0)*(x-x0)/(x1-x0)

def decide(profiles, model, offered_rps, tenants, memory_budget_mib, sla_p95_ms, *, max_error_rate=0.0):
    """Profiles: {model:{backend:{'memory_by_tenant':{},'p95_by_rate':{},'capacity_by_rate':{},'error_rate':0}}}.
    Capacity curve and P95 curve are valid only for their characterised tenant regime.
    The caller MUST supply matching tenant-conditioned curves; otherwise reject as unsupported.
    """
    if offered_rps<=0 or tenants<1 or memory_budget_mib<=0 or sla_p95_ms<=0: raise ValueError('invalid context')
    candidates=[]
    for backend, profile in profiles.get(model,{}).items():
        reasons=[]; est=None
        try:
            memory=interpolate(profile['memory_by_tenant'],tenants)
            # Nested curves keyed by tenant count; avoid silently using one density's latency at another.
            p95=interpolate({n:interpolate(curve,offered_rps) for n,curve in profile['p95_by_tenant_and_rate'].items()},tenants)
            capacity=interpolate({n:interpolate(curve,offered_rps) for n,curve in profile['capacity_by_tenant_and_rate'].items()},tenants)
            error=float(profile.get('error_rate',0))
            est=Estimate(memory,p95,capacity,error)
            if memory>memory_budget_mib: reasons.append('memory')
            if p95>sla_p95_ms: reasons.append('p95_sla')
            if capacity<offered_rps: reasons.append('insufficient_capacity')
            if error>max_error_rate: reasons.append('error_rate')
        except (KeyError,ValueError,TypeError) as e:
            reasons.append('unsupported_profile: '+str(e))
        candidates.append({'backend':backend,'estimate':est,'feasible':not reasons,'reasons':reasons})
    feasible=[c for c in candidates if c['feasible']]
    winner=min(feasible,key=lambda c:(c['estimate'].memory_mib,c['estimate'].p95_ms,c['backend'])) if feasible else None
    return {'admitted':winner is not None,'backend':winner['backend'] if winner else None,'candidates':candidates,'policy':'memory_first_feasible_v2'}
