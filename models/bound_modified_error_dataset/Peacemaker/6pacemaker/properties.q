// property 1
// reason: The upper-rate interval prevents ventricular pacing faster than the clinical bound.
A[] not PURI_test.interval or (PURI_test.t >= TURI)

// property 2
// reason: The atrioventricular interval must trigger ventricular support within TAVI.
A[] not PAVI.AVI or (PAVI.t <= TAVI)

// property 3
// reason: The ventricular refractory period is bounded to filter early/noisy ventricular events.
A[] not PVRP.VRP or (PVRP.t <= TVRP)
