#!/usr/bin/env bash

export PYTHONPATH=/data/zhenyus/oyente/z3-4.4.1-x64-ubuntu-14.04/bin
CORES=76

#pkill -9 -f batch_run;pkill -9 -f concExec; pkill -9 -f symExec

cd /data/zhenyus/oyente/concolic_execution
pwd=$(pwd)
for i in `seq 0 $(( $CORES - 1))`; do python2 ${pwd}/batch_run.py $CORES $i &> $i.log & done

cd /data/zhenyus/oyente/symbolic_execution
pwd=$(pwd)
for i in `seq 0 $(( $CORES - 1))`; do python2 ${pwd}/batch_run.py $CORES $i &> $i.log & done


while true; do
    sleep 60
    kill -9 $(ps -eo comm,pid,etimes,cmd|grep concExec.py| awk '{if ($3 > 400) { print $2}}')
    kill -9 $(ps -eo comm,pid,etimes,cmd|grep symExec.py| awk '{if ($3 > 400) { print $2}}')
done