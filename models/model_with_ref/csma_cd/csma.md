CSMA/CD Timed Automata Model - Extracted Content

*Source: BRICS RS-96-24 Technical Report*

1\. Protocol Background and CSMA/CD Basics

1.1 The Example

We assume that a number of stations are connected on an Ethernet-like
medium, see Figure 1, that is, the basic protocol is of type CSMA/CD. On
top of this basic protocol, we want to design a protocol without
collisions, that is, we want to guarantee a lower bound on the
transmission delay of a buffer - assuming that the medium does not loose
or corrupt data and also assuming that the stations function properly.
The basic (obvious) idea of the protocol is to introduce a dedicated
master station, which in turn asks the other stations if they want to
transmit data to another station. However, the master has to take into
account the possible buffer delays within the receiving stations.

1.2 Protocol Properties

Hence, we want the protocol to enjoy the following properties:

• Collision cannot occur.

• The transmitted data eventually reach their destination.

• Data which are received, have been transmitted by a sender.

• Assuming error-free transmission, there is a known upper bound on the
transmission delay.

Assuming that we know the buffer delays introduced by the medium and the
slave stations, it should not be difficult to make an reasonable
estimate of the upper bound by hand \-\-- assuming that the master makes
enquiries according to a round-robin strategy. However, if we want to
exploit the potential parallelism, it might very well be that one can
find a more intrinsic strategy, which decreases the upper bound. Hence
we would like to check for the following additional property:

• Does there exist a slave schedule with an upper bound being smaller
than the sum of the individual slave delays?

2\. The UPPAAL Tool for Timed Automata

2.1 UPPAAL Overview

UPPAAL is a tool suite for automatic verification of safety and bounded
liveness properties of real-time systems modeled as networks of timed
automata extended with data variables, developed during the past two
years. In this section, we summarize the main features of UPPAAL,
applications to various case-studies and provide pointer to the
theoretical foundation.

UPPAAL consists of a graphical user interface based on Autograph, that
allows system descriptions to be defined graphically and a model-checker
that combines on-the-fly verification with a symbolic technique reducing
the verification problem to that of solving simple constraint systems.
The current version of UPPAAL is able to check for invariant and
reachability properties, in particular whether certain combinations of
control-nodes of timed automata and constrains on variables are
reachable from an initial configuration. Bounded liveness properties can
be checked by reasoning about the system in the context of a testing
automata. In order to facilitate debugging, the model-checker will
report a diagnostic trace in case the verification procedure terminates
with a negative answer.

The current version of UPPAAL is implemented in C++. An overview of
UPPAAL is shown in Figure 7, and contains the following:

atg2ta: A compiler from the graphical representation (.atg) of a network
of timed automata, to the textual representation in UPPAAL (.ta).

hs2ta: A filter that automatically transforms linear hybrid automata
where the speed of clocks is given by an interval into timed automata,
thus extending the class of systems that can be analyzed by Uppaal.

checkta: Given a textual representation (in the .ta-format) of a network
of timed automata, checkta performs a number of simple but in practice
useful syntactical checks.

verifyta: A model-checker that combines on-the-fly verification with
constraint solving techniques.

2.2 Committed Locations

Committed Locations. UPPAAL adopts hand-shaking synchronization between
components in a network. A very recent case-study on the verification of
Philips Audio Control Protocol with bus-collisions shows that we need to
further extend the UPPAAL model with committed locations to model
behaviors such as atomic broadcasting in real-time systems. The notion
of committed locations is introduced in \[BGK+ 96\]. Our experiences
with UPPAAL show that the notion of committed locations implemented in
UPPAAL is not only useful in modeling real-time systems but also yields
significant reductions in time- and space-usages in verifying such
systems.

2.3 Urgent Actions

Urgent Actions. In order to model progress properties UPPAAL uses a
notion of maximal delay that requires discrete transitions to be taken
within a certain time bound. However, in some examples, e.g. the
Manufacturing Plant, synchronization on certain channels should happen
immediately. For this reason the UPPAAL model was extended with urgent
channels, on which processes should synchronize whenever possible. The
notion of urgent channels (also known as urgent actions in the
literature) has been implemented in both HyTech and Kronos.

2.4 Diagnostic Traces

Diagnostic Traces. Ideally, a model-checker should be able to report
diagnostic information whenever the verification of a particular
real-time system fails. UPPAAL reports such information by generating a
diagnostic trace from the initial state to a state violating the
property. The usefulness of this kind of information was shown during
the debugging of an early version of Philips Audio-Control Protocol.

UPPAAL has been applied to a number of case-studies and benchmark
examples, including: several versions of Fischers Protocol, two version
of Philips Audio-Control Protocol, a Steam Generator, a Train Gate
Controller, a Manufacturing Plant, a Mine-Pump Controller and a Water
Tank.

The growing list of successfully completed real-size verification
case-studies and recently initiated collaboration with Danish industry
makes us believe that the UPPAAL is reaching a level of maturity where
it can be applied to real industrial case-studies.

3\. Timed Automata Design for CSMA/CD Protocol

3.1 Design Overview

Having already made the PROMELA protocol design actually made the
modelling using timed automata a relatively easy task. The time spent on
the timed automata design has been considerably less than the time spent
on the initial PROMELA design.

The fundamental automata design is quite similar to the PROMELA design
in the sense that the same type of processes are modelled. That is, each
PROMELA process is matched by a timed automaton in the new design. The
main differences in the models, besides the timing, considers the way
communication between processes take part and the way the broadcasting
behaviour of the medium is expressed. In the timed automata model used
in UPPAAL there is no channel primitive and the only means of
interaction between automata is by pure synchronization of atomic
actions. Consequently, we use a combination of shared variables and
synchronization to simulate the message passing that would actually take
place in a real system.

3.2 The Master Timed Automaton

The master. The master process is modelled as the timed automaton
depicted in Figure 8. We consider a lossy communication medium and
therefore the master is equipped with a timer, see Figure 9, to
guarantee that new enquiries will be sent in the presence of message
loss.

The master starts by sending to the medium an enquire addressed to the
first slave. This is modelled by the initial transition from m0 to m1.
The master sets the shared variable data:=0 on this transition
indicating that the message is an enquiry. Having sent the enquiry and
without further delay, the master sets its timer and starts waiting
until the message has been broadcasted to all slaves, indicated by an
empty synchronization with the medium. This ensures that the master will
not receive its own message.

Now, the master will either receive data broadcasted by a slave or it
will timeout, if nothing is received within a certain time limit. In
either case the master sends an enquiry along to the next slave
indicated by increasing the shared variable next, setting data:=0 and
performing the output action to_medium!.

As indicated on Figure 8 the master waits for two time units before
sending out a new enquiry. This time limit guarantees that all slaves
have finished their internal business and will be ready to receive data.
I.e. messages will not be lost because of slave not ready to receive. To
increase the round-trip performance of the protocol, the master may
choose to decrease this waiting time, but obviously this may result in
messages being lost because of slaves not being ready.

3.3 The Medium Timed Automaton

The Medium. As mentioned the basic means of interaction between timed
automata is by binary synchronization. No basic broadcasting primitive
exists, but the notion of committed locations, see section 3.1, can be
used to model the broadcasting in a simple way. Having received a
message by synchronizing on the input action to_medium?, the medium
delays the message for one time unit and then it starts broadcasting,
see Figure 10. The broadcast consists of synchronizing in turn with each
of the not-sending processes connected to the medium. Atomicity of the
synchronization sequence is ensured by labelling each node that
participates in the synchronization sequence as committed. This
guarantees that no actions can interleave the broadcast.

The node labelled col will be entered upon collisions in the medium, and
it serves the same verification purpose as the accept_collision state in
the PROMELA model.

3.4 The Slaves Timed Automaton

The Slaves. In the UPPAAL model we need to model each slave as a unique
timed automaton. In Figure 11 one of the almost identical slaves is
depicted. The slaves synchronize with the medium on input action
from_medium? and either they loose messages or they receive correctly,
in which case they now determine what type of data is sent and to whom.
Depending on the outcome, slaves either return to their initial state,
sends data along to their users or asks their users for data to be send.
In the last two situations the slaves will delay some amount of time and
during this period they will not be able to detect messages sent to
them. This is modelled as the \'ignoring\' from_medium? input actions at
the nodes s1\_\_2 and s1\_\_4 of Figure 11.

3.5 The Users Timed Automaton

The Users. As for the slaves we need to model each user process as a
unique timed automaton. In Figure 12 the user automaton of the slave in
Figure 11 is depicted. Users are always ready to either responding to
enquiries from their slaves or receiving data sent from other users.
Responding to enquiries is done by sending data to another user. The
committed locations in the user automaton are for verification purposes
and will be explained in section 3.3.

4\. Verification in UPPAAL

4.1 Collision Avoidance Verification

The primary correctness criteria that we want to verify for the protocol
design explained in section 3.2 is that no collisions will ever occur.
As the medium delays messages for one time unit, two messages sent to
the medium within one time unit or less will eventually collide and this
scenario will force the medium automaton in Figure 10 in the node col.
What we need to verify is that it holds invariantly, that the protocol
can not reach a state where the medium automaton is in state col. Stated
as a property in the logic of UPPAAL this becomes:

**□(not medium.col)**

The satisfaction of the above formula is dependent upon the actual
timeout limit in the timer. UPPAAL successfully verifies the property if
we consider a perfect medium, i.e. not lossy. But when an erroneous
medium is introduced as in section 3.2 the timeout limit influences the
possibility of collisions. If a timeout occurs too soon, the master
interprets this as a situation where data is lost and all slaves are
waiting for messages. But obviously this need not be the case as a slave
can actually be in the process of enquiring its user. If this happens
the slave will try to send data from its user and the master will try to
send a new enquiry. If these two messages arrive at the medium within
the one time unit delay of the medium, they will collide. We discover by
repeated verification attempts that timeout limits greater than or equal
to 3 will ensure that no collisions can occur. Also we verify that for a
timeout limit of 2, a collision actually can occur, and the diagnostic
trace facility of UPPAAL gives us a possible trace leading to collision.

4.2 Bounded Liveness Properties Verification

Assuming a perfect medium (not lossy) and assuming that data is sent
from users in round-robin fashion (all user are interested) we want to
verify that the user-to-user communication delay is bounded by some
constant. Also, we want to verify an upper bound on the delay between
users sending data. This actually implies a bound on the delay between
enquiries from the master, as all users are interested in sending. The
above properties are examples of bounded liveness properties which can
not be expressed directly in the logical property language of UPPAAL. To
express the properties we introduce a separate test automaton that
probes the user processes in the protocol design. The test automaton
will be designed to enter a \'bad node\' if it tests an unwanted
behaviour of the protocol. This approach is quite analogous to the
never-claims used in the PROMELA language.

The test automaton for the properties described above is depicted in
Figure 13. The automaton probes the sending and receiving of data in the
user processes by synchronizing on actions send_1 and recv_1 (for user
1), see Figure 12. When a message is sent the test clock s is started
and if the data sent is not received within a certain time limit, the
test automaton is forced in the state bad1. Similarly, if a new sending
is not performed within a certain time from the last receiving, the bad
state bad2 can be entered. The property verified using UPPAAL is:

**□ not (check_1.bad1 or check_1.bad2)**

4.3 Round-Trip Time Verification

Using a similar approach as above we verify that there exists a
round-trip time bound for the protocol. We use the test automaton of
Figure 14 to verify that there exists a round-trip, modelled as user 1
having performed two sends, within a certain time bound. We verify:

**◇(check_2.ch2 and s ≤ 18)**

Also we verify that the following does not hold:

**◇(check_2.ch2 and s ≤ 17)**

That is, there exists no (initial) round-trip time of less than 18 time
units.

4.4 Test Automata Construction

Figure 15: Generation of Testing Timed Automata: The respective test
automata implements the following formulas: (a) tt, (b) f, (c)〈a〉≤n ,
(d) \[a\]≤n\', (e) φ1 Λ φ2 and (f) INV(φ). In the figure, T indicates
the testing automaton for φ. T1 and T2 indicates the automata for φ1 and
φ2 respectively.

5\. Summary: Advantages of Timed Automata Model

In the PROMELA design phase we made extensive use of the simulation
facilities of SPIN, especially the Message Sequence Charts. Within short
time a \'running\' prototype was designed and at an early stage faults
were detected without having the full design at hand. In contrast UPPAAL
does not yet allow for simulations and consequently, the UPPAAL design
has to be more fully developed before the verification can be applied
which delays the tool support in the design phase.

Considering the design languages, the obvious distinction is the
possibility of modelling real-time systems in UPPAAL. In the case study
it is shown that interesting bounded liveness properties can be
expressed and verified in UPPAAL. Another beneficial feature of UPPAAL
is the possibility of committed locations which makes possible a quite
natural modelling of the broadcast behaviour needed in the case study.
In contrast PROMELA can not apply the atomicity construct on sequences
of send- and receive statements as these might be blocking.

Considering the verification phase, the kind of properties expressible
in the property language of UPPAAL are restricted to invariance and
possibility properties. Other properties as e.g. the bounded liveness
properties of our case study needs to be expressed as separate test
automata probing the design. In section 3.4 we present ideas on how to
extend the property language and automatically generate the test
automata. This is already possible in SPIN for transforming LTL
properties to never automata.

The committed locations of UPPAAL make it possible to design non
realizable systems. In particular systems that may enter completely
blocked states (in the sense that neither actions nor time delays are
possible) can be described. Obviously, we would like the possibility of
checking whether the global design suffers such unrealizable properties
or not.

Both SPIN and UPPAAL offers diagnostic information upon negative
verification results. SPIN offers the possibility of examine an error
scenario using the MSC\'s and UPPAAL offers a textual sample error trace
leading to the unwanted state. By performing breadth first reachability
analysis UPPAAL makes available a shortest error trace, whereas this is
not guaranteed in SPIN as the reachability is performed depth first.

6\. References

**Source Document:**

*Henrik Ejersbo Jensen, Kim G. Larsen, Arne Skou. \"Modelling and
Analysis of a Collision Avoidance Protocol using SPIN and UPPAAL.\"
BRICS RS-96-24, July 1996.*

**Key References:**

\[BGK+ 96\] Johan Bengtsson, David Griffioen, Kåre Kristofersen, Kim G.
Larsen, Fredrik Larsson, Paul Pettersson, and Wang Yi. \"Verification of
an Audio Protocol with Bus Collision Using Uppaal.\" 8th Int. Conf. on
Computer Aided Verification, 1996.

\[BLL+ 95\] Johan Bengtsson, Kim G. Larsen, Fredrik Larsson, Paul
Pettersson, and Wang Yi. \"Uppaal \-- a Tool Suite for Automatic
Verification of Real-Time Systems.\" Proc. of the 4th DIMACS Workshop on
Verification and Control of Hybrid Systems, October 1995.

\[LPY95a\] Kim G. Larsen, Paul Pettersson, and Wang Yi. \"Compositional
and Symbolic Model-Checking of Real-Time Systems.\" Proc. of the 16th
IEEE Real-Time Systems Symposium, pages 76\--87, December 1995.

\[LPY95b\] Kim G. Larsen, Paul Pettersson, and Wang Yi. \"Diagnostic
Model-Checking for Real-Time Systems.\" Proc. of the 4th DIMACS Workshop
on Verification and Control of Hybrid Systems, Lecture Notes in Computer
Science, October 1995.

\[KV96\] K. Karsisto and A. Valmari. \"Verification-driven development
of a collision avoidance protocol for the ethernet.\" FTRTFT96, 1996.

\[YPD94\] Wang Yi, Paul Pettersson, and Mats Daniels. \"Automatic
Verification of Real-Time Communicating Systems By Constraint-Solving.\"
Proc. of the 7th International Conference on Formal Description
Techniques, 1994.
