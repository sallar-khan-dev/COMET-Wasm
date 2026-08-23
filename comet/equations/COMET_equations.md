# COMET-Wasm Equations

P(m) = <C_m, M_m, L_m, T_m, S_m, D_m, K_m>

Suitability(m,b) = w_C Fit_C(m,b) + w_M Fit_M(m,b) + w_L Fit_L(m,b) + w_T Fit_T(m,b) + w_K Fit_K(m,b) - w_X SwitchCost(m,b)

COMETScore(m,b) = λ1 C_m R_b + λ2 M_m A_b + λ3 T_m Q_b + λ4 L_m S_b + λ5 K_m H_b

b* = argmax_b COMETScore(m,b)
subject to Memory_b <= Budget, p95_b <= SLA_latency, Tenants_b <= Capacity_b
