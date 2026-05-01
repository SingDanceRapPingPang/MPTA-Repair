// property 1
// source: models\model_with_ref\Peacemaker\6Pacemaker.xml
A[] not Pvv.two_a or (Pvv.t <= TLRI)

// property 2
// 论文第4.2节描述了上限心率（Upper Rate Limit）安全性要求："We require that a ventricle pace (VP) can only occur at least TURI after a ventricle event (VS, VP)"。模型中 URI_test 组件的 interval 状态（PURI_test.interval）是一个 committed 位置，在检测到 VP 后立即计算与上一心室事件的时间间隔。此时钟 t 记录自上一心室事件（VS或VP）至当前 VP 的时间差，该值必须大于等于 TURI=400，即起搏器不能以超过上限心率的速度起搏心室。
// 来源：Section 4.2 "Upper Rate Limit" — "the property A[] (PURI_test.interval imply PURI_test.t >= TURI) is satisfied by the basic DDD pacemaker model"，TURI=400ms为上限心率间隔参数。
// source: models\model_with_ref\Peacemaker\pacemaker_ref.q
A[] not PURI_test.interval or (PURI_test.t >= TURI)

// property 3
// 论文第3.3节描述了AVI组件（房室间隔）的功能："It defines the longest interval between an atrial event and a ventricular event. If no ventricular event has been sensed within TAVI after an atrial event, the component will deliver ventricular pacing (VP)"。AVI 组件处于 AVI 状态（正在等待心室感知或起搏）时，其时钟 t 不应超过 TAVI=150ms，否则应已触发 VP。这一约束直接体现了 A-V 同步的时间安全性——心房激活后最多 TAVI 时间内必须发生心室激活，以维持正常心脏泵血功能。
// 来源：Section 3.3 "AVI component" — "defines the longest interval between an atrial event and a ventricular event...deliver VP after TAVI"，TAVI=150ms为临床参数。
// source: models\model_with_ref\Peacemaker\pacemaker_ref.q
A[] not PAVI.AVI or (PAVI.t <= TAVI)

// property 4
// 论文第3.3节描述了PVARP组件："After each ventricular event, there is a blanking period (PVAB) followed by a refractory period (PVARP) for the atrial events"。PVAB 阶段（PPVARP.PVAB）持续时间严格限定为 TPVAB=50ms，用于过滤心室事件后的近场噪声。若 PVAB 阶段时钟超过 TPVAB，说明心室后心房消隐期机制异常，可能导致噪声被误识别为心房信号，进而引发不适当的起搏。
// 来源：Section 3.3 "PVARP and PVAB" — "there is a blanking period (PVAB) followed by a refractory period"，TPVAB=50ms为消隐期参数。
// source: models\model_with_ref\Peacemaker\pacemaker_ref.q
A[] not PPVARP.PVAB or (PPVARP.t <= TPVAB)

// property 5
// 论文第3.3节描述了VRP组件（心室不应期）："the VRP follows each ventricular event (VP, VS) to filter noise and early events in the ventricular channel which could otherwise cause undesired pacemaker behavior"。VRP 阶段（PVRP.VRP）持续时间为 TVRP=150ms，在此期间心室通道的任何感知信号均被视为噪声而忽略。若 VRP 状态下时钟超过 TVRP，说明不应期机制出现异常，可能无法正确过滤噪声，影响起搏器对真实心室信号的识别。
// 来源：Section 3.3 "VRP component" — "VRP follows each ventricular event to filter noise...Fig.3(e) shows the UPPAAL design of VRP component"，TVRP=150ms为心室不应期参数。
// source: models\model_with_ref\Peacemaker\pacemaker_ref.q
A[] not PVRP.VRP or (PVRP.t <= TVRP)
