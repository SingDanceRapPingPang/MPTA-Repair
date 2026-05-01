// property 1
// reason: Two senders cannot remain in simultaneous transmission beyond the collision window.
A[] not P1.sender_transm or not P2.sender_transm or (P1.x < 52)

// property 2
// reason: The medium must detect and propagate collision information within the bus-delay bound.
A[] not P0.bus_collision1 or (P0.x < 26)

// property 3
// reason: Transmission overlap with P2 is bounded by the collision detection window.
A[] not P1.sender_transm or (p2t == 0) or (P1.x < 52)
