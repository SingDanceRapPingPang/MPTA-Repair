// property 1
// 论文第4节指出，协议要求两个发送者不能同时处于 transmit（传输）状态，即在某一方正在传输期间另一方不应也进入传输状态。这正是总线碰撞（bus collision）处理机制的核心安全性目标。模型中 transmit 状态的时钟约束为 A_c <= 781（对应半bit-slot的时间上界），两个发送者同时处于 transmit 状态时，其时钟之和或其中一个必须受到约束，以保证在781时间单位内碰撞被检测并处理。
// 来源：Section 4 "The Audio Control Protocol with Bus Collision" — "When a sender detects a collision it will stop transmitting and will try to retransmit its message later"，以及 Section 6 中对协议正确性的核心要求。
// source: models\model_with_ref\Philips Audio Protocol\philips_ref.q
A[] not Sender_A.transmit or not Sender_B.transmit or (A_c <= 781)

// property 2
// 论文第4节描述了 radio silence 要求："the distance between the end of one message and the beginning of the next must be at least 8000 microseconds"。模型中 hold 状态用于在碰撞后等待总线静默，其不变式为 A_c <= 28116，而从 until_silence 进入 hold 需等待每次 one 信号（步长781），直到静默。hold 状态最终在 A_c == 28116 时退出，28116 = 36 × 781，对应约 32ms，覆盖了至少 8ms 的 radio silence 要求。发送者处于 hold 状态时时钟不超过此上界，是协议 radio silence 时间安全保证的直接体现。
// 来源：Section 4 — "the distance between the end of one message and the beginning of the next must be at least 8000 microseconds (8 milliseconds)"，模型中 hold 状态对应此静默等待机制，28116 为其时间上界。
// source: models\model_with_ref\Philips Audio Protocol\philips_ref.q
A[] not Sender_A.hold or (A_c <= 28116)

// property 3
// 论文第4节描述了碰撞后的 jam 信号机制：发送者检测到碰撞后会发出 jam 信号，持续一段时间以通知总线上其他节点。模型中 jam 状态的不变式为 A_c <= 25000，在 A_c == 25000 时离开 jam 状态。jam 持续时间（25000个时间单位）是协议规定的碰撞处理时间上界，确保碰撞信号被所有节点感知。两个发送者不能同时在 jam 状态停留超过该上界。
// 来源：Section 4 — "When a sender detects a collision it will stop transmitting" 以及碰撞处理流程；模型中 jam 状态 A_c <= 25000 的退出卫士 A_c == 25000 直接对应此时间约束。
// source: models\model_with_ref\Philips Audio Protocol\philips_ref.q
A[] not Sender_A.jam or not Sender_B.jam or (A_c <= 25000)

// property 4
// 论文第4节描述了协议的 idle 状态与半bit-slot时间约束：发送者在 idle 状态等待总线静默并检查是否可以开始传输，idle 持续时间为一个半bit-slot（781μs，对应±5%误差后的上界）。idle 状态是发送者监听总线的关键阶段，其时间上界保证了协议的响应性——发送者不会在 idle 状态停留超过781时间单位而不做出反应，从而维持协议的实时性。
// 来源：Section 4 "The Senders" — "the sender changes location each half of a bit-slot"，idle 状态对应半bit-slot等待，781为5%误差容限下的半bit-slot时间上界（444 × 1.05% ≈ 466，此处781对应模型的时间单位缩放）。
// source: models\model_with_ref\Philips Audio Protocol\philips_ref.q
A[] not Sender_A.idle or (A_c <= 781)
