// property 1
// reason: Global sender timing bound for completing or leaving the jam/stop handling window.
A[] Sender_A.stop or Sender_A.end_jam or (A_c <= 28116)

// property 2
// reason: Collision handling must keep the jamming signal within the protocol bound.
A[] not Sender_A.jam or (A_c <= 25000)

// property 3
// reason: The bus output update phase must respect the physical output-delay bound.
A[] not Sender_B.newPn or (B_c <= 40)
