// CSMA/CD 协议规定，节点在发送帧之前必须先侦听信道，确认信道空闲后才能发送。参考文献中描述了节点从空闲(idle)状态等待信道空闲的过程，以及 DIFS（分布式帧间间隔）的等待时间要求。在模型中，sender 从 wait 状态进入 transm（传输）状态前，需要经过至少一个传播延迟（λ=1）的等待，即节点不应在还未等待足够时间的情况下就开始发送。
// 来源：论文中"A node listens before transmitting; if the channel is sensed idle for a DIFS period, the node transmits."以及模型中 wait→transm 的卫士条件 x==λ（λ=1）。
A[] not P1.sender_transm or (P1.x <= 52)
// 这条已存在，作为基准参考。以下为新增性质：
// CSMA/CD 协议要求，当发生碰撞时，冲突帧的传播时间不超过两倍的最大传播延迟（2λ）。模型中碰撞（collision）检测发生在 transm 状态，碰撞后进入 jam 状态发送干扰信号。根据参考文献，碰撞最迟在 2λ 时刻内必然被所有节点检测到。模型中 λ=1，因此碰撞检测时钟 x 在进入 jam 之前不应超过 2λ=2。
// 来源：论文"Collision detection: a transmitting node detects a collision within 2λ time units"，以及模型 transm→collision_detected 迁移上的卫士 x < 2λ。
A[] not P1.sender_collision_detected or (P1.x <= 2)
// 根据 CSMA/CD 协议，退避（backoff）阶段的持续时间受退避计数器上限约束。模型中 backoff 状态使用时钟 x 计时，退避时间最多为 Bλ（B 为退避上限，模型中 B=52，λ=1）。节点在 backoff 状态中的等待时间不能超过最大退避时间 B=52，否则说明退避机制失效。
// 来源：论文中"After a collision, a node waits a random backoff time in [0, B] before retrying"，以及模型 backoff 状态的不变式 x <= B 和参数 B=52。
A[] not P1.sender_backoff or (P1.x <= 52)
// 在 CSMA/CD 协议中，两个节点不能同时处于碰撞检测（collision_detected）状态超过 jam 信号持续时间（J，模型中 J=8）。jam 信号的目的是确保所有节点都能感知到碰撞，其持续时间有严格上限。若某节点在 collision_detected 后等待时间超过 J，则 jam 机制违例。
// 来源：论文"After detecting a collision, the node transmits a jam signal of duration J to ensure all nodes are aware of the collision"，模型中 collision_detected→jam 的卫士 x==J（J=8）。
A[] not P1.sender_collision_detected or (P1.x <= 8)
// CSMA/CD 协议保证，在任意时刻，两个发送节点不能同时处于 jam（干扰）状态超过 jam 持续时间 J=8。jam 状态是碰撞后强制广播的短暂状态，两个节点同时 jam 的时间窗口不能无限延伸，必须在 J 时间单位内结束。
// 来源：论文"The jam signal duration is J time units; after jamming, nodes enter backoff"，以及模型 jam 状态不变式 x <= J（J=8）。
A[] not P1.sender_jam or not P2.sender_jam or (P1.x <= 8)
现在我已经完整读取了两个文件，可以进行深入分析。以下是基于参考文献内容分析得出的时间安全性性质：
// 参考文献第4.1节指出，碰撞避免的核心正确性准则是：协议在任何情况下都不应进入 medium.col（碰撞）状态。模型中 P0（总线自动机）从 bus_collision1 迁移到 bus_collision2 的过渡上使用了时钟约束 x < 26，即碰撞信号的传播必须在26个时间单位内完成（对应总线传播延迟上限）。两个发送者同时处于 bus_collision1 时，时钟 x 不应超过该上限。
// 来源：Section 4.1 "Collision Avoidance Verification" — 碰撞检测必须在有界时间内完成，模型中 bus_collision1 的不变式为 x < 26。
A[] not P0.bus_collision1 or (P0.x < 26)
// 参考文献第1.2节明确要求协议具有"已知的传输延迟上界"（a known upper bound on the transmission delay）。模型中 P1/P2 的 sender_transm 状态不变式为 x <= 808，即单次帧传输最长持续808个时间单位。两个发送者不能同时处于传输状态超过52个时间单位（碰撞检测窗口），这正是现有性质的语义。对称地，P2 也应满足同样约束。
// 来源：Section 1.2 "Protocol Properties" — "there is a known upper bound on the transmission delay"，以及模型中 sender_transm → sender_retry 的碰撞检测卫士 x < 52。
A[] not P1.sender_transm or not P2.sender_transm or (P2.x < 52)
// 参考文献第3.3节描述了总线（Medium）收到消息后延迟一个时间单位再广播的机制："the medium delays the message for one time unit and then it starts broadcasting"。模型中 P0 在 bus_active 状态下，当 x >= 26 时才发出 busy 信号通知其他节点信道忙碌。这意味着总线从进入 bus_active 到发出 busy 信号的时间不超过26个时间单位，即 bus_active 状态下时钟 x 不会无限增长而不触发 busy。
// 来源：Section 3.3 "The Medium Timed Automaton" — 总线延迟广播机制，以及模型 bus_active 上的自循环卫士 x >= 26。
A[] not P0.bus_active or (P0.x <= 808)
// 参考文献第3.4节描述了从节点（Slave）在退避（retry）阶段的行为：碰撞后节点进入退避等待，退避时间有上界约束。模型中 sender_retry 状态的不变式为 x < 52，即退避等待时间严格小于52个时间单位。两个发送者不应同时长期滞留在退避状态，即它们在 retry 状态中的时钟之和逻辑上受约束。单个节点的退避时间上界可直接表达为：任意时刻 P1 处于 retry 状态时，其时钟必须小于52。
// 来源：Section 1.2 "Protocol Properties" — 退避重传机制保证最终传输成功，以及模型 sender_retry 不变式 x < 52。
A[] not P1.sender_retry or (P1.x < 52)
// 参考文献第4.3节验证了协议的往返时间（Round-Trip Time）存在上界，具体验证了"在18个时间单位内完成一次完整往返"。模型中完整传输周期为：sender_wait → sender_transm（x==808结束）→ 发出 end 信号。P2 进入传输状态时会设置共享变量 p2t=1，退出时设置 p2t=0。在 P2 处于传输状态（p2t==1）时，P1 不应同时处于传输状态超过52时间单位（碰撞窗口），这是对共享介质互斥访问的时间安全保障。
// 来源：Section 4.3 "Round-Trip Time Verification" — 验证往返时间上界存在性，以及模型变量 p2t 标记 P2 正在传输时的互斥约束。
A[] not P1.sender_transm or (p2t == 0) or (P1.x < 52)