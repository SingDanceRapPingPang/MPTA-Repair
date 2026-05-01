// property 1
// reason: The controller may raise the gate only when no train is still counted in the crossing.
A[] not (controller.controller3 && cnt>0)

// property 2
// reason: A train cannot already be inside the crossing while the gate is still closing.
A[] not (gate.gate1 && (train(1).train2 or train(1).train3))

// property 3
// reason: If the gate is open, an approaching train remains within the safe approach window.
A[] not (train(1).train1 && gate.gate0) or (train(1).x <= 2)
