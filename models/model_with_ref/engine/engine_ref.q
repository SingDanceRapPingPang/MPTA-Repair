// 正常情况下的最大换挡时间限制 (Normal Operation Performance Bound)
// 物理意义: 如果系统在“正常操作条件”下完成了换挡（即没有发生不可恢复的错误 ErrStat == 0，且引擎也没有发生难以达到零扭矩等可恢复错误 UseCase == 0），从换挡请求发起（SysTimer被重置）到最终完成的总耗时必须小于等于1000毫秒（1秒）。
// 论文来源: Section 4.1 Requirements -> 1. Performance -> (b) "A gear change, under normal operation conditions, should be performed within 1 second." 以及 Section 6.1 Formula (2)。
A[] not GearControl.GearChanged or ErrStat != 0 or UseCase != 0 or (SysTimer <= 1000)
// 包含可恢复错误时的绝对最大换挡时间 (Absolute Maximum Bounded Response)
// 物理意义: 只要车辆环境组件没有发生“不可恢复的致命错误”（ErrStat == 0），即使遇到了恶劣工况（如强制启动离合器换挡，即 UseCase > 0），换挡控制器也必须保证在1500毫秒（1.5秒）内强行完成换挡，防止车辆失去动力时间过长。
// 论文来源: Section 4.1 Requirements -> 1. Performance -> (a) "A gear change should be completed within 1.5 seconds." 以及 Section 6.1 Formula (1)。
A[] not GearControl.GearChanged or ErrStat != 0 or (SysTimer <= 1500)
// 引擎零扭矩故障应对的时间确界 (Fault-Tolerant Timing for Zero Torque Failure)
// 物理意义: 当发生“可恢复错误 1”（引擎试图降扭矩但超时失败，即 UseCase == 1）时，齿轮控制器会主动介入并断开离合器。此时整个系统的容错换挡事务总耗时应当被严格约束在1055毫秒之内。
// 论文来源: Section 6.1 Time Bound Derivation: "Similarly, for scenarios when the engine fails to deliver zero torque we derive the bound 1055 ms..."
A[] not GearControl.GearChanged or ErrStat != 0 or UseCase != 1 or (SysTimer <= 1055)