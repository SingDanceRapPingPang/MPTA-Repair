// property 1
// reason: The controller's waiting phase must respect the PLC polling-cycle upper bound.
A[] not Ctrl.wait_for_s2 or (Ctrl_z <= 1000)

// property 2
// reason: The grant-monitoring phase must keep observing the granted station within a cycle.
A[] not Ctrl.g1 or (Ctrl_z <= 1000)

// property 3
// reason: Station S1's local polling cycle remains within the configured PLC cycle time.
A[] not S1.I_am_safe or (S1_z <= 1000)
