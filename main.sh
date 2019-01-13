#!/usr/bin/env bash
export PYTHONPATH=/data/zhenyus/oyente/z3-4.4.1-x64-ubuntu-14.04/bin
CORES=76

cd /data/zhenyus/oyente/concolic_execution
pwd=$(pwd)
for i in `seq 0 $(( $CORES - 1))`; do python2 ${pwd}/batch_run.py $CORES $i &> $i.log & done

cd /data/zhenyus/oyente/symbolic_execution
pwd=$(pwd)
for i in `seq 0 $(( $CORES - 1))`; do python2 ${pwd}/batch_run.py $CORES $i &> $i.log & done

