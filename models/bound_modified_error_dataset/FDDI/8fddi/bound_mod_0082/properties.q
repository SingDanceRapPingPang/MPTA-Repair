// property 1
// reason: Station 1 must receive token access within the bounded ring-access time.
A[] (ST1.x <= 140)

// property 2
// reason: The token ring must not allow both stations to transmit at the same time.
A[] (ST1.station_z_idle or ST1.station_y_idle) or (ST2.station_z_idle or ST2.station_y_idle)

// property 3
// reason: A station's continuous token possession is limited by the target rotation time.
A[] not (ST1.station_z_idle or ST1.station_y_idle) imply (ST1.x <= 120)
