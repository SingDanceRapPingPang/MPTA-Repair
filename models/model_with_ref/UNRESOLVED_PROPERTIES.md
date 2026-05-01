# unresolved properties

The following properties could not be verified as satisfied and no verified replacement was found automatically.

| Family | Version | Index | Status | Formula |
| --- | --- | ---: | --- | --- |
| BangOlufsen | 5bando | 2 | not_satisfied | `A[] Sender_B.stop or Sender_B.end_jam or (B_c <= 28116)` |
| csma_cd | 2csma | 2 | not_satisfied | `A[] not P1.sender_transm or (P1.x <= 52)` |
| csma_cd | 2csma | 3 | error | `A[] not P1.sender_collision_detected or (P1.x <= 2)` |
| csma_cd | 2csma | 4 | error | `A[] not P1.sender_backoff or (P1.x <= 52)` |
| csma_cd | 2csma | 5 | error | `A[] not P1.sender_collision_detected or (P1.x <= 8)` |
| csma_cd | 2csma | 6 | error | `A[] not P1.sender_jam or not P2.sender_jam or (P1.x <= 8)` |
| Elevator | qostream_qos | 1 | timeout | `A[] Source.SEND imply x>=50` |
| Elevator | qostream_qos | 2 | timeout | `A[] Reciever.OK imply y>=5` |
| Elevator | qostream_qos | 3 | not_satisfied | `A[] not deadlock` |
| FDDI | 8fddi | 5 | not_satisfied | `A[] (ST1.station_z_idle imply ST1.y <= 200)` |
| TarTarRepairedDB | 0db2 | 1 | not_satisfied | `A[] not dbServer.serReceiving or (x <= 4)` |
