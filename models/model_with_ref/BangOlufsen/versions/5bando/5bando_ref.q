// property 1
// source: models\model_with_ref\BangOlufsen\5bando.xml
A[] Sender_A.stop or Sender_A.end_jam or (A_c <= 28116)

// property 2
//分析：来源于论文 3.2 节的协议语法说明和 3.3 节的 Collision Handling Rule（冲突处理规则）。
//分析：协议规定，当组件发生短于3个周期的冲突时，必须发出一个持续 25ms（即 25000µs）的阻塞信号（jamming signal）。该时间安全性性质断言，只要发送方A处于发出阻塞信号的阶段（jam状态），其用于计时的局部时钟 A_c 绝对不能超过 25000µs。这在物理层面上保障了系统能够准时撤销干扰电平，防止总线因超时被永久占用的危险。
// source: models\model_with_ref\BangOlufsen\bando_ref.q
A[] not Sender_A.jam or (A_c <= 25000)

// property 3
//分析：来源于论文 3.3 节的 Bus Output Rule（总线输出规则）以及 4.5 节的 Transmission phase 描述。
//分析：由于物理总线状态翻转需要时间，协议严格要求发送方在进行总线采样与输出之间必须有一个物理输出延迟（Output-delay），在模型中被精确估算并建模为 40µs。该性质指出，只要发送方B处于准备向总线写入新数据的短暂等待期（newPn状态），其等待时钟 B_c 必然受到 40µs 的严格上限约束。这保证了硬件电平驱动的物理时间安全性。
// source: models\model_with_ref\BangOlufsen\bando_ref.q
A[] not Sender_B.newPn or (B_c <= 40)

// property 4
//分析：来源于论文 4.5 节 Initialization phase（初始化阶段）中的 Frame Initialization Rule（帧初始化规则）。
//分析：协议要求，在发送方确认总线未被他人预留（T5信号检查通过）后，还需要再等待2个完整的周期（2*1562µs = 3124µs），其中前 2343µs 为静默等待期（对应 ex_silence1 状态）。该时间安全性性质断言，发送方A在 ex_silence1 状态下的局部时钟 A_c 绝对不能超过 2343µs。这从时间自动机状态可达性的角度，严格验证了初始化阶段退避时间的物理精确性，防止由于时钟漂移或逻辑错误导致的过早/过晚总线采样。
// source: models\model_with_ref\BangOlufsen\bando_ref.q
A[] not Sender_A.ex_silence1 or (A_c <= 2343)
