// property 1
// reason: A process may enter the critical section only after the required minimum delay.
A[] P(1).cs imply P(1).x >= 64

// property 2
// reason: The request phase respects the maximum write-delay bound.
A[] P(1).req imply P(1).x <= 32
