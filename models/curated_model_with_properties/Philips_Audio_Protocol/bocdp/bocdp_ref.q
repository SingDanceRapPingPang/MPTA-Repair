// property 1
// reason: Concurrent transmission is bounded by the half-bit-slot collision window.
A[] not Sender_A.transmit or not Sender_B.transmit or (A_c <= 781)

// property 2
// reason: The radio-silence hold phase must finish within the protocol timeout.
A[] not Sender_A.hold or (A_c <= 28116)

// property 3
// reason: Collision jamming is bounded so the bus is not occupied indefinitely.
A[] not Sender_A.jam or not Sender_B.jam or (A_c <= 25000)
