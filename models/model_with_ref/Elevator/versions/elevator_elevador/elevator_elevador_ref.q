// property 1
//This file was generated from (Commercial) UPPAAL 4.0.14 (rev. 5615), May 2014
// source: models\model_with_ref\Elevator\Elevator\elevador.q
A[] not deadlock

// property 2
// source: models\model_with_ref\Elevator\Elevator\elevador.q
A[] Elevator.First_Floor imply x>=2

// property 3
// source: models\model_with_ref\Elevator\Elevator\elevador.q
A[] Door.idle imply (x>=2 and x<=5)
