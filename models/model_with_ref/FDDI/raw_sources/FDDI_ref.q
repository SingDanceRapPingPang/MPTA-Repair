A[] (ST1.x <= 140)
//分析：根据论文 4.2 节提到的 "Bounded time for accessing the ring"，即任何站点两次连续接收令牌之间的时间间隔均受到理论常数 c1 的限制。示例性质中给出了针对 ST1 的界限，依据网络令牌环的对称性，节点 ST2 中负责记录“自上次收到令牌起流逝时间”的时钟 x 也必须受到同样的全局时间安全性限制（在当前 N=2, TRTT=120, SA=20 的配置下，最紧确的全局安全上限为 140）。这保证了网络节点的通信公平性和最差响应时间。
A[] (ST2.x <= 140)
//分析：根据论文 4.1 节 Token Ring Local Area Network 的基本网络物理拓扑原理，令牌环网络的核心安全要求是：在任何绝对时间点上，只能有一个站点拥有令牌并执行数据传输。在时间自动机模型中，站点处于 sync（同步传输）或 async（异步传输）代表其正独占令牌，而 idle 状态代表交出令牌并等待。因此，系统必须保证 ST1 和 ST2 不能同时处于非 idle 状态，这是避免物理信道数据碰撞的根本安全性约束。
A[] (ST1.station_z_idle or ST1.station_y_idle) or (ST2.station_z_idle or ST2.station_y_idle)
//分析：论文第 4 节开头明确指出，该验证的一大核心机制是限制每个站点对令牌的最大连续占有时间（"limits the possession time of the token by each station"）。在模型中，时钟 x 会在站点获取令牌离开 idle 状态时重置为 0。因此，只要站点处于传输状态（非 idle），此时的 x 就精确度量了其单次占用令牌的时间。按照 FDDI 协议，站点每次占用的总时间绝对不能超过目标令牌旋转时间 TTRT（在模型中定义为常量 TRTT = 120）。
A[] not (ST1.station_z_idle or ST1.station_y_idle) imply (ST1.x <= 120)
//分析：根据论文 4.1 节对 Token Holding Timer (THT) 和 Token Rotation Timer (TRT) 机制的描述，协议不仅要限制单次发送的时间，还要保证“等待获取令牌的时间”是有界的（Bounded time for accessing the ring）。在给定的时间自动机模型中，当 ST1 处于闲置状态（例如 station_z_idle）等待令牌时，系统整体的时间推进不能无限期停滞。时钟 y 和 z 分别交替作为记录令牌轮转周期的计时器。为了保证系统的有界响应性（即不存在导致某个站无限期饥饿的死锁或活锁），我们可以断言处于闲置状态的站点其等待时间必然受到全局上限参数的约束（在 N=2 的网络下理论最大轮转等待时间不会超过公式给定的 c1 界限，依据模型具体常量可缩紧为确定的常数，这里为了安全性断言，设定不应超过 TTRT + 2NSA = 120 + 80 = 200）。
性质：A[] (ST1.station_z_idle imply ST1.y <= 200)