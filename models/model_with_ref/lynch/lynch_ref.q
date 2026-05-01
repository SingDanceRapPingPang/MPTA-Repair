// 论文第5节 Algorithm 3 给出时间上界 (2C+10)c₂（Lemma 5.4）。模型中 T=16 是 delay 参数，对应论文中的 pause(delay)。进程在 L2 状态执行写操作后必须等待至多 T 个时间单位（delay窗口）才能继续，这是协议利用时序保证互斥的关键机制。L2 状态的时钟约束 c≤T=16 是协议时序参数的直接体现：进程在 L2 阶段的停留时间不得超过 T。
// 来源：Section 4 "The Timing-Based Case" 中 Algorithm 2 的 pause(delay) 机制，以及 Section 5 Lemma 5.4 中时间上界的推导，delay 参数 T=16 直接来自模型常量。
A[] not P(1).L2 or (P(1).c <= T)
// 论文第5节 Algorithm 3 的出口区（exit region）由 L8（y:=0）和 L9（x:=0）构成，出口区同样受时序约束。Lemma 5.4 表明在满足时序约束 [c1,c2] 的条件下，出口区的执行时间也有上界。模型中 L8 和 L9 的不变式均为 c≤T=16，说明进程在出口区各阶段的停留时间不超过 T，这体现了论文对出口区有界完成（Weak Deadlock-Freedom）的要求。
// 来源：Section 2 "Weak Deadlock-Freedom: exit region terminates" 以及 Section 5 Lemma 5.3/5.4 对出口区时间有界性的保证，T=16 为模型时序参数。
A[] not P(1).L8 or (P(1).c <= T)
// 论文第4节 Lemma 4.2 的不变式 I2 指出：当进程 i 处于 pause（等待）阶段（即 L3，对应 Algorithm 3 的 pc=2.d）且 x=i 时，任何仍在 L（即 L1/L2）的进程 j 的 ltime(j) 必须小于 ftime(i)+(delay-d)c1，即进程在等待阶段的时钟值有严格约束。模型中 L5 对应 Algorithm 3 的第4步（if y≠0 then goto L），进入 L5 之前需完成 delay 等待，L5 的时钟约束 c≤T=16 保证了这一阶段的时间有界性。两个进程同时处于 L5（尝试区后期）时，它们的时钟均不应超过 T。
// 来源：Section 4 Lemma 4.2 不变式 I2 对 pause 阶段时序的约束，以及 Section 5 Algorithm 3 第4-6步的时序互动关系，T=16 为协议时序参数。
A[] not P(1).L5 or (P(1).c <= T)