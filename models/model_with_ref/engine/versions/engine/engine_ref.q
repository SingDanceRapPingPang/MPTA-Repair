// property 1
///////////////////////////////////////////////////////////////////////////////
// 1996-11-20, 1997-02-20--27, and 1997-07-31 @ Uppsala University
// Paul Pettersson, DoCS and Magnus Lindahl, Mecel AB.
///////////////////////////////////////////////////////////////////////////////
//
// OVERVIEW
//
// This specification file (engine.q) comply with UPPAALs q-format. It is the
// actual input file used to check properties of the gearbox controller. The
// system is modelled in the file engine.atg. To verify the system run:
// 'atg2ta engine.atg engine.ta' and 'verifyta -sT engine.ta engine.q'.
//
// E1 to E11 are requirements on the environment of the gearbox controller,
// R1 to R9 are requirements on the gearbox controller design given by
// Mecel AB. P1 to P15 are properties satisfied by the gearbox controller.
// P1 to P16 prove R1 to R8 (given that E1 to E11 holds).
//
//
// REQUIREMENTS ON THE ENVIRONMENT OF GEARBOX CONTROLLER DESIGN
//
// E1 to E11 are requirements that the environment of the gearbox controller
// design should satisfy to guarantee the behavior of the controller. That is,
// if any of the requirements E1 to E11 are not satisfied by the environment
// then P1 to P15 are *not* guaranteed to hold:
//
// E1. Initially the clutch is closed.
//
// E2. To open the clutch (a) at least 100 ms and (b) at most 150 ms is needed.
//
// E3. To close the clutch (a) at least 100 ms and (b) at most 150 ms is
//     	needed.
//
// E4. Initially the gearbox is neutral.
//
// E5. To release the gear (a) at least 100 ms and (b) at most 200 ms is
//    	needed.
//
// E6. To set a gear (a) at least 100 ms and (b) at most 300 ms is needed.
//
// E7. The engine is always in a predefined state called "Initial"
//	(a) initially, and (b) when no gear is set.
//
// E8. To find zero torque in the engine (a) at least 150 ms and (b) at
//      most 400 ms are	needed.	(c) At 400 ms the engine will enter an error
//      state or find zero torque.
//
// E9. To find synchronous speed (a) at least 50 ms and (b) at most 200 ms are
//	needed. (c) At 200 ms the engine will enter an error state or find
//	synchronous speed.
//
// E10. The engine may regulate on synchronous speed at most 500 ms.
//
// E11.  When in error state the engine will regulate on synchronous speed
//	at least 50 ms ( and at most 500 ms ).
//
//
// REQUIREMENTS ON THE GEARBOX CONTROLLER DESIGN
//
// The Gearbox Controller should satisfy the following informal
// requirements. The number within parentheses refers to the properties
// that ensures that the requirement is satisfied:
//
// R1. A gear change is performed in 1 second (P6 - P8, P3) (*).
//
// R2. When an specific error arise the system will end in a known error
//     	state that points out the specific error (P9 - P11).
//
// R3. The system should be able to use all gears (P2-P3).
//
// R4. There will be no dead-locks or live-locks in the system. (R1).
//
// R5. When the system indicate gear neutral the engine will indicate
//      initial state (P12).
//
// R6. When the system indicate a gear the engine will indicate torque
//  	regulation (P13).
//
// R7. The gearbox controller will never indicate open or closed clutch
//	when the clutch is closed or open respectively (P14).
//
// R8. The gearbox controller will never indicate gear set or gear neutral
// 	when the gear is not set or not idle, respectively (P15).
//
// R9. When the engine is regulating on torque, the clutch is closed (P16).
//
// (*) If an ideal gear change scenario is considered (without the occurrence
//     	of errors) the change is guaranteed within 900 ms and will consume
//	at least 150 ms. If a gear change not involving gear N is considered
//	the change will consume at least 400 ms. A gear change may take up
//	to 1205 ms when successful but less ideal scenarios (with occurrence
//	of errors) are considered.
//
//
// FORMALIZING THE REQUIREMENT
//
// The requirement above have been formalised using variables and locations
// of automata. The system variables listed below are variables used by the
// components of the system, the auxiliary variables are decorations to the
// system used to formalise the requirements only. In the system the
// auxiliary variables appear only in assignments (not in guards). This
// ensures that the system behavior is not changed when the auxiliary
// variables are introduced (or removed).
//
// The variables ErrStat and UseCase are used to trace errors. ErrStat
// is set when unrecoverable errors occur, UseCase when recoverable errors,
// which are resolved by the gearbox controller, occur.
//
// The systems component locations that appears in the formulae below can
// be found in the system description file engine.{atg|ta}.
//
// System Variables:
//
// o GCTimer  - gearbox controller timer,
// o ETimer   - engine timer,
// o GBTimer  - gearbox timer,
// o CTimer   - clutch timer,
// o FromGear - selected gear before gear change (0=N, 1=1, ..., 6=R),
// o ToGear   - selected gear after gear change (0=N, 1=1, ..., 6=R).
//
// Auxiliary Variables:
//
// o SysTimer - system timer, reset at each request for new gear
//              (in the gearbox controller),
// o ErrStat  - 0 = no errors,
//		1 = close clutch error,
//        	2 = open clutch error,
//		3 = set gear failure,
//		4 = error releasing gear.
// o UseCase  - 0 = ideal scenario, no problems occurred,
//		1 = engine was not able to deliver zero torque,
//		2 = engine was not able to find synchronous speed.
//
//
///////////////////////////////////////////////////////////////////////////////
// ----------------------------------------------------------------------------
// P1. It is possible to change gear.
// ----------------------------------------------------------------------------
// source: models\model_with_ref\engine\engine.q
E<> GearControl.GearChanged

// property 2
// ----------------------------------------------------------------------------
// P2. It is possible to switch to gear nr 5 and to reverse (=R) gear.
// ----------------------------------------------------------------------------
// a)
// source: models\model_with_ref\engine\engine.q
E<> Interface.Gear5

// property 3
// b)
// source: models\model_with_ref\engine\engine.q
E<> Interface.GearR

// property 4
// ----------------------------------------------------------------------------
// P3. It is possible to switch gear in 1000 ms (not very interesting).
// ----------------------------------------------------------------------------
// source: models\model_with_ref\engine\engine.q
E<> ( GearControl.GearChanged and ( SysTimer<=1000 ) )

// property 5
// ----------------------------------------------------------------------------
// P4. When the gearbox is in position N the gear is not in position 1-5 or R.
// ----------------------------------------------------------------------------
// source: models\model_with_ref\engine\engine.q
A[] not ( GearBox.Neutral and ( Interface.Gear1 or Interface.Gear2 or Interface.Gear3 or Interface.Gear4 or Interface.Gear5 or Interface.GearR ) )

// property 6
// ----------------------------------------------------------------------------
// P5. The gear is never N when the gearbox is idle (expected to be neutral).
// ----------------------------------------------------------------------------
// a)
// source: models\model_with_ref\engine\engine.q
A[] not ( GearBox.Idle and Interface.GearN )

// property 7
// b)
// source: models\model_with_ref\engine\engine.q
A[] ( Interface.GearN imply GearBox.Neutral )

// property 8
// ----------------------------------------------------------------------------
// P6. If no errors (in gear and clutch) and ideal (engine) scenario:
// a)  a gear switch is guaranteed in 900 ms (including 900),
// a') a gear switch is not guaranteed in less than 900 ms,
// b)  it is impossible to switch gear in less than 150 ms,
// b') it is possible to switch gear at 150 ms,
// c)  it is impossible to switch gear in less than 400 ms if the switch is
//     not from/to gear N.
// c') it is possible to switch gear at 400 ms if the switch is not from/to
//     gear N.
// ----------------------------------------------------------------------------
// a)
// source: models\model_with_ref\engine\engine.q
A[] ( ( ErrStat==0 and UseCase==0 and SysTimer>=900 ) imply ( GearControl.GearChanged or GearControl.Gear ) )

// property 9
// a')
// source: models\model_with_ref\engine\engine.q
E<> ( ErrStat==0 and UseCase==0 and SysTimer>899 and SysTimer<900 and not ( GearControl.GearChanged or GearControl.Gear ) )

// property 10
// b)
// source: models\model_with_ref\engine\engine.q
A[] ( ( ErrStat==0 and UseCase==0 and ( SysTimer<150 ) ) imply not ( GearControl.GearChanged ) )

// property 11
// (In (b) GearControl.Gear is not implied since the property is then
// satisfied by the systems initial state.)
// b')
// source: models\model_with_ref\engine\engine.q
E<> ( ErrStat==0 and UseCase==0 and GearControl.GearChanged and ( SysTimer==150 ) )

// property 12
// c)
// source: models\model_with_ref\engine\engine.q
A[] ( ( ErrStat==0 and UseCase==0 and FromGear>0 and ToGear>0 and ( SysTimer<400 ) ) imply not ( GearControl.GearChanged ) )

// property 13
// c')
// source: models\model_with_ref\engine\engine.q
E<> ( ErrStat==0 and UseCase==0 and FromGear>0 and ToGear>0 and GearControl.GearChanged and ( SysTimer==400 ) )

// property 14
// ----------------------------------------------------------------------------
// P7. If no errors (in gear and clutch) but engine fails to deliver zero
//     torque:
// a)  a gear switch is guaranteed after 1055 ms (not including 1055),
// a') it is impossible to switch gear in 1055 ms,
// b)  it is impossible to switch gear in less than 550 ms,
// b') it is possible to switch gear at 550 ms,
// c)  it is impossible to switch gear in less than 700 ms if the switch is
//     not from/to gear N.
// c') it is possible to switch gear at 700 ms if the switch is not from/to
//     gear N.
// ----------------------------------------------------------------------------
// a)
// source: models\model_with_ref\engine\engine.q
A[] ( ( ErrStat==0 and UseCase==1 and SysTimer>1055 ) imply ( GearControl.GearChanged or GearControl.Gear ) )

// property 15
// a')
// source: models\model_with_ref\engine\engine.q
E<> ( ErrStat==0 and UseCase==1 and SysTimer==1055 and not ( GearControl.GearChanged or GearControl.Gear ) )

// property 16
// b)
// source: models\model_with_ref\engine\engine.q
A[] ( ( ErrStat==0 and UseCase==1 and SysTimer<550 ) imply not ( GearControl.GearChanged or GearControl.Gear ) )

// property 17
// b')
// source: models\model_with_ref\engine\engine.q
E<> ( ErrStat==0 and UseCase==1 and GearControl.GearChanged and ( SysTimer==550 ) )

// property 18
// c)
// source: models\model_with_ref\engine\engine.q
A[] ( ( ErrStat==0 and UseCase==1 and FromGear>0 and ToGear>0 and SysTimer<700 ) imply not ( GearControl.GearChanged and GearControl.Gear ) )

// property 19
// c')
// source: models\model_with_ref\engine\engine.q
E<> ( ErrStat==0 and UseCase==1 and FromGear>0 and ToGear>0 and GearControl.GearChanged and ( SysTimer==700 ) )

// property 20
// ----------------------------------------------------------------------------
// P8. If no errors but engine fails to find synchronous speed:
// a)  a gear switch is guaranteed in 1205 ms (including 1205),
// a') a gear switch is not guaranteed at less than 1205 ms,
// b)  it is impossible to switch gear in less than 450 ms,
// b') it is possible to switch gear at 450 ms,
// c)  it is impossible to switch gear in less than 750 ms if the switch is
//     not from/to gear N.
// c') it is possible to switch gear at 750 ms if the switch is not from/to
//     gear N.
// ----------------------------------------------------------------------------
// a)
// source: models\model_with_ref\engine\engine.q
A[] ( ( ErrStat==0 and UseCase==2 and SysTimer>=1205 ) imply ( GearControl.GearChanged or GearControl.Gear ) )

// property 21
// a')
// source: models\model_with_ref\engine\engine.q
E<> ( ErrStat==0 and UseCase==2 and SysTimer>1204 and SysTimer<1205 and not ( GearControl.GearChanged or GearControl.Gear ) )

// property 22
// b)
// source: models\model_with_ref\engine\engine.q
A[] ( ( UseCase==2 and ( SysTimer<450 ) ) imply not ( GearControl.GearChanged or GearControl.Gear ) )

// property 23
// b')
// source: models\model_with_ref\engine\engine.q
E<> ( UseCase==2 and GearControl.GearChanged and ( SysTimer==450 ) )

// property 24
// c)
// source: models\model_with_ref\engine\engine.q
A[] ( ( ErrStat==0 and UseCase==2 and FromGear>0 and ToGear>0 and SysTimer<750 ) imply not ( GearControl.GearChanged and GearControl.Gear ) )

// property 25
// c')
// source: models\model_with_ref\engine\engine.q
E<> ( ErrStat==0 and UseCase==2 and FromGear>0 and ToGear>0 and GearControl.GearChanged and ( SysTimer==750 ) )

// property 26
// ----------------------------------------------------------------------------
// P9. Clutch Errors.
// a) If the clutch is not closed properly (i.e. a timeout occurs) the gear-
//    box controller will enter the location CCloseError within 200 ms.
// b) When the gearbox controller enters location CCloseError, there is
//    always a problem in the clutch with closing the clutch.
// ----------------------------------------------------------------------------
// a)
// source: models\model_with_ref\engine\engine.q
A[] ( ( Clutch.ErrorClose and ( GCTimer>200 ) ) imply GearControl.CCloseError )

// property 27
// b)
// source: models\model_with_ref\engine\engine.q
A[] ( GearControl.CCloseError imply Clutch.ErrorClose )

// property 28
// ----------------------------------------------------------------------------
// P9. Clutch Errors (cont.)
// c) If the clutch is not opened properly (i.e. a timeout occurs) the gear-
//    box controller will enter the location COpenError within 200 ms.
// d) When the gearbox controller enters location COpenError there is always
//    a problem in the clutch with opening the clutch.
// ----------------------------------------------------------------------------
// c)
// source: models\model_with_ref\engine\engine.q
A[] ( ( Clutch.ErrorOpen and ( GCTimer>200 ) ) imply GearControl.COpenError )

// property 29
// d)
// source: models\model_with_ref\engine\engine.q
A[] ( ( GearControl.COpenError ) imply Clutch.ErrorOpen )

// property 30
// ----------------------------------------------------------------------------
// P10. Gearbox Errors.
// a) If the gearbox can not set a requested gear (i.e a timeout occurs) the
//    gearbox controller will enter the location GSetError within 350 ms.
// b) When the gearbox controller enters location GSetError there is always
//    a problem in the gearbox with setting the gear.
// ----------------------------------------------------------------------------
// a)
// source: models\model_with_ref\engine\engine.q
A[] ( ( GearBox.ErrorIdle and ( GCTimer>350 ) ) imply GearControl.GSetError )

// property 31
// b)
// source: models\model_with_ref\engine\engine.q
A[] ( ( GearControl.GSetError ) imply GearBox.ErrorIdle )

// property 32
// ----------------------------------------------------------------------------
// P10. Gearbox Errors (cont).
// c) If the gearbox can not switch to neutral gear (i.e. a timeout occurs)
//    the gearbox controller will enter the location GNeuError within 200 ms.
// d) When the gearbox controller enters location GNeuError there is always
//    a problem in the gearbox with switching to neutral gear.
// ----------------------------------------------------------------------------
// c)
// source: models\model_with_ref\engine\engine.q
A[] ( ( GearBox.ErrorNeu and ( GCTimer>200 ) ) imply GearControl.GNeuError )

// property 33
// d)
// source: models\model_with_ref\engine\engine.q
A[] ( ( GearControl.GNeuError ) imply GearBox.ErrorNeu )

// property 34
// ----------------------------------------------------------------------------
// P11. If no errors occur in the engine, it is guaranteed to find synchronous
//      speed.
// ----------------------------------------------------------------------------
// source: models\model_with_ref\engine\engine.q
A[] not ( ErrStat==0 and Engine.ErrorSpeed )

// property 35
//
// ----------------------------------------------------------------------------
// P12. When gear N then engine is in initial or on its way to initial (i.e.
//	ToGear==0 and engine in zero).
// ----------------------------------------------------------------------------
// source: models\model_with_ref\engine\engine.q
A[] ( Interface.GearN imply ( ( ToGear==0 and Engine.Zero ) or Engine.Initial ) )

// property 36
// ----------------------------------------------------------------------------
// P13. When the gear controller have a gear set, torque regulation is always
//	indicated in the engine.
// ----------------------------------------------------------------------------
// a)
// source: models\model_with_ref\engine\engine.q
A[] ( ( GearControl.Gear and Interface.GearR ) imply Engine.Torque )

// property 37
// b)
// source: models\model_with_ref\engine\engine.q
A[] ( ( GearControl.Gear and Interface.Gear1 ) imply Engine.Torque )

// property 38
// c)
// source: models\model_with_ref\engine\engine.q
A[] ( ( GearControl.Gear and Interface.Gear2 ) imply Engine.Torque )

// property 39
// d)
// source: models\model_with_ref\engine\engine.q
A[] ( ( GearControl.Gear and Interface.Gear3 ) imply Engine.Torque )

// property 40
// e)
// source: models\model_with_ref\engine\engine.q
A[] ( ( GearControl.Gear and Interface.Gear4 ) imply Engine.Torque )

// property 41
// f)
// source: models\model_with_ref\engine\engine.q
A[] ( ( GearControl.Gear and Interface.Gear5 ) imply Engine.Torque )

// property 42
// ----------------------------------------------------------------------------
// P14. a) If clutch is open then the gearbox controller is in location...
//	b) If clutch is closed then the gearbox controller is in location...
// ----------------------------------------------------------------------------
// a)
// source: models\model_with_ref\engine\engine.q
A[] ( Clutch.Open imply ( GearControl.ClutchOpen or GearControl.ClutchOpen2 or GearControl.CheckGearSet2 or GearControl.ReqSetGear2 or GearControl.GNeuError or GearControl.ClutchClose or GearControl.CheckClutchClosed or GearControl.CheckClutchClosed2 or GearControl.CCloseError or GearControl.GSetError or GearControl.CheckGearNeu2 ) )

// property 43
// b)
// source: models\model_with_ref\engine\engine.q
A[] ( Clutch.Closed imply ( GearControl.ReqTorqueC or GearControl.GearChanged or GearControl.Gear or GearControl.Initiate or GearControl.CheckTorque or GearControl.ReqNeuGear or GearControl.CheckGearNeu or GearControl.GNeuError or GearControl.ReqSyncSpeed or GearControl.CheckSyncSpeed or GearControl.ReqSetGear or GearControl.CheckGearSet1 or GearControl.GSetError ) )

// property 44
// ----------------------------------------------------------------------------
// P15. a) If gear is set then the gearbox controller is in location...
//	b) If gear is neutral then the gearbox controller is in location...
// ----------------------------------------------------------------------------
// a)
// source: models\model_with_ref\engine\engine.q
A[] ( GearBox.Idle imply ( GearControl.ClutchClose or GearControl.CheckClutchClosed or GearControl.CCloseError or GearControl.ReqTorqueC or GearControl.GearChanged or GearControl.Gear or GearControl.Initiate or GearControl.CheckTorque or GearControl.ReqNeuGear or GearControl.CheckClutch2 or GearControl.COpenError or GearControl.ClutchOpen2 ) )

// property 45
// b)
// source: models\model_with_ref\engine\engine.q
A[] ( GearBox.Neutral imply ( GearControl.ReqSetGear or GearControl.CheckClutchClosed2 or GearControl.CCloseError or GearControl.ReqTorqueC or GearControl.GearChanged or GearControl.Gear or GearControl.Initiate or GearControl.ReqSyncSpeed or GearControl.CheckSyncSpeed or GearControl.ReqSetGear or GearControl.CheckClutch or GearControl.COpenError or GearControl.ClutchOpen or GearControl.ReqSetGear2 ) )

// property 46
// ----------------------------------------------------------------------------
// P16. If engine regulates on torque, then the clutch is closed.
// ----------------------------------------------------------------------------
// source: models\model_with_ref\engine\engine.q
A[] ( Engine.Torque imply Clutch.Closed )

// property 47
// 正常情况下的最大换挡时间限制 (Normal Operation Performance Bound)
// 物理意义: 如果系统在“正常操作条件”下完成了换挡（即没有发生不可恢复的错误 ErrStat == 0，且引擎也没有发生难以达到零扭矩等可恢复错误 UseCase == 0），从换挡请求发起（SysTimer被重置）到最终完成的总耗时必须小于等于1000毫秒（1秒）。
// 论文来源: Section 4.1 Requirements -> 1. Performance -> (b) "A gear change, under normal operation conditions, should be performed within 1 second." 以及 Section 6.1 Formula (2)。
// source: models\model_with_ref\engine\engine_ref.q
A[] not GearControl.GearChanged or ErrStat != 0 or UseCase != 0 or (SysTimer <= 1000)

// property 48
// 包含可恢复错误时的绝对最大换挡时间 (Absolute Maximum Bounded Response)
// 物理意义: 只要车辆环境组件没有发生“不可恢复的致命错误”（ErrStat == 0），即使遇到了恶劣工况（如强制启动离合器换挡，即 UseCase > 0），换挡控制器也必须保证在1500毫秒（1.5秒）内强行完成换挡，防止车辆失去动力时间过长。
// 论文来源: Section 4.1 Requirements -> 1. Performance -> (a) "A gear change should be completed within 1.5 seconds." 以及 Section 6.1 Formula (1)。
// source: models\model_with_ref\engine\engine_ref.q
A[] not GearControl.GearChanged or ErrStat != 0 or (SysTimer <= 1500)

// property 49
// 引擎零扭矩故障应对的时间确界 (Fault-Tolerant Timing for Zero Torque Failure)
// 物理意义: 当发生“可恢复错误 1”（引擎试图降扭矩但超时失败，即 UseCase == 1）时，齿轮控制器会主动介入并断开离合器。此时整个系统的容错换挡事务总耗时应当被严格约束在1055毫秒之内。
// 论文来源: Section 6.1 Time Bound Derivation: "Similarly, for scenarios when the engine fails to deliver zero torque we derive the bound 1055 ms..."
// source: models\model_with_ref\engine\engine_ref.q
A[] not GearControl.GearChanged or ErrStat != 0 or UseCase != 1 or (SysTimer <= 1055)
