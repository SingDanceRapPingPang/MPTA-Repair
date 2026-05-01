3.4 An Example: Fischer's Protocol

As another example of real-time closed systems, we treat a simpliﬁed
version of a real-time mutual exclusion protocol proposed by Fischer
\[1985\] and described in \[Lamport 1987, page 2\]. The example was
suggested by Schneider, Bloom, and Marzullo \[1992\]. The protocol
consists of each process i executing the following code, where angle
brackets denote instantaneous atomic actions:

a: **await**〈x = 0〉;

b: 〈x := i〉;

c: **await**〈x = i〉;

cs: critical section

There is a maximum delay ∆b between the execution of the test in
statement a and the assignment in statement b, and a minimum delay δc
between the assignment in statement b and the test in statement c. The
problem is to prove that, with suitable conditions on ∆b and δc , this
protocol guarantees mutual exclusion (at most one process can enter
its critical section).

As written, Fischer,s protocol permits only one process to enter its
critical section one time. The protocol can be converted to an actual
mutual exclusion algorithm. The correctness proof of the protocol is
easily extended to a proof of such an algorithm.

The TLA speciﬁcation of the protocol is given in Figure 4. The formula
ΠF describing the untimed version is standard TLA. We assume a ﬁnite
set Proc of processes. Variable x represents the program variable x,
and variable pc represents the control state. The value of pc will be
an array indexed by Proc, where pc \[i\] equals one of the strings
"a", "b", "c", "cs" when control in process i is at the corresponding
statement. The initial predicate InitF asserts that pc \[i\] equals
"a" for each process i, so the processes start with control at
statement a. No assumption on the initial value of x is needed to
prove mutual exclusion.

Next come the deﬁnitions of the three actions corresponding to program
state- ments a, b, and c. They are deﬁned using the formula Go , where
Go (i, u, v) asserts that control in process i changes from u to v,
while control remains unchanged in the other processes. Action Ai
represents the execution of statement a by process i; actions Bi and
Ci have the analogous interpretation. In this simple protocol, a
process stops when it gets to its critical section, so there are no
other actions. The program,s next-state action NF is the disjunction
of all these actions. Formula ΠF asserts that all processes start at
statement a, and every step consists of executing the next statement
of some process.

Action Bi is enabled by the execution of action Ai. Therefore, the
maximum delay of ∆b between the execution of statements a and b can be
expressed by an upper-bound constraint on a volatile ∆b-timer for
action Bi. The variable Tb is an array of such timers, where Tb \[i\]
is the timer for action Bi.

The constant δc is the minimum delay between when control reaches
statement c and when that statement is executed. Therefore, we need an
array tc of lower-

InitF = ∀ i ∈ Proc : pc\[i\] = "a"

Go(i, u, v)
![](D:/study/毕设论文/项目/repair_model/models/model_with_ref/fischer/images/media/image46.png){width="8.490266841644795e-2in"
height="0.12337051618547681in"} ∧ pc\[i\] = u

∧ pc, \[i\] = v

∧ ∀ j ∈ Proc : (j
![](D:/study/毕设论文/项目/repair_model/models/model_with_ref/fischer/images/media/image47.png){width="8.490266841644795e-2in"
height="0.11390529308836396in"} i) ⇒ (pc, \[j\] = pc\[j\])

Ai = Go(i, "a", "b") ∧ (x = x, = 0)

Bi = Go(i, "b", "c") ∧ (x, = i)

Ci = Go(i, "c", "cs") ∧ (x = x, = i)

NF = ∃ i ∈ Proc : (Ai ∨ Bi ∨ Ci)

Π F = InitF ∧ □\[NF \] (x,pc)

Π ![](D:/study/毕设论文/项目/repair_model/models/model_with_ref/fischer/images/media/image48.png){width="8.490266841644795e-2in"
height="0.12336832895888014in"} ∧ Π F ∧ RT (x,pc)

∧ ∀ i ∈ Proc : ∧ VTimer(Tb\[i\] , Bi , ∆ b , (x, pc))

∧ MaxTime(Tb\[i\])

∧ ∀ i ∈ Proc : ∧ VTimer(tc\[i\] , Go(i, "c", "cs"), δc , (x, pc))

∧ Min Time(tc\[i\] , Ci , (x, pc))

Φ ![](D:/study/毕设论文/项目/repair_model/models/model_with_ref/fischer/images/media/image49.png){width="8.490266841644795e-2in"
height="0.12336832895888014in"} ∃Tb, tc : Π

Fig. 4. The TLA speciﬁcation of Fischer's real-time mutual exclusion
protocol.

bound timers for the actions Ci. The delay is measured from the time
control reaches statement c, so we want tc \[i\] to be a δc-timer on
an action that becomes enabled when process i reaches statement c and
is not executed until Ci is. (Since we are placing only a lower-bound
timer on it, the action need not be a subaction of ΠF.) A suitable
choice for this action is Go (i, "c", "cs").

Adding these timers and timing constraints to the untimed formula ΠF
yields formula Π of Figure 4, the speciﬁcation of the real-time
protocol with the timers visible. The ﬁnal speciﬁcation, Φ, is
obtained by quantifying over the timer variables Tb and tc. Since
〈Bj〉(x,pc) ∧ (now, = now) is a subaction of ΠF and 〈Go(i, "c",
"cs")〉(x,pc) is disjoint from 〈Bj〉(x,pc), for all i and j in Proc,
Theorem 2 implies that Π is nonZeno if ∆b is positive. Proposition 2
can then be applied to

prove that Φ is nonZeno.

Mutual exclusion asserts that two processes cannot be in their
critical sections at the same time. It is expressed by the predicate

Mutex ![](D:/study/毕设论文/项目/repair_model/models/model_with_ref/fischer/images/media/image50.png){width="9.990266841644795e-2in"
height="0.12669291338582678in"} ∀ i, j ∈ Proc : (pc \[i\] = pc \[j\] =
"cs") ⇒ (i = j)

The property to be proved is

Assump ∧ Φ ⇒ □Mutex (8)

where Assump expresses the assumptions about the constants Proc, ∆b ,
and δc needed for correctness. Since the timer variables do not occur
in Mutex or Assump , (8) is equivalent to

Assump ∧ Π ⇒ □Mutex

The standard method for proving this kind of invariance property leads
to the

ACM Transactions on Programming Languages and Systems, Vol ?, No. ?,
November 1993

invariant

∧ now ∈ **R** ∧ ∀ i ∈ Proc :

∧ Tb \[i\], tc \[i\] ∈ **R** ∪{∞}

∧ pc \[i\] ∈ { "a", "b", "c", "cs"}

∧ (pc \[i\] = "cs") ⇒ ∧ x = i

∧ ∀ j ∈ Proc : pc\[j\]
![](D:/study/毕设论文/项目/repair_model/models/model_with_ref/fischer/images/media/image51.png){width="9.990266841644795e-2in"
height="0.127422353455818in"} "b"

∧ (pc \[i\] = "c") ⇒ ∧ x
![](D:/study/毕设论文/项目/repair_model/models/model_with_ref/fischer/images/media/image52.png){width="9.990266841644795e-2in"
height="0.1280566491688539in"} 0

∧ ∀ j ∈ Proc : (pc \[j\] = "b") ⇒ (tc \[i\] \> Tb \[j\])

∧ (pc \[i\] = "b") ⇒ (Tb \[i\] \< now + δc )

∧ now ≤ Tb \[i\] and the assumption

Assump ![](D:/study/毕设论文/项目/repair_model/models/model_with_ref/fischer/images/media/image53.png){width="9.990266841644795e-2in"
height="0.12669181977252844in"} (0
![](D:/study/毕设论文/项目/repair_model/models/model_with_ref/fischer/images/media/image54.png){width="8.080708661417323e-2in"
height="0.1383694225721785in"} Proc) ∧ (∆b,δc ∈ **R**) ∧ (∆b \< δc )