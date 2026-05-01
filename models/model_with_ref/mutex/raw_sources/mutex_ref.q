// 论文第8节描述了改进后的协议：控制器在 Wait 状态（wait_for_s1/wait_for_s2）引入了 ε1+εC 秒的延迟，以确保充分观察对方节点的安全状态后才发出授权。模型中，Ctrl 从 wait_for_s2 进入 g1 的条件为 Ctrl_y0 >= 2000，即控制器必须连续观察 S2 处于 safe 状态至少 2000 个时间单位。这意味着控制器在 wait_for_s2 状态中，Ctrl_y0 的增长受 Ctrl_z 约束，每个轮询周期 Ctrl_z 不超过 1000。Ctrl 处于等待状态（wait_for_s2 或 wait_for_s1）时，其轮询周期时钟 Ctrl_z 不应超过周期上界 1000。
// 来源：Section 8 "An improved protocol" — "introducing delays for the waiting states...the delay of εi + εC seconds for state Wi"，以及模型中 Ctrl_y0 >= 2000 的授权门槛体现了此延迟要求。
A[] not Ctrl.wait_for_s2 or (Ctrl.Ctrl_z <= 1000)
// 论文第7.1节的反例分析（Fig. 6）揭示：当控制器处于 G1（grant1 已授权给 S1）状态时，若 S1 在极短时间（< ε1）内从 safe 切换到 unsafe，控制器可能误判 S1 仍处于 safe 而提前退出 W1 状态并进入 G2，导致互斥违例。改进后的协议要求控制器在 g1 状态中需持续监测 S1 的状态，g1 状态的轮询周期同样受 Ctrl_z <= 1000 约束。这保证了控制器在持有授权期间能够及时感知被授权方的状态变化。
// 来源：Section 7.1 的反例分析与 Fig. 6 — 控制器在 G1 状态停留时间过短导致误判；Section 8 改进方案要求在 grant 状态也保持足够的观测周期以确保安全。
A[] not Ctrl.g1 or (Ctrl.Ctrl_z <= 1000)
// 论文第2节描述了PLC轮询系统的循环机制：每个轮询周期由 poll、test、tick 三个阶段构成，整个周期必须在 ε 时间内完成（"a cycle...has to happen within ε s"）。模型中 S1 的每个轮询周期由 S1_IntStat 从0→1→0 的状态转换驱动，周期时钟 S1_z 在每次周期结束时被重置为0，其不变式为 S1_z <= 1000。S1 处于安全状态（I_am_safe）时，其轮询周期时钟不应超过周期上界，确保 S1 能及时响应来自控制器的授权信号（Ctrl_grant1）。
// 来源：Section 2 "PLC-Automata" — "there is an upper bound for a cycle...The upper time bound for cycles is the main key to verify such properties"，以及 Definition 1 中 ε 作为轮询周期上界的核心参数。
A[] not S1.I_am_safe or (S1.S1_z <= 1000)