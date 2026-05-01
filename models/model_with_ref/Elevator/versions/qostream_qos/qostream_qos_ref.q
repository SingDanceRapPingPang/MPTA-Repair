// property 1
//This file was generated from (Commercial) UPPAAL 4.0.14 (rev. 5615), May 2014
// source: models\model_with_ref\Elevator\QOStream\QOS.q
A[] Source.SEND imply x>=50

// property 2
// source: models\model_with_ref\Elevator\QOStream\QOS.q
A[] Reciever.OK imply y>=5

// property 3
// source: models\model_with_ref\Elevator\QOStream\QOS.q
A[] not deadlock
