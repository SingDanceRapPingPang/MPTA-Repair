性质2：
// 来源：论文 Section 3.1，控制器响应时间约束
// 论文指出控制器响应时间有上界 f，下界 e；模型中 z<=e 且转换条件 z==e
// 即控制器在 controller1 状态（已收到 approach，尚未发出 lower）停留时间不超过 e=1
A[] not controller.controller1 or (controller.z <= 1)
性质3：
// 来源：论文 Section 3.1，列车发出 approach 信号到实际进入道口之间，gate 必须已关闭
// 模型中 train 从 train1（x<=b）经 x>a 才进入 train2；gate 关闭延迟 <=c=1；controller 延迟 ==e=1
// 因此当 gate 正处于下降过程中（gate1，y<=c=1），train 时钟 x 应仍在安全窗口内（x < a=2），尚未进入道口
// 即 gate 还在关闭时（gate1），train 不应已进入道口（train2/train3）
A[] not (gate.gate1 && (train(1).train2 or train(1).train3))
性质4：
// 来源：论文 Section 3.1，gate 的关闭响应时间约束
// 论文要求 gate 响应时间在区间 (c, d)，模型中 gate1{y<=c=1}，gate3{y<=d=2}
// 安全性：gate 开始关闭后（gate1），关闭动作必须在 c=1 时间单位内完成
A[] not gate.gate1 or (gate.y <= 1)
性质5：
// 来源：论文 Section 3.1，参数约束 γ(f) > γ(a) - γ(d) 的时间安全蕴含
// 控制器发出 lower 后（controller2 状态），gate 正在关闭（gate1），
// 此时 train 的时钟 x 满足 x <= b=5，且尚未越过 x>a=2 进入道口
// 因此当 train 处于 train1 且 x 已超过 a 的边界时，gate 应当已经关闭（gate2）
A[] not (train(1).train1 && gate.gate0) or (train(1).x <= 2)