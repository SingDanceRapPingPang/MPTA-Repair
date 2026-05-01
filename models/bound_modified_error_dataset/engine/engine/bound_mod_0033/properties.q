// property 1
// reason: Normal gear changes must complete within the one-second industrial requirement.
A[] not GearControl.GearChanged or ErrStat != 0 or UseCase != 0 or (SysTimer <= 1000)

// property 2
// reason: All recoverable gear-change scenarios must satisfy the absolute response bound.
A[] not GearControl.GearChanged or ErrStat != 0 or (SysTimer <= 1500)

// property 3
// reason: Zero-torque failure recovery must complete within the derived fault-tolerant bound.
A[] not GearControl.GearChanged or ErrStat != 0 or UseCase != 1 or (SysTimer <= 1055)
