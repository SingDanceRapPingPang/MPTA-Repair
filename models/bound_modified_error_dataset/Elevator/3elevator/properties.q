// property 1
// reason: The door idle interval stays inside the modeled open/close timing window.
A[] not Door.idle or (x>=2 and x<=5)

// property 2
// reason: The elevator cannot report the first-floor state before the minimum travel delay.
A[] not Elevator.First_Floor or (x>=2)
