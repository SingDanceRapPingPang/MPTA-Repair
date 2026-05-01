// property 1
// reason: The write/pause phase of the timing-based mutual exclusion protocol is bounded.
A[] not P(1).L2 or (P(1).c <= T)

// property 2
// reason: The exit region must finish within the protocol delay bound.
A[] not P(1).L8 or (P(1).c <= T)

// property 3
// reason: The late trying-region phase remains inside the timing parameter used for mutual exclusion.
A[] not P(1).L5 or (P(1).c <= T)
