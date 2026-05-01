> DOI 10.1007/s00165-004-0034-9 BCS © 2004
>
> Formal Aspects of Computing (2004) 16: 104---120
>
> **Formal Aspects of Computing**
>
> **Comparing model checking and logical reasoning for real-time
> systems**
>
> Henning Dierks
>
> Department of Computer Science, University of Oldenburg, Oldenburg,
> Germany
>
> **Abstract.** We apply both model checking and logical reasoning to a
> real-time protocol for mutual exclusion. To this end we employ
> PLC-Automata, an abstract notion of programs for real-time systems. A
> logic-based semantics in terms of Duration Calculus is used to verify
> the correctness of the protocol by logical reasoning. An alternative
> but consistent operational semantics in terms of Timed Automata is
> used to verify the correctness by model checkers. Since model checking
> of the full model does not terminate in all cases within an acceptable
> time we examine abstractions and their inﬂuence on model-checking
> performance. We present two abstraction methods that can be applied
> successfully for the protocol presented.
>
> **Keywords:** Real-time; Duration Calculus; Timed Automata;
> Veriﬁcation; Model checking
>
> **1. Introduction**
>
> In recent years model checking of real-time systems has become popular
> because several tools have been devel- oped implementing theoretical
> results (e.g. \[ACD90\]) about Timed Automata \[AD94\]. In this paper
> we examine the usage of these tools applied to an example which can be
> easily handled with Duration Calculus \[ZHR91\].
>
> To this end webrieﬂy introduce an abstract device of real-time systems
> called "PLC-Automata" \[Die97, Die99\]. These automata have been
> developed in the UniForM-project \[KBPO+ 96\] as a speciﬁcation
> language for pro- grams of "programmable logic controllers" (PLCs)
> which are simple computing devices controlling systems like production
> cells and trafﬁc lights. PLC-Automata can be translated directly into
> source code for PLCs and have a Duration Calculus semantics describing
> the behaviour of a PLC executing the corresponding source code. In
> \[DFMV98a\] an operational semantics for PLC-Automata in terms of
> Timed Automata \[AD94\] has been developed and it was proven that both
> semantics are equivalent.
>
> Due to the latter result we can now test the applicability of model
> checkers like Kronos \[DOTY96, Yov97\] and Uppaal \[BLL+ 96, LPW97\]
> by specifying a system using PLC-Automata. The operational semantics
> of this system in terms of Timed Automata can be fed into these tools
> and we try to prove a typical constraint, namely a mutual exclusion
> property. By simple reasoning with the Duration Calculus semantics we
> will see that this property is not fulﬁlled for a ﬁrst version of the
> protocol. The model checkers are able to produce the same result
> within an acceptable time. After analysing the reason why the ﬁrst
> version failed to ensure the mutual exclusion we present an improved
> protocol which is correct. The correctness can be established by
> logical reasoning in Duration Calculus quite easily. Model checking
> the improved version is partly more difﬁcult. To overcome the problems
> we present abstraction methods for Timed Automata which can be used in
> our setting to make model checking feasible.

*Correspondence and offprint requests to*: Henning Dierks, Department of
Computer Science, University of Oldenburg, P.O. Box 2503, 26111

> Oldenburg, Germany. Email: dierks@informatik.uni-oldenburg.de
>
> Comparing model checking and logical reasoning for real-time systems
> 105

+---------------------------------------------------------------+
| > ![](./images/media/image1.png){width="3.2166754155730533in" |
| > height="0.5981791338582677in"}x                             |
| >                                                             |
| > A                                                           |
| >                                                             |
| > 0 *q*0                                                      |
+---------------------------------------------------------------+

> **Fig. 1.** An example of a PLC-Automaton
>
> The logical reasoning employs Duration Calculus as a means to express
> temporal properties precisely and efﬁciently. It does not make use of
> known formal deduction rules because they are not applicable here.
> Neverthe- less, all deductions presented in this paper are correct and
> one could easily establish appropriate sound deduction rules for them.
> Since this would lead to a very specialised set of rules this is
> omitted here.
>
> **2. PLC-Automata**
>
> In the UniForM-project \[KBPO+ 96\] an automaton-like device---called
> PLC-Automata---of polling real-time systems has been developed to
> enable a formal veriﬁcation of PLC-programs. Basically, Programmable
> Logic Controllers (PLCs), the hardware aim of the project, can be
> viewed as simple computers with a special real-time operating system.
> They have features for making the design of time- and safety-critical
> systems easier:
>
> • A PLC communicates with the environment via input and output
> channels. The environment may change the values of the inputs
> arbitrarily whereas the outputs are controlled by the PLC.
>
> • They behave in a cyclic manner where every cycle consists of the
> following phases:
>
> **--** Poll all inputs and store the read values.
>
> **--** Compute the new values for the outputs.
>
> **--** Update all outputs.
>
> The repeated execution of this cycle is managed by the operating
> system. The only part the programmer has to adapt is the computing
> phase.
>
> • Depending on the program and on the number of inputs and outputs
> there is an upper time bound for a cycle. In the case of real-time
> systems we often require upper time bounds for reactions to certain
> events. The upper time bound for cycles is the main key to verify such
> properties.
>
> • Convenient standardised libraries are given to simplify the handling
> of time.

In the formal deﬁnition of PLC-Automata below we consider the upper time
bound for a polling cycle and the possibility of delay reactions of the
system depending on state and input. Figure 1 gives an example of a PLC-
Automaton. It shows an automaton with three states ({q0 , q1 , q2 }) and
outputs {A, B, C}, that reacts to inputs of the alphabet {x, y}. Every
state has two annotations in the graphical representation. The upper one
denotes the output of the state; thus in state q0 the output is A and in
state q2 the output is C. The lower annotation is either 0 or a pair (d,
S) consisting of a real number d \> 0 and a subset S of inputs.

> A PLC-Automaton describes the behaviour of the system in the
> computation phase. The operational behav- iour is similar to a ﬁnite
> state machine, i.e. depending on the polled input value the system
> changes both its state and its output. The behaviour is modiﬁed in
> only one case:
>
> If
>
> • the annotation of the current state is (d, S) *and*
>
> • the polled input is in S *and*
>
> • the current state does not hold longer than d seconds,
>
> then no transition is executed.
>
> The PLC-Automaton in Fig. 1 thus behaves as follows: It starts in
> state q0 and remains there as long as it reads only the input x. The
> ﬁrst time it reads y it changes to state q1. In q1 the automaton
> reacts to the input x by changing the state back to q0 independently
> of the time it stayed in state q1. It reacts to the input y by
> changing the state to q2 provided that q1 holds longer than 10 s. If
> this transition takes place the automaton enters q2
>
> and remains there forever. Hence, we know that the automaton changes
> its output to C when y holds a little bit longer than 10 s (the cycle
> time has to be considered). We formalise this graphic notation using
> an automaton-like structure extended by some components.
>
> **Deﬁnition 1 (PLC-Automaton)** A tuple A = (Q, Σ, δ, q0 ,ε, St,
> Se,Ω,ω) is a *PLC-Automaton* if
>
> • Q is a nonempty, ﬁnite set of *states*,
>
> • Σ is a nonempty, ﬁnite set of *inputs*,
>
> • δ is a function of type Q × Σ }−→ Q (*transition function*),
>
> • q0 ∈ Q is the *initial state*,
>
> • ε \> 0 is the *upper bound* for a cycle,
>
> • St is a function of type Q }−→ IR ≥0 assigning to each state q a
> *delay time* how long the inputs contained in Se (q) should be
> ignored,
>
> • Se is a function of type Q }−→ P(Σ) assigning to each state a set of
> *delayed inputs*,1
>
> • Ω is a nonempty, ﬁnite set of *outputs*, and
>
> • ω is a function of type Q }−→ Ω (*output function*)
>
> The components Q, Σ , δ, and q0 have the same meaning as in usual
> ﬁnite state automata. The additional components are needed tomodel a
> polling behaviour and to enrich the language for dealing with
> real-time aspects. The ε represents the upper time bound for a polling
> cycle and enables us to model this cycle in the semantics. The delay
> function St and Se represent the annotations of the states. In the
> case of St (q) = 0 no delay time is given and the value Se (q) is
> arbitrary. If the delay time St (q) is greater than 0 the set Se (q)
> denotes the set of inputs for which the delay time is valid.
>
> Note that PLC-Automata are implementable. In \[Die99\] a translation
> of PLC-Automata into source code for PLCs is given. Recently also a
> translation into code for Lego Mindstorms has been developed. The
> logical relationship between the execution of the code by the
> real-world hardware and the semantics given in the rest of this paper
> is *reﬁnement*. In other words: the real-world implementation cannot
> show a behaviour that is not covered by the formal semantics. Due to
> the lack of a formal semantics for the implementation languages we
> cannot establish this claim formally.
>
> **3. The Duration Calculus**
>
> In the following sections we shall demonstrate the various
> construction techniques of our approach. In our case study the
> speciﬁcation language will be the Duration Calculus \[ZHR91, Zho93,
> HZ97\] (DC for short). It is a real-time interval temporal logic
> extending earlier work on discrete interval temporal logic of
> \[Mos85\].
>
> A formal description of a real-time system using DC starts by choosing
> a number of time-dependent state variables ("observable") obs of a
> certain type. An interpretation I assigns to each state variable a
> function obsI : Time }−→ D where Time is the time domain, here the
> non-negative reals, and D is the type of obs. If D is ﬁnite, these
> functions obsI are required to be*ﬁnitely variable*, which means that
> any interval \[b, e\] ⊆ Time can be divided into ﬁnitely many
> subintervals such that obsI is constant on the open subintervals.
>
> **State assertions** P are obtained by applying propositional
> connectives to elementary assertions of the form obs = v (v for short
> if obs is clear) for a v ∈ D. For a given interpretation I state
> assertions denote functions PI : Time }−→ {0, 1}.
>
> **Duration terms** are of type real and their values depend on a given
> time interval \[b, e\]. The simplest duration term is the symbol l
> denoting the length e − b of \[b, e\]. For each state assertion P
> there is a duration term ∫ P measuring the duration of P , i.e. the
> accumulated time P holds in the given interval. Semantically, ∫ P
> denotes ![](./images/media/image2.png){width="0.12761701662292213in"
> height="0.1985990813648294in"} PI (t)dt on the interval \[b, e\].
>
> **Duration formulas** are built from arithmetical relations applied to
> duration terms, the special symbols true and false, and other terms of
> type real, and they are closed under propositional connectives and
> quantiﬁcation over rigid variables. Their truth values depend on a
> given interval. We use F for a typical duration formula. true and
> false evaluate to true resp. false on every given interval. Further
> basic duration formulas are:
>
> **Relation over Durations:** For example, ∫ P = k expresses that the
> *duration* of the state assertion P in \[b, e\] is k.
>
> 1 If St(q) = 0 the set Se(q) can be arbitrarily chosen. The single 0
> represents this in the graphical notation (cf. Fig. 1).
>
> **Chop:** The composite duration formula F1 ; F2 (read as F1 *chop*
> F2) holds in \[b, e\] if this interval can be divided into an initial
> subinterval \[b, m\] where F1 holds and a ﬁnal subinterval \[m, e\]
> where F2 holds.
>
> Besides this basic syntax various abbreviations are used: point
> interval: 「l
> ![](./images/media/image3.png){width="0.45736548556430445in"
> height="0.1744838145231846in"}
>
> everywhere: 「Pl
> ![](./images/media/image4.png){width="1.157833552055993in"
> height="0.18340879265091864in"}
>
> somewhere: ◇F
> ![](./images/media/image5.png){width="0.8475404636920385in"
> height="0.1722681539807524in"}
>
> always: ✷F ![](./images/media/image6.png){width="0.5469050743657042in"
> height="0.16770450568678916in"}
>
> Since phases are often assigned a duration requirement the following
> abbreviations are useful:
>
> Ft ![](./images/media/image7.png){width="0.7985017497812773in"
> height="0.1744838145231846in"}
>
> F\~t ![](./images/media/image8.png){width="0.18469488188976377in"
> height="0.17448490813648293in"}F Λ l \~ t) with \~∈ {\<, ≤ ,\>, ≥}

A duration formula F *holds* in an interpretation I if F evaluates to
true in I and every interval of the form \[0, t\] with t ∈ Time. If
convenient, we use F to describe a set of interpretations, namely all
interpretations in which F holds.

> The following so-called *standard forms* are useful to describe
> dynamic behaviour: followed-by: F −→「Pl
> ![](./images/media/image9.png){width="0.10017935258092739in"
> height="0.12570975503062118in"} ✷一(F ;「一Pl)
>
> timed leads-to: F
> **−**![](./images/media/image10.png){width="8.693132108486439e-2in"
> height="0.11187992125984252in"}−→「Pl
> ![](./images/media/image11.png){width="9.042869641294839e-2in"
> height="0.1194520997375328in"} (F Λ l = t) −→「Pl
>
> timed up-to: F
> **−**![](./images/media/image12.png){width="8.68908573928259e-2in"
> height="0.12076334208223972in"}![](./images/media/image13.png){width="0.1757425634295713in"
> height="0.17770231846019247in"}「Pl
> ![](./images/media/image14.png){width="9.038713910761155e-2in"
> height="0.12215441819772528in"} (F Λ l ≤ t) −→「Pl To avoid
> parentheses the following precedence rules are used:
>
> 1\. ∫
>
> 2\. real operators
>
> 3\. real predicates
>
> 4\. 一, ✷, ◇
>
> 5\. ;
>
> 6\. Λ, V
>
> 7\. =→ , −→,
> **−**![](./images/media/image15.png){width="8.204286964129484e-2in"
> height="0.12029418197725285in"}![](./images/media/image16.png){width="0.16593722659667542in"
> height="0.17701334208223973in"} ,
> **−**![](./images/media/image17.png){width="8.204286964129484e-2in"
> height="0.11396653543307086in"}−→
>
> 8\. quantiﬁcation
>
> **4. The logical semantics**
>
> Let A = (Q, Σ, δ, q0 ,ε, Se, St,Ω,ω) be a PLC-Automaton. The Duration
> Calculus semantics \[\[A\]\]DC of A is given by the conjunction of the
> predicates (1)---(11) regarding the state variables
>
> state :Time l−→ Q
>
> input :Time l−→ Σ
>
> output :Time l−→ Ω .
>
> First of all, the starting of the automaton in the proper initial
> state is expressed by:

「l V「q0 l ; true. (1) Note that「q0 l is an abbreviation of「state =
q0 l. Next, we want to describe the behaviour of the automaton in state
q. The cyclic behaviour of PLCs has to be reﬂected in the semantics to
achieve a realistic modelling. One question the semantics should answer
is: When a state q is entered, what kind of input can inﬂuence the
behaviour of the PLC? The answer to this question is:

> • only the inputs after entering q and
>
> • only the inputs during the last cycle-time ε .
>
> This is expressed by the following predicates where A ranges over all
> *sets of inputs* with ∅
> ![](./images/media/image18.png){width="0.10017935258092739in"
> height="0.12370297462817148in"} A ⊆ Σ :

「¬ql ;「q ∧ Al −→「q ∨ δ(q, A)l (2)

「q ∧ Al
**−**![](./images/media/image19.png){width="7.718175853018373e-2in"
height="0.11858267716535432in"}−→「q ∨ δ(q, A)l (3) Note that we use A
in the formulas as an abbreviation for input ∈ A resp. δ(q, A) for state
∈ {δ(q, a)\|a ∈ A}. The statement (2) formalises the fact that after a
change of the automaton's state to q only the set of inputs A that is
valid after the change can have an effect on the behaviour in the
future. The statement (3) represents the formalisation of the cyclic
behaviour of PLCs. A PLC reacts only to inputs during the last cycle.
Preceding inputs are forgotten and cannot inﬂuence the PLC anymore. The
quantiﬁcation over all nonempty subsets ofthe input alphabet was
motivated by the behaviour of the PLCs. The more we know about the
inputs during the last cycle the more we know about the actions of the
PLC.

> For states without a stability requirement we expect a change to δ(q,
> A) or more generally we expect that the automaton reacts accordingly
> in at most 2ε seconds. For states with a stability requirement we
> expect this behaviour after the required period of time. This leads us
> to additional statements in the semantics:

St ![](./images/media/image20.png){width="0.16701115485564305in"
height="0.1600929571303587in"} = 0 =⇒「q ∧ Al
![](./images/media/image21.png){width="0.622150043744532in"
height="0.20336067366579177in"}q, A)l (4)

> St (q) \> 0 =⇒「ql ;「q ∧ Al2ε
> ![](./images/media/image22.png){width="9.514654418197725e-2in"
> height="0.14967847769028872in"}![](./images/media/image23.png){width="0.1714009186351706in"
> height="0.14967847769028872in"}![](./images/media/image24.png){width="3.471667760279965in"
> height="0.20917432195975502in"} St (q) = 0 ∧ q
> ![](./images/media/image25.png){width="7.541119860017498e-2in"
> height="0.1248086176727909in"} δ(q, A) =⇒「¬ql ;「q ∧ Alε −→「¬ql (6)
>
> Statement (4) says that after at most 2ε seconds the automaton reacts
> to the input accordingly if there is no stability required for q. Note
> that ε seconds are needed to assure that the PLC reads at least once
> and ε seconds are needed to react to this input in the worst case.
> Formula (5) states this behaviour after St (q) seconds: if St (q)
> seconds have elapsed the automaton reacts to inputs in at most 2ε
> seconds. In the case that we know that the automaton has just changed
> the state then we want to be able to exploit the information that
> within the next ε seconds another reaction to the inputs in A has to
> occur. This is formalised by (6).
>
> Next we want to describe the automaton's behaviour if it is in a state
> q where a stability is required and the St (q) seconds have not
> elapsed. Then we want to hold this state provided that during this
> phase only inputs in Se (q) are read. That means inputs in Se (q)
> cannot cause a change of state during the ﬁrst St (q) seconds:

![](./images/media/image26.png){width="6.302120516185477in"
height="0.20917322834645669in"}

> However, we have to take into account the cyclic behaviour of the
> hardware again. In particular, we should require that if q is left
> during the stability phase then there has to be an input not contained
> in Se (q) at most ε seconds ago:

![](./images/media/image27.png){width="6.302135826771654in"
height="0.20917432195975502in"}

> Furthermore, we know that the automaton reacts according to the input
> if there is a set A that is valid for the last 2ε seconds and disjoint
> from Se (q):

St (q) \> 0 ∧ A ∩ Se (q) = ∅ ∧ q
![](./images/media/image28.png){width="7.428040244969379e-2in"
height="0.1248086176727909in"} δ(q, A) =⇒「q ∧ Al
**−**![](./images/media/image29.png){width="9.48611111111111e-2in"
height="0.14144028871391076in"}![](./images/media/image30.png){width="2.9081802274715662in"
height="0.20336067366579177in"}

St (q) \> 0 ∧ A ∩ Se (q) = ∅ ∧ q
![](./images/media/image31.png){width="7.541119860017498e-2in"
height="0.1248086176727909in"} δ(q, A) =⇒「¬ql ;「q ∧ Alε −→「¬ql (10)

> Formula (10) corresponds to (6). Note that (2), (6), (7), (8), and
> (10) require a change from「¬ql to「ql to restrict the possible
> behaviour. But for the initial state there is no change and therefore
> the assertions are not applicable in this case. This can be expressed
> by ﬁve corresponding assertions suitable for the initial state, which
> for brevity are omitted here.
>
> Finally, the relation between the state variables state and output is
> established by
>
> ✷(「ql =⇒「ω(q)l) (11) The latter formula allows *no* time delay
> between an entry of a new state and the issuing of the corresponding
> output. This is justiﬁed by the black box view on the PLC. The
> semantics does not intend to describe the internal

behaviour of the PLC. It describes the external observable behaviour of
the system. For example, it does not use a state variable that describes
the *polled* input value. From the perspective of the external observer
the state variables state and output change their values at the same
time points.

+---------------------------------+
| > tock, z\>10,{z}               |
|                                 |
| ![](./images/media/image32.png) |
+---------------------------------+

> **Fig. 2.** A Timed Automaton
>
> **5. Timed Automata**

Timed Automata \[AD90, ACD90, ACD93, AD94\] are the predominant model
for real-time systems with con- tinuous time. Basically, they are simple
ﬁnite state automata extended by clocks. These clocks are variables with
domain IR ≥0 which increase uniformly with time. Transitions ofthe
automaton carry guards consisting of boolean expressions for the
comparisons between a clock value (or the difference of two clock
values) and a constant. If a transition is taken then a subset of clocks
can be reset. Moreover the states of the automaton can be labelled with
a guard of the same type as the transitions. These guards represent
invariants restricting the admissible clock values.

> In Fig. 2 a timed automaton is given that starts its computation in
> the location with the proposition A and holds this state as long as it
> can perform the transition with label *tock*. This transition can only
> be taken when the z-clock has a value greater than 10. As long as z ≤
> 10 holds, no transition is allowed. If the *tock*-transition is taken,
> the z-clock will be reset to 0. If z reaches the value 100 the
> automaton may take the transition with label *error* to enter a state
> with proposition B . Due to the fact that the A-state has the
> invariant z ≤ 100 it has to take one of the transitions if z reaches
> 100.
>
> A system of Timed Automata in parallel composition uses labels (*tock*
> and *error* in Fig. 2) for synchronisation. It is assumed that
> transitions happen instantaneously, which means that they do not
> consume time.
>
> Although the basic concepts are very similar, various deﬁnitions of
> syntax and semantics can be found in the literature \[ACD90, NSY92,
> AD94, HNSY94, MP95, MY96\]. Here we use a variant of timed automata
> that is deﬁned in \[MY96\]:

**Deﬁnition 2 (Timed Automaton)** A *timed automaton* T is a tuple (S ,
X , L, E , IV , P,µ, S0) where:

> • S is a ﬁnite set of *locations*,
>
> • X is a ﬁnite set of real-valued variables called *clocks* whose
> values increase uniformly with time,
>
> • L is a ﬁnite set of *labels*.

• E is a ﬁnite set of *edges* ofthe form e = (s, L, φ, ρ, s/), or
alternatively written as
![](./images/media/image33.png){width="0.21638888888888888in"
height="0.1330457130358705in"}−,φ−,![](./images/media/image34.png){width="0.12733595800524936in"
height="0.18442694663167103in"}s/, where s, s/ ∈ S,

> φ ::= x + c ≤ d \| c ≤ x + d \| x + c ≤ y + d \| ¬φ \| φ 1 ∧ φ2
>
> with x, y ∈ X and c, d ∈ IR, and ρ ⊆ X is the set of clocks which are
> to be reset to 0 by the transition,
>
> • IV assigns to each location a clock constraint that serves as an
> *invariant* within the location,
>
> • P is a ﬁnite set of atomic propositions,
>
> • µ is a labelling of the locations with a set of atomic propositions
> over P ,
>
> • S0 ⊆ S is the set of *initial locations*.
>
> Usually only natural numbers are allowed as constants in the clock
> constraints, but in order to associate a timed automaton to each
> PLC-Automaton our deﬁnition allows for real-valued constants. The
> price we have to pay is that we cannot model-check this kind of timed
> automata. However, as long as the PLC-Automaton uses only discrete
> delays and a discrete cycle time, the corresponding timed automaton
> semantics uses only discrete time constants, too.
>
> **Deﬁnition 3 (Run of a timed automaton)** A *run* of T is an inﬁnite
> sequence r = ((si, vi, ti ))i∈IN0 where, for each i ∈ IN0 ,
>
> • si ∈ S is a location,
>
> • vi ∈ X l−→ IR ≥0 is a *valuation* of the clocks,
>
> • ti ∈ IR ≥0 is a time stamp,
>
> and r satisﬁes the following properties:
>
> • the initial location is contained in S0: s0 ∈ S0 ,
>
> • initially all the clocks have value 0: ∀x ∈ X : v0 (x) = 0,
>
> • time starts at 0: t0 = 0,
>
> • the sequence of time stamps is monotonic and diverging: ti ≤ ti+1,
> for all i ∈ IN0 , and limi −→∞ ti = ∞ , • for all i ∈ IN0 the
> invariant IV(si ) is fulﬁlled during \[ti, ti+1\]:
>
> ∀0 ≤ t ≤ ti+1 − ti : IV(si )(vi + t)
>
> with (vi + ![](./images/media/image35.png){width="5.654807524059493in"
> height="0.1825229658792651in"} valuation v ,
>
> • for all i ∈ IN0 there is an edge e = (si, L,φ,ρ, si+1) such that
>
> **--** clock constraint φ holds at time ti+1: φ(vi + ti+1 − ti ), and
>
> **--** valuation vi+1 is updated according to ρ:
>
> ![](./images/media/image36.png){width="2.792043963254593in"
> height="0.3230500874890639in"}
>
> By R(T) we denote the set of runs of a timed automaton T.
>
> **6. The model-check semantics**
>
> In the following we give an operational semantics of a PLC-Automaton
> in terms of a set of timed traces accepted by a Timed Automaton. In
> \[DFMV98a\] it was proven that the following semantics is stronger
> than the Duration Calculus semantics above (and equivalent to a slight
> extension of the semantics in Sect. 4).
>
> **Deﬁnition 4 (Timed Automaton semantics)** Let A be a PLC-Automaton
> with A = (Q, Σ, δ, q0 ,ε, St, Se,Ω,ω).
> ![](./images/media/image37.png){width="2.7866152668416446in"
> height="0.18523403324584428in"}
>
> • ![](./images/media/image38.png){width="2.4771456692913385in"
> height="0.1744838145231846in"}
>
> • ![](./images/media/image39.png){width="1.348779527559055in"
> height="0.17448272090988626in"}
>
> • ![](./images/media/image40.png){width="2.053277559055118in"
> height="0.1744838145231846in"}
>
> • The set of transitions E is given in Fig. 3 where i ∈ {0, 1, 2, 3},
> a, b, c ∈ Σ , and q ∈ Q,
>
> • ![](./images/media/image41.png){width="0.58790791776028in"
> height="0.17448272090988626in"} ≤ ε as invariant for each location s ∈
> S,
>
> • P = Σ ∪ Q ∪ Ω is the set of propositions,
>
> • ![](./images/media/image42.png){width="4.686267497812773in"
> height="0.1744838145231846in"}
>
> • S![](./images/media/image43.png){width="0.828646106736658in"
> height="0.18523403324584428in"}0)\|a, b ∈ Σ} as set of initial
> locations.
>
> The set of locations2 of T(A) (refer Def. 4) consists of four
> dimensions. The ﬁrst part ("program counter") with range {0, 1, 2, 3}
> describes the internal status of the polling system. "0" denotes the
> ﬁrst part of the cycle. The polling has not occurred yet. "1" denotes
> that the polling has happened in the current cycle. The check whether
> to react has not occurred yet. "2" denotes that polling and testing
> have happened. The system decided not to
>
> 2 Note that "locations" refers to the Timed Automaton and "states" to
> the PLC-Automaton.

+-------------------------------------------------------------------------------------------------------------------------------------------------+
| +---------------------------------------------------------------+------------------------------------------------------------------+---------:+ |
| | > ![](./images/media/image44.png){width="2.423786089238845in" | > c                                                              | \(12\)   | |
| | > height="0.208497375328084in"}                               | > ![](./images/media/image46.png){width="0.10017935258092739in"  |          | |
| |                                                               | > height="0.12370297462817148in"} a                              | \(13\)   | |
| | ![](./images/media/image45.png){width="2.024233377077865in"   |                                                                  |          | |
| | height="0.20820538057742782in"}                               |                                                                  |          | |
| +---------------------------------------------------------------+------------------------------------------------------------------+----------+ |
| | ![](./images/media/image47.png){width="2.44966426071741in"    | > St (q) \> 0 ∧ b ∈ Se (q)                                       | \(14\)   | |
| | height="0.20917322834645669in"}                               |                                                                  |          | |
| +---------------------------------------------------------------+------------------------------------------------------------------+----------+ |
| | ![](./images/media/image48.png){width="2.449650043744532in"   | > St (q) \> 0 ∧ b ∈ Se (q)                                       | \(15\)   | |
| | height="0.20917322834645669in"}                               |                                                                  |          | |
| +---------------------------------------------------------------+------------------------------------------------------------------+----------+ |
| | ![](./images/media/image49.png){width="2.4496489501312335in"  | > St (q) = 0 ∨ b                                                 | \(16\)   | |
| | height="0.20384733158355206in"}                               | > ![](./images/media/image51.png){width="7.748687664041995e-2in" |          | |
| |                                                               | > height="0.12370297462817148in"} Se (q)                         | \(17\)   | |
| | ![](./images/media/image50.png){width="2.021327646544182in"   |                                                                  |          | |
| | height="0.208497375328084in"}                                 |                                                                  |          | |
| +---------------------------------------------------------------+------------------------------------------------------------------+----------+ |
| | ![](./images/media/image52.png){width="2.44966426071741in"    | > q = δ(q, b)                                                    | \(18\)   | |
| | height="0.20849628171478565in"}                               |                                                                  |          | |
| +---------------------------------------------------------------+------------------------------------------------------------------+----------+ |
| | ![](./images/media/image53.png){width="2.449650043744532in"   | > q                                                              | \(19\)   | |
| | height="0.20207349081364828in"}                               | > ![](./images/media/image54.png){width="0.10017935258092739in"  |          | |
| |                                                               | > height="0.12370297462817148in"} δ(q, b)                        |          | |
| +---------------------------------------------------------------+------------------------------------------------------------------+----------+ |
+-------------------------------------------------------------------------------------------------------------------------------------------------+

> **Fig. 3.** The transitions of the TA-semantics

+---------------------------------------------------------------+
| > ![](./images/media/image55.png){width="3.881317804024497in" |
| > height="2.217568897637795in"}0 not polled yet *poll*        |
| >                                                             |
| > 1 not tested yet                                            |
| >                                                             |
| > *test test*                                                 |
| >                                                             |
| > 2 will not take transition 3 will take transition           |
+---------------------------------------------------------------+

> **Fig. 4.** The program counter
>
> react to the input. "3" denotes that polling and testing have
> happened. The system decided to react to the input (cf. Fig. 4).

The second component of the locations denotes the latest input event
while the third component contains the latest polled input. The last
component represents the current state of the PLC-Automaton. There are
three clocks in use: Clock x measures how long the latest input is
valid, clock y measures how long the current state is valid, and clock z
measures the time of the current cycle. Transitions that change the ﬁrst
component of the locations are labelled with poll , test, and tick. The
remaining transitions (12) are labelled with inputs and are not
restricted anyhow. They change the second component which represents the
latest input-event. The third component describes the input which is
polled by the system. The polling has to happen after an amount of time
since the beginning of the cycle. To this end the clock z is used. This
clock denotes the elapsed time for the current cycle. Hence, the polling
transition (13) is labelled with the condition z \> 0. Furthermore, it
is not allowed to poll an input at the same time point where it gets
valid. Hence, we introduced the clock x denoting the time since the last
input is valid and restricted the poll-event with x \> 0. Otherwise the
system could react to input that was valid only for a point of time
which has to be avoided in order to keep the consistency with the
DC-semantics. After the polling the testing has to occur (14)---(16).
These transitions reﬂect the decision of the system whether to react to
the polled b input or not. It depends on the deﬁnitions of Se , St , and
the value of the y-clock which denotes the time how long the current
*state* q is valid. It can only decide to ignore the input when b ∈ Se
(q) and St (q) \> 0 are true (14) and moreover the delay time has not
elapsed: y ≤ St (q). Finally, the tick-events ﬁnish the cycle
(17)---(19). Depending on the previous decision by the test-event the
state may change or not. All necessary clocks are reset. Due to the
invariants z ≤ ε for all locations we know that a cycle consisting of a
poll-, a test-, and a tick-event has to happen within ε s because only
the tick-events reset z.

+----------------------------------------------------------------------------------------------------------------+
| > Env1 Env2                                                                                                    |
|                                                                                                                |
| +-------------------------------------------------------------+-------------+-----------+-----------+-------:+ |
| | ![](./images/media/image56.png){width="4.532693569553806in" | > *unsafe2* |           | > *safe1* | *not   | |
| | height="2.3258267716535435in"}*not G1*                      |             |           |           | G2*    | |
| +-------------------------------------------------------------+-------------+-----------+-----------+--------+ |
| | > safe1                                                     | > W2        | > *safe2* | > G1      | safe2  | |
| +-------------------------------------------------------------+-------------+-----------+-----------+--------+ |
| | > 0                                                         | > 0         |           | > 0       | > 0    | |
| +-------------------------------------------------------------+-------------+-----------+-----------+--------+ |
|                                                                                                                |
| > *Env1 G1 unsafe2 unsafe1 Env2 G2*                                                                            |
+----------------------------------------------------------------------------------------------------------------+

> **Fig. 5.** The system with three PLC-Automata
>
> **7. A "Protocol"**
>
> Now we consider a system of PLC-Automata which works in parallel. Two
> automata ("A1", "A2") have a state which is "unsafe". The automaton
> "Controller" is used to assure the mutual exclusion of both unsafe
> states (Fig. 5). In the Duration Calculus semantics the parallel
> composition is simply the conjunction of the semantics of the three
> automata in the system in addition with the following linking
> formulas:

□(「l ∨「input1 = outputCtrll) □(「l ∨「outputA1 = inputtrll) (20)

□(「l ∨「input2 = outputCtrll) □(「l ∨「outputA2 = inputl) (21)

> These formulas say that the output of Controller is the input of A1
> and A2. The outputs of A1 and A2 are inputs of Controller. Note that
> we deﬁned the PLC-Automaton only for one input. It is obvious how to
> extend this deﬁnition to cope with multiple inputs using the Cartesian
> product.
>
> The inﬂuence of the environment is modelled by the inputs Env1 and
> Env2 of Boolean type. In Fig. 5 the transitions are labelled with
> predicates over the inputs instead of input-elements to enhance
> readability. The Controller waits in state Wi ("Wait", i ∈ {1, 2}) as
> long as Ai is unsafe. If the Controller recognises that Ai is safe, it
> changes to G(3 − i) ("Grant") which allows A(3 − i) to enter its
> unsafe state. The grant is given until the Controller detects that A(3
> − i) has entered the unsafe state. The mutual exclusion shall be
> guaranteed by the Wi-states. We assume that these PLC-Automata are
> equipped with the upper cycle bounds ε 1 = ε2 = εC .
>
> Now we are interested whether we can prove the mutual exclusion of
> both unsafe-states. Due to the exis- tence of two semantics we can
> compare the logical approach with the model-checking approach. For the
> model checking of the system we used the model checker Kronos
> \[DOTY96\] (Version 2.4.4, August 2000) and UPPAAL \[BLL+ 96\]
> (Version 3.1.64, June 2001).
>
> **7.1. Using Duration Calculus**
>
> First we try to prove the mutual exclusion property of the protocol by
> reasoning in Duration Calculus. This means, that we have to prove this
> property:3
>
> \[\[A 1\]\]DC ∧ \[\[Ctrl\]\]DC ∧ \[\[A2\]\]DC ∧ (20) ∧ (21) =⇒ ¬◇(「u1
> ∧ u2 l)
>
> 3 Note the mutual exclusion property (¬◇(「u1 ∧ u2l)) only uses two
> state variables whereas the semantics of the automata and the linking
> formulas use some more. There are some extensions of DC that allow for
> quantiﬁcation over state variables. This would enable us to hide the
> additional state variables by quantiﬁers. However, in this simple case
> it sufﬁces to conceive the DC formula ¬◇(「u1 ∧ u2l) as a speciﬁcation
> of all state variables used by the semantics.
>
> Note that we abbreviate unsafei and safei by ui and si , respectively.
> To prove this we try to derive a contradiction from
>
> ◇(「u1 ∧ u2 l)
>
> by the assumptions. In the ﬁrst step we exploit the information about
> the initial states (1). Both automata A1 and A2 start in the safe
> state, hence we have to observe a state change from a safe situation
> (i.e. one automaton is in the safe state) to the unsafe situation
> (both automata are unsafe). Without loss of generality we assume that
> the second automaton executes the incorrect transition:
>
> {W.l.o.g., (1)} =⇒ true;「s2 l ;「u1 ∧ u2 l ; true
>
> By the deﬁnition ofA2 we know that the transition from safe2 to
> unsafe2 requires that a grant is given less than ε2 seconds ago:
>
> ![](./images/media/image57.png){width="3.146719160104987in"
> height="0.3230577427821522in"}
>
> By the deﬁnition of the controller's transitions we know that the
> controller has to visit the states W2, G1, and W1 in this order before
> it may enter G2:
>
> {(1), (2)} =⇒ true;「W2l ;「G1l ;「W 1l ;
> (「![](./images/media/image58.png){width="0.11474409448818898in"
> height="0.27273075240594924in"}2u;
> ;![](./images/media/image59.png){width="9.644903762029747e-2in"
> height="0.27307633420822397in"}s ) ;「u1 ∧ u2 l ; true

Now we consider the behaviour of A1 during the「W1l-phase. Due to (2)
and (3) for A1 we know that transitions from s1 to u1 are only possible
if a grant was given while s1 and less than ε 1 seconds ago. With
similar arguments for the controller we can conclude that the transition
from W1 to G2 requires a「s1 l-phase during the「W1l-phase less than εC
time units before the transition happens. Hence, we can categorise the
behaviour of A1 during the 「W1l-phase in four cases:

> ![](./images/media/image60.png){width="4.006491688538933in"
> height="0.7963560804899388in"}
>
> ![](./images/media/image61.png){width="1.2100699912510937in"
> height="0.32305555555555554in"}u1 ∧ u2 l ; true

At the last line we can stop the proof attempt. The reason is that the
case distinction discovers a case (「s1 l\<ε1 ;「u1 l\<εC ) where our
system could fail. In all other cases we could derive the desired
contradiction because due to (2) and (3) for A1 the state is not allowed
to change to u1 during the「G2l-phase. But in the case 「s1 l\<ε1 ;「u1
l\<εC we have lost, because the Controller has left W1 too early
believing that A1 is in the safe state. From above it is easy to derive
a complete trace how the system can violate the mutual exclusion
property (cf. Fig. 6 where the polling events are sketched by arrows).

> Thus, Duration Calculus helped us to discover the error in our
> protocol because it gave us an appropriate way to reason about phases
> and their durations.
>
> **7.2. Using model checkers**
>
> In order to apply model checkers for Timed Automata we have to
> translate the speciﬁcation of the protocol into in the syntaxes of the
> tools Kronos and Uppaal. The tool Moby/PLC \[DT98, TD98\] for
> PLC-Automata offers compiling functions for arbitrary systems of
> PLC-Automata such that the translation can be done mechanically.
>
> To apply Kronos we have to translate each of the three automata
> separately into the Kronos-format "timed graphs". The resulting timed
> graphs had the following dimensions given in Table 1. In addition we
> have to add two small automata to model the environment. They are
> designed such that Env1 and Env2 may change arbitrarily. The size of
> the product automaton computed by Kronos is also given in the table.
> Kronos is able to model- check whether a system of Timed Automata
> satisfy a formula given in the logic TCTL.4 The TCTL-formula that
> expresses mutual exclusion is

4 An introduction ofTCTL is omitted because (22) is the only
TCTL-formula we need in this paper. See \[ACD90\] for a deﬁnition of
TCTL.

+--------+------+--------------------------------------------------------------------------------------------------+--------+
| > A1   | u1   | > \< ε 1                                                                                         | > Time |
| >      |      | >                                                                                                |        |
| > Ctrl | s1   | > ![](./images/media/image62.png){width="4.284776902887139e-3in"                                 |        |
| >      |      | > height="3.237970253718285e-2in"}~~✛                                                            |        |
| > A2   | G2   | > ✲~~![](./images/media/image63.png){width="4.284776902887139e-3in"                              |        |
|        |      | > height="3.237970253718285e-2in"}                                                               |        |
|        | W1   | >                                                                                                |        |
|        |      | > ![](./images/media/image64.png){width="0.49765310586176725in" height="4.101377952755905e-2in"} |        |
|        | G1   | >                                                                                                |        |
|        |      | > ![](./images/media/image65.png){width="5.527121609798775e-3in"                                 |        |
|        | W2   | > height="3.280511811023622e-2in"}                                                               |        |
|        |      | >                                                                                                |        |
|        | > u2 | > ▲ ▲                                                                                            |        |
|        | >    | >                                                                                                |        |
|        | > s2 | > ❄                                                                                              |        |
|        |      | >                                                                                                |        |
|        |      | > [❄]{.underline}                                                                                |        |
|        |      | >                                                                                                |        |
|        |      | > ▲                                                                                              |        |
|        |      | >                                                                                                |        |
|        |      | > ![](./images/media/image66.png){width="0.30080489938757654in"                                  |        |
|        |      | > height="3.2468285214348205e-2in"}                                                              |        |
|        |      | >                                                                                                |        |
|        |      | > ![](./images/media/image67.png){width="0.29532699037620297in"                                  |        |
|        |      | > height="5.228127734033246e-2in"}![](./images/media/image68.png){width="5.476815398075241e-3in" |        |
|        |      | > height="3.233267716535433e-2in"}                                                               |        |
|        |      | >                                                                                                |        |
|        |      | > \< εC                                                                                          |        |
|        |      | >                                                                                                |        |
|        |      | > [❄]{.underline}                                                                                |        |
|        |      | >                                                                                                |        |
|        |      | > **~~✲~~**                                                                                      |        |
+--------+------+--------------------------------------------------------------------------------------------------+--------+

> **Fig. 6.** A counterexample
>
> **Table 1.**

+--------------+-------------+---------------+------------+----------+
|              | > locations | > transitions | > integers | > clocks |
+--------------+-------------+---------------+------------+----------+
| > Kronos                                                           |
+--------------+-------------+---------------+------------+----------+
| > A1         | > 49        | > 342         | > ---      | > 2      |
+--------------+-------------+---------------+------------+----------+
| > Controller | > 65        | > 324         | > ---      | > 2      |
+--------------+-------------+---------------+------------+----------+
| > A2         | > 49        | > 342         | > ---      | > 2      |
+--------------+-------------+---------------+------------+----------+
| > Env. for   | > 3         | > 4           | > ---      | > ---    |
| > A1         |             |               |            |          |
+--------------+-------------+---------------+------------+----------+
| > Env. for   | > 3         | > 4           | > ---      | > ---    |
| > A2         |             |               |            |          |
+--------------+-------------+---------------+------------+----------+
| > product    | > 1681      | > 8404        | > ---      | > 6      |
+--------------+-------------+---------------+------------+----------+
| > Uppaal                                                           |
+--------------+-------------+---------------+------------+----------+
| > A1         | > 2         | > 16          | > 4        | > 2      |
+--------------+-------------+---------------+------------+----------+
| > Controller | > 4         | > 24          | > 4        | > 2      |
+--------------+-------------+---------------+------------+----------+
| > A2         | > 2         | > 16          | > 4        | > 2      |
+--------------+-------------+---------------+------------+----------+
| > Env. for   | > 1         | > 2           | > 1        | > ---    |
| > A1         |             |               |            |          |
+--------------+-------------+---------------+------------+----------+
| > Env. for   | > 1         | > 2           | > 1        | > ---    |
| > A2         |             |               |            |          |
+--------------+-------------+---------------+------------+----------+

> ¬∃ true U≥0 (u1 Λ u2). (22) The formula can be read as follows: There
> exists no run of the system in which a state occurs that fulﬁls (u1 Λ
> u2). Model checking the product automaton if the mutual exclusion
> property is fulﬁlled yields the result "false" within approx. 16 s
> using an UltraSPARC 1 machine with a depth-ﬁrst strategy and within
> about 2.5 min on the same machine with breadth-ﬁrst. If Kronos is
> applied with the backward analysis option we get the same answer
> within 3 s. The drawback of the backward analysis option is that no
> counterexamples are provided and that makes it difﬁcult to get
> conﬁdence into the model of the system and to understand why the
> veriﬁcation failed.
>
> The model checker Uppaal is able to accept integer-variables.
> Therefore, we use an alternative representation of the Timed Automaton
> semantics for PLC-Automata. The integers are used to represent the
> program counter, the polled inputs, and the outputs. This makes the
> description of the system in Fig. 5 acceptably small (see Table 1).
> Uppaal can check a system of Timed Automata against reachability
> properties like (22) only whereas a forward analysis algorithm is
> used. With the same machine as above Uppaal discovers a counterexample
> in approx. 9 s.5 Both tools produced a counterexample which
> corresponds to the one presented in Fig. 6.
>
> 5 With the depth-ﬁrst option. In case of breadth-ﬁrst search it takes
> approx. 10 min.

+-------------------------------------------------------------+
| ![](./images/media/image69.png){width="4.532693569553806in" |
| height="2.3258267716535435in"}                              |
|                                                             |
| > Controller                                                |
+-------------------------------------------------------------+

> **Fig. 7.** The system with an improved controller
>
> **8. An improved protocol**

We can derive an improved version of our protocol from the
counterexample given in Fig. 6. The idea of the improvement is that we
avoid the only situation in which the previous protocol can fail. This
can be done by using delays to ensure that the states of A1 and A2 are
checked over a certain time period. This is possible by introducing
delays for the waiting states (cf. Fig. 7). The delay of εi + εC seconds
for state Wi is valid for *all* inputs. Again we try to verify the
protocol with logical reasoning and model checking.

> We can apply the same arguments as in Sect. 7.1 to derive the formula
>
> ![](./images/media/image70.png){width="4.186905074365704in"
> height="0.7963484251968503in"}
>
> (「![](./images/media/image71.png){width="0.11473097112860893in"
> height="0.27272856517935257in"}2u;
> ;![](./images/media/image72.png){width="9.646106736657918e-2in"
> height="0.2730741469816273in"}s ) ;「u1 ∧ u2 l ; true
>
> As before (2) and (3) can be used to get a contradiction for all cases
> except for the subformula「s1 l\<ε1 ;「u1 l\<εC : {(2), (3)} =⇒
> true;「W2l ;「G1l ; (「W1l ∧「s1 l\<ε1 ;「u1 l\<εC ) ; (23)
>
> ![](./images/media/image73.png){width="2.021966316710411in"
> height="0.32305446194225723in"}
>
> Formula (7) with
> ![](./images/media/image74.png){width="2.2330249343832023in"
> height="0.17448490813648293in"} 「¬W1l
> ;「W![](./images/media/image75.png){width="0.9786297025371828in"
> height="0.20703958880139983in"}

which says that state W1 holds at least ε 1 + εC seconds and this
contradicts (23). Hence, we proved mutual exclusion for the improved
protocol.

> The model-checking results for the improved protocol are as follows:
> When we use the backward analysis option of Kronos we get the correct
> result within 7 s. Forward analysis fails: Kronos exceeded the memory
> limitation of 700 MB (\> 1 h). Uppaal was able to produce the correct
> result but it took approx. 4 h.
>
> **9. Abstractions**

The partially disappointing model-checking results in Sect. 8 call for
ways of improvements. The forward analysis failed to verify the mutual
exclusion or it took a lot of time. Only the backward analysis gave the
correct answer within acceptable time. However, the backward analysis of
Kronos is only applicable to a single automaton. Therefore, we have to
compute the product automaton beforehand and this procedure is limited
by the size of the product because Kronos does not accept automata of
arbitrary size.

It is possible to improve the model checking if we are able to reduce
the model in a way such that we can draw conclusions from the results of
the smaller model about the bigger model. To this end we deﬁne a notion
of *simulation* to formalise a relation between two models.

> **Deﬁnition 5 (Simulation)** Let Ti = (Si, Xi, L, Ei, IVi, Pi,µi,
> S0,i) with i = 1, 2 Timed Automata. We say that T1 is a *simulation*
> of T2 (in symbols: T1
> ![](./images/media/image76.png){width="0.10017935258092739in"
> height="0.18043307086614174in"}T2) iff holds:
>
> P2 ⊆ P1
>
> and ∀((s, v, tj )j∈IN0 ) ∈ R(T1) :
>
> ∃((s, v, tj )j∈IN0 ) ∈ R(T2) :
>
> ∀j ∈ IN0 : µ2 (s) = P2 ∩ µ1 (s)

Roughly speaking, T1
![](./images/media/image77.png){width="0.10017935258092739in"
height="0.18043307086614174in"}T2 holds if for each run of T1 there is a
run of T2 with the same time stamps and the

> The deﬁnition of
> ![](./images/media/image78.png){width="2.4754779090113734in"
> height="0.20647419072615922in"}
> ≤![](./images/media/image79.png){width="9.01017060367454e-2in"
> height="0.17420931758530184in"}T by Lynch and Vaandrager. In \[LV96\]
> they deﬁned for the timed transition systems A, B the relation A
> ≤![](./images/media/image80.png){width="9.345363079615047e-2in"
> height="0.17420931758530184in"}T B as inclusion of inﬁnite, non-Zeno
> traces speaking over the visual events of A and B . In Def. 5 we
> conceive the propositions as visual entities and thus we require for
> each run ofT1 a run ofT2 with the same time stamps and the same
> observable behaviour. In the sense of \[LV96\] we require trace
> inclusion. For an extensive analysis of timed simulation relations the
> reader is referred to \[LV96\].
>
> The deﬁnition of simulation is given on the semantical level. More
> convenient are methods to prove simula- tion on the syntactical level.
> To this end we spend a little work on giving a sufﬁcient condition on
> the syntactical level to prove simulation.
>
> **Lemma 1** Let Ti = (Si, X , L, Ei, IVi, Pi,µi, S0,i) with i = 1, 2
> Timed Automata with P2 ⊆ P1. If a function f : S1 }−→ S2 exists with
>
> f (S0, 1) ⊆ S0,2
>
> ∀s1 ∈ S1 : µ 1 (s1) ∩ P2 = µ2 (f (s1))
>
> ∀s1 ∈ S1 : IV1 (s1) =⇒ IV2 (f (s1))
>
> ∀(s1 , L,φ, R, s ) ∈ E1 : (f (s1), L,φ, R, f (s)) ∈ E2
>
> then T1 ![](./images/media/image81.png){width="0.10017935258092739in"
> height="0.18043416447944008in"}T2 holds.
>
> *Proof.* Let r = ((sj , vj , tj )j∈IN0 ) ∈ R(T1) be a run of T1. Then
> it is clear that ((f (sj ), vj , tj )j∈IN0 ) is a run of T2:
>
> • s0 ∈ S0, 1 and thus f (s0) ∈ f (S0, 1) ⊆ S0,2.
>
> • t0 = 0, ∀x ∈ X : v0 (x) = 0, and time is diverging because r is a
> run of T1.
>
> • for all i ∈ IN0 and 0 ≤ t ≤ ti+1 − ti is IV1 (si )(vi + t) fulﬁlled
> because r is a run. Hence, IV2 (f (si ))(vi + t) holds because the
> invariant of si is stronger than the invariant of f (si ).
>
> • for all i ∈ IN0 exists an edge (f (si ), L,φ, R, f (si+1)) ∈ E2 with
>
> φ(vi + ti+1 − ti )
>
> and vi+1 = (vi + ti+1 − ti )\[R := 0\]
>
> because there is an edge (si, L,φ, R, si+1) ∈ E1 with these
> properties. Otherwise r would not be a run of T1.
> ![](./images/media/image82.png){width="7.803915135608049e-2in"
> height="7.319663167104112e-2in"}
>
> In the following lemma we give a sufﬁcient condition when it is
> possible to draw conclusions from model- checking results of
> abstracted models.
>
> **Lemma 2 (Correctness of abstractions)** Let T and T/ be Timed
> Automata with
> T![](./images/media/image83.png){width="0.10804571303587052in"
> height="0.18043416447944008in"}T/ and let ϕ be a TCTL-for-
>
> p, →彐ϕ1 U\~c ϕ2 , Vϕ1 U\~c ϕ2
>
> and T/ \|= ϕ holds, then is T \|= ϕ valid. If ϕ is of the form彐ϕ1
> U\~c ϕ2 , →Vϕ1 U\~c ϕ2 ,
>
> and T/ \|![](./images/media/image84.png){width="0.10118875765529309in"
> height="0.12370297462817148in"} ϕ is true, then T
> \|![](./images/media/image85.png){width="0.10118875765529309in"
> height="0.12370297462817148in"} ϕ is true.
>
> *Proof.* The assumption
> T![](./images/media/image86.png){width="0.10803915135608048in"
> height="0.18043307086614174in"}T/ assures that all runs of T have a
> corresponding run of T/. For the ﬁrst kind of TCTL-formulas we know
> that T/ \|= ϕ means that all runs of T/ fulﬁll a condition speaking of
> propositions in PT/ . Hence, all runs of T have to fulﬁll the
> condition, too.
>
> The second case can be reduced to the ﬁrst case with →ϕ . □

Note that the restriction to TCTL without explicit clock constraints is
necessary because the notion of simulation
![](./images/media/image87.png){width="4.456048775153106in"
height="0.20119750656167978in"} .

> In the following we explain some abstraction methods which are useful
> in the setting of PLC-Automata. Clocks are the most expensive entities
> in Timed Automata when model checking is intended. Therefore, it is
> advantageous to use abstractions of clocks:
>
> **Deﬁnition 6 (Clock-Abstraction)** Let T = (S , X , L, E , IV , P,µ,
> S0) be a Timed Automaton and *clk* ∈ X. An automaton

T/ = (S , X \\{*clk*}, L, E/ , IV/ , P,µ, S0) with

> V(s1 , L,φ,ρ, s2) ∈ E :
>
> 彐(s1 , L,φ/ ,ρ \\{*clk*}, s2) ∈ E/ :
>
> Vv ∈ \[X }−→ IR ≥0\] : φ(v) =→ φ/(v\|X \\{*clk*})
>
> and Vs ∈ S, v ∈ \[X }−→ IR ≥0\] : IV(s)(v) =→ IV/(s)(v\|X \\{*clk*})
> is called an *clk-abstraction of* T.
>
> Thus, a *clk*-abstraction ofT can be constructed by removing *clk*
> from X and replacing all clock constraints and invariants using *clk*
> by weaker constraints resp. invariants not using *clk*.
>
> **Lemma 3 (Clock-Abstraction)** Let T and *clk* as in Def. 6. If T/ is
> a *clk*-abstraction of T, then holds:
> T![](./images/media/image88.png){width="0.10802602799650043in"
> height="0.18043416447944008in"}T/
>
> *Proof.* If ((si, vi, ti )i∈IN0 ) is a run of T, then it is easy to
> verify that ((si , vi \|X \\{*clk*} , ti )i∈IN0 )
>
> is a run of T/. □
>
> A good candidate for a clock abstraction in the TA semantics of
> PLC-Automata is the clock x. If we abstract these clocks in the system
> under consideration we can save three clocks in total because the
> system consists of three automata.
>
> Another way to decrease the complexity of model checking is to reduce
> the number of locations of the automaton. We will use the following
> lemma to reduce the number of locations in the TA semantics.
>
> **Table 2.** Sizes of the TA models

+----------+-------------+----------------+--------+----------+
|          | > locations | > transitions  | > ints | > clocks |
+----------+-------------+----------------+--------+----------+
| > Kronos |             |                |        |          |
+----------+-------------+----------------+--------+----------+
| > Full   | > 1969      | > 10132        | > ---  | > 7      |
| > model  |             |                |        |          |
+----------+-------------+----------------+--------+----------+
| > Env.   | > 493       | > 1751         | > ---  | > 7      |
| > abstr. |             |                |        |          |
+----------+-------------+----------------+--------+----------+
| > x      | > 1969      | > 10132        | > ---  | > 4      |
| > abstr. |             |                |        |          |
+----------+-------------+----------------+--------+----------+
| > both   | > 493       | > 1751         | > ---  | > 4      |
+----------+-------------+----------------+--------+----------+
| > Uppaal | > 2/4/2/1/1 | > 16/28/16/2/2 | > 14   | > 7      |
| >        |             |                |        |          |
| > Full   |             |                |        |          |
| > model  |             |                |        |          |
+----------+-------------+----------------+--------+----------+
| > Env.   | > 2/4/2     | > 14/28/14     | > 10   | > 7      |
| > abstr. |             |                |        |          |
+----------+-------------+----------------+--------+----------+
| > x      | > 2/4/2/1/1 | > 16/28/16/2/2 | > 14   | > 4      |
| > abstr. |             |                |        |          |
+----------+-------------+----------------+--------+----------+
| > both   | > 2/4/2     | > 14/28/14     | > 10   | > 4      |
+----------+-------------+----------------+--------+----------+

> **Table 3.** Model-checking results

+----------+----------+-----------+------------+
| > model  | > Uppaal | > Kronos  | > Kronos   |
|          |          | > (forw.) | > (backw.) |
+----------+----------+-----------+------------+
| > Full   | > 3 h 53 | > ---     | > 4 s      |
| > model  | > m      |           |            |
+----------+----------+-----------+------------+
| > Env.   | > 1 m 7  | > 4 m 13  | > 1 s      |
| > abstr. | > s      | > s       |            |
+----------+----------+-----------+------------+
| > x      | > 2 m 33 | > 1 m 30  | > 2 s      |
| > abstr. | > s      | > s       |            |
+----------+----------+-----------+------------+
| > both   | > 6 s    | > 16 s    | > 1 s      |
+----------+----------+-----------+------------+

**Lemma 4 (State reduction)** Let T = (S , X , L, E , IV , P,µ, S0) be a
Timed Automaton. Let f be a function with dom(f) = S and P/ ⊆ P. If

> ∀s, s/ ∈ S : f (s) = f (s/) =⇒ µ(s) ∩ P/ = µ(s/) ∩ P/ holds, then is T
> a simulation of the Timed Automaton

Tf,P/ ![](./images/media/image89.png){width="2.253079615048119in"
height="0.18523512685914262in"} where

> Ef = {(f (s), L,φ, R, f (s/))\|(s, L, φ, R, s/) ∈ E} IVf (f (s)) = V
> IV(s/)
>
> s/ ∈f−1(f (s))
>
> µf (f (s)) = µ(s) ∩ P/ In symbols:
> T![](./images/media/image90.png){width="0.10803915135608048in"
> height="0.18043307086614174in"}Tf,P/ .

Note that IVf and µf are well-deﬁned.

> *Proof.* Apply Lemma 1 on page 116.
>
> For the system of Fig. 7 it is reasonable to apply Lemma 4 to the
> Timed Automata representing the semantics of A1 and A2. Their
> locations carry the information about the input of the environments
> Env1 resp. Env2. For the mutual exclusion property this information is
> not of interest. Therefore we can apply a function that projects the
> locations of type
>
> {0, 1, 2, 3}× ( IB ×{W1,G1,W2,G2}) × ( IB ×{W1,G1,W2,G2}) ×{ui, si }
> down to locations of type
>
> {0, 1, 2, 3}×{W1,G1,W2,G2}×{W1,G1,W2,G2}×{ui, si }.

In order to fulﬁll the property of Lemma 4 we have to remove the
Envi-input proposition from the set of propo-

sitions of the new locations. In sum, we get automata A1' and A2' with
the fourth of the locations as A1 and A2.

> Let S denote the system given in Fig. 7. Now we can apply the model
> checkers to three abstractions:
>
> • The system S1 where the Envi-inputs are abstracted.
>
> • The system S2 where all x-clocks are abstracted.
>
> • The system S3 where the Envi-inputs *and* the x-clocks are
> abstracted.
>
> The sizes ofthe system are given in Table 2 while the model-checking
> results are given in Table 3. We can observe that the combination of
> both abstractions enables us to explore the whole state space within
> less than a minute.

Since S![](./images/media/image91.png){width="0.10672134733158355in"
height="0.17698818897637794in"}Si
![](./images/media/image92.png){width="0.10672134733158355in"
height="0.17698818897637794in"}S3 holds with i = 1, 2 we can conclude by
Lemma 2 from the model-checking results for S1, S2 ,

> **10. Conclusion**

The paper demonstrated that dense real-time model checking is becoming
feasible for tiny and small systems within acceptable time. If the
property that has to be shown is expressible in TCTL it seems to be a
natural decision to apply the model checkers.

> In case of *tiny* systems model checking is preferred since the tools
> will provide faster and more reliable answers. In case of *small*
> systems model checking is still reasonable. However, the experiments
> presented indicate that the user still has to understand the system
> that should be veriﬁed. This is because abstractions are necessary.

These abstractions usually have to be made by the user and they have to
be justiﬁed. Hence, human interaction and reasoning is necessary even
when model checkers will be applied. Therefore, pure logical reasoning
(like using DC) is equivalent from our point of view. It requires the
same: human brains and a good understanding of the problem.

In case of *larger* systems the purpose of model checkers is limited to
ﬁnd bugs in early design stages. It is hopeless to search the whole
state space to prove the absence of bugs. Hence, logical reasoning is
still the only way to prove correctness in the case of larger systems.

**Acknowledgements**

> The author thanks E.-R. Olderog and the members of the "semantics
> group"in Oldenburg for fruitful discussions on the subject of this
> paper. Moreover, he would like to thank the anonymous referees for
> several helpful remarks on how to improve the paper. This research was
> partially supported by the German Ministry for Education and Research
> (BMBF), project UniForM, grant no. FKZ 01 IS 521 B3, and partially
> supported by the Leibniz Programme of the Deutsche
> Forschungsgemeinschaft (DFG) under grant No. Ol 98/1-1.
>
> **References**
>
> \[ACD90\] Alur R, Courcoubetis C, Dill D (1990) Model-checking for
> real-time systems. In: Fifth annual IEEE symposium on logic in
> computer science, IEEE Press, pp 414---425
>
> \[ACD93\] Alur R, Courcoubetis C, Dill D (1993) Model-checking in
> dense real-time. Inform Comput 104(1):2---34

\[AD90\] Alur R, Dill DL (1990) Automata for modeling real-time systems.
In: Paterson MS (ed) ICALP 90: automata, languages, and

> programming, vol 443 of lecture notes in computer science, Springer,
> Berlin Heidelberg New York, pp 322---335
>
> \[AD94\] Alur R, Dill DL (1994) A theory of timed automata. Theor
> Comput Sci 126:183---235
>
> \[AHS96\] Alur R, Henzinger TA, Sontag ED, (eds) (1996) Hybrid systems
> III---veriﬁcation and control, vol 1066 of lecture notes in computer
> science. Springer, Berlin Heidelberg New York
>
> \[BLL+ 96\] Bengtsson J, Larsen KG, Larsson F, Pettersson P, Yi W
> Uppaal (1996) A tool suite for automatic veriﬁcation of real-time
> systems. In: \[AHS96\], pp 232---243
>
> \[DFMV98a\] Dierks H, Fehnker A, Mader A, Vaandrager FW (1998)
> Operational and logical semantics for polling real-time systems. In:
> \[RR98\], pp 29---40
>
> \[DFMV98b\] Dierks H, Fehnker A, Mader A, Vaandrager FW (1998)
> Operational and logical semantics for polling real-time systems. Tech-
> nical Report CSI-R9813, Computer Science Institute Nijmegen, Faculty
> of mathematics and informatics, Catholic University of Nijmegen

\[Die97\] Dierks H (1997) PLC-Automata: a new class of implementable
real-time automata. In: Bertran M, Rus T (eds) ARTS'97,

> vol 1231 of lecture notes in computer science, Mallorca, Spain,
> Springer, Berlin Heidelberg New York, pp 111---125
>
> \[Die99\] Dierks H (1999) Speciﬁcation and veriﬁcation of polling
> real-time systems. PhD Thesis, University of Oldenburg \[DOTY96\] Daws
> C, Olivero A, Tripakis S, Yovine S (1996) The tool kronos. In:
> \[AHS96\], pp 208---219
>
> \[DT98\] Dierks H, Tapken J (1998) Tool-supported hierarchical design
> of distributed real-time systems. In: Proceedings of the 10th
> euromicro workshop on real time systems, IEEE computer society, pp
> 222---229
>
> \[HNSY94\] Henzinger T, NicollinX, SifakisJ, Yovine S (1994) Symbolic
> model checking for real-time systems. Inform Comput 111:193---244
> \[HZ97\] Hansen MR, Zhou C (1997) Duration calculus: logical
> foundations. Formal Aspects Comput 9:283---330
>
> \[KBPO+ 96\] Krieg-Bru... ckner B, Peleska J, Olderog E-R, Balzer D,
> Baer A (1996) UniForM---universal formal methods workbench. In: Grote
> U, Wolf G (eds) Statusseminar des BMBF Softwaretechnologie, BMBF,
> Berlin, pp 357---378
>
> \[LPW97\] Larsen KG, Petterson P, Yi W (1997) Uppaal in a nutshell.
> Int J Softw Tools Tech Trans 1(1-2):134---152

\[LV96\] Lynch N, Vaandrager FW (1996) Forward and backward simulations
part II: timing-based systems. Inform Comput 128(1):1---25

\[Mos85\] Moszkowski B (1985) A temporal logic for multilevel reasoning
about hardware. IEEE Comput 18(2):10---19

\[MP95\] Maler O, Pnueli A (1995) Timing analysis of asynchronous
circuits using timed automata. In: Proceedings CHARME'95, vol 987 of
lecture notes in computer science, Springer, Berlin Heidelberg New York,
pp 189---205

\[MY96\] MalerO, Yovine S (1996) Hardware timing veriﬁcation using
kronos. In: Proceedings 7th conference on computer-based systems and
software engineering. IEEE Press

\[NSY92\] Nicollin X, Sifakis J, Yovine S (1992) Compiling real-time
speciﬁcations into extended automata. IEEE Trans Software Eng
18(9):794---804

\[RR98\] Ravn AP, Rischel H (eds) (1998) Formal techniques in real-time
and fault-tolerant systems, vol 1486 of lecture notes in computer
science, Lyngby, Denmark, Springer, Berlin Heidelberg New York

\[TD98\] Tapken J, Dierks H (1998) MOBY/PLC --- graphical development of
PLC-automata. In: \[RR98\], pp 311---314

\[Yov97\] Yovine S (1997) Kronos: a veriﬁcation tool for real-time
systems. Int J Softw Tools Tech Trans 1(1-2):123---133

\[Zho93\] Zhou C (1993) Duration calculi: An overview. In: Bjørner D,
Broy M, Pottosin IV (eds) Formal methods in programming and

> their application, vol 735 of lecture notes in computer science,
> Springer, Berlin Heidelberg New York, pp 256---266

\[ZHR91\] Zhou C, Hoare CAR, Ravn AP (1991) A calculus of durations.
Inform Proc Lett 40(5):269---276

> *Received June 1999*
>
> *Accepted in revised form September 2003 by M. R. Hansen and C. B.
> Jones Published online 28 April 2004*
